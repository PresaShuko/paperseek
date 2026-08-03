import json
import threading
import time
import unittest

from paperseek_core.candidate_selector import CandidateSelector
from paperseek_core.llm import LLMClient
from paperseek_core.planning import SearchPlan
from paperseek_core.query_view_selector import select_query_views
from paperseek_core.retrieval import document_key
from paperseek_core.selector import select_query_views as compatibility_select_query_views
from paperseek_core.sources.providers import PaperRecord, PaperSource


class QueueLLM(LLMClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def chat(self, messages, temperature=0.3):
        return self.chat_json(messages, temperature=temperature)

    def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        self.messages.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ConcurrentLLM(LLMClient):
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def chat(self, messages, temperature=0.3):
        return self.chat_json(messages, temperature=temperature)

    def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        payload = json.loads(messages[-1]["content"])
        with self.lock:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        return _response(
            *[
                _decision(candidate["candidate_id"])
                for candidate in payload["candidates"]
            ]
        )


def _paper(uid, title, abstract="abstract", year=2024):
    return PaperRecord(
        uid=uid,
        title=title,
        abstract=abstract,
        source=PaperSource(source_title="Test Venue", publish_year=year),
        provider="openalex",
    )


def _plan():
    return SearchPlan(
        intent="Find causal bandit methods for choosing interventions",
        question_type="method_application",
        core_concepts=["causal bandits", "intervention selection"],
        likely_synonyms=["causal experimentation"],
        boundaries=["Exclude purely observational causal discovery"],
        ambiguities=["bandit may refer to non-causal online learning"],
    )


def _response(*decisions):
    return json.dumps({"decisions": list(decisions)})


def _decision(candidate_id, label="include", score=0.9, **updates):
    payload = {
        "candidate_id": candidate_id,
        "label": label,
        "relevance_score": score,
        "concept_coverage": {"causal bandits": score},
        "missing_concepts": [],
        "evidence": ["The title and abstract discuss causal bandit interventions."],
        "recommended_actions": ["none"],
        "reason_codes": ["direct_match"],
    }
    payload.update(updates)
    return payload


class CandidateSelectorTest(unittest.TestCase):
    def test_query_view_selector_compatibility_import_is_preserved(self):
        self.assertIs(compatibility_select_query_views, select_query_views)

    def test_selects_every_candidate_with_stable_plan_context(self):
        first = _paper("A", "Causal Bandits")
        second = _paper("B", "Observational Causal Discovery")
        first_id = document_key(first)
        second_id = document_key(second)
        llm = QueueLLM([
            _response(
                _decision(first_id),
                _decision(
                    second_id,
                    label="exclude",
                    score=0.1,
                    evidence=["The paper is observational and does not choose interventions."],
                    reason_codes=["explicit_scope_mismatch"],
                ),
            )
        ])

        result = CandidateSelector(llm).select("Which causal bandit methods choose good interventions?", _plan(), [first, second])

        self.assertEqual([item.label for item in result.decisions], ["include", "exclude"])
        self.assertEqual(result.llm_calls, 1)
        prompt = llm.messages[0][1]["content"]
        self.assertIn("Find causal bandit methods for choosing interventions", prompt)
        self.assertIn("Exclude purely observational causal discovery", prompt)

    def test_missing_abstract_cannot_be_excluded(self):
        paper = _paper("A", "Possibly Relevant Causal Study", abstract="")
        llm = QueueLLM([
            _response(
                _decision(
                    document_key(paper),
                    label="exclude",
                    score=0.0,
                    evidence=["No abstract was available."],
                    recommended_actions=["none"],
                )
            )
        ])

        decision = CandidateSelector(llm).select("causal bandits", _plan(), [paper]).decisions[0]

        self.assertEqual(decision.label, "uncertain")
        self.assertIn("missing_abstract_guard", decision.reason_codes)
        self.assertIn("enrich", decision.recommended_actions)

    def test_weak_exclusion_is_downgraded_to_uncertain(self):
        paper = _paper("A", "Related Online Learning")
        llm = QueueLLM([
            _response(
                _decision(
                    document_key(paper),
                    label="exclude",
                    score=0.6,
                    evidence=[],
                )
            )
        ])

        decision = CandidateSelector(llm).select("causal bandits", _plan(), [paper]).decisions[0]

        self.assertEqual(decision.label, "uncertain")
        self.assertIn("weak_exclusion_evidence_guard", decision.reason_codes)

    def test_missing_named_concept_is_not_an_explicit_exclusion(self):
        paper = _paper(
            "A",
            "Gradient Descent Finds Global Minima of Deep Neural Networks",
            abstract="We prove convergence of gradient descent for over-parameterized neural networks.",
        )
        llm = QueueLLM([
            _response(
                _decision(
                    document_key(paper),
                    label="exclude",
                    score=0.1,
                    evidence=["The paper does not explicitly name the earlier Global Descent work."],
                    missing_concepts=["Global Descent", "extension"],
                    reason_codes=["missing_concept"],
                )
            )
        ])

        decision = CandidateSelector(llm).select(
            "Which papers extend Global Descent?",
            _plan(),
            [paper],
        ).decisions[0]

        self.assertEqual(decision.label, "uncertain")
        self.assertIn("absence_is_not_contradiction_guard", decision.reason_codes)

    def test_explicit_behavior_mismatch_is_not_confused_with_missing_mention(self):
        paper = _paper(
            "A",
            "Observational Causal Discovery",
            abstract="This work estimates a static graph and does not choose interventions.",
        )
        llm = QueueLLM([
            _response(
                _decision(
                    document_key(paper),
                    label="exclude",
                    score=0.1,
                    evidence=["The paper is observational and does not choose interventions."],
                    reason_codes=["explicit_scope_mismatch"],
                )
            )
        ])

        decision = CandidateSelector(llm).select("causal bandits", _plan(), [paper]).decisions[0]

        self.assertEqual(decision.label, "exclude")

    def test_incomplete_response_retries_only_missing_candidates(self):
        first = _paper("A", "First")
        second = _paper("B", "Second")
        llm = QueueLLM([
            _response(_decision(document_key(first))),
            _response(_decision(document_key(second), label="uncertain", score=0.5)),
        ])

        result = CandidateSelector(llm, max_attempts=2).select("causal bandits", _plan(), [first, second])

        self.assertEqual(result.llm_calls, 2)
        retry_payload = json.loads(llm.messages[1][1]["content"])
        self.assertEqual(
            [item["candidate_id"] for item in retry_payload["candidates"]],
            [document_key(second)],
        )
        self.assertEqual([item.label for item in result.decisions], ["include", "uncertain"])

    def test_malformed_responses_preserve_candidates_as_uncertain(self):
        papers = [_paper("A", "First"), _paper("B", "Second", abstract="")]
        llm = QueueLLM(["not json", RuntimeError("endpoint failed")])

        result = CandidateSelector(llm, max_attempts=2).select("causal bandits", _plan(), papers)

        self.assertEqual([item.label for item in result.decisions], ["uncertain", "uncertain"])
        self.assertEqual(result.fallback_count, 2)
        self.assertEqual(result.llm_calls, 2)
        self.assertTrue(result.errors)
        self.assertIn("enrich", result.decisions[1].recommended_actions)

    def test_unknown_and_duplicate_ids_are_ignored_without_losing_expected_candidate(self):
        paper = _paper("A", "First")
        candidate_id = document_key(paper)
        llm = QueueLLM([
            _response(
                _decision("uid:unknown"),
                _decision(candidate_id, label="uncertain", score=0.5),
                _decision(candidate_id, label="exclude", score=0.0),
            )
        ])

        result = CandidateSelector(llm).select("causal bandits", _plan(), [paper, paper])

        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(result.decisions[0].label, "uncertain")

    def test_cache_avoids_repeating_llm_call(self):
        paper = _paper("A", "First")
        llm = QueueLLM([_response(_decision(document_key(paper)))])
        selector = CandidateSelector(llm)

        first = selector.select("causal bandits", _plan(), [paper])
        second = selector.select("causal bandits", _plan(), [paper])

        self.assertEqual(first.llm_calls, 1)
        self.assertEqual(second.llm_calls, 0)
        self.assertEqual(second.cache_hits, 1)
        self.assertEqual(len(llm.messages), 1)

    def test_cache_key_changes_with_candidate_metadata(self):
        selector = CandidateSelector(QueueLLM([]))
        first = _paper("A", "First", abstract="first abstract")
        second = _paper("A", "First", abstract="updated abstract")

        self.assertNotEqual(
            selector.cache_key("causal bandits", _plan(), first),
            selector.cache_key("causal bandits", _plan(), second),
        )

    def test_budget_exhaustion_is_recall_preserving(self):
        paper = _paper("A", "First")
        result = CandidateSelector(QueueLLM([]), max_llm_calls=0).select("causal bandits", _plan(), [paper])

        self.assertEqual(result.decisions[0].label, "uncertain")
        self.assertEqual(result.llm_calls, 0)
        self.assertEqual(result.fallback_count, 1)
        self.assertIn("selector_llm_budget_exhausted", result.errors)

    def test_independent_batches_run_concurrently(self):
        papers = [_paper(str(index), f"Candidate {index}") for index in range(24)]
        llm = ConcurrentLLM()

        result = CandidateSelector(llm, batch_size=12, concurrency=2).select(
            "causal bandits",
            _plan(),
            papers,
        )

        self.assertEqual(len(result.decisions), 24)
        self.assertEqual(result.llm_calls, 2)
        self.assertEqual(llm.max_active, 2)

    def test_concurrent_batches_share_one_atomic_call_budget(self):
        papers = [_paper(str(index), f"Candidate {index}") for index in range(24)]
        llm = ConcurrentLLM()

        result = CandidateSelector(
            llm,
            batch_size=12,
            concurrency=2,
            max_llm_calls=1,
            max_attempts=1,
        ).select("causal bandits", _plan(), papers)

        self.assertEqual(len(result.decisions), 24)
        self.assertEqual(result.llm_calls, 1)
        self.assertEqual(llm.calls, 1)
        self.assertEqual(result.fallback_count, 12)
        self.assertIn("selector_llm_budget_exhausted", result.errors)


if __name__ == "__main__":
    unittest.main()
