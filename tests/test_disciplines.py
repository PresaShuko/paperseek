import json
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paperseek_core.agent import PaperSeekAgent
from paperseek_core.client import ApiException
from paperseek_core.disciplines import (
    apply_arxiv_category_filter,
    apply_wos_discipline_filter,
    list_discipline_fields,
    list_source_filter_options,
    normalize_discipline_ids,
    normalize_source_filter_values,
    openalex_field_filter,
    source_filter_mode,
    wos_category_clause,
)
from paperseek_core.planning import parse_search_plan
from paperseek_core.domain.models import PaperIdentifiers, PaperRecord
from paperseek_core.sources.contracts import CitationSeedPlan, ProviderError, ProviderSearchResult, SearchMetadata
from paperseek_core.sources.openalex import OpenAlexProvider


class FakeResponse:
    url = "https://api.openalex.org/works"

    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {"meta": {"count": 0, "page": 1, "per_page": 1}, "results": []}
        self.status_code = status_code
        self.text = "{}"

    def json(self):
        return self._payload


class BatchRankingLlm:
    def __init__(self, calls=None, fail_uid=""):
        self.calls = calls if calls is not None else []
        self.fail_uid = fail_uid
        self.last_response_info = {}

    def fork(self):
        return BatchRankingLlm(self.calls, fail_uid=self.fail_uid)

    def chat(self, messages, temperature=0.3):
        text = messages[-1]["content"]
        reason_indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", text, re.MULTILINE)]
        if reason_indexes:
            return json.dumps({"reasons": [[index, "ranked"] for index in reason_indexes]})
        entries = _compact_work_entries(text)
        uids = [f"W{work_index:02d}" for _, work_index in entries]
        self.calls.append(tuple(uids))
        if self.fail_uid and self.fail_uid in uids:
            raise RuntimeError("simulated batch failure")
        return json.dumps({"scores": [[local_index, work_index] for local_index, work_index in entries]})


def _compact_work_entries(text):
    entries = []
    for block in text.split("\n\n"):
        local_match = re.search(r"^(\d+)\.$", block, re.MULTILINE)
        work_match = re.search(r"^\s*Title: Work (\d+)$", block, re.MULTILINE)
        if local_match and work_match:
            entries.append((int(local_match.group(1)), int(work_match.group(1))))
    return entries


def openalex_work(work_id, field_id):
    return {
        "id": f"https://openalex.org/{work_id}",
        "display_name": f"Work {work_id}",
        "primary_topic": {"field": {"id": f"https://openalex.org/fields/{field_id}"}},
        "referenced_works": [],
    }


def ranking_record(index):
    uid = f"W{index:02d}"
    return PaperRecord(uid=uid, title=f"Work {index}", raw={})


class DisciplineMappingTest(unittest.TestCase):
    def test_openalex_field_catalog_has_26_fields(self):
        fields = list_discipline_fields()
        self.assertEqual(len(fields), 26)
        self.assertEqual(fields[6]["id"], "17")
        self.assertEqual(fields[6]["label"], "Computer Science")

    def test_normalize_accepts_ids_urls_and_labels(self):
        values = ["https://openalex.org/fields/17", "Business, Management and Accounting", "17"]
        self.assertEqual(normalize_discipline_ids(values), ("17", "14"))

    def test_normalize_accepts_semicolon_separated_labels_with_commas(self):
        values = "Computer Science;Business, Management and Accounting"
        self.assertEqual(normalize_discipline_ids(values), ("17", "14"))

    def test_normalize_keeps_comma_support_for_pure_id_lists(self):
        self.assertEqual(normalize_discipline_ids("17,14"), ("17", "14"))

    def test_source_specific_mappings(self):
        self.assertEqual(openalex_field_filter(["17", "14"]), "primary_topic.field.id:17|14")
        self.assertEqual(source_filter_mode("paperhub"), "text")
        self.assertEqual(len(list_source_filter_options("wos")), 254)
        self.assertIn("cs.LG", [item["id"] for item in list_source_filter_options("arxiv")])
        self.assertEqual(normalize_source_filter_values("arxiv", ["cs.LG", "cs.IR"]), ("cs.LG", "cs.IR"))
        self.assertIn("WC=(", wos_category_clause(["Computer Science, Artificial Intelligence"]))
        self.assertIn("Computer Science, Artificial Intelligence", wos_category_clause(["Computer Science, Artificial Intelligence"]))

    def test_wos_filter_is_used_as_context_only_for_starter_api(self):
        query = apply_wos_discipline_filter("TS=(open innovation)", ["Computer Science, Artificial Intelligence"])
        self.assertEqual(query, "TS=(open innovation)")
        self.assertEqual(apply_wos_discipline_filter(query, ["Computer Science, Artificial Intelligence"]), query)

    def test_wos_filter_removes_unsupported_wc_clause(self):
        query = apply_wos_discipline_filter(
            "(TS=(AI) OR TS=(governance)) AND WC=(Computer Science, Artificial Intelligence)",
            ["Computer Science, Artificial Intelligence"],
        )
        self.assertEqual(query, "(TS=(AI) OR TS=(governance))")

    def test_wos_raw_fallback_handles_non_strict_response_fields(self):
        captured = {}

        def fake_get(url, *, params=None, headers=None, timeout=45):
            captured["url"] = url
            captured["params"] = params or {}
            captured["has_key"] = bool((headers or {}).get("X-ApiKey"))
            return FakeResponse(payload={
                "metadata": {"total": "1", "page": "1", "limit": "5"},
                "hits": [{
                    "uid": "WOS:1",
                    "title": "AI Governance",
                    "types": ["Article"],
                    "source": {"sourceTitle": "Research Policy", "publishYear": "2025"},
                    "names": {"authors": [{"displayName": "Ada Lovelace"}]},
                    "identifiers": {"doi": "10.1234/example"},
                    "citations": [{"db": "WOS", "count": "7"}],
                }],
            })

        config = SimpleNamespace(
            data_source="wos",
            discipline_fields=(),
            expand_citations=False,
            target_max=5,
            wos_api_key="secret",
            wos_db="WOS",
        )
        agent = PaperSeekAgent(config, object())

        with patch.object(agent.documents_api, "documents_get", side_effect=ValueError("strict parse")):
            with patch("paperseek_core.sources.wos.requests.get", side_effect=fake_get):
                result = agent._provider_search("TS=(AI governance)")

        self.assertEqual(captured["params"]["q"], "TS=(AI governance)")
        self.assertTrue(captured["has_key"])
        self.assertEqual(result.metadata.total, 1)
        self.assertEqual(result.hits[0].title, "AI Governance")
        self.assertEqual(result.hits[0].source.publish_year, 2025)
        self.assertEqual(result.hits[0].citations[0].count, 7)

    def test_wos_search_retries_once_after_rate_limit(self):
        class FakeDocumentsApi:
            def __init__(self):
                self.calls = 0

            def documents_get(self, q, db, limit, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise ApiException(status=429, reason="Too Many Requests", body="rate limited")
                return ProviderSearchResult(
                    metadata=SearchMetadata(total=1, page=1, limit=limit),
                    hits=[PaperRecord(uid="WOS:1", title="AI Governance")],
                )

        config = SimpleNamespace(
            data_source="wos",
            discipline_fields=(),
            expand_citations=False,
            target_max=5,
            wos_api_key="secret",
            wos_db="WOS",
        )
        agent = PaperSeekAgent(config, object())
        agent.documents_api = FakeDocumentsApi()

        with patch("paperseek_core.sources.wos.time.sleep") as sleep:
            result = agent._provider_search("TS=(AI governance)")

        self.assertEqual(agent.documents_api.calls, 2)
        sleep.assert_called_once()
        self.assertEqual(result.hits[0].title, "AI Governance")

    def test_arxiv_filter_is_appended_once(self):
        query = apply_arxiv_category_filter("graph neural networks", ["cs.LG"])
        self.assertEqual(query, "graph neural networks AND (cat:cs.LG)")
        self.assertEqual(apply_arxiv_category_filter(query, ["cs.IR"]), query)

    def test_arxiv_filter_groups_or_query(self):
        query = apply_arxiv_category_filter('all:"graph neural networks" OR all:GNN', ["cs.LG"])
        self.assertEqual(query, '(all:"graph neural networks" OR all:GNN) AND (cat:cs.LG)')

    def test_openalex_provider_sends_field_filter(self):
        captured = {}

        def fake_get(_, __, *, params=None, headers=None, timeout=30, query="", attempts=3):
            captured.update(params or {})
            return FakeResponse(), {"method": "GET", "url": FakeResponse.url, "status": 200, "elapsed_ms": 1}

        with patch("paperseek_core.sources.openalex.get_with_retries", side_effect=fake_get):
            result = OpenAlexProvider().search("open innovation", limit=1, field_ids=("17", "14"))

        self.assertEqual(result.metadata.total, 0)
        self.assertEqual(captured["filter"], "primary_topic.field.id:17|14")

    def test_agent_passes_discipline_fields_to_openalex_citation_expansion(self):
        captured = {}

        class FakeOpenAlexProvider(OpenAlexProvider):
            def citation_neighbors_with_graph(self, seeds, per_seed=4, max_records=40, field_ids=None, seed_plans=None, depth=1):
                captured["field_ids"] = field_ids
                captured["seed_plans"] = seed_plans
                captured["depth"] = depth
                return {"records": [], "nodes": [], "edges": []}

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=("17", "14"),
            expand_citations=True,
            citation_seed_count=1,
            citation_per_seed=2,
            citation_max_records=10,
            target_max=5,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, object())
        seed = PaperRecord(
            uid="https://openalex.org/Wseed",
            title="Seed",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/Wseed"),
            raw={"referenced_works": []},
        )
        agent.provider = FakeOpenAlexProvider()
        agent._rank_results = lambda question, candidates, **_: [{"document": seed, "score": 10}]

        agent._prepare_candidates("open innovation", [seed])

        self.assertEqual(captured["field_ids"], ("17", "14"))
        self.assertEqual(captured["depth"], 2)
        self.assertEqual(len(captured["seed_plans"]), 1)
        self.assertEqual(agent.search_run_state.citation_planning_decisions[0].seed_limit, 1)
        self.assertEqual(agent.search_run_state.citation_planning_decisions[0].depth, 2)

    def test_agent_builds_multi_lane_citation_seed_plans(self):
        captured = {}

        class FakeOpenAlexProvider(OpenAlexProvider):
            def citation_neighbors_with_graph(self, seeds, per_seed=4, max_records=40, field_ids=None, seed_plans=None, depth=1):
                captured["seed_plans"] = seed_plans
                captured["depth"] = depth
                return {"records": [], "nodes": [], "edges": []}

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=True,
            citation_seed_count=6,
            citation_per_seed=2,
            citation_max_records=20,
            citation_depth=2,
            target_max=5,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, object())
        records = []
        for index, (citations, year) in enumerate(((2, 2020), (50, 2016), (4, 2024), (25, 2021), (1, 2025), (12, 2019)), start=1):
            records.append(PaperRecord(
                uid=f"https://openalex.org/Wseed{index}",
                title=f"Seed {index}",
                source=SimpleNamespace(publish_year=year),
                citations=[SimpleNamespace(count=citations)],
                identifiers=PaperIdentifiers(openalex=f"https://openalex.org/Wseed{index}"),
                raw={"referenced_works": []},
            ))
        agent.provider = FakeOpenAlexProvider()
        agent._rank_results = lambda question, candidates, **_: [
            {"document": doc, "score": score}
            for doc, score in zip(records, (10, 9, 8, 6, 5, 4))
        ]

        agent._prepare_candidates("open innovation", records)

        plans = captured["seed_plans"]
        self.assertEqual(len(plans), 6)
        self.assertEqual(captured["depth"], 2)
        roles_by_uid = {plan.record.uid: plan.role for plan in plans}
        self.assertIn("relevance", roles_by_uid["https://openalex.org/Wseed1"])
        self.assertIn("impact", roles_by_uid["https://openalex.org/Wseed2"])
        self.assertIn("recent", roles_by_uid["https://openalex.org/Wseed5"])
        first_three_roles = {role for plan in plans[:3] for role in plan.role.split("+")}
        self.assertTrue({"relevance", "impact", "recent"}.issubset(first_three_roles))
        directions = {plan.role: set(plan.directions) for plan in plans}
        self.assertIn("backward", directions["relevance"])
        self.assertIn("forward", directions["relevance"])
        planning = agent.search_run_state.citation_planning_decisions[0]
        self.assertEqual(planning.seed_limit, 6)
        self.assertEqual((planning.relevance_quota, planning.impact_quota, planning.recent_quota), (3, 1, 2))

    def test_agent_selects_bounded_citation_seed_pool_without_llm_ranking(self):
        captured = {}

        class FakeOpenAlexProvider(OpenAlexProvider):
            def citation_neighbors_with_graph(self, seeds, per_seed=4, max_records=40, field_ids=None, seed_plans=None, depth=1):
                captured["seed_plans"] = seed_plans
                return {"records": [], "nodes": [], "edges": []}

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=True,
            citation_seed_count=30,
            citation_per_seed=2,
            citation_max_records=20,
            citation_depth=2,
            ranking_candidate_limit=256,
            target_max=50,
            retrieval_pool_max=3000,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, object())
        records = [
            PaperRecord(
                uid=f"https://openalex.org/Wseed{index}",
                title=f"Seed {index}",
                identifiers=PaperIdentifiers(openalex=f"https://openalex.org/Wseed{index}"),
                raw={"referenced_works": []},
            )
            for index in range(1000)
        ]
        agent.provider = FakeOpenAlexProvider()

        agent._rank_results = lambda *args, **kwargs: self.fail("citation seed selection must not call the LLM ranker")

        agent._prepare_candidates("open innovation", records)

        self.assertEqual(len(captured["seed_plans"]), 30)
        self.assertEqual(agent.search_run_state.citation_planning_decisions[0].seed_ranking_count, 120)

    def test_citation_seed_pool_preserves_successor_view_candidates(self):
        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=True,
            citation_seed_count=30,
            ranking_candidate_limit=256,
            target_max=50,
            retrieval_pool_max=3000,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, object())
        agent.search_plan = parse_search_plan(
            """
            {
              "intent": "Survey image retrieval.",
              "question_type": "broad_landscape",
              "query_views": [
                {
                  "view_id": "successor",
                  "view_type": "successor_paradigm",
                  "purpose": "Modern successor terminology",
                  "concept_groups": [{"label": "successor", "terms": ["vision-language pretraining"]}]
                }
              ]
            }
            """,
            "What works are related to image retrieval?",
        )
        global_candidates = [PaperRecord(uid=f"W{index}", title=f"Global {index}") for index in range(200)]
        successor_candidates = global_candidates[140:180]
        agent.query_portfolio_lane_results = {"successor": successor_candidates}

        pool = agent._citation_seed_candidate_pool(global_candidates, 120)

        self.assertEqual(len(pool), 120)
        self.assertTrue(all(document in pool for document in successor_candidates))

    def test_agent_records_candidate_queue_for_citation_expansion_dedupe(self):
        class FakeOpenAlexProvider(OpenAlexProvider):
            def citation_neighbors_with_graph(self, seeds, per_seed=4, max_records=40, field_ids=None, seed_plans=None, depth=1):
                duplicate = PaperRecord(
                    uid="https://openalex.org/Wseed",
                    title="Seed duplicate",
                    identifiers=PaperIdentifiers(openalex="https://openalex.org/Wseed"),
                    raw={"referenced_works": []},
                )
                new_neighbor = PaperRecord(
                    uid="https://openalex.org/Wnew",
                    title="New neighbor",
                    identifiers=PaperIdentifiers(openalex="https://openalex.org/Wnew"),
                    raw={"referenced_works": []},
                )
                return {
                    "records": [duplicate, new_neighbor],
                    "nodes": [],
                    "edges": [
                        {
                            "source": "https://openalex.org/Wseed",
                            "target": "https://openalex.org/Wnew",
                            "type": "references",
                            "seed": "https://openalex.org/Wseed",
                            "layer": "1",
                        }
                    ],
                }

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=True,
            citation_seed_count=1,
            citation_per_seed=2,
            citation_max_records=10,
            citation_depth=1,
            target_max=5,
            openalex_api_key="",
            openalex_email="",
        )
        seed = PaperRecord(
            uid="https://openalex.org/Wseed",
            title="Seed",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/Wseed"),
            raw={"referenced_works": []},
        )
        agent = PaperSeekAgent(config, object())
        agent.provider = FakeOpenAlexProvider()
        agent._rank_results = lambda question, candidates, **_: [{"document": seed, "score": 10}]

        candidates = agent._prepare_candidates("open innovation", [seed])

        self.assertEqual(
            {document.uid for document in candidates},
            {"https://openalex.org/Wseed", "https://openalex.org/Wnew"},
        )
        self.assertEqual(agent.citation_map["added_candidates"], 1)
        queue = agent.search_run_state.candidate_queue
        self.assertEqual(queue.origin_counts["retrieval"], 1)
        self.assertEqual(queue.origin_counts["citation_expansion"], 1)
        self.assertEqual(queue.duplicate_count, 1)
        self.assertEqual(queue.events[1].duplicates, 1)
        neighbor = queue.ledger["openalex:https://openalex.org/wnew"]
        self.assertEqual(neighbor.origins, ["citation_expansion"])
        self.assertEqual(len(neighbor.citation_paths), 1)
        self.assertEqual(neighbor.citation_paths[0].seed_id, "https://openalex.org/Wseed")
        self.assertEqual(neighbor.citation_paths[0].direction, "backward")
        self.assertEqual(neighbor.citation_paths[0].depth, 1)
        self.assertIsNotNone(neighbor.retrieval_score)
        self.assertIn("citation_expansion", neighbor.retrieval_lanes)

    def test_agent_retries_citation_expansion_with_reduced_budget(self):
        captured = {"calls": []}

        class FlakyOpenAlexProvider(OpenAlexProvider):
            def citation_neighbors_with_graph(self, seeds, per_seed=4, max_records=40, field_ids=None, seed_plans=None, depth=1):
                captured["calls"].append((per_seed, max_records, depth))
                if len(captured["calls"]) == 1:
                    raise ProviderError("openalex", "temporary citation failure", status=503)
                neighbor = PaperRecord(
                    uid="https://openalex.org/Wneighbor",
                    title="Recovered neighbor",
                    identifiers=PaperIdentifiers(openalex="https://openalex.org/Wneighbor"),
                    raw={"referenced_works": []},
                )
                return {"records": [neighbor], "nodes": [], "edges": []}

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=True,
            citation_seed_count=1,
            citation_per_seed=4,
            citation_max_records=20,
            citation_depth=2,
            target_max=5,
            openalex_api_key="",
            openalex_email="",
        )
        seed = PaperRecord(
            uid="https://openalex.org/Wseed",
            title="Seed",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/Wseed"),
            raw={"referenced_works": []},
        )
        agent = PaperSeekAgent(config, object())
        agent.provider = FlakyOpenAlexProvider()
        agent._rank_results = lambda question, candidates, **_: [{"document": seed, "score": 10}]

        candidates = agent._prepare_candidates("open innovation", [seed])

        self.assertEqual(captured["calls"], [(4, 20, 2), (2, 10, 1)])
        self.assertEqual(
            {document.uid for document in candidates},
            {"https://openalex.org/Wseed", "https://openalex.org/Wneighbor"},
        )
        self.assertEqual(agent.citation_map["status"], "complete")
        self.assertEqual(agent.citation_map["citation_depth"], 1)
        state = agent.search_run_state
        self.assertEqual(state.citation_traversal_observations[0].status, "error")
        self.assertEqual(state.citation_recovery_decisions[0].action, "retry_reduced")
        self.assertEqual(state.citation_traversal_observations[1].status, "complete")

    def test_agent_skips_citation_expansion_after_reduced_retry_fails(self):
        captured = {"calls": []}

        class FailingOpenAlexProvider(OpenAlexProvider):
            def citation_neighbors_with_graph(self, seeds, per_seed=4, max_records=40, field_ids=None, seed_plans=None, depth=1):
                captured["calls"].append((per_seed, max_records, depth))
                raise ProviderError("openalex", "persistent citation failure", status=503)

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=True,
            citation_seed_count=1,
            citation_per_seed=4,
            citation_max_records=20,
            citation_depth=2,
            target_max=5,
            openalex_api_key="",
            openalex_email="",
        )
        seed = PaperRecord(
            uid="https://openalex.org/Wseed",
            title="Seed",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/Wseed"),
            raw={"referenced_works": []},
        )
        agent = PaperSeekAgent(config, object())
        agent.provider = FailingOpenAlexProvider()
        agent._rank_results = lambda question, candidates, **_: [{"document": seed, "score": 10}]

        candidates = agent._prepare_candidates("open innovation", [seed])

        self.assertEqual(captured["calls"], [(4, 20, 2), (2, 10, 1)])
        self.assertEqual([document.uid for document in candidates], ["https://openalex.org/Wseed"])
        self.assertEqual(agent.citation_map["status"], "error")
        state = agent.search_run_state
        self.assertEqual([item.status for item in state.citation_traversal_observations], ["error", "error"])
        self.assertEqual([item.action for item in state.citation_recovery_decisions], ["retry_reduced", "skip_citation_expansion"])

    def test_agent_ranks_large_candidate_sets_in_parallel_batches(self):
        calls = []
        llm = BatchRankingLlm(calls)
        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=8,
            ranking_concurrency=4,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, llm)

        ranked = agent._rank_results("open innovation", [ranking_record(index) for index in range(40)])

        self.assertEqual(len(calls), 5)
        self.assertEqual(sorted(len(call) for call in calls), [8, 8, 8, 8, 8])
        self.assertEqual(ranked[0]["document"].uid, "W39")
        self.assertEqual(ranked[-1]["document"].uid, "W00")

    def test_agent_keeps_results_when_one_parallel_ranking_batch_fails(self):
        calls = []
        llm = BatchRankingLlm(calls, fail_uid="W04")
        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=4,
            ranking_concurrency=2,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, llm)

        ranked = agent._rank_results("open innovation", [ranking_record(index) for index in range(12)])

        self.assertEqual(len(ranked), 12)
        self.assertEqual(len(calls), 3)
        self.assertEqual(ranked[0]["document"].uid, "W11")
        failed_batch = {entry["document"].uid: entry for entry in ranked if entry["document"].uid in {"W04", "W05", "W06", "W07"}}
        self.assertTrue(failed_batch)
        self.assertTrue(all(entry["score"] == 0 for entry in failed_batch.values()))

    def test_agent_keeps_local_order_when_single_ranking_batch_fails(self):
        class FailingRankingLlm:
            def chat(self, messages, temperature=0.3):
                raise RuntimeError("LLM network error: timeout")

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=8,
            ranking_concurrency=4,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, FailingRankingLlm())
        events = []
        agent.event_handler = events.append

        ranked = agent._rank_results("open innovation", [ranking_record(index) for index in range(3)])

        self.assertEqual([entry["document"].uid for entry in ranked], ["W00", "W01", "W02"])
        self.assertTrue(all(entry["score"] == 0 for entry in ranked))
        step_statuses = [
            step.get("status")
            for event in events
            for step in (event.get("data") or {}).get("ranking_steps", [])
        ]
        self.assertIn("skipped", step_statuses)

    def test_agent_keeps_local_order_when_all_parallel_ranking_batches_fail(self):
        class AlwaysFailRankingLlm:
            def fork(self):
                return AlwaysFailRankingLlm()

            def chat(self, messages, temperature=0.3):
                raise RuntimeError("LLM network error: timeout")

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=4,
            ranking_concurrency=8,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, AlwaysFailRankingLlm())
        events = []
        agent.event_handler = events.append

        ranked = agent._rank_results("open innovation", [ranking_record(index) for index in range(8)])

        self.assertEqual([entry["document"].uid for entry in ranked], [f"W{index:02d}" for index in range(8)])
        self.assertTrue(all(entry["score"] == 0 for entry in ranked))
        log_text = "\n".join(event.get("message", "") for event in events if event.get("type") == "log")
        self.assertIn("All result ranking batches failed; returning candidates in source order", log_text)
        self.assertFalse(any(
            step.get("status") == "error"
            for event in events
            for step in (event.get("data") or {}).get("ranking_steps", [])
        ))

    def test_agent_retries_failed_ranking_batches_at_lower_concurrency(self):
        class RetryOnceRankingLlm(BatchRankingLlm):
            def __init__(self, calls, attempts=None):
                super().__init__(calls)
                self.attempts = attempts if attempts is not None else {}

            def fork(self):
                return RetryOnceRankingLlm(self.calls, self.attempts)

            def chat(self, messages, temperature=0.3):
                text = messages[-1]["content"]
                reason_indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", text, re.MULTILINE)]
                if reason_indexes:
                    return json.dumps({"reasons": [[index, "ranked"] for index in reason_indexes]})
                entries = _compact_work_entries(text)
                uids = [f"W{work_index:02d}" for _, work_index in entries]
                self.calls.append(tuple(uids))
                if "W04" in uids and not self.attempts.get("W04"):
                    self.attempts["W04"] = 1
                    raise RuntimeError("temporary endpoint pressure")
                return json.dumps({"scores": [[local_index, work_index] for local_index, work_index in entries]})

        calls = []
        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=4,
            ranking_concurrency=32,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, RetryOnceRankingLlm(calls))
        events = []
        agent.event_handler = events.append

        ranked = agent._rank_results("open innovation", [ranking_record(index) for index in range(12)])

        self.assertEqual(len(ranked), 12)
        self.assertGreater(len(calls), 3)
        self.assertEqual(ranked[0]["document"].uid, "W11")
        self.assertEqual(ranked[-1]["document"].uid, "W00")
        log_text = "\n".join(event.get("message", "") for event in events if event.get("type") == "log")
        self.assertIn("Retrying 1 failed result-ranking batch(es) with concurrency=16.", log_text)
        self.assertFalse(any(
            "concurrency=1." in line or "concurrency=1;" in line
            for line in log_text.splitlines()
        ))

    def test_agent_backs_off_before_submitting_all_batches_after_rate_limit(self):
        class RateLimitRankingLlm(BatchRankingLlm):
            def __init__(self, calls):
                super().__init__(calls)

            def fork(self):
                return RateLimitRankingLlm(self.calls)

            def chat(self, messages, temperature=0.3):
                text = messages[-1]["content"]
                reason_indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", text, re.MULTILINE)]
                if reason_indexes:
                    return json.dumps({"reasons": [[index, "ranked"] for index in reason_indexes]})
                entries = _compact_work_entries(text)
                uids = [f"W{work_index:02d}" for _, work_index in entries]
                self.calls.append(tuple(uids))
                if "W00" in uids:
                    raise RuntimeError("LLM API error (429): too many requests")
                return json.dumps({"scores": [[local_index, work_index] for local_index, work_index in entries]})

        calls = []
        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=1,
            ranking_concurrency=32,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, RateLimitRankingLlm(calls))
        events = []
        agent.event_handler = events.append

        ranked = agent._rank_results("open innovation", [ranking_record(index) for index in range(80)])

        self.assertEqual(len(ranked), 80)
        first_tier_uids = {uid for call in calls[:32] for uid in call}
        self.assertTrue(first_tier_uids)
        self.assertTrue(all(int(uid.replace("W", "")) < 32 for uid in first_tier_uids))
        log_text = "\n".join(event.get("message", "") for event in events if event.get("type") == "log")
        self.assertIn("Rate limit detected at concurrency=32", log_text)

    def test_ranking_concurrency_schedule_never_goes_below_four(self):
        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_concurrency=2,
            openalex_api_key="",
            openalex_email="",
        )
        agent = PaperSeekAgent(config, BatchRankingLlm([]))

        self.assertEqual(agent._ranking_concurrency(), 4)
        self.assertEqual(agent._ranking_concurrency_schedule(8), [4])

        delattr(config, "ranking_concurrency")
        self.assertEqual(agent._ranking_concurrency(), 16)
        self.assertEqual(agent._ranking_concurrency_schedule(8), [16, 8, 4])

        config.ranking_concurrency = "invalid"
        self.assertEqual(agent._ranking_concurrency(), 16)

        config.ranking_concurrency = 32
        self.assertEqual(agent._ranking_concurrency_schedule(8), [32, 16, 8, 4])
        self.assertTrue(all(value >= 4 for value in agent._ranking_concurrency_schedule(8)))

    def test_ranking_stage_events_include_search_context(self):
        class FakeProvider:
            def search(self, query, limit=50, field_ids=()):
                return ProviderSearchResult(
                    metadata=SearchMetadata(total=2, page=1, limit=limit),
                    hits=[ranking_record(0), ranking_record(1)],
                )

        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            ranking_batch_size=8,
            ranking_concurrency=4,
            target_min=1,
            target_max=5,
            max_iterations=1,
            fetch_abstracts=False,
            openalex_api_key="",
            openalex_email="",
        )
        events = []
        agent = PaperSeekAgent(config, BatchRankingLlm())
        agent.provider = FakeProvider()
        agent._generate_query = lambda question: "open innovation"
        agent.search("open innovation", event_handler=events.append)

        ranking_events = [
            event for event in events
            if event.get("type") == "stage" and event.get("stage") == "ranking" and event.get("status") == "processing"
        ]
        self.assertGreaterEqual(len(ranking_events), 1)
        payload = ranking_events[0]["data"]
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual(payload["final_query"], "open innovation")
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["history"][0]["action"], "accept")
        self.assertEqual(payload["source"], "openalex")
        self.assertTrue(any((event.get("data") or {}).get("ranking_steps") for event in ranking_events))

    def test_openalex_citation_expansion_filters_neighbors_by_field(self):
        captured = {}

        def fake_get(_, url, *, params=None, headers=None, timeout=30, query="", attempts=3):
            request_filter = (params or {}).get("filter", "")
            if request_filter.startswith("openalex:"):
                captured["backward_filter"] = request_filter
                return FakeResponse({
                    "meta": {"count": 2, "page": 1, "per_page": 2},
                    "results": [openalex_work("Wback_in", "17"), openalex_work("Wback_out", "14")],
                }), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            captured["forward_filter"] = request_filter
            return FakeResponse({
                "meta": {"count": 2, "page": 1, "per_page": 2},
                "results": [openalex_work("Wforward_in", "17"), openalex_work("Wforward_out", "14")],
            }), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        seed = PaperRecord(
            uid="https://openalex.org/Wseed",
            title="Seed",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/Wseed"),
            raw={
                "referenced_works": [
                    "https://openalex.org/Wback_in",
                    "https://openalex.org/Wback_out",
                ]
            },
        )

        with patch("paperseek_core.sources.openalex.get_with_retries", side_effect=fake_get):
            citation_data = OpenAlexProvider().citation_neighbors_with_graph(
                [seed],
                per_seed=4,
                max_records=10,
                field_ids=("17",),
            )

        self.assertEqual(captured["backward_filter"], "openalex:Wback_in|Wback_out")
        self.assertEqual(captured["forward_filter"], "cites:Wseed,primary_topic.field.id:17")
        record_ids = {record.uid for record in citation_data["records"]}
        self.assertIn("https://openalex.org/Wback_in", record_ids)
        self.assertIn("https://openalex.org/Wforward_in", record_ids)
        self.assertNotIn("https://openalex.org/Wback_out", record_ids)
        self.assertNotIn("https://openalex.org/Wforward_out", record_ids)
        node_ids = {node["id"] for node in citation_data["nodes"]}
        self.assertIn("https://openalex.org/Wback_in", node_ids)
        self.assertIn("https://openalex.org/Wforward_in", node_ids)
        self.assertNotIn("https://openalex.org/Wback_out", node_ids)
        self.assertNotIn("https://openalex.org/Wforward_out", node_ids)

    def test_openalex_citation_expansion_uses_seed_plan_depth_and_direction(self):
        calls = []

        def work(work_id, references=None):
            payload = openalex_work(work_id, "17")
            payload["referenced_works"] = references or []
            return payload

        def fake_get(_, url, *, params=None, headers=None, timeout=30, query="", attempts=3):
            calls.append((url, params or {}, query))
            request_filter = (params or {}).get("filter", "")
            if request_filter.startswith("cites:"):
                return FakeResponse({
                    "meta": {"count": 1, "page": 1, "per_page": 1},
                    "results": [work("Wforward_should_not_be_called")],
                }), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            if request_filter == "openalex:Wback1":
                return FakeResponse({"results": [work("Wback1", ["https://openalex.org/Wback2"])]}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            if request_filter == "openalex:Wback2":
                return FakeResponse({"results": [work("Wback2")]}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            return FakeResponse({"results": []}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        seed = PaperRecord(
            uid="https://openalex.org/Wseed",
            title="Seed",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/Wseed"),
            raw={"referenced_works": ["https://openalex.org/Wback1"]},
        )

        with patch("paperseek_core.sources.openalex.get_with_retries", side_effect=fake_get):
            citation_data = OpenAlexProvider().citation_neighbors_with_graph(
                [seed],
                per_seed=2,
                max_records=10,
                field_ids=("17",),
                seed_plans=[CitationSeedPlan(record=seed, role="impact", directions=("backward",), depth=2)],
                depth=2,
            )

        record_ids = {record.uid for record in citation_data["records"]}
        self.assertIn("https://openalex.org/Wback1", record_ids)
        self.assertIn("https://openalex.org/Wback2", record_ids)
        self.assertFalse(any((params or {}).get("filter", "").startswith("cites:") for _, params, _ in calls))
        self.assertEqual({edge.get("layer") for edge in citation_data["edges"]}, {"1", "2"})


if __name__ == "__main__":
    unittest.main()
