"""Capability-driven candidate retrieval orchestration."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Optional

from paperseek_core.execution import SearchCancelled
from paperseek_core.retrieval import RetrievalLane, fuse_candidates_rrf


class RetrievalPipeline:
    def __init__(self, host: Any):
        self.host = host

    def run(self, question: str, query: str, primary_hits: list) -> list:
        host = self.host
        capabilities = host._retrieval_capabilities()
        lane_limits = {
            lane: host._effective_lane_limit(capabilities, lane)
            for lane in capabilities.lanes
        }
        lane_results = self._collect_capability_lanes(
            question,
            query,
            primary_hits,
            capabilities,
            lane_limits,
        )
        lane_results = self._supplement_lane_results(query, primary_hits, capabilities.lanes, lane_results)
        if not lane_results:
            host._emit_ranking_step(
                "multi_lane_retrieval",
                "complete",
                "Multi-lane retrieval",
                current=max(1, len(capabilities.lanes)),
                total=max(1, len(capabilities.lanes)),
                detail="No retrieval lanes returned candidates; using the primary source response.",
            )
            return list(primary_hits or [])
        return self._fuse_and_enhance(question, capabilities.lanes, lane_results)

    def _collect_capability_lanes(
        self,
        question: str,
        query: str,
        primary_hits: list,
        capabilities: Any,
        lane_limits: dict[str, int],
    ) -> dict[str, list]:
        host = self.host
        lane_results = {}
        lane_total = max(1, len(capabilities.lanes))
        try:
            concurrency = max(
                1,
                min(len(capabilities.lanes), int(getattr(capabilities, "lane_concurrency", 1) or 1)),
            )
        except (TypeError, ValueError):
            concurrency = 1
        host._emit_ranking_step(
            "multi_lane_retrieval",
            "processing",
            "Multi-lane retrieval",
            current=0,
            total=lane_total,
            detail=(
                f"Starting {', '.join(capabilities.lanes)} lanes; lane limits {lane_limits}; "
                f"concurrency {concurrency}."
            ),
        )
        host._emit_log(
            "Lightweight multi-lane retrieval started: "
            f"source={host.data_source}; lanes={','.join(capabilities.lanes)}; "
            f"lane_limits={lane_limits}; lane_concurrency={concurrency}; "
            f"pool_max={host._retrieval_pool_max()}."
        )
        completed_lanes = 0
        host._retrieval_primary_hits = list(primary_hits or [])

        def collect(lane: str) -> list:
            lane_query = question if lane == RetrievalLane.SEMANTIC else query
            return host._collect_retrieval_lane(lane_query, lane, lane_limits[lane])

        def record(lane: str, documents: Optional[list] = None, error: Optional[Exception] = None) -> None:
            nonlocal completed_lanes
            if error is None:
                lane_results[lane] = list(documents or [])
                host._emit_log(f"Retrieval lane completed: {lane}; candidates={len(lane_results[lane])}.")
            else:
                host._emit_log(
                    f"Retrieval lane skipped after error: {lane}; {error.__class__.__name__}: {error}"
                )
            completed_lanes += 1
            host._emit_ranking_step(
                "multi_lane_retrieval",
                "processing",
                "Multi-lane retrieval",
                current=completed_lanes,
                total=lane_total,
                detail=(
                    f"{lane} lane finished; collected "
                    f"{sum(len(values) for values in lane_results.values())} lane candidates."
                ),
                lane_counts={key: len(value) for key, value in lane_results.items()},
            )

        try:
            if concurrency == 1:
                for lane in capabilities.lanes:
                    try:
                        record(lane, collect(lane))
                    except SearchCancelled:
                        raise
                    except Exception as exc:
                        record(lane, error=exc)
            else:
                self._collect_concurrently(capabilities.lanes, concurrency, collect, record)
        finally:
            host._retrieval_primary_hits = []

        return {
            lane: lane_results[lane]
            for lane in capabilities.lanes
            if lane in lane_results
        }

    def _collect_concurrently(self, lanes: tuple[str, ...], concurrency: int, collect: Any, record: Any) -> None:
        host = self.host
        executor = ThreadPoolExecutor(max_workers=concurrency)
        try:
            future_to_lane = {executor.submit(collect, lane): lane for lane in lanes}
            pending = set(future_to_lane)
            while pending:
                done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                host._check_cancelled()
                for future in done:
                    lane = future_to_lane[future]
                    try:
                        record(lane, future.result())
                    except SearchCancelled:
                        raise
                    except Exception as exc:
                        record(lane, error=exc)
        except SearchCancelled:
            executor.shutdown(wait=False, cancel_futures=True)
            executor = None
            raise
        finally:
            if executor is not None:
                executor.shutdown(wait=True)

    def _supplement_lane_results(
        self,
        query: str,
        primary_hits: list,
        capability_lanes: tuple[str, ...],
        lane_results: dict[str, list],
    ) -> dict[str, list]:
        host = self.host
        for view_id, documents in host.query_portfolio_lane_results.items():
            if documents:
                lane_results[f"query_view:{view_id}"] = host._dedupe_documents(documents)
        iteration_lanes = host._query_iteration_lanes(query)
        lane_results.update(iteration_lanes)
        if iteration_lanes:
            host._emit_log(
                "Query iteration memory added to candidate fusion: "
                f"lanes={len(iteration_lanes)}; candidates="
                f"{sum(len(documents) for documents in iteration_lanes.values())}."
            )
        if not lane_results and primary_hits:
            lane_results[RetrievalLane.RELEVANCE] = list(primary_hits)
        return lane_results

    def _fuse_and_enhance(self, question: str, capability_lanes: tuple[str, ...], lane_results: dict[str, list]) -> list:
        host = self.host
        ordered_docs = [document for lane_docs in lane_results.values() for document in lane_docs]
        unique_docs = host._dedupe_documents(ordered_docs)
        host._emit_ranking_step(
            "embedding_similarity",
            "processing",
            "Embedding similarity",
            current=0,
            total=max(1, len(unique_docs)),
            detail=f"Computing semantic similarity for {len(unique_docs)} unique candidates.",
        )
        embedding_scores = host._external_embedding_scores(question, unique_docs)
        host._emit_ranking_step(
            "embedding_similarity",
            "complete",
            "Embedding similarity",
            current=len(unique_docs),
            total=max(1, len(unique_docs)),
            detail="External embedding completed." if embedding_scores else "Using local sparse hashing similarity.",
        )
        host._emit_ranking_step(
            "rrf_fusion",
            "processing",
            "RRF fusion",
            current=0,
            total=max(1, len(unique_docs)),
            detail=(
                "Fusing lane rank, BM25/term coverage, and embedding signals for "
                f"{len(unique_docs)} candidates."
            ),
        )
        fused = fuse_candidates_rrf(
            question,
            lane_results,
            pool_max=host._retrieval_pool_max(),
            rrf_k=host._retrieval_rrf_k(),
            embedding_scores_by_key=host._embedding_score_map(unique_docs, embedding_scores),
        )
        host.retrieval_metadata_by_key = fused.metadata_by_key
        host._emit_ranking_step(
            "rrf_fusion",
            "complete",
            "RRF fusion",
            current=len(fused.documents),
            total=max(1, fused.total_candidates),
            detail=f"Fused {fused.total_candidates} unique candidates into a pool of {len(fused.documents)}.",
            lane_counts=fused.lane_counts,
            candidate_count=len(fused.documents),
        )
        documents = host.external_retrieval.enrich_crossref(fused.documents)
        documents = host._apply_external_reranker(question, documents)
        host._emit_log(
            "Lightweight multi-lane retrieval completed: "
            f"unique_candidates={fused.total_candidates}; fused_candidates={len(documents)}; "
            f"lane_counts={fused.lane_counts}."
        )
        lane_total = max(1, len(capability_lanes))
        host._emit_ranking_step(
            "multi_lane_retrieval",
            "complete",
            "Multi-lane retrieval",
            current=lane_total,
            total=lane_total,
            detail=f"Retrieval completed with {len(documents)} fused candidates.",
            lane_counts=fused.lane_counts,
            candidate_count=len(documents),
        )
        return documents
