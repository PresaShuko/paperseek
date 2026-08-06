import json
import re
import unittest
from types import SimpleNamespace

from paperseek_core.client import ApiException
from paperseek_core.agent import PaperSeekAgent, SearchCancelled
from paperseek_core.harness import (
    ACTION_ACCEPT,
    ACTION_ACCEPT_HIGH,
    ACTION_ACCEPT_POOL,
    ACTION_BROADEN,
    ACTION_EMPTY,
    ACTION_NARROW,
    CITATION_RETRY_REDUCED,
    CITATION_SKIP_EXPANSION,
    RANKING_KEEP_LOCAL_ORDER,
    RANKING_RETRY_LOWER_CONCURRENCY,
    RANKING_RETRY_SAME_TIER,
    RECOVERY_BROADEN_QUERY,
    RECOVERY_FAIL,
    RECOVERY_REPAIR_QUERY,
    RECOVERY_SIMPLIFY_QUERY,
    QueryLoopSnapshot,
    SearchRunState,
    SearchLoopController,
)
from paperseek_core.sources.providers import PaperRecord, ProviderError, ProviderSearchResult, SearchMetadata


def _compact_paper_entries(text):
    entries = []
    for block in text.split("\n\n"):
        local_match = re.search(r"^(\d+)\.$", block, re.MULTILINE)
        paper_match = re.search(r"^\s*Title: Paper (\d+)$", block, re.MULTILINE)
        if local_match and paper_match:
            entries.append((int(local_match.group(1)), int(paper_match.group(1))))
    return entries


def snapshot(**overrides):
    base = dict(
        iteration=1,
        configured_iterations=5,
        adaptive_max_iterations=13,
        total=25,
        target_min=5,
        target_max=50,
        retrieval_pool_min=5,
        retrieval_pool_max=3000,
        history=[],
    )
    base.update(overrides)
    return QueryLoopSnapshot(**base)


class SearchLoopControllerTest(unittest.TestCase):
    def test_accepts_results_inside_target_range(self):
        decision = SearchLoopController().decide(snapshot(total=25))
        self.assertEqual(decision.action, ACTION_ACCEPT)
        self.assertTrue(decision.terminal)

    def test_title_drift_narrows_before_accepting_target_range(self):
        decision = SearchLoopController().decide(snapshot(
            total=25,
            query='"overseas Chinese" investment crowding',
            intent_terms=["overseas", "chinese", "investment", "crowding"],
            top_titles=[
                "Air pollution and regional innovation in European cities",
                "Local government debt and municipal fiscal stress",
                "Environmental regulation intensity and green growth",
            ],
        ))

        self.assertEqual(decision.action, ACTION_NARROW)
        self.assertFalse(decision.terminal)
        self.assertIn("off-intent", decision.message)
        self.assertIn("Title-intent coverage", decision.reason)

    def test_title_drift_does_not_override_adaptive_limit(self):
        decision = SearchLoopController().decide(snapshot(
            total=25,
            iteration=13,
            adaptive_max_iterations=13,
            query='"overseas Chinese" investment crowding',
            intent_terms=["overseas", "chinese", "investment", "crowding"],
            top_titles=[
                "Air pollution and regional innovation in European cities",
                "Local government debt and municipal fiscal stress",
                "Environmental regulation intensity and green growth",
            ],
        ))

        self.assertEqual(decision.action, ACTION_ACCEPT)
        self.assertTrue(decision.terminal)

    def test_accepts_pool_sized_results_without_more_narrowing(self):
        decision = SearchLoopController().decide(snapshot(total=1200, target_max=50, retrieval_pool_max=3000))
        self.assertEqual(decision.action, ACTION_ACCEPT_POOL)
        self.assertTrue(decision.terminal)

    def test_first_large_source_count_is_narrowed_before_materialization(self):
        decision = SearchLoopController().decide(snapshot(total=31561, iteration=1))
        self.assertEqual(decision.action, ACTION_NARROW)
        self.assertFalse(decision.terminal)
        self.assertIn("bounded retrieval pool of 3000", decision.message)

    def test_improving_large_source_count_keeps_narrowing_past_soft_budget(self):
        decision = SearchLoopController().decide(snapshot(
            total=5000,
            iteration=5,
            history=[
                {"iteration": 1, "total": 31561, "action": ACTION_NARROW},
                {"iteration": 2, "total": 18000, "action": ACTION_NARROW},
                {"iteration": 3, "total": 10000, "action": ACTION_NARROW},
                {"iteration": 4, "total": 7000, "action": ACTION_NARROW},
            ],
        ))
        self.assertEqual(decision.action, ACTION_NARROW)
        self.assertFalse(decision.terminal)

    def test_accepts_stalled_large_source_count_into_bounded_pool(self):
        decision = SearchLoopController().decide(snapshot(
            total=5000,
            iteration=5,
            history=[
                {"iteration": 1, "total": 6200, "action": ACTION_NARROW},
                {"iteration": 2, "total": 5900, "action": ACTION_NARROW},
                {"iteration": 3, "total": 5500, "action": ACTION_NARROW},
                {"iteration": 4, "total": 5200, "action": ACTION_NARROW},
            ],
        ))
        self.assertEqual(decision.action, ACTION_ACCEPT_HIGH)
        self.assertTrue(decision.terminal)
        self.assertIn("bounded retrieval", decision.message)

    def test_accepts_large_source_count_at_adaptive_hard_limit(self):
        decision = SearchLoopController().decide(snapshot(total=5000, iteration=13))
        self.assertEqual(decision.action, ACTION_ACCEPT_HIGH)
        self.assertTrue(decision.terminal)
        self.assertIn("adaptive hard limit", decision.message)

    def test_title_drift_can_redirect_large_source_count_within_soft_budget(self):
        decision = SearchLoopController().decide(snapshot(
            total=500000,
            query='"remote work" productivity',
            intent_terms=["remote", "work", "productivity"],
            top_titles=[
                "Air pollution and regional innovation",
                "Urban fiscal policy and local debt",
                "Environmental regulation intensity",
            ],
        ))

        self.assertEqual(decision.action, ACTION_NARROW)
        self.assertFalse(decision.terminal)

    def test_zero_results_broaden_past_configured_soft_budget(self):
        controller = SearchLoopController()
        self.assertEqual(controller.decide(snapshot(total=0, iteration=1)).action, ACTION_BROADEN)
        self.assertEqual(controller.decide(snapshot(total=0, iteration=5)).action, ACTION_BROADEN)
        self.assertEqual(controller.decide(snapshot(total=0, iteration=13, adaptive_max_iterations=13)).action, ACTION_EMPTY)

    def test_repeated_zero_results_stop_before_adaptive_limit(self):
        decision = SearchLoopController().decide(snapshot(
            total=0,
            iteration=3,
            history=[
                {"iteration": 1, "total": 0, "action": "broaden"},
                {"iteration": 2, "total": 0, "action": "broaden"},
            ],
        ))
        self.assertEqual(decision.action, ACTION_EMPTY)

    def test_native_evaluate_appends_validation_observation_and_decision(self):
        controller = SearchLoopController()
        state = SearchRunState(question="AI governance", source="openalex", current_query="AI governance")

        updated, decision = controller.evaluate(state, snapshot(
            query="AI governance",
            total=1200,
            hit_count=2,
            top_titles=["AI Governance", "Responsible AI"],
        ))

        self.assertEqual(decision.action, ACTION_ACCEPT_POOL)
        self.assertEqual(len(updated.validations), 1)
        self.assertTrue(updated.validations[0].ok)
        self.assertEqual(updated.observations[0].top_titles, ["AI Governance", "Responsible AI"])
        self.assertEqual(updated.decisions[0].action, ACTION_ACCEPT_POOL)



    def test_preflight_records_invalid_query_before_source_request(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="")
        updated, validation = SearchLoopController().preflight(
            state,
            '("AI governance" OR "AI policy"',
        )

        self.assertFalse(validation.ok)
        self.assertEqual(validation.stage, "preflight")
        self.assertEqual(updated.current_query, '("AI governance" OR "AI policy"')
        self.assertEqual(updated.validations[0].issue, validation.issue)


    def test_native_source_search_returns_result_and_keeps_state(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="")
        result_obj = object()

        updated, result, error = SearchLoopController().source_search(
            state,
            "AI governance",
            lambda query: result_obj,
        )

        self.assertIs(result, result_obj)
        self.assertIsNone(error)
        self.assertEqual(updated.current_query, "AI governance")
        self.assertEqual(updated.errors, [])

    def test_source_search_records_provider_error_without_swallowing_it(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="")
        exc = ProviderError("openalex", "Invalid query parameters error.", status=400, query="bad query")

        updated, result, error = SearchLoopController().source_search(
            state,
            "bad query",
            lambda query: (_ for _ in ()).throw(exc),
        )

        self.assertIsNone(result)
        self.assertIs(error, exc)
        self.assertEqual(updated.errors[0].stage, "source_search")
        self.assertEqual(updated.errors[0].status, 400)
        self.assertTrue(updated.errors[0].retryable)


    def test_native_recovery_repairs_retryable_provider_error(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="bad query")
        exc = ProviderError("openalex", "Invalid query parameters error.", status=400, query="bad query")

        updated, decision = SearchLoopController().recover_source_error(
            state,
            exc,
            query="bad query",
            repair_attempts=0,
            max_repair_attempts=2,
        )

        self.assertEqual(decision.action, RECOVERY_REPAIR_QUERY)
        self.assertTrue(decision.retryable)
        self.assertEqual(updated.recovery_decisions[0].action, RECOVERY_REPAIR_QUERY)

    def test_native_recovery_fails_when_repair_budget_is_exhausted(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="bad query")
        exc = ProviderError("openalex", "Invalid query parameters error.", status=400, query="bad query")

        updated, decision = SearchLoopController().recover_source_error(
            state,
            exc,
            query="bad query",
            repair_attempts=2,
            max_repair_attempts=2,
        )

        self.assertEqual(decision.action, RECOVERY_FAIL)
        self.assertFalse(decision.retryable)
        self.assertEqual(updated.recovery_decisions[0].action, RECOVERY_FAIL)

    def test_native_recovery_simplifies_wos_server_error_when_variant_exists(self):
        state = SearchRunState(question="AI governance", source="wos", current_query='TS=("AI governance")')
        exc = ApiException(status=512, reason="Server error", body="query too complex")

        updated, decision = SearchLoopController().recover_source_error(
            state,
            exc,
            query='TS=("AI governance")',
            has_server_error_variant=True,
        )

        self.assertEqual(decision.action, RECOVERY_SIMPLIFY_QUERY)
        self.assertTrue(decision.retryable)
        self.assertEqual(updated.recovery_decisions[0].action, RECOVERY_SIMPLIFY_QUERY)

    def test_native_recovery_broadens_wos_query_syntax_error_when_allowed(self):
        state = SearchRunState(question="AI governance", source="wos", current_query='TS=("AI governance")')
        exc = ApiException(status=400, reason="Bad Request", body="query syntax rejected")

        updated, decision = SearchLoopController().recover_source_error(
            state,
            exc,
            query='TS=("AI governance")',
            allow_broaden_query=True,
        )

        self.assertEqual(decision.action, RECOVERY_BROADEN_QUERY)
        self.assertTrue(decision.retryable)
        self.assertEqual(updated.recovery_decisions[0].action, RECOVERY_BROADEN_QUERY)


    def test_native_records_ranking_batch_error_and_lower_concurrency_decision(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="AI governance")
        exc = RuntimeError("LLM API error (429): too many requests")
        controller = SearchLoopController()

        updated, observation = controller.observe_ranking_batch_error(
            state,
            exc,
            step_id="llm_reranking",
            batch_index=2,
            batch_count=8,
            concurrency=32,
            candidate_count=8,
            rate_limited=True,
        )
        updated, decision = controller.recover_ranking_failures(
            updated,
            step_id="llm_reranking",
            concurrency=32,
            next_concurrency=16,
            failed_batches=3,
            failed_candidates=24,
            rate_limited=True,
        )

        self.assertEqual(observation.step_id, "llm_reranking")
        self.assertTrue(observation.rate_limited)
        self.assertEqual(decision.action, RANKING_RETRY_LOWER_CONCURRENCY)
        self.assertEqual(decision.next_concurrency, 16)
        self.assertEqual(updated.ranking_batch_observations[0].batch_index, 2)
        self.assertEqual(updated.ranking_recovery_decisions[0].action, RANKING_RETRY_LOWER_CONCURRENCY)

    def test_native_records_ranking_keep_local_order_at_minimum_concurrency(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="AI governance")

        updated, decision = SearchLoopController().recover_ranking_failures(
            state,
            step_id="llm_reranking",
            concurrency=4,
            next_concurrency=0,
            failed_batches=2,
            failed_candidates=16,
            rate_limited=False,
        )

        self.assertEqual(decision.action, RANKING_KEEP_LOCAL_ORDER)
        self.assertFalse(decision.retryable)
        self.assertEqual(updated.ranking_recovery_decisions[0].failed_candidates, 16)

    def test_native_records_same_tier_retry_for_empty_ranking_output(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="AI governance")

        updated, decision = SearchLoopController().recover_ranking_failures(
            state,
            step_id="llm_reranking",
            concurrency=16,
            next_concurrency=16,
            failed_batches=1,
            failed_candidates=8,
            rate_limited=False,
        )

        self.assertEqual(decision.action, RANKING_RETRY_SAME_TIER)
        self.assertTrue(decision.retryable)
        self.assertEqual(updated.ranking_recovery_decisions[0].next_concurrency, 16)


    def test_native_plans_citation_expansion_roles(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="AI governance")

        updated, decision = SearchLoopController().plan_citation_expansion(
            state,
            candidate_count=100,
            seed_ranking_count=64,
            configured_seed_count=6,
            configured_depth=2,
        )

        self.assertEqual(decision.seed_limit, 6)
        self.assertEqual(decision.depth, 2)
        self.assertEqual((decision.relevance_quota, decision.impact_quota, decision.recent_quota), (3, 1, 2))
        self.assertEqual(updated.citation_planning_decisions[0].candidate_count, 100)


    def test_native_candidate_queue_records_origins_and_duplicates(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="AI governance")
        state = state.with_candidate_queue(
            state.candidate_queue.model_copy(
                update={"records": [{"key": "existing", "id": "existing", "title": "Existing paper"}]}
            )
        )
        controller = SearchLoopController()

        updated, first = controller.update_candidate_queue(
            state,
            candidate_keys=["doi:10.1/example", "uid:W1", "doi:10.1/example", ""],
            origin="retrieval",
        )
        updated, second = controller.update_candidate_queue(
            updated,
            candidate_keys=["uid:W1", "uid:W2"],
            origin="citation_expansion",
        )

        self.assertEqual(first.added, 2)
        self.assertEqual(first.duplicates, 1)
        self.assertEqual(second.added, 1)
        self.assertEqual(second.duplicates, 1)
        self.assertEqual(updated.candidate_queue.origin_counts["retrieval"], 2)
        self.assertEqual(updated.candidate_queue.origin_counts["citation_expansion"], 1)
        self.assertEqual(updated.candidate_queue.duplicate_count, 2)
        self.assertEqual(updated.candidate_queue.keys, ["doi:10.1/example", "uid:W1", "uid:W2"])
        self.assertEqual(updated.candidate_queue.records[0]["title"], "Existing paper")


    def test_native_citation_recovery_retries_with_reduced_budget_then_skips(self):
        state = SearchRunState(question="AI governance", source="openalex", current_query="AI governance")
        exc = ProviderError("openalex", "temporary citation failure", status=503, query="AI governance")
        controller = SearchLoopController()

        updated, observation = controller.observe_citation_traversal(
            state,
            status="error",
            seed_count=6,
            depth=2,
            per_seed=4,
            max_records=160,
            candidate_pool=20,
            error=exc,
        )
        updated, retry = controller.recover_citation_error(
            updated,
            exc,
            seed_count=6,
            depth=2,
            per_seed=4,
            max_records=160,
            retry_attempts=0,
            max_retries=1,
        )
        updated, skip = controller.recover_citation_error(
            updated,
            exc,
            seed_count=6,
            depth=1,
            per_seed=retry.per_seed,
            max_records=retry.max_records,
            retry_attempts=1,
            max_retries=1,
        )

        self.assertEqual(observation.status, "error")
        self.assertEqual(retry.action, CITATION_RETRY_REDUCED)
        self.assertEqual((retry.per_seed, retry.max_records, retry.depth), (2, 80, 1))
        self.assertEqual(skip.action, CITATION_SKIP_EXPANSION)
        self.assertEqual(updated.citation_recovery_decisions[0].action, CITATION_RETRY_REDUCED)
        self.assertEqual(updated.citation_recovery_decisions[1].action, CITATION_SKIP_EXPANSION)



class AgentSearchLoopIntegrationTest(unittest.TestCase):
    def test_ranking_cancellation_is_not_swallowed_by_local_fallback(self):
        class NeverCalledLlm:
            def fork(self):
                return self

            def chat(self, messages, temperature=0.3):
                raise AssertionError("cancelled ranking should not call the LLM")

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=1,
            ranking_concurrency=4,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, NeverCalledLlm())
        agent.cancel_check = lambda: True
        documents = [PaperRecord(uid="W1", title="AI governance", provider="fake")]

        with self.assertRaises(SearchCancelled):
            agent._rank_results("AI governance", documents)

    def test_agent_native_loop_runs_across_supported_sources_without_network(self):
        sources = ("openalex", "crossref", "arxiv", "semanticscholar", "pubmed", "googlescholar", "paperhub")

        class FakeLLM:
            def __init__(self):
                self.calls = 0
                self.last_response_info = {}

            def chat(self, messages, temperature=0.0):
                self.calls += 1
                if self.calls == 1:
                    return '{"intent":"Find graph neural network literature","core_concepts":["graph neural networks"],"likely_synonyms":["GNN"],"boundaries":[],"adjustment_strategy":"Keep a compact source query."}'
                if self.calls == 2:
                    return '{"query":"graph neural networks","rationale":"Compact initial query."}'
                return "[]"

        class UniversalProvider:
            def __init__(self, source):
                self.source = source
                self.queries = []

            def search(self, query, limit=100, page=1, lane="relevance", **kwargs):
                self.queries.append({"query": query, "lane": lane, "kwargs": kwargs})
                return ProviderSearchResult(
                    SearchMetadata(total=7, page=page, limit=limit),
                    [PaperRecord(uid=f"{self.source}-1", title="Graph Neural Networks", provider=self.source)],
                )

        for source in sources:
            with self.subTest(source=source):
                config = SimpleNamespace(
                    data_source=source,
                    discipline_fields=(),
                    search_field="",
                    expand_citations=False,
                    target_min=1,
                    target_max=20,
                    max_iterations=5,
                    fetch_abstracts=False,
                    openalex_api_key="",
                    openalex_email="",
                    crossref_email="",
                    semantic_scholar_api_key="",
                    pubmed_api_key="",
                    pubmed_email="",
                    pubmed_tool="paperseek",
                    serper_api_key="serper-test",
                    retrieval_pool_max=3000,
                    retrieval_pool_min=5,
                )
                agent = PaperSeekAgent(config, FakeLLM())
                provider = UniversalProvider(source)
                agent.provider = provider
                agent._retrieve_candidates = lambda question, query, hits: hits
                agent._rank_results = lambda question, documents, **_: []

                result = agent.search("graph neural networks")

                self.assertEqual(provider.queries[0]["query"], "graph neural networks")
                self.assertEqual(result["source"], source)
                self.assertEqual(result["history"][0]["action"], ACTION_ACCEPT)
                self.assertEqual(result["search_state"]["source"], source)
                self.assertEqual(result["search_state"]["observations"][0]["total"], 7)

    def test_agent_uses_pool_acceptance_instead_of_target_max_narrowing(self):
        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, temperature=0.0):
                self.calls += 1
                if self.calls == 1:
                    return '{"intent":"Find AI governance papers","core_concepts":["AI governance"],"likely_synonyms":[],"boundaries":[],"adjustment_strategy":"Keep AI governance."}'
                if self.calls == 2:
                    return '{"query":"AI governance","rationale":"Initial query."}'
                return "[]"

        class FakeProvider:
            queries = []

            def search(self, query, limit=100, page=1, lane="relevance", **kwargs):
                self.queries.append(query)
                return ProviderSearchResult(
                    SearchMetadata(total=1200, page=1, limit=limit),
                    [PaperRecord(uid="p1", title="AI governance", provider="fake")],
                )

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=5,
            target_max=50,
            max_iterations=5,
            fetch_abstracts=False,
            openalex_api_key="",
            openalex_email="",
            retrieval_pool_max=3000,
            retrieval_pool_min=5,
        )
        agent = PaperSeekAgent(config, FakeLLM())
        provider = FakeProvider()
        agent.provider = provider
        agent._retrieve_candidates = lambda question, query, hits: hits
        agent._rank_results = lambda question, documents, **_: []

        result = agent.search("AI governance")

        self.assertEqual(provider.queries, ["AI governance"])
        self.assertEqual(result["history"][0]["action"], ACTION_ACCEPT_POOL)
        self.assertEqual(result["search_state"]["source"], "openalex")
        self.assertEqual(result["search_state"]["observations"][0]["total"], 1200)
        self.assertEqual(result["search_state"]["decisions"][0]["action"], ACTION_ACCEPT_POOL)

    def test_agent_narrows_first_broad_result_before_pool_acceptance(self):
        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, temperature=0.0):
                self.calls += 1
                if self.calls == 1:
                    return '{"intent":"Find digital innovation architecture literature","core_concepts":["digital innovation","layered modular architecture"],"likely_synonyms":["digital artifacts"],"boundaries":[],"adjustment_strategy":"Keep architecture and innovation together."}'
                if self.calls == 2:
                    return '{"query":"digital technology modularity innovation","rationale":"Initial source query."}'
                if self.calls == 3:
                    return '{"query":"digital innovation layered modular architecture","rationale":"Tighten the broad technology term around the required architecture facet."}'
                return "[]"

        class FakeProvider:
            def __init__(self):
                self.queries = []

            def search(self, query, limit=100, page=1, lane="relevance", **kwargs):
                self.queries.append(query)
                total = 31561 if len(self.queries) == 1 else 1200
                return ProviderSearchResult(
                    SearchMetadata(total=total, page=page, limit=limit),
                    [
                        PaperRecord(uid="p1", title="The New Organizing Logic of Digital Innovation", provider="fake"),
                        PaperRecord(uid="p2", title="Layered Modular Architecture and Digital Artifacts", provider="fake"),
                        PaperRecord(uid="p3", title="Digital Innovation Management", provider="fake"),
                    ],
                )

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=5,
            target_max=50,
            max_iterations=5,
            fetch_abstracts=False,
            openalex_api_key="",
            openalex_email="",
            retrieval_pool_max=3000,
            retrieval_pool_min=5,
        )
        agent = PaperSeekAgent(config, FakeLLM())
        provider = FakeProvider()
        agent.provider = provider
        agent._retrieve_candidates = lambda question, query, hits: hits
        agent._rank_results = lambda question, documents, **_: []

        result = agent.search("digital innovation and layered modular architecture")

        self.assertEqual(
            provider.queries,
            ["digital technology modularity innovation", "digital innovation layered modular architecture"],
        )
        self.assertEqual([row["action"] for row in result["history"]], [ACTION_NARROW, ACTION_ACCEPT_POOL])
        self.assertEqual(result["total"], 1200)

    def test_agent_uses_top_title_drift_to_revise_apparently_acceptable_query(self):
        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, temperature=0.0):
                self.calls += 1
                if self.calls == 1:
                    return '{"intent":"Find overseas Chinese investment crowding literature","core_concepts":["overseas Chinese investment","crowding"],"likely_synonyms":[],"boundaries":["environmental regulation"],"adjustment_strategy":"Keep overseas Chinese and crowding together."}'
                if self.calls == 2:
                    return '{"query":"overseas Chinese investment","rationale":"Initial compact query."}'
                if self.calls == 3:
                    return '{"query":"overseas Chinese investment crowding","rationale":"Top titles were off-intent; add the missing crowding facet."}'
                return "[]"

        class FakeProvider:
            def __init__(self):
                self.queries = []

            def search(self, query, limit=100, page=1, lane="relevance", **kwargs):
                self.queries.append(query)
                if len(self.queries) == 1:
                    return ProviderSearchResult(
                        SearchMetadata(total=25, page=page, limit=limit),
                        [
                            PaperRecord(uid="p1", title="Air pollution and regional innovation in European cities", provider="fake"),
                            PaperRecord(uid="p2", title="Local government debt and municipal fiscal stress", provider="fake"),
                            PaperRecord(uid="p3", title="Environmental regulation intensity and green growth", provider="fake"),
                        ],
                    )
                return ProviderSearchResult(
                    SearchMetadata(total=8, page=page, limit=limit),
                    [PaperRecord(uid="p4", title="Overseas Chinese investment and crowding effects", provider="fake")],
                )

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=5,
            target_max=50,
            max_iterations=5,
            fetch_abstracts=False,
            openalex_api_key="",
            openalex_email="",
            retrieval_pool_max=3000,
            retrieval_pool_min=5,
        )
        agent = PaperSeekAgent(config, FakeLLM())
        provider = FakeProvider()
        agent.provider = provider
        agent._retrieve_candidates = lambda question, query, hits: hits
        agent._rank_results = lambda question, documents, **_: []

        result = agent.search("overseas Chinese investment crowding")

        self.assertEqual(provider.queries, ["overseas Chinese investment", "overseas Chinese investment crowding"])
        self.assertEqual([row["action"] for row in result["history"]], [ACTION_NARROW, ACTION_ACCEPT])
        self.assertIn("off-intent", result["history"][0]["message"])
        self.assertEqual(result["search_state"]["decisions"][0]["action"], ACTION_NARROW)
        self.assertEqual(result["search_state"]["decisions"][1]["action"], ACTION_ACCEPT)

    def test_agent_falls_back_to_recent_nonzero_pool_after_terminal_zero_query(self):
        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, temperature=0.0):
                self.calls += 1
                if self.calls == 1:
                    return '{"intent":"Find knowledge reuse productization literature","core_concepts":["knowledge reuse","productization"],"likely_synonyms":[],"boundaries":[],"adjustment_strategy":"Avoid empty over-constrained queries."}'
                if self.calls == 2:
                    return '{"query":"broad query","rationale":"Initial broad query."}'
                if self.calls == 3:
                    return '{"query":"too narrow query","rationale":"Narrow a large pool."}'
                if self.calls == 4:
                    return '{"query":"still zero query","rationale":"Broaden the zero-result query."}'
                return "[]"

        class FakeProvider:
            def __init__(self):
                self.queries = []

            def search(self, query, limit=100, page=1, lane="relevance", **kwargs):
                self.queries.append(query)
                if query == "broad query":
                    return ProviderSearchResult(
                        SearchMetadata(total=5000, page=page, limit=limit),
                        [
                            PaperRecord(uid="p1", title="Air pollution and regional innovation", provider="fake"),
                            PaperRecord(uid="p2", title="Municipal fiscal stress and local debt", provider="fake"),
                            PaperRecord(uid="p3", title="Environmental regulation and green growth", provider="fake"),
                        ],
                    )
                return ProviderSearchResult(SearchMetadata(total=0, page=page, limit=limit), [])

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=5,
            target_max=50,
            max_iterations=2,
            adaptive_max_iterations=3,
            fetch_abstracts=False,
            openalex_api_key="",
            openalex_email="",
            retrieval_pool_max=3000,
            retrieval_pool_min=5,
        )
        agent = PaperSeekAgent(config, FakeLLM())
        provider = FakeProvider()
        agent.provider = provider
        agent._retrieve_candidates = lambda question, query, hits: hits
        agent._rank_results = lambda question, documents, **_: []

        result = agent.search("knowledge reuse productization")

        self.assertEqual(provider.queries, ["broad query", "too narrow query", "still zero query"])
        self.assertEqual(result["final_query"], "broad query")
        self.assertEqual(result["total"], 5000)
        self.assertEqual([row["action"] for row in result["history"]], [ACTION_NARROW, ACTION_BROADEN, ACTION_EMPTY, "fallback"])
        self.assertIn("fell back", result["history"][-1]["message"])

    def test_title_feedback_loop_runs_across_all_sources_without_network(self):
        sources = (
            "openalex",
            "crossref",
            "arxiv",
            "semanticscholar",
            "pubmed",
            "googlescholar",
            "paperhub",
            "wos",
        )
        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, temperature=0.0):
                self.calls += 1
                if self.calls == 1:
                    return '{"intent":"Find AI governance accountability literature","core_concepts":["AI governance","accountability"],"likely_synonyms":["responsible AI"],"boundaries":["air pollution"],"adjustment_strategy":"Keep AI governance and accountability together."}'
                if self.calls == 2:
                    return '{"query":"AI governance","rationale":"Initial compact source query."}'
                if self.calls == 3:
                    return '{"query":"AI governance accountability","rationale":"Top titles were off-intent; add the missing accountability facet."}'
                return "[]"

        class TwoStepProvider:
            def __init__(self):
                self.queries = []

            def search(self, query, limit=100, page=1, lane="relevance", **kwargs):
                self.queries.append(query)
                if len(self.queries) == 1:
                    return ProviderSearchResult(
                        SearchMetadata(total=25, page=page, limit=limit),
                        [
                            PaperRecord(uid="p1", title="Air pollution and regional innovation in European cities", provider="fake"),
                            PaperRecord(uid="p2", title="Municipal fiscal stress and local debt", provider="fake"),
                            PaperRecord(uid="p3", title="Environmental regulation intensity and green growth", provider="fake"),
                        ],
                    )
                return ProviderSearchResult(
                    SearchMetadata(total=9, page=page, limit=limit),
                    [PaperRecord(uid="p4", title="AI governance accountability and responsible AI", provider="fake")],
                )

        for source in sources:
            with self.subTest(source=source):
                config = SimpleNamespace(
                    data_source=source,
                    discipline_fields=(),
                    search_field="",
                    expand_citations=False,
                    target_min=5,
                    target_max=50,
                    max_iterations=5,
                    fetch_abstracts=False,
                    openalex_api_key="",
                    openalex_email="",
                    crossref_email="",
                    semantic_scholar_api_key="",
                    pubmed_api_key="",
                    pubmed_email="",
                    pubmed_tool="paperseek",
                    serper_api_key="serper-test",
                    wos_api_key="wos-test",
                    wos_db="WOS",
                    retrieval_pool_max=3000,
                    retrieval_pool_min=5,
                )
                agent = PaperSeekAgent(config, FakeLLM())
                provider = TwoStepProvider()
                if source == "wos":
                    agent._provider_search = provider.search
                else:
                    agent.provider = provider
                agent._retrieve_candidates = lambda question, query, hits: hits
                agent._rank_results = lambda question, documents, **_: []

                result = agent.search("AI governance accountability")

                self.assertEqual(provider.queries, ["AI governance", "AI governance accountability"])
                self.assertEqual([row["action"] for row in result["history"]], [ACTION_NARROW, ACTION_ACCEPT])
                self.assertIn("off-intent", result["history"][0]["message"])
                self.assertEqual(result["search_state"]["decisions"][0]["action"], ACTION_NARROW)
                self.assertEqual(result["search_state"]["decisions"][1]["action"], ACTION_ACCEPT)

    def test_agent_repairs_invalid_query_in_preflight_before_provider_request(self):
        class FakeLLM:
            last_response_info = {}

            def chat(self, messages, temperature=0.0):
                return '{"query":"AI governance policy","rationale":"Preflight repair produced a balanced query."}'

        class FakeProvider:
            def __init__(self):
                self.queries = []

            def search(self, query, limit=100, page=1, lane="relevance", **kwargs):
                self.queries.append(query)
                return ProviderSearchResult(
                    SearchMetadata(total=1, page=1, limit=limit),
                    [PaperRecord(uid="p1", title="AI governance policy", provider="fake")],
                )

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=1,
            target_max=5,
            max_iterations=1,
            fetch_abstracts=False,
            openalex_api_key="",
            openalex_email="",
            retrieval_pool_max=3000,
            retrieval_pool_min=5,
        )
        agent = PaperSeekAgent(config, FakeLLM())
        agent._analyze_intent = lambda question: ""
        agent._generate_query = lambda question: '("AI governance" OR "AI policy"'
        provider = FakeProvider()
        agent.provider = provider
        agent._retrieve_candidates = lambda question, query, hits: hits
        agent._rank_results = lambda question, documents, **_: []

        result = agent.search("AI governance")

        self.assertEqual(provider.queries, ["AI governance policy"])
        self.assertEqual(result["history"][0]["action"], "repair")
        self.assertIn("preflight", result["history"][0]["message"])
        validations = result["search_state"]["validations"]
        self.assertEqual(validations[0]["stage"], "preflight")
        self.assertFalse(validations[0]["ok"])
        self.assertEqual(validations[1]["stage"], "preflight")
        self.assertTrue(validations[1]["ok"])

    def test_agent_records_provider_error_through_harness_source_search(self):
        class FakeLLM:
            def __init__(self):
                self.calls = 0

            def chat(self, messages, temperature=0.0):
                self.calls += 1
                if self.calls == 1:
                    return '{"intent":"Find AI governance papers","core_concepts":["AI governance"],"likely_synonyms":[],"boundaries":[],"adjustment_strategy":"Keep AI governance."}'
                if self.calls == 2:
                    return '{"query":"AI governance","rationale":"Initial query."}'
                return '{"query":"AI governance policy","rationale":"Repair query."}'

        class RejectOnceProvider:
            def __init__(self):
                self.queries = []

            def search(self, query, limit=100, page=1, lane="relevance", **kwargs):
                self.queries.append(query)
                if len(self.queries) == 1:
                    raise ProviderError("openalex", "Invalid query parameters error.", status=400, query=query)
                return ProviderSearchResult(
                    SearchMetadata(total=1, page=1, limit=limit),
                    [PaperRecord(uid="p1", title="AI governance policy", provider="fake")],
                )

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=1,
            target_max=5,
            max_iterations=1,
            fetch_abstracts=False,
            openalex_api_key="",
            openalex_email="",
            retrieval_pool_max=3000,
            retrieval_pool_min=5,
        )
        agent = PaperSeekAgent(config, FakeLLM())
        provider = RejectOnceProvider()
        agent.provider = provider
        agent._retrieve_candidates = lambda question, query, hits: hits
        agent._rank_results = lambda question, documents, **_: []

        result = agent.search("AI governance")

        self.assertEqual(provider.queries, ["AI governance", "AI governance policy"])
        self.assertEqual(result["search_state"]["errors"][0]["stage"], "source_search")
        self.assertEqual(result["search_state"]["errors"][0]["status"], 400)
        self.assertEqual(result["search_state"]["recovery_decisions"][0]["action"], RECOVERY_REPAIR_QUERY)

    def test_agent_records_ranking_recovery_decisions(self):
        class RateLimitThenRecoverLlm:
            def __init__(self):
                self.failed = False

            def fork(self):
                return self

            def chat(self, messages, temperature=0.3):
                text = messages[-1]["content"]
                reason_indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", text, re.MULTILINE)]
                if reason_indexes:
                    return json.dumps({"reasons": [[index, "ranked"] for index in reason_indexes]})
                entries = _compact_paper_entries(text)
                uids = [f"W{paper_index:02d}" for _, paper_index in entries]
                if "W00" in uids and not self.failed:
                    self.failed = True
                    raise RuntimeError("LLM API error (429): too many requests")
                return json.dumps({"scores": [[local_index, paper_index] for local_index, paper_index in entries]})

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=1,
            ranking_concurrency=32,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, RateLimitThenRecoverLlm())
        documents = [PaperRecord(uid=f"W{index:02d}", title=f"Paper {index}", provider="fake") for index in range(6)]

        ranked = agent._rank_results("AI governance", documents)

        self.assertEqual(len(ranked), 6)
        self.assertEqual(agent.search_run_state.ranking_batch_observations[0].batch_index, 1)
        self.assertEqual(agent.search_run_state.ranking_recovery_decisions[0].action, RANKING_RETRY_LOWER_CONCURRENCY)

    def test_agent_retries_empty_global_score_output_in_compact_chunks(self):
        class EmptyOnceRankingLlm:
            def __init__(self):
                self.empty_returned = False

            def fork(self):
                return self

            def chat(self, messages, temperature=0.3):
                text = messages[-1]["content"]
                reason_indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", text, re.MULTILINE)]
                if reason_indexes:
                    return json.dumps({"reasons": [[index, "ranked"] for index in reason_indexes]})
                entries = _compact_paper_entries(text)
                uids = [f"W{paper_index:02d}" for _, paper_index in entries]
                if "W00" in uids and not self.empty_returned:
                    self.empty_returned = True
                    return "[]"
                return json.dumps({"scores": [[local_index, paper_index] for local_index, paper_index in entries]})

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=2,
            ranking_concurrency=4,
            openalex_api_key="",
            openalex_email="",
        )
        llm = EmptyOnceRankingLlm()
        agent = PaperSeekAgent(config, llm)
        documents = [PaperRecord(uid=f"W{index:02d}", title=f"Paper {index}", provider="fake") for index in range(6)]

        ranked = agent._rank_results("AI governance", documents)

        self.assertEqual(len(ranked), 6)
        self.assertEqual(ranked[0]["document"].uid, "W05")
        self.assertTrue(llm.empty_returned)

    def test_agent_retries_invalid_global_score_output_in_compact_chunks(self):
        class InvalidOnceRankingLlm:
            def __init__(self):
                self.invalid_returned = False

            def fork(self):
                return self

            def chat(self, messages, temperature=0.3):
                text = messages[-1]["content"]
                reason_indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", text, re.MULTILINE)]
                if reason_indexes:
                    return json.dumps({"reasons": [[index, "ranked"] for index in reason_indexes]})
                entries = _compact_paper_entries(text)
                uids = [f"W{paper_index:02d}" for _, paper_index in entries]
                if "W00" in uids and not self.invalid_returned:
                    self.invalid_returned = True
                    return "[1, null, {\"score\": 8}]"
                return json.dumps({"scores": [[local_index, paper_index] for local_index, paper_index in entries]})

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=2,
            ranking_concurrency=4,
            openalex_api_key="",
            openalex_email="",
        )
        llm = InvalidOnceRankingLlm()
        agent = PaperSeekAgent(config, llm)
        documents = [PaperRecord(uid=f"W{index:02d}", title=f"Paper {index}", provider="fake") for index in range(6)]

        ranked = agent._rank_results("AI governance", documents)

        self.assertEqual(len(ranked), 6)
        self.assertEqual(ranked[0]["document"].uid, "W05")
        self.assertTrue(llm.invalid_returned)

    def test_rank_from_scores_ignores_invalid_checkpoint_entries(self):
        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, object())
        documents = [
            PaperRecord(uid="W01", title="First", provider="fake"),
            PaperRecord(uid="W02", title="Second", provider="fake"),
        ]

        ranked = agent._rank_from_scores(
            documents,
            [1, None, {"score": 10}, {"uid": "W02", "score": "9", "reasoning": "relevant"}],
        )

        self.assertEqual([entry["document"].uid for entry in ranked], ["W02", "W01"])
        self.assertEqual(ranked[0]["score"], 9.0)
