import json
import re
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paperseek_core.agent import PaperSeekAgent
from paperseek_core.planning import SearchPlan
from paperseek_core.retrieval import RetrievalLane, document_key, fuse_candidates_rrf
from paperseek_core.sources.providers import (
    ArxivProvider,
    PaperCitation,
    PaperHubProvider,
    PaperIdentifiers,
    PaperRecord,
    PaperSource,
    ProviderSearchResult,
    SearchMetadata,
    SemanticScholarProvider,
)


class FakeLLM:
    def chat(self, messages, temperature=0.3):
        return "[]"


class FakeResponse:
    def __init__(self, payload=None, text="", status_code=200, url="https://example.test"):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.url = url

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def record(uid, title, abstract="", year=2024, citations=0, doi=""):
    return PaperRecord(
        uid=uid,
        title=title,
        abstract=abstract,
        source=PaperSource(source_title="Journal", publish_year=year),
        identifiers=PaperIdentifiers(doi=doi),
        citations=[PaperCitation(db="test", count=citations)] if citations else [],
        provider="test",
    )


def config(**overrides):
    base = dict(
        data_source="openalex",
        target_min=5,
        target_max=50,
        max_iterations=5,
        retrieval_pool_max=3000,
        retrieval_pool_min=5,
        retrieval_lane_limit=1000,
        retrieval_rrf_k=60,
        retrieval_embedding_provider="local",
        retrieval_embedding_model="qwen3-embedding:8b",
        retrieval_embedding_base_url="",
        retrieval_embedding_api_key="",
        retrieval_reranker_provider="",
        retrieval_reranker_model="qwen3-reranker:8b",
        retrieval_reranker_base_url="",
        retrieval_reranker_api_key="",
        retrieval_crossref_enrichment=False,
        expand_citations=False,
        search_field="",
        discipline_fields=(),
        openalex_api_key="",
        openalex_email="",
        crossref_email="",
        semantic_scholar_api_key="",
        pubmed_api_key="",
        pubmed_email="",
        pubmed_tool="paperseek",
        wos_api_key="",
        wos_db="WOS",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class RetrievalFusionTest(unittest.TestCase):
    def test_rrf_fusion_prefers_documents_supported_by_multiple_lanes(self):
        shared = record("A", "graph retrieval for literature search", "graph neural retrieval")
        relevance_only = record("B", "unrelated platform governance")
        impact_only = record("C", "graph retrieval citation classic")
        fused = fuse_candidates_rrf(
            "graph retrieval literature",
            {
                RetrievalLane.RELEVANCE: [shared, relevance_only],
                RetrievalLane.IMPACT: [impact_only, shared],
                RetrievalLane.RECENT: [shared],
            },
            pool_max=3,
            rrf_k=60,
        )
        self.assertEqual(document_key(fused.documents[0]), document_key(shared))
        self.assertEqual(set(fused.metadata_by_key[document_key(shared)]["retrieval_lanes"]), {
            RetrievalLane.RELEVANCE,
            RetrievalLane.IMPACT,
            RetrievalLane.RECENT,
        })
        self.assertEqual(
            fused.metadata_by_key[document_key(shared)]["retrieval_source_ranks"],
            {
                RetrievalLane.RELEVANCE: 1,
                RetrievalLane.IMPACT: 2,
                RetrievalLane.RECENT: 1,
            },
        )
        metadata = fused.metadata_by_key[document_key(shared)]
        self.assertEqual(metadata["retrieval_rrf_normalized"], 1.0)
        self.assertEqual(metadata["retrieval_primary_prior"], 1.0)

    def test_normalized_rrf_and_primary_prior_protect_provider_top_result(self):
        provider_top = record("top", "specialized source result")
        local_match = record("local", "graph retrieval literature benchmark", "graph retrieval literature")

        fused = fuse_candidates_rrf(
            "graph retrieval literature",
            {
                RetrievalLane.RELEVANCE: [provider_top],
                "query_view:method": [local_match],
            },
            pool_max=2,
        )

        self.assertEqual(document_key(fused.documents[0]), document_key(provider_top))
        top_metadata = fused.metadata_by_key[document_key(provider_top)]
        self.assertEqual(top_metadata["retrieval_primary_prior"], 1.0)
        self.assertGreater(top_metadata["retrieval_rrf_normalized"], 0.0)

    def test_rrf_fusion_dedupes_by_doi(self):
        first = record("A", "First", doi="10.1234/example")
        second = record("B", "Second", doi="https://doi.org/10.1234/example")
        fused = fuse_candidates_rrf("example", {RetrievalLane.RELEVANCE: [first], RetrievalLane.IMPACT: [second]})
        self.assertEqual(len(fused.documents), 1)

    def test_rrf_fusion_dedupes_exact_title_across_different_identifiers(self):
        first = record("A", "BraveGuard: From Open-World Threats to Safer Computer-Use Agents", doi="10.1/a")
        second = record("B", "  BraveGuard:   From Open-World Threats to Safer Computer-Use Agents  ", doi="10.1/b")

        fused = fuse_candidates_rrf(
            "computer-use agent security",
            {RetrievalLane.RELEVANCE: [first], RetrievalLane.RECENT: [second]},
        )

        self.assertEqual(len(fused.documents), 1)
        metadata = fused.metadata_by_key[document_key(first)]
        self.assertEqual(set(metadata["retrieval_lanes"]), {RetrievalLane.RELEVANCE, RetrievalLane.RECENT})


class CrossrefEnrichmentTest(unittest.TestCase):
    def test_enrichment_is_disabled_by_default(self):
        agent = PaperSeekAgent(config(retrieval_crossref_enrichment=False), FakeLLM())
        document = record("A", "Paper", year=None, doi="10.1000/example")
        with patch("paperseek_core.retrieval_clients.requests.get") as request:
            result = agent.external_retrieval.enrich_crossref([document])
        self.assertIs(result[0], document)
        request.assert_not_called()

    def test_enrichment_fills_missing_citations_and_year(self):
        agent = PaperSeekAgent(config(retrieval_crossref_enrichment=True), FakeLLM())
        document = record("A", "Paper", year=None, doi="10.1000/example")
        response = FakeResponse(
            {
                "message": {
                    "is-referenced-by-count": 12,
                    "published-online": {"date-parts": [[2023, 4, 2]]},
                }
            }
        )
        with patch("paperseek_core.retrieval_clients.requests.get", return_value=response) as request:
            result = agent.external_retrieval.enrich_crossref([document])
        self.assertIs(result[0], document)
        self.assertEqual(document.citations[0].db, "Crossref")
        self.assertEqual(document.citations[0].count, 12)
        self.assertEqual(document.source.publish_year, 2023)
        request.assert_called_once_with(
            "https://api.crossref.org/works/10.1000/example",
            headers={"Accept": "application/json", "User-Agent": "paperseek/1.0"},
            timeout=20,
        )

    def test_enrichment_skips_records_without_doi(self):
        agent = PaperSeekAgent(config(retrieval_crossref_enrichment=True), FakeLLM())
        document = record("A", "Paper", year=None)
        with patch("paperseek_core.retrieval_clients.requests.get") as request:
            result = agent.external_retrieval.enrich_crossref([document])
        self.assertIs(result[0], document)
        request.assert_not_called()


class ProviderLaneTest(unittest.TestCase):
    def test_arxiv_recent_lane_uses_submitted_date_sort(self):
        captured = {}
        atom = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"><opensearch:totalResults>0</opensearch:totalResults></feed>"""

        def fake_get(provider, url, params=None, headers=None, timeout=0, query="", attempts=None):
            captured.update(params or {})
            captured["url"] = url
            captured["timeout"] = timeout
            captured["attempts"] = attempts
            return FakeResponse(text=atom), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        with patch("paperseek_core.sources.providers.get_with_retries", fake_get):
            ArxivProvider().search("graph retrieval", lane=RetrievalLane.RECENT)

        self.assertEqual(captured["sortBy"], "submittedDate")
        self.assertEqual(captured["url"], "http://export.arxiv.org/api/query")
        self.assertEqual(captured["timeout"], 45)
        self.assertEqual(captured["attempts"], 3)

    def test_semantic_scholar_impact_lane_uses_bulk_citation_sort(self):
        captured = {}

        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            captured.update({"url": url, "params": dict(params or {})})
            return FakeResponse(payload={"total": 0, "data": []}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        with patch("paperseek_core.sources.providers.get_with_retries", fake_get):
            SemanticScholarProvider(api_key="key").search("graph retrieval", lane=RetrievalLane.IMPACT)

        self.assertTrue(captured["url"].endswith("/paper/search/bulk"))
        self.assertEqual(captured["params"]["sort"], "citationCount:desc")

    def test_paperhub_local_quality_orders_by_score_and_venue(self):
        papers = [
            {"id": "a", "title": "Graph Retrieval", "abstract": "graph retrieval", "conference": "AAAI", "year": 2025},
            {"id": "b", "title": "Graph Retrieval", "abstract": "graph retrieval", "conference": "NeurIPS", "year": 2024},
        ]
        with patch.object(PaperHubProvider, "_load_papers", return_value=papers):
            result = PaperHubProvider().search("graph retrieval", lane=RetrievalLane.LOCAL_QUALITY)
        self.assertEqual(result.hits[0].uid, "b")

    def test_paperhub_query_uses_required_terms_or_and_metadata_filters(self):
        papers = [
            {"id": "a", "title": "Graph Neural Retrieval", "abstract": "retrieval benchmark", "conference": "ICLR", "year": 2025},
            {"id": "b", "title": "Graph Neural Networks Survey", "abstract": "retrieval benchmark", "conference": "ICLR", "year": 2025},
            {"id": "c", "title": "Graph Neural Retrieval", "abstract": "retrieval benchmark", "conference": "NeurIPS", "year": 2025},
            {"id": "d", "title": "Vision Retrieval", "abstract": "image benchmark", "conference": "ICLR", "year": 2025},
        ]

        with patch.object(PaperHubProvider, "_load_papers", return_value=papers):
            result = PaperHubProvider().search('"graph neural" OR GNN retrieval -survey conference:ICLR year:2025', limit=10)

        self.assertEqual([hit.uid for hit in result.hits], ["a"])

    def test_paperhub_plain_terms_are_required_not_broadening_or_terms(self):
        papers = [
            {"id": "a", "title": "Graph Retrieval", "abstract": "", "conference": "ICLR", "year": 2025},
            {"id": "b", "title": "Graph Generation", "abstract": "", "conference": "ICLR", "year": 2025},
            {"id": "c", "title": "Neural Retrieval", "abstract": "", "conference": "ICLR", "year": 2025},
        ]

        with patch.object(PaperHubProvider, "_load_papers", return_value=papers):
            broad = PaperHubProvider().search("graph", limit=10)
            narrow = PaperHubProvider().search("graph retrieval", limit=10)

        self.assertEqual(broad.metadata.total, 2)
        self.assertEqual(narrow.metadata.total, 1)


class RetrievalAgentTest(unittest.TestCase):
    def test_post_citation_fusion_gives_relevant_neighbor_a_ranking_slot(self):
        question = "semiconductor supply chain resilience measurement"
        base_candidates = [
            record(
                f"base-{index}",
                f"General organizational management study {index}",
                "enterprise routines and operational performance",
            )
            for index in range(300)
        ]
        citation_neighbor = record(
            "citation-hit",
            "Measuring semiconductor supply chain resilience",
            "A resilience index for the global chip industry chain and its driving factors.",
        )
        initial = fuse_candidates_rrf(
            question,
            {RetrievalLane.RELEVANCE: base_candidates},
            pool_max=300,
        )
        agent = PaperSeekAgent(config(expand_citations=True, retrieval_pool_max=1000), FakeLLM())
        agent.retrieval_metadata_by_key = initial.metadata_by_key
        agent._enqueue_candidate_queue(initial.documents, "retrieval")
        agent._enqueue_candidate_queue([citation_neighbor], "citation_expansion")

        fused = agent._refuse_candidates_after_citation(
            question,
            [*initial.documents, citation_neighbor],
        )
        selected = fused[:256]
        agent._record_candidate_gate(fused, selected, 256)

        neighbor_key = document_key(citation_neighbor)
        self.assertIn(neighbor_key, {document_key(document) for document in selected})
        evidence = agent.search_run_state.candidate_queue.ledger[neighbor_key]
        self.assertEqual(evidence.ranking_gate_label, "selected")
        self.assertIsNotNone(evidence.retrieval_score)
        self.assertIn(RetrievalLane.CITATION, evidence.retrieval_lanes)
        self.assertGreater(evidence.concept_coverage["bm25"], 0.0)

    def test_candidate_ledger_tracks_retrieval_gate_ranking_and_output(self):
        document = record("W1", "Graph retrieval for literature search", "retrieval benchmark", citations=12)
        key = document_key(document)
        agent = PaperSeekAgent(config(expand_citations=False), FakeLLM())
        agent.retrieval_metadata_by_key = {
            key: {
                "source_rank": 2,
                "retrieval_source_ranks": {"relevance": 2, "impact": 7},
                "retrieval_lanes": ["relevance", "impact", "query_view:mechanism"],
                "retrieval_score": 0.73,
                "retrieval_embedding_score": 0.61,
                "retrieval_bm25_score": 0.52,
                "retrieval_term_coverage": 0.4,
                "retrieval_rrf_score": 0.08,
                "retrieval_rrf_normalized": 0.9,
                "retrieval_primary_prior": 0.5,
                "rerank_score": 3.2,
            }
        }

        candidates = agent._prepare_candidates("graph retrieval", [document])
        agent._record_candidate_gate(candidates, candidates, 256)
        ranked = [{"document": document, "score": 9, "reasoning": "directly relevant"}]
        agent._record_candidate_scores(ranked, "llm_scored")
        agent._record_final_candidates(ranked)

        evidence = agent.search_run_state.candidate_queue.ledger[key]
        self.assertEqual(evidence.origins, ["retrieval"])
        self.assertEqual(evidence.query_views, ["mechanism"])
        self.assertEqual(evidence.retrieval_lanes, ["relevance", "impact", "query_view:mechanism"])
        self.assertEqual(evidence.source_ranks, {"relevance": 2, "impact": 7})
        self.assertEqual(evidence.retrieval_score, 0.73)
        self.assertEqual(evidence.concept_coverage["rrf_normalized"], 0.9)
        self.assertEqual(evidence.concept_coverage["primary_prior"], 0.5)
        self.assertEqual(evidence.rerank_score, 3.2)
        self.assertEqual(evidence.llm_score, 9.0)
        self.assertEqual(evidence.ranking_gate_label, "selected")
        self.assertEqual(
            [event.action for event in evidence.lifecycle],
            ["added", "selected_for_llm", "llm_scored", "final_output"],
        )

    def test_candidate_ledger_records_ranking_gate_decisions(self):
        first = record("W1", "First result")
        second = record("W2", "Second result")
        agent = PaperSeekAgent(config(expand_citations=False), FakeLLM())
        candidates = agent._prepare_candidates("result", [first, second])

        agent._record_candidate_gate(candidates, candidates[:1], 1)

        first_evidence = agent.search_run_state.candidate_queue.ledger[document_key(first)]
        second_evidence = agent.search_run_state.candidate_queue.ledger[document_key(second)]
        self.assertEqual(first_evidence.ranking_gate_label, "selected")
        self.assertEqual(second_evidence.ranking_gate_label, "truncated")
        self.assertIn("ranking_candidate_limit", second_evidence.ranking_gate_reason_codes)
        self.assertEqual(second_evidence.lifecycle[-1].action, "truncated_before_llm")

    def test_candidate_preparation_keeps_records_already_in_iteration_ledger(self):
        remembered = record("W1", "Remembered iteration result")
        fresh = record("W2", "Fresh retrieval result")
        agent = PaperSeekAgent(config(expand_citations=False), FakeLLM())
        agent._enqueue_candidate_queue([remembered], "query_iteration:1")

        candidates = agent._prepare_candidates("result", [remembered, fresh])

        self.assertEqual([document.uid for document in candidates], ["W1", "W2"])
        remembered_evidence = agent.search_run_state.candidate_queue.ledger[document_key(remembered)]
        self.assertEqual(remembered_evidence.origins, ["query_iteration:1", "retrieval"])

    def test_search_state_payload_summarizes_and_bounds_candidate_ledger(self):
        documents = [record(f"W{index}", f"Candidate {index}") for index in range(520)]
        agent = PaperSeekAgent(config(expand_citations=False), FakeLLM())
        candidates = agent._prepare_candidates("candidate", documents)
        agent._record_candidate_gate(candidates, candidates[-2:], 2)
        ranked = [{"document": document, "score": 8} for document in candidates[-2:]]
        agent._record_candidate_scores(ranked, "llm_scored")
        agent._record_final_candidates(ranked[-1:])

        payload = agent._search_state_payload()
        queue = payload["candidate_queue"]
        summary = queue["ledger_summary"]

        self.assertEqual(len(agent.search_run_state.candidate_queue.ledger), 520)
        self.assertEqual(summary["total_candidates"], 520)
        self.assertEqual(summary["serialized_candidates"], 512)
        self.assertEqual(summary["omitted_candidates"], 8)
        self.assertEqual(summary["ranking_gate_counts"], {"truncated": 518, "selected": 2})
        self.assertEqual(summary["lifecycle_candidate_counts"]["selected_for_llm"], 2)
        self.assertEqual(summary["lifecycle_candidate_counts"]["final_output"], 1)
        self.assertIn(document_key(candidates[-1]), queue["ledger"])
        self.assertIn(document_key(candidates[-2]), queue["ledger"])

    def test_retrieve_candidates_uses_provider_capability_lanes(self):
        class Provider:
            def retrieval_capabilities(self):
                return SimpleNamespace(source="fake", lanes=(RetrievalLane.RELEVANCE, RetrievalLane.RECENT), max_lane_limit=10)

            def search(self, query, limit=50, page=1, lane=RetrievalLane.RELEVANCE):
                if lane == RetrievalLane.RECENT:
                    return ProviderSearchResult(SearchMetadata(total=1, page=1, limit=limit), [record("recent", "graph retrieval recent", year=2025)])
                return ProviderSearchResult(SearchMetadata(total=1, page=1, limit=limit), [record("rel", "graph retrieval relevant", year=2022)])

        agent = PaperSeekAgent(config(data_source="openalex", retrieval_lane_limit=10, retrieval_pool_max=10), FakeLLM())
        agent.provider = Provider()
        docs = agent._retrieve_candidates("graph retrieval", "graph retrieval", [])
        self.assertEqual({doc.uid for doc in docs}, {"rel", "recent"})

    def test_retrieve_candidates_runs_provider_lanes_with_bounded_concurrency(self):
        barrier = threading.Barrier(2, timeout=2)

        class Provider:
            def retrieval_capabilities(self):
                return SimpleNamespace(
                    source="fake",
                    lanes=(RetrievalLane.RELEVANCE, RetrievalLane.RECENT),
                    max_lane_limit=10,
                    lane_concurrency=2,
                )

            def search(self, query, limit=50, page=1, lane=RetrievalLane.RELEVANCE):
                barrier.wait()
                return ProviderSearchResult(
                    SearchMetadata(total=1, page=page, limit=limit),
                    [record(lane, f"{lane} result")],
                )

        agent = PaperSeekAgent(config(data_source="openalex", retrieval_lane_limit=10, retrieval_pool_max=10), FakeLLM())
        agent.provider = Provider()

        docs = agent._retrieve_candidates("graph retrieval", "graph retrieval", [])

        self.assertEqual([doc.uid for doc in docs], [RetrievalLane.RELEVANCE, RetrievalLane.RECENT])

    def test_effective_lane_limit_does_not_page_beyond_llm_gate(self):
        agent = PaperSeekAgent(
            config(retrieval_lane_limit=1000, retrieval_pool_max=3000, ranking_candidate_limit=256),
            FakeLLM(),
        )
        capabilities = SimpleNamespace(max_lane_limit=1000)

        self.assertEqual(agent._effective_lane_limit(capabilities), 256)
        self.assertEqual(agent._effective_lane_limit(capabilities, RetrievalLane.RECENT), 100)

    def test_semantic_lane_uses_original_question_not_compiled_query(self):
        class Provider:
            def __init__(self):
                self.calls = []

            def retrieval_capabilities(self):
                return SimpleNamespace(
                    source="fake",
                    lanes=(RetrievalLane.RELEVANCE, RetrievalLane.SEMANTIC),
                    max_lane_limit=10,
                )

            def search(self, query, limit=50, page=1, lane=RetrievalLane.RELEVANCE):
                self.calls.append((lane, query))
                return ProviderSearchResult(
                    SearchMetadata(total=1, page=1, limit=limit),
                    [record(lane, f"{lane} result")],
                )

        provider = Provider()
        agent = PaperSeekAgent(config(data_source="openalex", retrieval_lane_limit=10, retrieval_pool_max=10), FakeLLM())
        agent.provider = provider

        agent._retrieve_candidates("natural language research question", "compiled boolean query", [])

        self.assertEqual(
            provider.calls,
            [
                (RetrievalLane.RELEVANCE, "compiled boolean query"),
                (RetrievalLane.SEMANTIC, "natural language research question"),
            ],
        )

    def test_relevance_lane_reuses_primary_page_before_fetching_next_page(self):
        primary = [record(f"primary-{index}", f"Primary {index}") for index in range(100)]

        class Provider:
            def __init__(self):
                self.calls = []

            def retrieval_capabilities(self):
                return SimpleNamespace(source="fake", lanes=(RetrievalLane.RELEVANCE,), max_lane_limit=150)

            def search(self, query, limit=50, page=1, lane=RetrievalLane.RELEVANCE):
                self.calls.append((lane, page, limit))
                hits = [record(f"page-2-{index}", f"Page 2 {index}") for index in range(50)]
                return ProviderSearchResult(SearchMetadata(total=150, page=page, limit=limit), hits)

        provider = Provider()
        agent = PaperSeekAgent(config(data_source="openalex", retrieval_lane_limit=150, retrieval_pool_max=150), FakeLLM())
        agent.provider = provider

        docs = agent._retrieve_candidates("question", "compiled query", primary)

        self.assertEqual(provider.calls, [(RetrievalLane.RELEVANCE, 2, 50)])
        self.assertEqual(len(docs), 150)
        self.assertIn("primary-0", {doc.uid for doc in docs})
        self.assertIn("page-2-49", {doc.uid for doc in docs})

    def test_retrieval_lane_keeps_completed_pages_when_later_page_fails(self):
        primary = [record(f"primary-{index}", f"Primary {index}") for index in range(100)]

        class Provider:
            def search(self, query, limit=50, page=1, lane=RetrievalLane.RELEVANCE):
                raise RuntimeError("temporary page failure")

        agent = PaperSeekAgent(config(data_source="openalex", retrieval_lane_limit=150, retrieval_pool_max=150), FakeLLM())
        agent.provider = Provider()
        events = []
        agent.event_handler = events.append

        docs = agent._collect_retrieval_lane(
            "compiled query",
            RetrievalLane.RELEVANCE,
            150,
            initial_hits=primary,
        )

        self.assertEqual(len(docs), 100)
        messages = "\n".join(str(event.get("message") or "") for event in events)
        self.assertIn("retained 100 candidates after page 2 failed", messages)

    def test_llm_ranking_candidate_limit_is_separate_from_retrieval_pool(self):
        agent = PaperSeekAgent(config(retrieval_pool_max=3000, target_max=50), FakeLLM())
        self.assertEqual(agent._llm_ranking_candidate_limit(), 256)

        agent = PaperSeekAgent(config(retrieval_pool_max=30, target_max=50), FakeLLM())
        self.assertEqual(agent._llm_ranking_candidate_limit(), 30)

    def test_ranked_output_keeps_all_high_score_results_after_llm_limit(self):
        agent = PaperSeekAgent(config(), FakeLLM())
        ranked = [
            {"document": record(f"r{index}", f"paper {index}"), "score": 7 if index < 70 else 4}
            for index in range(90)
        ]

        selected = agent._select_ranked_output(ranked)

        self.assertEqual(len(selected), 70)
        self.assertTrue(all(item["score"] >= 5 for item in selected))

    def test_ranked_output_falls_back_to_top_fifty_when_high_score_results_are_few(self):
        agent = PaperSeekAgent(config(), FakeLLM())
        ranked = [
            {"document": record(f"r{index}", f"paper {index}"), "score": 7 if index < 20 else 4}
            for index in range(90)
        ]

        self.assertEqual(len(agent._select_ranked_output(ranked)), 50)

    def test_ranked_output_keeps_all_when_total_is_below_fifty(self):
        agent = PaperSeekAgent(config(), FakeLLM())
        ranked = [
            {"document": record(f"r{index}", f"paper {index}"), "score": 3}
            for index in range(12)
        ]

        self.assertEqual(len(agent._select_ranked_output(ranked)), 12)

    def test_ranking_batch_size_does_not_expand_for_large_candidate_sets(self):
        agent = PaperSeekAgent(config(ranking_batch_size=8), FakeLLM())
        self.assertEqual(agent._ranking_batch_size(100), 8)

    def test_default_ranking_batch_scores_full_candidate_limit_in_one_request(self):
        agent = PaperSeekAgent(config(), FakeLLM())
        self.assertEqual(agent._ranking_batch_size(256), 256)

    def test_specific_intent_balances_precision_with_candidate_recall(self):
        agent = PaperSeekAgent(config(), FakeLLM())
        agent.search_intent = "Find how platform governance affects user innovation."
        agent.search_plan = SearchPlan(
            intent=agent.search_intent,
            question_type="specific_relation",
            core_concepts=["platform governance", "user innovation"],
            must_have_facets=["platform governance", "user innovation"],
            required_relation="effects of platform governance on user innovation",
        )

        context = agent._intent_context()

        self.assertIn("normally with two or three mandatory concept groups", context)
        self.assertIn("broad umbrella term", context)
        self.assertIn("Do not turn every must_have_facet into a separate AND clause", context)
        self.assertIn("ranking and query-portfolio evidence", context)

    def test_broad_intent_retains_high_recall_policy(self):
        agent = PaperSeekAgent(config(), FakeLLM())
        agent.search_intent = "Survey research on platform governance."
        agent.search_plan = SearchPlan(
            intent=agent.search_intent,
            question_type="broad_landscape",
            core_concepts=["platform governance"],
            must_have_facets=["platform governance"],
        )

        context = agent._intent_context()

        self.assertIn("Build a high-recall candidate query around the central subject", context)
        self.assertNotIn("normally with two or three mandatory concept groups", context)

    def test_score_only_global_ranking_falls_back_to_sixty_four_candidate_chunks(self):
        class TransportFailureThenCompactLLM:
            def __init__(self):
                self.requests = []
                self.failed = False
                self.score_successes = 0

            def chat_json(self, messages, temperature=0.0, max_tokens=None):
                system = messages[0]["content"]
                prompt = messages[-1]["content"]
                if "integer-indexed papers" in system:
                    indexes = [int(value) for value in re.findall(r"^(\d+)\.$", prompt, re.MULTILINE)]
                    self.requests.append(("scores", len(indexes)))
                    if not self.failed:
                        self.failed = True
                        raise RuntimeError(
                            'LLM API error (502): {"error":{"message":"upstream transport failure","type":"proxy_error"}}'
                        )
                    self.score_successes += 1
                    return json.dumps({
                        "scores": [
                            [index, 8 if self.score_successes == 1 and index <= 50 else 2]
                            for index in indexes
                        ]
                    })
                if "Explain the supplied relevance scores" in system:
                    indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", prompt, re.MULTILINE)]
                    self.requests.append(("reasons", len(indexes)))
                    return json.dumps({"reasons": [[index, "Relevant."] for index in indexes]})
                raise AssertionError("unexpected ranking request")

        llm = TransportFailureThenCompactLLM()
        documents = [record(f"W{index}", f"Paper {index}") for index in range(256)]
        agent = PaperSeekAgent(config(), llm)

        ranked = agent._rank_results("graph retrieval", documents)

        self.assertEqual(len(ranked), 256)
        self.assertEqual(
            llm.requests,
            [("scores", 256), ("scores", 64), ("scores", 64), ("scores", 64), ("scores", 64), ("reasons", 50)],
        )
        self.assertTrue(all(entry["reasoning"] == "Relevant." for entry in ranked[:50]))
        self.assertTrue(all(entry["reasoning"] == "" for entry in ranked[50:]))

    def test_global_score_only_batch_uses_compact_output_budget(self):
        class StructuredRankingLLM:
            def __init__(self):
                self.max_tokens = None
                self.system = ""

            def chat_json(self, messages, temperature=0.0, max_tokens=None):
                self.max_tokens = max_tokens
                self.system = messages[0]["content"]
                return json.dumps({"scores": [[index, 5] for index in range(1, 257)]})

        llm = StructuredRankingLLM()
        agent = PaperSeekAgent(config(), llm)
        scores = agent._request_compact_ranking_scores(
            "graph retrieval",
            [record(f"r{index}", f"Paper {index}") for index in range(256)],
            llm,
        )
        self.assertEqual(len(scores), 256)
        self.assertEqual(llm.max_tokens, 4096)
        self.assertIn("do not output explanations", llm.system)

    def test_ranking_batch_prefers_structured_json_mode(self):
        class StructuredRankingLLM:
            def __init__(self):
                self.calls = []

            def chat_json(self, messages, temperature=0.3, max_tokens=None):
                self.calls.append((messages, temperature, max_tokens))
                if "integer-indexed papers" in messages[0]["content"]:
                    return '{"scores":[[1,9]]}'
                return '{"reasons":[[1,"Direct match."]]}'

            def chat(self, messages, temperature=0.3):
                raise AssertionError("plain chat must not be used when chat_json is available")

        llm = StructuredRankingLLM()
        agent = PaperSeekAgent(config(), llm)

        scores = agent._rank_results("graph retrieval", [record("a", "Graph retrieval")])

        self.assertEqual(scores[0]["score"], 9)
        self.assertEqual(scores[0]["reasoning"], "Direct match.")
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[0][1:], (0.0, 4096))

    def test_partial_global_score_only_output_retries_in_chunks(self):
        class PartialRankingLLM:
            def __init__(self):
                self.requests = []
                self.score_calls = 0

            def chat_json(self, messages, temperature=0.0, max_tokens=None):
                system = messages[0]["content"]
                prompt = messages[-1]["content"]
                if "integer-indexed papers" in system:
                    indexes = [int(value) for value in re.findall(r"^(\d+)\.$", prompt, re.MULTILINE)]
                    self.requests.append(("scores", indexes))
                    self.score_calls += 1
                    if self.score_calls == 1:
                        indexes = indexes[:-1]
                    return json.dumps({"scores": [[index, 8] for index in indexes]})
                if "Explain the supplied relevance scores" in system:
                    indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", prompt, re.MULTILINE)]
                    self.requests.append(("reasons", indexes))
                    return json.dumps({"reasons": [[index, "Relevant."] for index in indexes]})
                raise AssertionError("unexpected ranking request")

        llm = PartialRankingLLM()
        documents = [record(f"W{index}", f"Paper {index}") for index in range(16)]
        agent = PaperSeekAgent(config(), llm)

        scores = agent._rank_results("graph retrieval", documents)

        self.assertEqual(len(scores), 16)
        self.assertEqual([request[0] for request in llm.requests], ["scores", "scores", "reasons"])
        self.assertEqual(llm.requests[1][1], list(range(1, 17)))
        self.assertTrue(all(entry["reasoning"] == "Relevant." for entry in scores))

    def test_two_stage_reasoning_only_targets_high_scores_or_top_fifty(self):
        documents = [record(f"W{index}", f"Paper {index}") for index in range(80)]
        scores = [
            {"uid": f"W{index}", "score": 8 if index < 55 else 2, "reasoning": ""}
            for index in range(80)
        ]
        agent = PaperSeekAgent(config(), FakeLLM())

        selected = agent._ranking_reason_documents(documents, scores)

        self.assertEqual(len(selected), 55)
        self.assertEqual([document.uid for document in selected], [f"W{index}" for index in range(55)])

    def test_ranking_batch_receives_stable_search_plan_context(self):
        class StructuredRankingLLM:
            def __init__(self):
                self.messages = []

            def chat_json(self, messages, temperature=0.0, max_tokens=None):
                self.messages.append(messages)
                if "integer-indexed papers" in messages[0]["content"]:
                    return '{"scores":[[1,8]]}'
                return '{"reasons":[[1,"Relevant."]]}'

        llm = StructuredRankingLLM()
        agent = PaperSeekAgent(config(), llm)
        agent.search_plan = SearchPlan(
            intent="Find methods that extend Global Descent",
            question_type="specific_relation",
            core_concepts=["Global Descent", "deep learning"],
            boundaries=["Exclude unrelated optimization domains"],
        )

        agent._rank_results("Which works extend Global Descent?", [record("a", "A paper")])

        prompt = llm.messages[0][-1]["content"]
        self.assertIn("Stable SearchPlan", prompt)
        self.assertIn("Find methods that extend Global Descent", prompt)
        self.assertIn("Exclude unrelated optimization domains", prompt)

    def test_external_embedding_uses_openai_compatible_endpoint(self):
        agent = PaperSeekAgent(
            config(
                retrieval_embedding_provider="cstcloud",
                retrieval_embedding_api_key="sk-test",
                retrieval_embedding_base_url="https://uni-api.cstcloud.cn/v1",
                retrieval_embedding_model="qwen3-embedding:8b",
            ),
            FakeLLM(),
        )
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=0):
            captured.update({"url": url, "headers": dict(headers or {}), "json": dict(json or {})})
            return FakeResponse(payload={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [1.0, 0.0]},
                    {"index": 2, "embedding": [0.0, 1.0]},
                ]
            })

        docs = [record("a", "graph retrieval"), record("b", "platform governance")]
        with patch("paperseek_core.retrieval_clients.requests.post", fake_post):
            scores = agent._external_embedding_scores("graph retrieval", docs)

        self.assertEqual(captured["url"], "https://uni-api.cstcloud.cn/v1/embeddings")
        self.assertEqual(captured["json"]["model"], "qwen3-embedding:8b")
        self.assertEqual(captured["json"]["encoding_format"], "float")
        self.assertEqual(scores, [1.0, 0.0])

    def test_nvidia_embedding_marks_query_and_passages(self):
        agent = PaperSeekAgent(
            config(
                retrieval_embedding_provider="nvidia",
                retrieval_embedding_api_key="nv-test",
                retrieval_embedding_base_url="https://integrate.api.nvidia.com/v1",
                retrieval_embedding_model="nvidia/nv-embedqa-e5-v5",
            ),
            FakeLLM(),
        )
        calls = []

        def fake_post(url, headers=None, json=None, timeout=0):
            calls.append({"url": url, "json": dict(json or {})})
            if json["input_type"] == "query":
                data = [{"index": 0, "embedding": [1.0, 0.0]}]
            else:
                data = [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 1, "embedding": [0.0, 1.0]}]
            return FakeResponse(payload={"data": data})

        docs = [record("a", "graph retrieval"), record("b", "platform governance")]
        with patch("paperseek_core.retrieval_clients.requests.post", fake_post):
            scores = agent._external_embedding_scores("graph retrieval", docs)

        self.assertEqual([call["url"] for call in calls], ["https://integrate.api.nvidia.com/v1/embeddings"] * 2)
        self.assertEqual([call["json"]["input_type"] for call in calls], ["query", "passage"])
        self.assertEqual(calls[0]["json"]["input"], ["graph retrieval"])
        self.assertEqual(calls[1]["json"]["input"][0], "graph retrieval Journal 2024")
        self.assertEqual(calls[1]["json"]["input"][1], "platform governance Journal 2024")
        self.assertEqual(scores, [1.0, 0.0])

    def test_external_embedding_falls_back_to_next_model(self):
        agent = PaperSeekAgent(
            config(
                retrieval_embedding_provider="cstcloud",
                retrieval_embedding_api_key="sk-test",
                retrieval_embedding_base_url="https://uni-api.cstcloud.cn/v1",
                retrieval_embedding_model="qwen3-embedding:8b,bge-large-zh:latest",
            ),
            FakeLLM(),
        )
        models = []

        def fake_post(url, headers=None, json=None, timeout=0):
            models.append(json["model"])
            if json["model"] == "qwen3-embedding:8b":
                return FakeResponse(payload={"error": "temporary"}, status_code=503, text="temporary")
            return FakeResponse(payload={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [1.0, 0.0]},
                ]
            })

        with patch("paperseek_core.retrieval_clients.requests.post", fake_post):
            scores = agent._external_embedding_scores("graph retrieval", [record("a", "graph retrieval")])

        self.assertEqual(models, ["qwen3-embedding:8b", "bge-large-zh:latest"])
        self.assertEqual(scores, [1.0])

    def test_external_embedding_rotates_key_pool_on_retryable_status(self):
        agent = PaperSeekAgent(
            config(
                retrieval_embedding_provider="cstcloud",
                retrieval_embedding_api_key="sk-a,sk-b",
                retrieval_embedding_base_url="https://uni-api.cstcloud.cn/v1",
                retrieval_embedding_model="qwen3-embedding:8b",
            ),
            FakeLLM(),
        )
        calls = []

        def fake_post(url, headers=None, json=None, timeout=0):
            calls.append(headers.get("Authorization"))
            if len(calls) == 1:
                return FakeResponse(payload={"error": "limited"}, status_code=429, text="limited")
            return FakeResponse(payload={"data": [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 1, "embedding": [1.0, 0.0]}]})

        with patch("paperseek_core.retrieval_clients.requests.post", fake_post):
            scores = agent._external_embedding_scores("graph retrieval", [record("a", "graph retrieval")])

        self.assertEqual(calls, ["Bearer sk-a", "Bearer sk-b"])
        self.assertEqual(scores, [1.0])

    def test_external_reranker_reorders_prefix_when_available(self):
        agent = PaperSeekAgent(
            config(
                retrieval_reranker_provider="cstcloud",
                retrieval_reranker_api_key="sk-test",
                retrieval_reranker_base_url="https://uni-api.cstcloud.cn/v1",
                retrieval_reranker_model="qwen3-reranker:8b",
            ),
            FakeLLM(),
        )

        def fake_post(url, headers=None, json=None, timeout=0):
            return FakeResponse(payload={"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]})

        docs = [record("a", "less relevant"), record("b", "more relevant")]
        with patch("paperseek_core.retrieval_clients.requests.post", fake_post):
            reranked = agent._apply_external_reranker("graph retrieval", docs)

        self.assertEqual([doc.uid for doc in reranked], ["b", "a"])

    def test_nvidia_reranker_uses_rankings_endpoint_and_logit_scores(self):
        agent = PaperSeekAgent(
            config(
                retrieval_reranker_provider="nvidia",
                retrieval_reranker_api_key="nv-test",
                retrieval_reranker_base_url="https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking",
                retrieval_reranker_model="nv-rerank-qa-mistral-4b:1",
            ),
            FakeLLM(),
        )
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=0):
            captured.update({"url": url, "headers": dict(headers or {}), "json": dict(json or {})})
            return FakeResponse(payload={"rankings": [{"index": 1, "logit": 4.7}, {"index": 0, "logit": -1.0}]})

        docs = [record("a", "less relevant"), record("b", "more relevant")]
        with patch("paperseek_core.retrieval_clients.requests.post", fake_post):
            reranked = agent._apply_external_reranker("graph retrieval", docs)

        self.assertEqual(captured["url"], "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking")
        self.assertEqual(captured["headers"]["Accept"], "application/json")
        self.assertEqual(captured["json"]["model"], "nv-rerank-qa-mistral-4b:1")
        self.assertEqual(captured["json"]["query"], {"text": "graph retrieval"})
        self.assertEqual(captured["json"]["passages"], [{"text": "less relevant Journal 2024"}, {"text": "more relevant Journal 2024"}])
        self.assertEqual([doc.uid for doc in reranked], ["b", "a"])

    def test_nvidia_reranker_preserves_ranking_endpoint(self):
        agent = PaperSeekAgent(
            config(
                retrieval_reranker_provider="nvidia",
                retrieval_reranker_api_key="nv-test",
                retrieval_reranker_base_url="http://localhost:8000/v1/ranking",
                retrieval_reranker_model="nv-rerank-qa-mistral-4b:1",
            ),
            FakeLLM(),
        )
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=0):
            captured["url"] = url
            return FakeResponse(payload={"rankings": [{"index": 0, "logit": 1.0}]})

        with patch("paperseek_core.retrieval_clients.requests.post", fake_post):
            agent._apply_external_reranker("graph retrieval", [record("a", "relevant")])

        self.assertEqual(captured["url"], "http://localhost:8000/v1/ranking")

    def test_external_reranker_falls_back_to_next_model(self):
        agent = PaperSeekAgent(
            config(
                retrieval_reranker_provider="cstcloud",
                retrieval_reranker_api_key="sk-test",
                retrieval_reranker_base_url="https://uni-api.cstcloud.cn/v1",
                retrieval_reranker_model="qwen3-reranker:8b,bge-reranker-v2-m3",
            ),
            FakeLLM(),
        )
        models = []

        def fake_post(url, headers=None, json=None, timeout=0):
            models.append(json["model"])
            if json["model"] == "qwen3-reranker:8b":
                return FakeResponse(payload={"error": "temporary"}, status_code=503, text="temporary")
            return FakeResponse(payload={"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]})

        docs = [record("a", "less relevant"), record("b", "more relevant")]
        with patch("paperseek_core.retrieval_clients.requests.post", fake_post):
            reranked = agent._apply_external_reranker("graph retrieval", docs)

        self.assertEqual(models, ["qwen3-reranker:8b", "bge-reranker-v2-m3"])
        self.assertEqual([doc.uid for doc in reranked], ["b", "a"])

    def test_external_reranker_rotates_key_pool_on_retryable_status(self):
        agent = PaperSeekAgent(
            config(
                retrieval_reranker_provider="nvidia",
                retrieval_reranker_api_key="nv-a,nv-b",
                retrieval_reranker_base_url="https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking",
                retrieval_reranker_model="nv-rerank-qa-mistral-4b:1",
            ),
            FakeLLM(),
        )
        calls = []

        def fake_post(url, headers=None, json=None, timeout=0):
            calls.append(headers.get("Authorization"))
            if len(calls) == 1:
                return FakeResponse(payload={"error": "limited"}, status_code=429, text="limited")
            return FakeResponse(payload={"rankings": [{"index": 1, "logit": 4.0}, {"index": 0, "logit": 1.0}]})

        docs = [record("a", "less relevant"), record("b", "more relevant")]
        with patch("paperseek_core.retrieval_clients.requests.post", fake_post):
            reranked = agent._apply_external_reranker("graph retrieval", docs)

        self.assertEqual(calls, ["Bearer nv-a", "Bearer nv-b"])
        self.assertEqual([doc.uid for doc in reranked], ["b", "a"])

    def test_retrieval_provider_default_base_urls_include_common_embedding_vendors(self):
        agent = PaperSeekAgent(config(llm_api_key="sk-test"), FakeLLM())
        self.assertEqual(agent._retrieval_base_url("embedding", "dashscope"), "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(agent._retrieval_base_url("embedding", "siliconflow"), "https://api.siliconflow.cn/v1")
        self.assertEqual(agent._retrieval_base_url("embedding", "modelscope"), "https://api-inference.modelscope.cn/v1")
        self.assertEqual(agent._retrieval_base_url("embedding", "openrouter"), "https://openrouter.ai/api/v1")
        self.assertEqual(agent._retrieval_base_url("embedding", "nvidia"), "https://integrate.api.nvidia.com/v1")
        self.assertEqual(agent._retrieval_base_url("reranker", "nvidia"), "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking")
        self.assertEqual(agent._retrieval_base_url("reranker", "modelscope"), "")
        self.assertEqual(agent._retrieval_api_key("embedding", "dashscope"), "sk-test")
        self.assertEqual(agent._retrieval_api_key("reranker", "openrouter"), "sk-test")

    def test_modelscope_embedding_defaults_to_supported_qwen_models(self):
        agent = PaperSeekAgent(config(retrieval_embedding_model="qwen3-embedding:8b,bge-large-zh:latest"), FakeLLM())
        self.assertEqual(
            agent._retrieval_model_candidates("embedding", "qwen3-embedding:8b", "modelscope"),
            ["Qwen/Qwen3-Embedding-8B", "Qwen/Qwen3-Embedding-4B"],
        )

    def test_modelscope_reranker_is_skipped(self):
        agent = PaperSeekAgent(config(retrieval_reranker_provider="modelscope", llm_api_key="sk-test"), FakeLLM())
        docs = [record("a", "graph retrieval")]
        with patch("paperseek_core.retrieval_clients.requests.post") as post:
            self.assertEqual(agent._apply_external_reranker("graph retrieval", docs), docs)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
