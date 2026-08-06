"""Candidate queue and evidence-ledger ownership."""

from __future__ import annotations

from typing import Any, Dict, Optional

from paperseek_core.harness import (
    CandidateCitationPath,
    CandidateEvidence,
    CandidateLifecycleEvent,
    SearchRunState,
)
from paperseek_core.retrieval import document_key


_SERIALIZED_LEDGER_LIMIT = 512


def _citation_count(document) -> int:
    return sum(int(getattr(item, "count", 0) or 0) for item in getattr(document, "citations", []) or [])


class CandidateLedger:
    def __init__(self, host) -> None:
        self._host = host

    def payload(self) -> dict:
        host = self._host
        if host.search_run_state is None:
            return {}

        payload = host.search_run_state.model_dump()
        queue_payload = payload.get("candidate_queue") or {}
        ledger = host.search_run_state.candidate_queue.ledger
        ranking_gate_counts: Dict[str, int] = {}
        lifecycle_candidate_counts: Dict[str, int] = {}
        citation_candidate_count = 0
        ranked_ledger_keys = []

        for insertion_order, (key, evidence) in enumerate(ledger.items()):
            gate_label = str(evidence.ranking_gate_label or "unseen")
            ranking_gate_counts[gate_label] = ranking_gate_counts.get(gate_label, 0) + 1
            actions = {str(event.action or "") for event in evidence.lifecycle if event.action}
            for action in actions:
                lifecycle_candidate_counts[action] = lifecycle_candidate_counts.get(action, 0) + 1
            if evidence.citation_paths:
                citation_candidate_count += 1

            priority = 4
            if "final_output" in actions:
                priority = 0
            elif "llm_scored" in actions:
                priority = 1
            elif "selected_for_llm" in actions:
                priority = 2
            elif evidence.citation_paths:
                priority = 3
            ranked_ledger_keys.append((priority, insertion_order, key))

        retained_keys = {
            key
            for _, _, key in sorted(ranked_ledger_keys)[:_SERIALIZED_LEDGER_LIMIT]
        }
        serialized_ledger = {
            key: value
            for key, value in dict(queue_payload.get("ledger") or {}).items()
            if key in retained_keys
        }
        queue_payload["ledger"] = serialized_ledger
        queue_payload["ledger_summary"] = {
            "total_candidates": len(ledger),
            "serialized_candidates": len(serialized_ledger),
            "omitted_candidates": max(0, len(ledger) - len(serialized_ledger)),
            "ranking_gate_counts": ranking_gate_counts,
            "lifecycle_candidate_counts": lifecycle_candidate_counts,
            "citation_candidate_count": citation_candidate_count,
        }
        payload["candidate_queue"] = queue_payload
        return payload

    def enqueue(
        self,
        documents: list,
        origin: str,
        evidence_by_key: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> list:
        host = self._host
        docs = list(documents or [])
        keys = [document_key(document) for document in docs]
        if host.search_run_state is None:
            host.search_run_state = SearchRunState(question="", source=host.data_source, current_query="")
        before = set(host.search_run_state.candidate_queue.keys)
        host.search_run_state, _ = host.search_loop.update_candidate_queue(
            host.search_run_state,
            candidate_keys=keys,
            origin=origin,
        )
        queue = host.search_run_state.candidate_queue
        records = list(queue.records)
        ledger = dict(queue.ledger)
        recorded_keys = {str(record.get("key") or "") for record in records}
        for document, key in zip(docs, keys):
            if not key:
                continue
            identifiers = getattr(document, "identifiers", None)
            if key not in recorded_keys:
                records.append(
                    {
                        "key": key,
                        "id": key,
                        "title": str(getattr(document, "title", "") or ""),
                        "doi": str(getattr(identifiers, "doi", "") or ""),
                        "arxiv": str(getattr(identifiers, "arxiv", "") or ""),
                        "pmid": str(getattr(identifiers, "pmid", "") or ""),
                    }
                )
                recorded_keys.add(key)

            metadata = dict(host.retrieval_metadata_by_key.get(key, {}) or {})
            extra = dict((evidence_by_key or {}).get(key, {}) or {})
            existing = ledger.get(key)
            source = getattr(document, "source", None)
            provider = str(getattr(document, "provider", "") or host.data_source or "")
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
            event = CandidateLifecycleEvent(
                stage=origin,
                action="duplicate" if key in before else "added",
                origin=origin,
                detail=str(extra.get("detail") or ""),
            )
            citation_paths = [
                item if isinstance(item, CandidateCitationPath) else CandidateCitationPath.model_validate(item)
                for item in (extra.get("citation_paths") or [])
            ]
            if existing is None:
                evidence = CandidateEvidence(
                    candidate_id=key,
                    title=str(getattr(document, "title", "") or ""),
                    doi=str(getattr(identifiers, "doi", "") or ""),
                    arxiv=str(getattr(identifiers, "arxiv", "") or ""),
                    pmid=str(getattr(identifiers, "pmid", "") or ""),
                    openalex=str(getattr(identifiers, "openalex", "") or ""),
                    semanticscholar=str(getattr(identifiers, "semanticscholar", "") or ""),
                    year=getattr(source, "publish_year", None) if source else None,
                    citations=_citation_count(document),
                    sources=[provider] if provider else [],
                    origins=[origin] if origin else [],
                    query_views=query_views,
                    retrieval_lanes=retrieval_lanes,
                    source_ranks=source_ranks,
                    citation_paths=citation_paths,
                    concept_coverage={
                        name: float(metadata.get(field, 0.0) or 0.0)
                        for name, field in (
                            ("embedding", "retrieval_embedding_score"),
                            ("bm25", "retrieval_bm25_score"),
                            ("term", "retrieval_term_coverage"),
                            ("rrf", "retrieval_rrf_score"),
                            ("rrf_normalized", "retrieval_rrf_normalized"),
                            ("primary_prior", "retrieval_primary_prior"),
                        )
                    },
                    retrieval_score=self._optional_float(metadata.get("retrieval_score")),
                    rerank_score=self._optional_float(metadata.get("rerank_score")),
                    lifecycle=[event],
                )
            else:
                evidence = existing.model_copy(
                    update={
                        "sources": self._merge_unique(existing.sources, [provider]),
                        "origins": self._merge_unique(existing.origins, [origin]),
                        "query_views": self._merge_unique(existing.query_views, query_views),
                        "retrieval_lanes": self._merge_unique(existing.retrieval_lanes, retrieval_lanes),
                        "source_ranks": {**existing.source_ranks, **source_ranks},
                        "citation_paths": self._merge_citation_paths(existing.citation_paths, citation_paths),
                        "concept_coverage": {
                            **existing.concept_coverage,
                            **{
                                name: float(metadata.get(field, 0.0) or 0.0)
                                for name, field in (
                                    ("embedding", "retrieval_embedding_score"),
                                    ("bm25", "retrieval_bm25_score"),
                                    ("term", "retrieval_term_coverage"),
                                    ("rrf", "retrieval_rrf_score"),
                                    ("rrf_normalized", "retrieval_rrf_normalized"),
                                    ("primary_prior", "retrieval_primary_prior"),
                                )
                                if field in metadata
                            },
                        },
                        "retrieval_score": self._optional_float(metadata.get("retrieval_score"))
                        if "retrieval_score" in metadata
                        else existing.retrieval_score,
                        "rerank_score": self._optional_float(metadata.get("rerank_score"))
                        if "rerank_score" in metadata
                        else existing.rerank_score,
                        "lifecycle": [*existing.lifecycle, event],
                    }
                )
            ledger[key] = evidence

        if len(records) != len(queue.records) or ledger != queue.ledger:
            host.search_run_state = host.search_run_state.with_candidate_queue(
                queue.model_copy(update={"records": records, "ledger": ledger})
            )
        added = []
        added_keys = set()
        for document, key in zip(docs, keys):
            if not key or key in before or key in added_keys:
                continue
            added_keys.add(key)
            added.append(document)
        return added

    @staticmethod
    def _merge_unique(existing: list, incoming: list) -> list:
        output = list(existing or [])
        seen = {str(value) for value in output}
        for value in incoming or []:
            text = str(value or "").strip()
            if text and text not in seen:
                output.append(text)
                seen.add(text)
        return output

    @staticmethod
    def _merge_citation_paths(existing: list, incoming: list) -> list:
        output = list(existing or [])
        seen = {
            (item.seed_id, item.parent_id, item.direction, item.depth)
            for item in output
        }
        for item in incoming or []:
            key = (item.seed_id, item.parent_id, item.direction, item.depth)
            if key not in seen:
                output.append(item)
                seen.add(key)
        return output

    @staticmethod
    def _optional_float(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def record_gate(self, all_candidates: list, selected_candidates: list, limit: int) -> None:
        host = self._host
        if host.search_run_state is None:
            return
        selected_keys = {
            document_key(document)
            for document in selected_candidates or []
            if document_key(document)
        }
        queue = host.search_run_state.candidate_queue
        ledger = dict(queue.ledger)
        for document in all_candidates or []:
            key = document_key(document)
            evidence = ledger.get(key)
            if not key or evidence is None:
                continue
            selected = key in selected_keys
            action = "selected_for_llm" if selected else "truncated_before_llm"
            reason = "within_ranking_candidate_limit" if selected else "ranking_candidate_limit"
            reason_codes = [reason]
            origin = "local_fused_rank"
            ledger[key] = evidence.model_copy(
                update={
                    "ranking_gate_label": "selected" if selected else "truncated",
                    "ranking_gate_reason_codes": self._merge_unique(evidence.ranking_gate_reason_codes, reason_codes),
                    "lifecycle": [
                        *evidence.lifecycle,
                        CandidateLifecycleEvent(
                            stage="ranking_gate",
                            action=action,
                            origin=origin,
                            detail=f"ranking_candidate_limit={limit}",
                        ),
                    ],
                }
            )
        host.search_run_state = host.search_run_state.with_candidate_queue(
            queue.model_copy(update={"ledger": ledger})
        )

    def record_scores(self, ranked: list, action: str) -> None:
        host = self._host
        if host.search_run_state is None:
            return
        queue = host.search_run_state.candidate_queue
        ledger = dict(queue.ledger)
        for entry in ranked or []:
            document = (entry or {}).get("document") if isinstance(entry, dict) else None
            key = document_key(document) if document is not None else ""
            evidence = ledger.get(key)
            if not key or evidence is None:
                continue
            ledger[key] = evidence.model_copy(
                update={
                    "llm_score": self._optional_float((entry or {}).get("score")),
                    "lifecycle": [
                        *evidence.lifecycle,
                        CandidateLifecycleEvent(stage="ranking", action=action, origin="llm_ranking"),
                    ],
                }
            )
        host.search_run_state = host.search_run_state.with_candidate_queue(
            queue.model_copy(update={"ledger": ledger})
        )

    def record_final(self, ranked: list) -> None:
        host = self._host
        if host.search_run_state is None:
            return
        queue = host.search_run_state.candidate_queue
        ledger = dict(queue.ledger)
        for entry in ranked or []:
            document = (entry or {}).get("document") if isinstance(entry, dict) else None
            key = document_key(document) if document is not None else ""
            evidence = ledger.get(key)
            if not key or evidence is None:
                continue
            ledger[key] = evidence.model_copy(
                update={
                    "lifecycle": [
                        *evidence.lifecycle,
                        CandidateLifecycleEvent(stage="results", action="final_output", origin="ranked_output"),
                    ]
                }
            )
        host.search_run_state = host.search_run_state.with_candidate_queue(
            queue.model_copy(update={"ledger": ledger})
        )
