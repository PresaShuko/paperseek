from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path

from paperseek.formatter import format_json
from paperseek.history import result_payload_from_search_result
from paperseek_core.agent import PaperSeekAgent
from paperseek_core.config import LLMConfig, SearchConfig, SourceConfig, build_runtime_config
from paperseek_core.retrieval import RetrievalLane
from paperseek_core.sources.contracts import ProviderSearchResult, SearchMetadata
from paperseek_core.sources.openalex import OpenAlexProvider
from tests.helpers import read_json, read_text


QUESTION = "How do transparent AI decision systems affect accountability in public agencies?"
FIXTURE_ROOT = Path("tests/fixtures/golden_search")


class GoldenFixtureLLM:
    def __init__(self) -> None:
        self._responses = [
            read_text("tests/fixtures/llm/intent_search_plan.json"),
            read_text(str(FIXTURE_ROOT / "llm_query.json")),
            read_text(str(FIXTURE_ROOT / "llm_ranking_scores.json")),
            read_text(str(FIXTURE_ROOT / "llm_ranking_reasons.json")),
        ]
        self._lock = threading.Lock()
        self.calls: list[dict] = []
        self.last_response_info = {"finish_reason": "stop", "completion_tokens": 64}
        self.timeout_seconds = 30
        self.attempts = 1

    def fork(self):
        return self

    def chat_json(self, messages, *, temperature=0.0, max_tokens=4096):
        with self._lock:
            if not self._responses:
                raise AssertionError("golden LLM response sequence was exhausted")
            self.calls.append(
                {
                    "messages": copy.deepcopy(messages),
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            )
            return self._responses.pop(0)


class GoldenOpenAlexProvider(OpenAlexProvider):
    def __init__(self) -> None:
        super().__init__(api_key="", email="")
        payload = read_json(str(FIXTURE_ROOT / "source_responses.json"))
        self._payload = payload
        self._works = {
            str(work["id"]).rstrip("/").split("/")[-1]: work
            for work in [*payload["relevance"], *payload["citations"]["records"]]
        }
        self.calls: list[dict] = []
        self._calls_lock = threading.Lock()

    def search(
        self,
        query: str,
        limit: int = 50,
        page: int = 1,
        field_ids=None,
        lane: str = RetrievalLane.RELEVANCE,
    ) -> ProviderSearchResult:
        with self._calls_lock:
            self.calls.append(
                {
                    "query": query,
                    "limit": limit,
                    "page": page,
                    "field_ids": list(field_ids or []),
                    "lane": lane,
                }
            )
        if lane == RetrievalLane.IMPACT:
            time.sleep(0.005)
        elif lane == RetrievalLane.RECENT:
            time.sleep(0.01)

        if page > 1:
            raw_works = []
        elif lane == RetrievalLane.RELEVANCE:
            raw_works = self._payload["relevance"]
        else:
            raw_works = [self._works[item["ref"]] for item in self._payload[lane]]
        hits = [self._to_record(work) for work in raw_works[:limit]]
        total = 5 if lane == RetrievalLane.RELEVANCE else len(raw_works)
        self.last_response_info = {
            "method": "GET",
            "url": "https://api.openalex.org/works",
            "status": 200,
            "attempts": 1,
        }
        return ProviderSearchResult(
            metadata=SearchMetadata(total=total, page=page, limit=max(1, len(hits))),
            hits=hits,
        )

    def citation_neighbors_with_graph(
        self,
        seeds,
        per_seed=4,
        max_records=40,
        field_ids=None,
        seed_plans=None,
        depth=1,
        cancel_check=None,
        progress_callback=None,
        request_attempts=3,
        request_timeout=30,
    ):
        del per_seed, max_records, field_ids, request_attempts, request_timeout
        plans = list(seed_plans or seeds or [])
        if cancel_check:
            cancel_check()
        if progress_callback:
            progress_callback({"event": "start", "current": 0, "total": len(plans), "records": 0})
        payload = copy.deepcopy(self._payload["citations"])
        payload["records"] = [self._to_record(work) for work in payload["records"]]
        payload["frontier"]["depth"] = depth
        payload["frontier"]["processed_plans"] = len(plans)
        if progress_callback:
            progress_callback(
                {
                    "event": "complete",
                    "current": len(plans),
                    "total": len(plans),
                    "records": len(payload["records"]),
                }
            )
        return payload


def _candidate_pool_jsonl(final_result: dict) -> str:
    queue = final_result["search_state"]["candidate_queue"]
    rows = [
        {
            "record_type": "summary",
            "keys": queue["keys"],
            "ledger_summary": queue["ledger_summary"],
            "origin_counts": queue["origin_counts"],
            "duplicate_count": queue["duplicate_count"],
        }
    ]
    rows.extend(
        {"record_type": "candidate", **queue["ledger"][key]}
        for key in queue["keys"]
    )
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )


def _cli_json_export(result: dict) -> str:
    return format_json(
        items=result["ranked"],
        question=result["question"],
        final_query=result["final_query"],
        db=result["db"],
        total_count=result["total"],
        iterations=result["iterations"],
        field_name=result["field"],
        history=result.get("history", []),
        source=result.get("source", ""),
        citation_map=result.get("citation_map", {}),
        search_intent=result.get("search_intent", ""),
        search_plan=result.get("search_plan", {}),
        query_view_selection=result.get("query_view_selection", []),
        query_portfolio=result.get("query_portfolio", []),
        query_iteration_memory=result.get("query_iteration_memory", []),
        search_state=result.get("search_state", {}),
        ranking_steps=result.get("ranking_steps", []),
    ) + "\n"


def build_search_artifacts() -> dict:
    config = build_runtime_config(
        search=SearchConfig(
            data_source="openalex",
            retrieval_embedding_provider="",
        ),
        source=SourceConfig(),
        llm=LLMConfig(),
    )
    llm = GoldenFixtureLLM()
    provider = GoldenOpenAlexProvider()
    agent = PaperSeekAgent(config, llm)
    agent.provider = provider
    result = agent.search(QUESTION)
    final_result = result_payload_from_search_result(result, config.data_source)
    return {
        "final_result": final_result,
        "final_result_text": json.dumps(final_result, ensure_ascii=False, indent=2) + "\n",
        "candidate_pool_text": _candidate_pool_jsonl(final_result),
        "citation_map_text": json.dumps(result["citation_map"], ensure_ascii=False, indent=2) + "\n",
        "json_export_text": _cli_json_export(result),
        "llm_calls": llm.calls,
        "provider_calls": provider.calls,
    }
