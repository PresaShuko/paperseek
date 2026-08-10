import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paperseek_core.agent import PaperSeekAgent
from paperseek_core.domain.models import PaperRecord
from paperseek_core.llm import LLMError
from paperseek_core.planning import parse_search_plan
from paperseek_core.ranking import EmptyRankingBatchError
from tests.helpers import read_text


QUESTION = "How do transparent AI decision systems affect accountability in public agencies?"


class FixtureLLM:
    def __init__(self, *fixture_paths: str):
        self.responses = [read_text(path) for path in fixture_paths]
        self.calls = []
        self.last_response_info = {"finish_reason": "stop", "completion_tokens": 64}

    def _respond(self, messages, *, temperature, max_tokens):
        if not self.responses:
            raise AssertionError("fixture response sequence was exhausted")
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.responses.pop(0)

    def chat_json(self, messages, *, temperature=0.0, max_tokens=4096):
        return self._respond(messages, temperature=temperature, max_tokens=max_tokens)

    def chat(self, messages, temperature=0.3):
        return self._respond(messages, temperature=temperature, max_tokens=None)


def fixture_agent(llm, *, query_portfolio_enabled=False):
    config = SimpleNamespace(
        data_source="arxiv",
        discipline_fields=(),
        search_field="",
        expand_citations=False,
        query_portfolio_enabled=query_portfolio_enabled,
    )
    return PaperSeekAgent(config, llm)


def ranking_documents():
    return [
        PaperRecord(
            uid="fixture:accountability",
            title="Accountable Automated Decisions in Public Agencies",
            abstract="A controlled study of accountability mechanisms for automated public decisions.",
            provider="arxiv",
            raw={},
        ),
        PaperRecord(
            uid="fixture:audit",
            title="Auditing Public-Sector Algorithms",
            abstract="A governance framework for auditing algorithms used by public institutions.",
            provider="arxiv",
            raw={},
        ),
        PaperRecord(
            uid="fixture:transparency",
            title="Transparency Practices for Decision Support",
            abstract="A general survey of transparency practices for decision-support systems.",
            provider="arxiv",
            raw={},
        ),
    ]


class LLMStructuredOutputFixtureTest(unittest.TestCase):
    def test_intent_fixture_uses_current_search_plan_schema(self):
        llm = FixtureLLM("tests/fixtures/llm/intent_search_plan.json")
        agent = fixture_agent(llm, query_portfolio_enabled=True)

        audit = agent._analyze_intent(QUESTION)

        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(llm.calls[0]["temperature"], 0.0)
        self.assertEqual(llm.calls[0]["max_tokens"], 4096)
        self.assertEqual(
            set(agent.search_plan.model_dump()),
            {
                "intent",
                "question_type",
                "core_concepts",
                "must_have_facets",
                "optional_facets",
                "required_relation",
                "likely_synonyms",
                "adjacent_concepts",
                "boundaries",
                "adjustment_strategy",
                "ambiguities",
                "query_views",
            },
        )
        self.assertEqual(
            set(agent.search_plan.query_views[0].model_dump()),
            {"view_id", "view_type", "purpose", "concept_groups", "exclusions"},
        )
        self.assertEqual(len(agent.search_plan.query_views), 3)
        self.assertIn("required_relation: effect of transparent AI decision systems on accountability", audit)

    def test_invalid_intent_output_gets_one_repair(self):
        llm = FixtureLLM(
            "tests/fixtures/llm/intent_invalid.txt",
            "tests/fixtures/llm/intent_search_plan.json",
        )
        agent = fixture_agent(llm, query_portfolio_enabled=True)

        agent._analyze_intent(QUESTION)

        self.assertEqual(len(llm.calls), 2)
        self.assertEqual([item["attempt"] for item in agent.search_plan_diagnostics], [1, 2])
        self.assertTrue(agent.search_plan_diagnostics[0]["coverage_gaps"])
        self.assertEqual(agent.search_plan_diagnostics[1]["coverage_gaps"], [])
        self.assertEqual(agent.search_plan.intent, "Find evidence on how transparent AI decision systems affect accountability in public agencies.")

    def test_two_invalid_intent_outputs_use_deterministic_fallback(self):
        llm = FixtureLLM(
            "tests/fixtures/llm/intent_invalid.txt",
            "tests/fixtures/llm/intent_invalid.txt",
        )
        agent = fixture_agent(llm, query_portfolio_enabled=True)

        audit = agent._analyze_intent(QUESTION)

        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(agent.search_plan.query_views, [])
        self.assertEqual(agent.search_plan.intent, QUESTION)
        self.assertIn("Structured planning fallback", audit)

    def test_query_generation_and_iteration_fixtures_use_query_schema(self):
        llm = FixtureLLM(
            "tests/fixtures/llm/query_generated.json",
            "tests/fixtures/llm/query_broadened.json",
            "tests/fixtures/llm/query_narrowed.json",
        )
        agent = fixture_agent(llm)

        generated = agent._generate_query(QUESTION)
        broadened = agent._broaden_query(QUESTION, generated)
        narrowed = agent._narrow_query(QUESTION, broadened)

        self.assertEqual(generated, 'all:"AI governance" AND all:accountability')
        self.assertEqual(
            broadened,
            'all:("AI governance" OR "algorithmic governance") AND all:accountability',
        )
        self.assertEqual(
            narrowed,
            'all:"AI governance" AND all:accountability AND all:"public agency"',
        )
        self.assertEqual(len(llm.calls), 3)
        self.assertTrue(all(call["temperature"] == 0.0 for call in llm.calls))
        self.assertTrue(all(call["max_tokens"] == 2048 for call in llm.calls))
        self.assertEqual(agent.last_query_audit, "Added the public-agency context as one narrowing group.")

    @patch("paperseek_core.query_contract.pydantic_ai_query_retry_enabled", return_value=False)
    def test_malformed_query_output_gets_one_native_json_repair(self, _retry_enabled):
        llm = FixtureLLM(
            "tests/fixtures/llm/query_malformed.json",
            "tests/fixtures/llm/query_broadened.json",
        )
        agent = fixture_agent(llm)

        query = agent._generate_query(QUESTION)

        self.assertEqual(
            query,
            'all:("AI governance" OR "algorithmic governance") AND all:accountability',
        )
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("replacement arXiv search_query string", llm.calls[1]["messages"][-1]["content"])

    @patch("paperseek_core.query_contract.pydantic_ai_query_retry_enabled", return_value=False)
    def test_failed_query_repair_keeps_previous_query_but_generation_fails(self, _retry_enabled):
        revision_llm = FixtureLLM(
            "tests/fixtures/llm/query_malformed.json",
            "tests/fixtures/llm/query_invalid.txt",
        )
        revision_agent = fixture_agent(revision_llm)
        previous_query = 'all:"AI governance" AND all:accountability'

        revised = revision_agent._broaden_query(QUESTION, previous_query)

        self.assertEqual(revised, previous_query)
        self.assertEqual(len(revision_llm.calls), 2)
        self.assertEqual(revision_agent.last_query_audit, "")

        generation_llm = FixtureLLM(
            "tests/fixtures/llm/query_malformed.json",
            "tests/fixtures/llm/query_invalid.txt",
        )
        generation_agent = fixture_agent(generation_llm)

        with self.assertRaisesRegex(LLMError, "did not return valid JSON with a query field"):
            generation_agent._generate_query(QUESTION)

        self.assertEqual(len(generation_llm.calls), 2)

    def test_ranking_score_and_reason_fixtures_use_current_codecs(self):
        llm = FixtureLLM(
            "tests/fixtures/llm/ranking_scores.json",
            "tests/fixtures/llm/ranking_reasons.json",
        )
        agent = fixture_agent(llm)
        agent.search_plan = parse_search_plan(
            read_text("tests/fixtures/llm/intent_search_plan.json"),
            QUESTION,
        )
        documents = ranking_documents()

        scores = agent._score_ranking_batch(QUESTION, documents, llm)
        scores = agent._attach_ranking_reasons(QUESTION, documents, scores, llm)

        self.assertEqual(
            scores,
            [
                {
                    "uid": "fixture:accountability",
                    "score": 9.0,
                    "reasoning": "Directly addresses accountable AI use in public agencies.",
                },
                {
                    "uid": "fixture:audit",
                    "score": 6.0,
                    "reasoning": "Provides relevant governance mechanisms but less direct outcome evidence.",
                },
                {
                    "uid": "fixture:transparency",
                    "score": 3.0,
                    "reasoning": "Offers adjacent transparency context with weaker accountability focus.",
                },
            ],
        )
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0]["max_tokens"], 4096)
        self.assertEqual(llm.calls[1]["max_tokens"], 2048)

    def test_two_invalid_ranking_outputs_raise_empty_batch_error(self):
        llm = FixtureLLM(
            "tests/fixtures/llm/query_invalid.txt",
            "tests/fixtures/llm/query_invalid.txt",
        )
        agent = fixture_agent(llm)

        with self.assertRaisesRegex(EmptyRankingBatchError, "omitted 3/3 candidate"):
            agent._score_ranking_batch(QUESTION, ranking_documents(), llm)

        self.assertEqual(len(llm.calls), 2)

    def test_invalid_reason_output_keeps_scores_without_inventing_reasons(self):
        llm = FixtureLLM("tests/fixtures/llm/query_invalid.txt")
        agent = fixture_agent(llm)
        documents = ranking_documents()
        scores = [
            {"uid": document.uid, "score": score, "reasoning": "stale"}
            for document, score in zip(documents, (9.0, 6.0, 3.0))
        ]

        output = agent._attach_ranking_reasons(QUESTION, documents, scores, llm)

        self.assertTrue(all(item["reasoning"] == "" for item in output))
        self.assertEqual(len(llm.calls), 1)


if __name__ == "__main__":
    unittest.main()
