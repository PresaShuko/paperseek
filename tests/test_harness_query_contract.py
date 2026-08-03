import unittest
from types import SimpleNamespace

from paperseek_core.agent import PaperSeekAgent
from paperseek_core.harness import (
    dedupe_repeated_top_level_conjunctions,
    extract_json_object_text,
    parse_query_proposal,
    pydantic_ai_available,
    run_query_proposal_agent,
    query_response_from_json,
    validate_source_query,
)
from tests.helpers import temporary_env


class QueryContractTest(unittest.TestCase):
    def test_extracts_first_balanced_json_object_from_text(self):
        raw = 'Reasoning text. {"query":"AI governance","rationale":"structured"} trailing text'

        self.assertEqual(
            extract_json_object_text(raw),
            '{"query":"AI governance","rationale":"structured"}',
        )

    def test_parses_code_fenced_query_proposal(self):
        proposal = parse_query_proposal(
            '```json\n{"query":"graph neural networks","rationale":["kept graph","kept learning"]}\n```'
        )

        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.query, "graph neural networks")
        self.assertEqual(proposal.rationale, "kept graph; kept learning")

    def test_accepts_nested_query_alias(self):
        query, rationale = query_response_from_json(
            '{"source_query":{"value":"AI governance accountability"},"reason":"provider alias"}'
        )

        self.assertEqual(query, "AI governance accountability")
        self.assertEqual(rationale, "provider alias")

    def test_rejects_free_text_reasoning_as_query(self):
        query, rationale = query_response_from_json("Let's finalize: AI governance AND accountability")

        self.assertEqual(query, "")
        self.assertEqual(rationale, "")

    def test_validates_structured_source_query_syntax(self):
        validation = validate_source_query("openalex", '("AI governance" OR "AI policy"')

        self.assertFalse(validation.ok)
        self.assertIn("unbalanced", validation.issue)

    def test_openalex_requires_grouping_when_and_intersects_or_synonyms(self):
        validation = validate_source_query(
            "openalex",
            '"GUI agents" OR "computer-use agents" AND (security OR attacks)',
        )

        self.assertFalse(validation.ok)
        self.assertIn("parenthesized", validation.issue)
        self.assertTrue(
            validate_source_query(
                "openalex",
                '("GUI agents" OR "computer-use agents") AND (security OR attacks)',
            ).ok
        )

    def test_openalex_rejects_search_values_too_long_for_safe_request_url(self):
        validation = validate_source_query("openalex", " ".join(["governance"] * 400))

        self.assertFalse(validation.ok)
        self.assertIn("too long", validation.issue)

    def test_dedupes_repeated_top_level_and_clauses_without_changing_boolean_meaning(self):
        query = (
            '("remote work" OR telework) AND (productivity OR well-being) AND '
            '("remote work" OR telework) AND (productivity OR well-being)'
        )

        self.assertEqual(
            dedupe_repeated_top_level_conjunctions(query),
            '("remote work" OR telework) AND (productivity OR well-being)',
        )

    def test_rejects_truncated_minimal_boolean_query(self):
        validation = validate_source_query("googlescholar", '("AI governance" OR "AI policy"')

        self.assertFalse(validation.ok)
        self.assertIn("unbalanced", validation.issue)

    def test_preflight_enforces_each_source_query_dialect(self):
        invalid_queries = {
            "openalex": "AI govern*",
            "arxiv": 'title:"graph neural networks"',
            "crossref": "AI governance AND accountability",
            "semanticscholar": 'title:"AI governance"',
            "pubmed": 'all:"AI governance"',
            "googlescholar": "AI governance AND accountability",
            "paperhub": "GUI agents NOT robotics",
        }

        for source, query in invalid_queries.items():
            with self.subTest(source=source):
                validation = validate_source_query(source, query)
                self.assertFalse(validation.ok)
                self.assertTrue(validation.issue)

    def test_preflight_rejects_unknown_source(self):
        validation = validate_source_query("unknown", "AI governance")

        self.assertFalse(validation.ok)
        self.assertIn("unsupported data source", validation.issue)


class PydanticAIQueryContractTest(unittest.TestCase):
    def setUp(self):
        if not pydantic_ai_available():
            self.skipTest("pydantic-ai-slim is not installed")

    def test_pydantic_ai_adapter_retries_dirty_query_output(self):
        class DirtyThenJsonLLM:
            def __init__(self):
                self.calls = 0
                self.messages = []

            def chat(self, messages, temperature=0.3):
                self.calls += 1
                self.messages.append(messages)
                if self.calls == 1:
                    return "Let's finalize: AI governance AND accountability"
                return '{"query":"AI governance accountability","rationale":"retry corrected dirty output"}'

        llm = DirtyThenJsonLLM()
        proposal = run_query_proposal_agent(
            llm,
            [
                {"role": "system", "content": "Return a JSON query proposal."},
                {"role": "user", "content": "Question: AI governance"},
            ],
            retries=1,
        )

        self.assertEqual(proposal.query, "AI governance accountability")
        self.assertEqual(llm.calls, 2)
        retry_messages = "\n".join(message["content"] for message in llm.messages[-1])
        self.assertIn("json_invalid", retry_messages)

    def test_agent_format_retry_can_use_pydantic_ai_contract(self):
        class DirtyThenJsonLLM:
            def __init__(self):
                self.calls = 0
                self.last_response_info = {}

            def chat(self, messages, temperature=0.3):
                self.calls += 1
                if self.calls == 1:
                    return "But note: the query should be fine"
                return '{"query":"AI governance accountability","rationale":"schema retry"}'

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            openalex_api_key="",
            openalex_email="",
            search_loop_backend="native",
        )
        llm = DirtyThenJsonLLM()
        agent = PaperSeekAgent(config, llm)
        with temporary_env({"PAPERSEEK_PYDANTICAI_QUERY_RETRY": "1"}):
            query = agent._retry_malformed_source_query(
                "AI governance",
                "Let's finalize: AI governance",
                system_prompt="Return a JSON query proposal.",
                log_name="openalex_query_generation",
                output_label="OpenAlex search query string",
                issue="missing query field in JSON response",
            )

        self.assertEqual(query, "AI governance accountability")
        self.assertEqual(llm.calls, 2)
        self.assertEqual(agent.last_query_audit, "schema retry")


if __name__ == "__main__":
    unittest.main()
