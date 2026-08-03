import unittest
from types import SimpleNamespace
from threading import Event

from paperseek_core.agent import PaperSeekAgent, SearchCancelled
from paperseek_core.checkpoints import paper_records_from_checkpoint
from paperseek_core.harness.schemas import SearchCheckpoint, SearchRunState, SelectorBatch, SelectorDecision
from paperseek_core.planning import SearchPlan
from paperseek_core.retrieval import document_key
from paperseek_core.sources.providers import PaperIdentifiers, PaperRecord


class _UnusedLlm:
    pass


class _AbstractFetcher:
    def __init__(self):
        self.dois = []

    def fetch(self, doi):
        self.dois.append(doi)
        return "The enriched abstract directly studies causal intervention selection."


class _Selector:
    def __init__(self):
        self.calls = []

    @staticmethod
    def cache_key(question, plan, document):
        return f"{document_key(document)}:{getattr(document, 'abstract', '')}"

    def select(self, question, plan, documents):
        documents = list(documents)
        self.calls.append([document_key(document) for document in documents])
        decisions = []
        for document in documents:
            candidate_id = document_key(document)
            title = (document.title or "").casefold()
            abstract = (document.abstract or "").strip()
            if "off topic" in title:
                decisions.append(
                    SelectorDecision(
                        candidate_id=candidate_id,
                        label="exclude",
                        relevance_score=0.05,
                        evidence=["The title explicitly concerns an unrelated topic."],
                        recommended_actions=["none"],
                    )
                )
            elif not abstract:
                decisions.append(
                    SelectorDecision(
                        candidate_id=candidate_id,
                        label="uncertain",
                        relevance_score=0.5,
                        missing_concepts=["intervention selection"],
                        recommended_actions=["enrich"],
                    )
                )
            else:
                decisions.append(
                    SelectorDecision(
                        candidate_id=candidate_id,
                        label="include",
                        relevance_score=0.9,
                        concept_coverage={"intervention selection": 1.0},
                        evidence=["The available metadata matches the stable SearchPlan."],
                        recommended_actions=["none"],
                    )
                )
        return SelectorBatch(decisions=decisions)


class _CitationProvider:
    def __init__(self):
        self.calls = []

    def citation_neighbors_with_graph(self, seeds, seed_plans=None, **kwargs):
        seed = seeds[0]
        plan = seed_plans[0]
        direction = plan.directions[0]
        self.calls.append((seed.uid, direction))
        neighbor = PaperRecord(
            uid=f"{seed.uid}-{direction}",
            title=f"Citation neighbor of {seed.uid}",
            abstract="Relevant citation-neighbor abstract.",
            provider="openalex",
        )
        return {
            "records": [neighbor],
            "nodes": [
                {"id": seed.uid, "title": seed.title, "roles": ["seed"]},
                {"id": neighbor.uid, "title": neighbor.title, "roles": [direction]},
            ],
            "edges": [
                {
                    "source": seed.uid,
                    "target": neighbor.uid,
                    "direction": direction,
                    "seed_uid": seed.uid,
                }
            ],
            "frontier": {"request_count": 1, "stop_reason": "completed"},
        }


def _config(**updates):
    values = dict(
        data_source="openalex",
        discipline_fields=(),
        search_field="",
        expand_citations=False,
        fetch_abstracts=False,
        retrieval_pool_max=3000,
        crawler_enabled=True,
        candidate_selector_enabled=True,
        citation_feedback_enabled=True,
        crawler_max_reader_requests=8,
        crawler_max_citation_requests=4,
        crawler_max_wall_seconds=30,
        crawler_low_yield_round_limit=2,
        citation_seed_count=3,
        citation_per_seed=1,
        citation_depth=2,
    )
    values.update(updates)
    return SimpleNamespace(**values)


def _agent(config, selector, abstract_fetcher=None):
    agent = PaperSeekAgent(config, _UnusedLlm(), abstract_fetcher=abstract_fetcher)
    agent.search_plan = SearchPlan(
        intent="Find causal bandit methods for intervention selection",
        core_concepts=["causal bandits", "intervention selection"],
    )
    agent.search_run_state = SearchRunState(
        question="question",
        source="openalex",
        search_plan=agent.search_plan.model_dump(),
    )
    agent._candidate_selector_instance = selector
    return agent


class CandidateFeedbackIntegrationTest(unittest.TestCase):
    def test_disabled_selector_still_records_candidates_for_ablation_observability(self):
        agent = _agent(_config(candidate_selector_enabled=False), _Selector())
        candidate = PaperRecord(
            uid="observable",
            title="Observable baseline candidate",
            abstract="Metadata remains unchanged.",
            provider="openalex",
        )

        selected = agent._prepare_candidates("question", [candidate])

        self.assertEqual(selected, [candidate])
        self.assertIn(document_key(candidate), agent.search_run_state.candidate_queue.ledger)
        self.assertEqual(
            agent.search_run_state.candidate_queue.ledger[document_key(candidate)].selector_label,
            "unseen",
        )

    def test_feedback_selector_samples_large_pool_without_dropping_unseen_candidates(self):
        selector = _Selector()
        agent = _agent(_config(crawler_selector_sample_size=24), selector)
        candidates = [
            PaperRecord(
                uid=f"candidate-{index}",
                title=f"Causal intervention candidate {index}",
                abstract="Relevant metadata is available.",
                provider="openalex",
            )
            for index in range(40)
        ]

        selected = agent._prepare_candidates("question", candidates)

        self.assertEqual(len(selected), 40)
        self.assertEqual(sum(len(call) for call in selector.calls), 24)
        labels = {
            evidence.selector_label
            for evidence in agent.search_run_state.candidate_queue.ledger.values()
        }
        self.assertEqual(labels, {"include", "unseen"})

    def test_selector_sampling_also_applies_without_citation_feedback(self):
        selector = _Selector()
        agent = _agent(
            _config(
                crawler_selector_sample_size=24,
                citation_feedback_enabled=False,
                expand_citations=False,
            ),
            selector,
        )
        candidates = [
            PaperRecord(
                uid=f"legacy-candidate-{index}",
                title=f"Legacy causal intervention candidate {index}",
                abstract="Relevant metadata is available.",
                provider="openalex",
            )
            for index in range(40)
        ]

        selected = agent._prepare_candidates("question", candidates)

        self.assertEqual(len(selected), 40)
        self.assertEqual(sum(len(call) for call in selector.calls), 24)
        labels = {
            evidence.selector_label
            for evidence in agent.search_run_state.candidate_queue.ledger.values()
        }
        self.assertEqual(labels, {"include", "unseen"})

    def test_uncertain_missing_abstract_is_enriched_and_reselected(self):
        selector = _Selector()
        fetcher = _AbstractFetcher()
        agent = _agent(_config(), selector, fetcher)
        relevant = PaperRecord(
            uid="W1",
            title="Causal intervention selection",
            abstract="",
            identifiers=PaperIdentifiers(doi="10.1000/example"),
            provider="openalex",
        )
        excluded = PaperRecord(
            uid="W2",
            title="Off topic astronomy",
            abstract="Unrelated astronomy research.",
            provider="openalex",
        )

        selected = agent._prepare_candidates("question", [relevant, excluded])

        self.assertEqual([document.uid for document in selected], ["W1"])
        self.assertEqual(fetcher.dois, ["10.1000/example"])
        self.assertGreaterEqual(len(selector.calls), 2)
        evidence = agent.search_run_state.candidate_queue.ledger[document_key(relevant)]
        self.assertEqual(evidence.selector_label, "include")
        self.assertTrue(evidence.selector_input_hash)
        self.assertEqual(agent.search_run_state.action_frontier.budget.reader_requests, 1)

    def test_uncertain_candidates_can_be_removed_only_for_false_negative_ablation(self):
        selector = _Selector()
        agent = _agent(_config(candidate_selector_keep_uncertain=False), selector)
        uncertain = PaperRecord(
            uid="W3",
            title="Possibly relevant causal method",
            abstract="",
            provider="openalex",
        )

        selected = agent._prepare_candidates("question", [uncertain])

        self.assertEqual(selected, [])
        evidence = agent.search_run_state.candidate_queue.ledger[document_key(uncertain)]
        self.assertEqual(evidence.selector_label, "uncertain")

    def test_citation_candidates_are_selected_before_deeper_expansion(self):
        selector = _Selector()
        agent = _agent(_config(expand_citations=True), selector)
        provider = _CitationProvider()
        agent.provider = provider
        seed = PaperRecord(
            uid="S1",
            title="Causal intervention selection",
            abstract="Relevant seed abstract.",
            provider="openalex",
        )

        selected = agent._prepare_candidates("question", [seed])

        self.assertGreater(len(selected), 1)
        self.assertTrue(any(seed_uid != "S1" for seed_uid, _ in provider.calls))
        self.assertLessEqual(len(provider.calls), 4)
        self.assertEqual(agent.citation_map["status"], "complete")
        self.assertGreater(agent.citation_map["added_candidates"], 0)
        self.assertEqual(
            agent.search_run_state.action_frontier.budget.citation_requests,
            len(provider.calls),
        )
        citation_keys = {
            outcome.action_id
            for outcome in agent.search_run_state.action_frontier.outcomes
        }
        self.assertTrue(citation_keys)

    def test_citation_feedback_checkpoint_resume_does_not_repeat_completed_action(self):
        cancel = Event()
        snapshots = []
        first_selector = _Selector()
        first_agent = _agent(_config(expand_citations=True), first_selector)
        first_provider = _CitationProvider()
        first_agent.provider = first_provider
        first_agent.run_question = "question"
        first_agent.checkpoint_handler = snapshots.append
        first_agent.cancel_check = cancel.is_set
        seed = PaperRecord(
            uid="S1",
            title="Causal intervention selection",
            abstract="Relevant seed abstract.",
            provider="openalex",
        )

        def save_and_cancel(payload):
            snapshots.append(payload)
            if payload["stage"] == "citation_layer":
                cancel.set()

        first_agent.checkpoint_handler = save_and_cancel
        with self.assertRaises(SearchCancelled):
            first_agent._prepare_candidates("question", [seed])

        checkpoint = SearchCheckpoint.model_validate(snapshots[-1])
        completed_before = {
            outcome.action_id
            for outcome in SearchRunState.model_validate(checkpoint.search_state).action_frontier.outcomes
        }
        self.assertTrue(completed_before)

        resumed_selector = _Selector()
        resumed_agent = _agent(_config(expand_citations=True), resumed_selector)
        resumed_provider = _CitationProvider()
        resumed_agent.provider = resumed_provider
        resumed_agent._restore_checkpoint_state(checkpoint)
        restored_records = paper_records_from_checkpoint(checkpoint.records)

        resumed_agent._prepare_candidates("question", restored_records)

        resumed_outcomes = resumed_agent.search_run_state.action_frontier.outcomes
        self.assertEqual(
            len({outcome.action_id for outcome in resumed_outcomes}),
            len(resumed_outcomes),
        )
        self.assertTrue(completed_before.issubset({outcome.action_id for outcome in resumed_outcomes}))


if __name__ == "__main__":
    unittest.main()
