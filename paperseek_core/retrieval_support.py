from __future__ import annotations

from typing import Any, Dict

from paperseek_core.retrieval import RetrievalLane, document_key, fuse_candidates_rrf


class RetrievalSupport:
    """Post-retrieval fusion and candidate-ledger evidence updates."""

    def __init__(self, host: Any) -> None:
        self.host = host

    @staticmethod
    def is_citation_origin(origin: str) -> bool:
        value = str(origin or "")
        return value == "citation_expansion" or value.startswith("citation_frontier:")

    def refusion_after_citation(self, question: str, candidates: list) -> list:
        host = self.host
        unique_candidates = host._dedupe_documents(list(candidates or []))
        if not unique_candidates or host.search_run_state is None:
            return unique_candidates

        ledger = host.search_run_state.candidate_queue.ledger
        citation_keys = {
            key
            for key, evidence in ledger.items()
            if any(self.is_citation_origin(origin) for origin in evidence.origins)
        }
        citation_documents = [
            document
            for document in unique_candidates
            if document_key(document) in citation_keys
        ]
        if not citation_documents:
            return unique_candidates

        documents_by_key = {
            document_key(document): document
            for document in unique_candidates
            if document_key(document)
        }
        ranked_lanes: Dict[str, list] = {}
        for key, document in documents_by_key.items():
            metadata = dict(host.retrieval_metadata_by_key.get(key, {}) or {})
            for lane, rank in dict(metadata.get("retrieval_source_ranks", {}) or {}).items():
                try:
                    lane_rank = int(rank)
                except (TypeError, ValueError):
                    continue
                ranked_lanes.setdefault(str(lane), []).append((lane_rank, key, document))

        lane_results: Dict[str, list] = {
            lane: [document for _, _, document in sorted(values, key=lambda item: (item[0], item[1]))]
            for lane, values in ranked_lanes.items()
            if values
        }
        pre_citation_documents = []
        for document in unique_candidates:
            key = document_key(document)
            evidence = ledger.get(key)
            origins = list(evidence.origins) if evidence is not None else []
            if not origins or any(not self.is_citation_origin(origin) for origin in origins):
                pre_citation_documents.append(document)
        if pre_citation_documents:
            lane_results[RetrievalLane.LOCAL_QUALITY] = pre_citation_documents
        lane_results[RetrievalLane.CITATION] = citation_documents

        host._emit_ranking_step(
            "citation_refusion",
            "processing",
            "Citation-aware candidate fusion",
            current=0,
            total=max(1, len(unique_candidates)),
            detail=(
                "Re-ranking the complete candidate pool after citation expansion with local BM25, "
                "sparse hashing similarity, and RRF."
            ),
            candidate_count=len(unique_candidates),
        )
        fused = fuse_candidates_rrf(
            question,
            lane_results,
            pool_max=host._retrieval_pool_max(),
            rrf_k=host._retrieval_rrf_k(),
        )
        prior_metadata = host.retrieval_metadata_by_key
        merged_metadata: Dict[str, Dict[str, Any]] = {}
        for key, metadata in fused.metadata_by_key.items():
            merged = {**dict(prior_metadata.get(key, {}) or {}), **dict(metadata or {})}
            if "rerank_score" in prior_metadata.get(key, {}):
                merged["rerank_score"] = prior_metadata[key]["rerank_score"]
            merged_metadata[key] = merged
        host.retrieval_metadata_by_key = merged_metadata
        self.refresh_candidate_evidence(fused.documents)
        host._emit_log(
            "Citation-aware local fusion completed: "
            f"candidates={fused.total_candidates}; citation_candidates={len(citation_documents)}; "
            f"fused_candidates={len(fused.documents)}."
        )
        host._emit_ranking_step(
            "citation_refusion",
            "complete",
            "Citation-aware candidate fusion",
            current=len(fused.documents),
            total=max(1, fused.total_candidates),
            detail=(
                f"Re-fused {fused.total_candidates} candidates after citation expansion; "
                f"citation candidates={len(citation_documents)}."
            ),
            candidate_count=len(fused.documents),
            lane_counts=fused.lane_counts,
        )
        return fused.documents

    def refresh_candidate_evidence(self, documents: list) -> None:
        host = self.host
        if host.search_run_state is None:
            return
        queue = host.search_run_state.candidate_queue
        ledger = dict(queue.ledger)
        for document in documents or []:
            key = document_key(document)
            evidence = ledger.get(key)
            metadata = dict(host.retrieval_metadata_by_key.get(key, {}) or {})
            if not key or evidence is None or not metadata:
                continue
            retrieval_lanes = [str(value) for value in metadata.get("retrieval_lanes", []) if value]
            query_views = [
                lane.split(":", 1)[1]
                for lane in retrieval_lanes
                if lane.startswith("query_view:") and ":" in lane
            ]
            source_ranks = {
                str(lane): int(rank)
                for lane, rank in dict(metadata.get("retrieval_source_ranks", {}) or {}).items()
                if rank is not None
            }
            concept_coverage = {
                name: float(metadata.get(field, 0.0) or 0.0)
                for name, field in (
                    ("embedding", "retrieval_embedding_score"),
                    ("bm25", "retrieval_bm25_score"),
                    ("term", "retrieval_term_coverage"),
                    ("rrf", "retrieval_rrf_score"),
                    ("rrf_normalized", "retrieval_rrf_normalized"),
                    ("primary_prior", "retrieval_primary_prior"),
                )
            }
            ledger[key] = evidence.model_copy(
                update={
                    "query_views": host._merge_unique(evidence.query_views, query_views),
                    "retrieval_lanes": retrieval_lanes,
                    "source_ranks": source_ranks,
                    "concept_coverage": {**evidence.concept_coverage, **concept_coverage},
                    "retrieval_score": host._optional_float(metadata.get("retrieval_score")),
                    "rerank_score": (
                        host._optional_float(metadata.get("rerank_score"))
                        if "rerank_score" in metadata
                        else evidence.rerank_score
                    ),
                }
            )
        host.search_run_state = host.search_run_state.with_candidate_queue(
            queue.model_copy(update={"ledger": ledger})
        )
