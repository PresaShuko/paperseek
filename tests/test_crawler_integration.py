import unittest
from types import SimpleNamespace

from paperseek_core.agent import PaperSeekAgent
from paperseek_core.harness.schemas import SearchRunState, SelectorBatch, SelectorDecision
from paperseek_core.planning import ConceptGroup, QueryView, SearchPlan
from paperseek_core.retrieval import document_key
from paperseek_core.sources.providers import PaperRecord, ProviderSearchResult, SearchMetadata


class _UnusedLlm:
    pass


class _GapSelector:
    def __init__(self):
        self.calls = []

    @staticmethod
    def cache_key(question, plan, document):
        return f"selector:{document_key(document)}:{getattr(document, 'abstract', '')}"

    def select(self, question, plan, documents):
        documents = list(documents)
        self.calls.append([document_key(document) for document in documents])
        if len(self.calls) == 1:
            return SelectorBatch(
                decisions=[
                    SelectorDecision(
                        candidate_id=document_key(document),
                        label="uncertain",
                        relevance_score=0.5,
                        missing_concepts=["intervention selection"],
                        recommended_actions=["none"],
                        reason_codes=["missing_intervention_concept"],
                    )
                    for document in documents
                ]
            )
        return SelectorBatch(
            decisions=[
                SelectorDecision(
                    candidate_id=document_key(document),
                    label="include",
                    relevance_score=0.9,
                    concept_coverage={"intervention selection": 1.0},
                    evidence=["The title directly covers intervention selection."],
                    recommended_actions=["none"],
                    reason_codes=["direct_match"],
                )
                for document in documents
            ]
        )


class _ExcludeSelector:
    @staticmethod
    def cache_key(question, plan, document):
        return f"exclude:{document_key(document)}"

    def select(self, question, plan, documents):
        return SelectorBatch(
            decisions=[
                SelectorDecision(
                    candidate_id=document_key(document),
                    label="exclude",
                    relevance_score=0.05,
                    evidence=["The candidate explicitly studies an unrelated object."],
                    recommended_actions=["none"],
                )
                for document in documents
            ]
        )


class _Provider:
    def __init__(self, source="openalex", *, fail=False):
        self.source = source
        self.fail = fail
        self.queries = []

    def search(self, query, limit=50, page=1, lane="relevance", **kwargs):
        self.queries.append(query)
        if self.fail:
            raise RuntimeError(f"{self.source} unavailable")
        return ProviderSearchResult(
            metadata=SearchMetadata(total=1, page=page, limit=limit),
            hits=[
                PaperRecord(
                    uid=f"{self.source}-{len(self.queries)}",
                    title="Intervention selection with causal bandits",
                    abstract="A method for choosing interventions.",
                    provider=self.source,
                )
            ],
        )


def _config():
    return SimpleNamespace(
        data_source="openalex",
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
        crawler_enabled=True,
        candidate_selector_enabled=True,
        crawler_intermediate_selector_enabled=True,
        crawler_max_wall_seconds=30,
    )


def _plan():
    return SearchPlan(
        intent="Find causal bandit methods for choosing interventions",
        core_concepts=["causal bandits", "intervention selection"],
        query_views=[
            QueryView(
                view_id="direct",
                view_type="direct_terminology",
                purpose="Direct terminology",
                concept_groups=[ConceptGroup(label="causal bandits", terms=["causal bandits"])],
            ),
            QueryView(
                view_id="interventions",
                view_type="mechanism_method",
                purpose="Missing intervention concept",
                concept_groups=[
                    ConceptGroup(label="intervention selection", terms=["intervention selection"])
                ],
            ),
        ],
    )


class CrawlerAgentIntegrationTest(unittest.TestCase):
    def test_intermediate_selector_is_off_by_default_but_final_selector_remains_available(self):
        config = _config()
        config.crawler_intermediate_selector_enabled = False
        agent = PaperSeekAgent(config, _UnusedLlm())
        agent.provider = _Provider()
        agent.search_plan = _plan()
        agent.search_run_state = SearchRunState(
            question="question",
            source="openalex",
            current_query="primary query",
            search_plan=agent.search_plan.model_dump(),
        )
        selector = _GapSelector()
        agent._candidate_selector_instance = selector
        primary = [PaperRecord(uid="primary", title="Causal bandits overview", provider="openalex")]

        combined = agent._execute_query_portfolio("question", "primary query", primary, [])

        self.assertEqual(selector.calls, [])
        self.assertEqual(len(agent.provider.queries), 1)
        self.assertEqual(len(combined), 2)
        self.assertTrue(agent._candidate_selector_active())

    def test_query_iteration_selector_feedback_drives_redirect_decision(self):
        agent = PaperSeekAgent(_config(), _UnusedLlm())
        agent.search_plan = _plan()
        agent.search_run_state = SearchRunState(
            question="question",
            source="openalex",
            current_query="primary query",
            search_plan=agent.search_plan.model_dump(),
        )
        agent.run_question = "question"
        agent.search_intent = agent.search_plan.audit_summary()
        agent._candidate_selector_instance = _ExcludeSelector()
        hits = [
            PaperRecord(
                uid=f"off-{index}",
                title=f"Unrelated astronomy result {index}",
                abstract="This paper studies stellar observations.",
                provider="openalex",
            )
            for index in range(4)
        ]

        batch = agent._query_iteration_selector_feedback("question", "primary query", hits, 1)
        decision = agent._query_loop_decision(
            "primary query",
            hits,
            25,
            1,
            5,
            13,
            [],
        )

        self.assertEqual(decision.action, "narrow")
        self.assertEqual(agent.last_query_selector_feedback["exclude"], 4)
        self.assertEqual(agent.search_run_state.crawler_state.selector_counts["exclude"], 4)

    def test_primary_selector_gap_changes_first_query_action(self):
        agent = PaperSeekAgent(_config(), _UnusedLlm())
        agent.provider = _Provider()
        agent.search_plan = _plan()
        agent.search_run_state = SearchRunState(
            question="question",
            source="openalex",
            current_query="primary query",
            search_plan=agent.search_plan.model_dump(),
        )
        selector = _GapSelector()
        agent._candidate_selector_instance = selector
        primary = [
            PaperRecord(
                uid="primary",
                title="Causal bandits overview",
                abstract="A broad overview.",
                provider="openalex",
            )
        ]

        combined = agent._execute_query_portfolio("question", "primary query", primary, [])

        self.assertEqual(len(agent.provider.queries), 1)
        self.assertIn("intervention selection", agent.provider.queries[0].casefold())
        self.assertEqual(len(combined), 2)
        self.assertEqual(len(selector.calls), 2)
        self.assertEqual(agent.search_run_state.action_frontier.budget.source_requests, 1)
        self.assertEqual(agent.search_run_state.crawler_state.selector_counts["include"], 1)
        completed = next(item for item in agent.query_portfolio if item["status"] == "completed")
        self.assertEqual(completed["view_id"], "interventions")
        skipped = next(item for item in agent.query_portfolio if item["view_id"] == "direct")
        self.assertEqual(skipped["status"], "skipped_selector")

    def test_frontier_compiles_and_executes_query_views_across_sources(self):
        config = _config()
        config.crawler_sources = ("crossref",)
        config.query_portfolio_max = 3
        agent = PaperSeekAgent(config, _UnusedLlm())
        primary_provider = _Provider("openalex")
        crossref_provider = _Provider("crossref")
        agent.provider = primary_provider
        agent._source_providers["crossref"] = crossref_provider
        agent.search_plan = _plan()
        agent.search_run_state = SearchRunState(
            question="question",
            source="openalex",
            current_query="primary query",
            search_plan=agent.search_plan.model_dump(),
        )
        agent._candidate_selector_instance = _GapSelector()
        primary = [PaperRecord(uid="primary", title="Causal bandits overview", provider="openalex")]

        combined = agent._execute_query_portfolio("question", "primary query", primary, [])

        completed_sources = {
            item["source"] for item in agent.query_portfolio if item["status"] == "completed"
        }
        self.assertEqual(completed_sources, {"openalex", "crossref"})
        self.assertTrue(primary_provider.queries)
        self.assertTrue(crossref_provider.queries)
        self.assertEqual(len(combined), 2)
        self.assertEqual(agent.search_run_state.action_frontier.budget.source_requests, 3)
        self.assertTrue(all(item.get("source") for item in agent.query_view_selection))

    def test_alternate_source_failure_is_isolated_from_primary_candidates(self):
        config = _config()
        config.crawler_sources = ("crossref",)
        config.query_portfolio_max = 1
        agent = PaperSeekAgent(config, _UnusedLlm())
        agent._source_providers["crossref"] = _Provider("crossref", fail=True)
        agent.search_plan = _plan()
        agent.search_run_state = SearchRunState(
            question="question",
            source="openalex",
            current_query="primary query",
            search_plan=agent.search_plan.model_dump(),
        )
        agent._candidate_selector_instance = _GapSelector()
        primary = [PaperRecord(uid="primary", title="Causal bandits overview", provider="openalex")]

        combined = agent._execute_query_portfolio("question", "primary query", primary, [])

        self.assertEqual([document.uid for document in combined], ["primary"])
        failed = [item for item in agent.query_portfolio if item["status"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["source"], "crossref")
        self.assertIn("unavailable", failed[0]["error"])
        self.assertEqual(agent.search_run_state.source, "openalex")
        self.assertEqual(agent.search_run_state.errors[-1].source, "crossref")

    def test_alternate_source_availability_failure_opens_circuit_and_falls_back_to_primary(self):
        config = _config()
        config.crawler_intermediate_selector_enabled = False
        config.crawler_sources = ("crossref",)
        config.query_portfolio_max = 2
        agent = PaperSeekAgent(config, _UnusedLlm())
        primary_provider = _Provider("openalex")
        alternate_provider = _Provider("crossref", fail=True)
        agent.provider = primary_provider
        agent._source_providers["crossref"] = alternate_provider
        agent.search_plan = _plan()
        agent.search_run_state = SearchRunState(
            question="question",
            source="openalex",
            current_query="primary query",
            search_plan=agent.search_plan.model_dump(),
        )
        primary = [PaperRecord(uid="primary", title="Causal bandits overview", provider="openalex")]

        combined = agent._execute_query_portfolio("question", "primary query", primary, [])

        self.assertEqual(len(alternate_provider.queries), 1)
        self.assertEqual(len(primary_provider.queries), 1)
        self.assertEqual({document.provider for document in combined}, {"openalex"})
        self.assertTrue(
            any(item["status"] == "skipped_source_unavailable" for item in agent.query_portfolio)
        )
        self.assertTrue(
            any(item["status"] == "completed" and item["source"] == "openalex" for item in agent.query_portfolio)
        )


if __name__ == "__main__":
    unittest.main()
