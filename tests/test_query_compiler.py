import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paperseek_core.agent import PaperSeekAgent
from paperseek_core.harness import validate_source_query
from paperseek_core.planning import ConceptGroup, QueryView, SearchPlan
from paperseek_core.query_compiler import (
    CrossrefQueryCompiler,
    GoogleScholarQueryCompiler,
    PaperHubQueryCompiler,
    PubMedQueryCompiler,
    SemanticScholarQueryCompiler,
    WosQueryCompiler,
    compile_query_view,
    query_compiler_sources,
    supports_query_portfolio,
)
from paperseek_core.domain.models import PaperRecord
from paperseek_core.sources.contracts import ProviderSearchResult, SearchMetadata
from paperseek_core.sources.paperhub import PaperHubProvider


def sample_view() -> QueryView:
    return QueryView(
        view_id="governance",
        purpose="Find AI governance accountability research",
        concept_groups=[
            ConceptGroup(label="topic", terms=["AI governance", "artificial intelligence governance"]),
            ConceptGroup(label="mechanism", terms=["accountability", "public oversight"], field_hint="title"),
            ConceptGroup(label="optional", terms=["public administration"], required=False),
        ],
        exclusions=["corporate finance"],
    )


class QueryCompilerRegistryTest(unittest.TestCase):
    def test_registry_covers_every_current_source(self):
        expected = {
            "arxiv",
            "crossref",
            "googlescholar",
            "openalex",
            "paperhub",
            "pubmed",
            "semanticscholar",
            "wos",
        }
        self.assertEqual(set(query_compiler_sources()), expected)
        self.assertTrue(all(supports_query_portfolio(source) for source in expected))
        self.assertFalse(supports_query_portfolio("unknown"))

    def test_registry_rejects_unknown_source(self):
        with self.assertRaisesRegex(ValueError, "No structured query compiler"):
            compile_query_view("unknown", sample_view())

    def test_every_compiler_output_passes_source_preflight(self):
        for source in query_compiler_sources():
            with self.subTest(source=source):
                compiled = compile_query_view(source, sample_view())
                validation = validate_source_query(source, compiled.query)
                self.assertTrue(validation.ok, validation.issue)


class PlainTextCompilerTest(unittest.TestCase):
    def test_crossref_emits_plain_bibliographic_terms(self):
        query = CrossrefQueryCompiler().compile(sample_view()).query

        self.assertEqual(
            query,
            "AI governance artificial intelligence governance accountability public oversight",
        )
        self.assertNotRegex(query, r"\b(?:AND|OR|NOT)\b")
        self.assertNotIn("query.bibliographic=", query)
        self.assertNotIn("[Title", query)

    def test_semantic_scholar_relevance_query_uses_plain_text(self):
        query = SemanticScholarQueryCompiler().compile(sample_view()).query

        self.assertEqual(
            query,
            "AI governance artificial intelligence governance accountability public oversight",
        )
        self.assertNotRegex(query, r"[+*|]")
        self.assertNotRegex(query, r"\b(?:AND|OR|NOT)\b")

    def test_semantic_scholar_replaces_hyphens_that_break_relevance_search(self):
        view = QueryView(
            view_id="hyphenated",
            concept_groups=[
                ConceptGroup(
                    label="topic",
                    terms=["retrieval-augmented generation", "human–computer interaction"],
                )
            ],
        )

        query = SemanticScholarQueryCompiler().compile(view).query

        self.assertEqual(query, "retrieval augmented generation human computer interaction")


class StructuredCompilerTest(unittest.TestCase):
    def test_pubmed_emits_balanced_fielded_boolean_query(self):
        query = PubMedQueryCompiler().compile(sample_view()).query

        self.assertEqual(
            query,
            '("AI governance"[Title/Abstract] OR "artificial intelligence governance"[Title/Abstract]) '
            'AND (accountability[Title] OR "public oversight"[Title]) NOT "corporate finance"[Title/Abstract]',
        )
        self.assertEqual(query.count("("), query.count(")"))


class _UnusedLlm:
    def chat(self, messages, temperature=0.3):
        raise AssertionError("portfolio execution should not call the LLM")


class _RecordingProvider:
    def __init__(self, source):
        self.source = source
        self.queries = []

    def search(self, query, limit=50, page=1, lane="relevance", **kwargs):
        self.queries.append(query)
        suffix = len(self.queries)
        return ProviderSearchResult(
            metadata=SearchMetadata(total=1, page=page, limit=limit),
            hits=[PaperRecord(uid=f"{self.source}:{suffix}", title=f"{self.source} portfolio result {suffix}", provider=self.source)],
        )


class QueryPortfolioAgentIntegrationTest(unittest.TestCase):
    def _agent(self, source):
        config = SimpleNamespace(
            data_source=source,
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=5,
            target_max=50,
            max_iterations=1,
            fetch_abstracts=False,
            retrieval_pool_max=3000,
            query_portfolio_enabled=True,
            query_portfolio_max=1,
            query_portfolio_limit=10,
        )
        agent = PaperSeekAgent(config, _UnusedLlm())
        agent.provider = _RecordingProvider(source)
        agent.search_plan = SearchPlan(
            intent="Find AI governance accountability research",
            query_views=[sample_view()],
        )
        return agent

    def test_agent_executes_portfolio_for_every_provider_backed_source(self):
        for source in ("openalex", "arxiv", "crossref", "semanticscholar", "pubmed", "googlescholar", "paperhub"):
            with self.subTest(source=source):
                agent = self._agent(source)
                primary = [PaperRecord(uid=f"{source}:primary", title="Primary result", provider=source)]

                combined = agent._execute_query_portfolio("AI governance", "primary query", primary, [])

                self.assertEqual(len(agent.provider.queries), 1)
                self.assertEqual(len(combined), 2)
                self.assertEqual(agent.query_portfolio[0]["status"], "completed")
                self.assertEqual(agent.query_portfolio[0]["added_unique"], 1)

    def test_compiler_failure_preserves_primary_results(self):
        agent = self._agent("pubmed")
        primary = [PaperRecord(uid="pubmed:primary", title="Primary result", provider="pubmed")]

        with patch("paperseek_core.query_view_selector.compile_query_view", side_effect=ValueError("invalid view")):
            combined = agent._execute_query_portfolio("AI governance", "primary query", primary, [])

        self.assertEqual(combined, primary)
        self.assertEqual(agent.provider.queries, [])
        self.assertEqual(agent.query_portfolio[0]["status"], "failed")
        self.assertIn("invalid view", agent.query_portfolio[0]["error"])

    def test_google_scholar_uses_small_or_groups_and_exclusion(self):
        query = GoogleScholarQueryCompiler().compile(sample_view()).query

        self.assertEqual(
            query,
            '("AI governance" OR "artificial intelligence governance") '
            '(accountability OR "public oversight") -"corporate finance"',
        )
        self.assertNotIn(" AND ", query)

    def test_paperhub_output_round_trips_through_local_parser(self):
        query = PaperHubQueryCompiler().compile(sample_view()).query
        parsed = PaperHubProvider._parse_query(query)

        self.assertEqual(
            parsed.groups,
            [["ai governance", "artificial intelligence governance"], ["accountability", "public oversight"]],
        )
        self.assertEqual(parsed.excludes, ["corporate finance"])

    def test_wos_wraps_topic_groups_once(self):
        query = WosQueryCompiler().compile(sample_view()).query

        self.assertEqual(
            query,
            'TS=(("AI governance" OR "artificial intelligence governance") AND '
            '(accountability OR "public oversight") NOT "corporate finance")',
        )
        self.assertEqual(query.count("("), query.count(")"))


if __name__ == "__main__":
    unittest.main()
