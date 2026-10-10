"""External candidate scoring and durable selection before LLM ranking."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from time import perf_counter

from paperseek_core.document_identity import document_key
from paperseek_core.decision_selection import decision_signature, select_with_decisions
from paperseek_core.execution import NEVER_CANCELLED, record_checkpoint
from paperseek_core.http_retry import failure_details
from paperseek_core.models import (
    CandidateSelectionResult, CheckpointDraft, CoreProgressEvent, PaperRecord,
    RetrievalEmbeddingState, DecisionBatchCheckpoint,
)
from paperseek_core.ports import CancellationToken, DecisionPort, EmbeddingPort, RerankPort, WorkflowObserver
from paperseek_core.retrieval_fusion import dedupe_documents, document_text, fuse_citation_candidates


def _text_hash(document: PaperRecord) -> str:
    return hashlib.sha256(document_text(document)[:1800].encode("utf-8")).hexdigest()


def embedding_provenance(document: PaperRecord, state: RetrievalEmbeddingState | None) -> dict:
    if state is None or document_key(document) not in state.scores_by_identity:
        return {}
    return {
        "external_embedding_score": state.scores_by_identity[document_key(document)],
        "embedding_model": state.model,
        "embedding_provider": state.provider,
    }


class CandidateSelectionPipeline:
    def __init__(
        self, observer: WorkflowObserver, *, embedding: EmbeddingPort | None = None,
        reranker: RerankPort | None = None, decision: DecisionPort | None = None, cancellation: CancellationToken = NEVER_CANCELLED,
    ) -> None:
        self.observer = observer
        self.embedding = embedding
        self.reranker = reranker
        self.decision = decision
        if decision is not None and (embedding is not None or reranker is not None):
            raise ValueError("Decision selection cannot be combined with embedding or reranking.")
        self.cancellation = cancellation

    async def embed(
        self, question: str, documents: list[PaperRecord], warnings: list[str], *,
        previous: RetrievalEmbeddingState | None = None, stage: str = "retrieval",
    ) -> RetrievalEmbeddingState | None:
        if self.embedding is None or not documents:
            return None
        documents = dedupe_documents(documents)
        hashes = {document_key(doc): _text_hash(doc) for doc in documents}
        reusable = previous is not None and previous.question == question
        scores = {
            key: score for key, score in previous.scores_by_identity.items()
            if key in hashes and previous.text_hashes.get(key) == hashes[key]
        } if reusable else {}
        missing = [doc for doc in documents if document_key(doc) not in scores]
        if not missing:
            return previous
        started = perf_counter()
        try:
            self.cancellation.raise_if_cancelled()
            result = await self.embedding.embedding_scores(
                question, missing, model=previous.model if reusable else None,
            )
            self.cancellation.raise_if_cancelled()
            if len(result.scores) != len(missing) or not all(math.isfinite(s) for s in result.scores):
                raise ValueError("Embedding scores do not match candidate count or contain invalid values.")
            if reusable and (result.model, result.provider) != (previous.model, previous.provider):
                raise ValueError("Incremental embedding scores must use the original model and provider.")
            scores.update({document_key(doc): score for doc, score in zip(missing, result.scores, strict=True)})
            state = RetrievalEmbeddingState(
                question=question, provider=result.provider, model=result.model,
                scores_by_identity=scores, text_hashes=hashes,
            )
        except Exception as exc:
            code = "retrieval_embedding_failed_local_similarity_retained"
            warnings.append(code)
            self._event(f"{stage}.degraded", {
                "code": code, "error_type": type(exc).__name__, "candidate_count": len(missing), **failure_details(exc),
            }, stage)
            return None
        self._event(f"{stage}.embedding_completed", {
            "provider": result.provider, "model": result.model,
            "candidate_count": len(documents), "scored_count": len(missing),
            "reused_count": len(documents) - len(missing),
            "duration_ms": round((perf_counter() - started) * 1000),
        }, stage)
        return state

    async def run(
        self, *, question: str, candidates: list[PaperRecord], provenance: dict,
        embedding_state: RetrievalEmbeddingState | None, pool_max: int,
        ranking_limit: int, rrf_k: int = 60, resume: CandidateSelectionResult | None = None,
        search_plan: str = "", decision_batches: list[DecisionBatchCheckpoint] | None = None,
    ) -> CandidateSelectionResult:
        self.cancellation.raise_if_cancelled()
        documents = dedupe_documents(candidates)
        fingerprint = hashlib.sha256(json.dumps({
            "question": question, "pool_max": pool_max, "ranking_limit": ranking_limit,
            "rrf_k": rrf_k,
            **({"decision": decision_signature(self.decision), "search_plan": search_plan} if self.decision else {}),
            "candidates": [
                (document_key(doc), hashlib.sha256(document_text(doc).encode("utf-8")).hexdigest())
                for doc in documents
            ],
        }, sort_keys=True).encode("utf-8")).hexdigest()
        if resume is not None:
            if resume.input_fingerprint != fingerprint:
                raise ValueError("Candidate selection checkpoint does not match its inputs.")
            return resume
        warnings = []
        requested_mode = "decision" if self.decision else "embedding_rerank" if self.embedding or self.reranker else "local_fusion"
        self._event("selection.started", {"candidate_count": len(documents), "requested_mode": requested_mode}, "selection")
        has_expansion = any(
            "citation_expansion" in detail.get("origins", []) for detail in provenance.values()
        )
        if has_expansion:
            embedding_state = await self.embed(
                question, documents, warnings, previous=embedding_state, stage="selection",
            )
        fused = await asyncio.to_thread(
            fuse_citation_candidates, question, documents, provenance, pool_max=pool_max,
            rrf_k=rrf_k,
            embedding_scores_by_key=embedding_state.scores_by_identity if embedding_state else None,
        )
        provenance = fused.metadata_by_key
        for document in fused.documents:
            provenance[document_key(document)].update(embedding_provenance(document, embedding_state))
        documents, rerank_status = await self._rerank(question, fused.documents, provenance, ranking_limit, warnings)
        embedding_status = "disabled"
        if self.embedding:
            embedding_status = "failed" if documents else "skipped"
        if embedding_state and embedding_state.scores_by_identity:
            embedding_status = "succeeded"
        statuses = {
            "embedding": embedding_status,
            "reranker": rerank_status,
            "decision": "disabled",
        }
        if embedding_status == "succeeded" and rerank_status == "succeeded":
            actual_mode = "embedding_rerank"
        elif embedding_status == "succeeded":
            actual_mode = "embedding"
        elif rerank_status == "succeeded":
            actual_mode = "rerank"
        else:
            actual_mode = "local_fusion"
        if self.decision:
            selected = documents[:min(pool_max, 2 * ranking_limit)]
            ordered, succeeded = await select_with_decisions(
                self.decision, self.observer, self.cancellation,
                question=question, search_plan=search_plan, documents=selected,
                provenance=provenance, warnings=warnings, rrf_k=rrf_k, resume=decision_batches or [],
            )
            statuses["decision"] = "skipped" if not selected else "succeeded" if succeeded else "failed"
            actual_mode = "decision" if selected and succeeded else "local_fusion"
            documents = [*ordered, *documents[len(selected):]][:pool_max]
            provenance = {document_key(doc): provenance[document_key(doc)] for doc in documents}
        result = CandidateSelectionResult(
            requested_mode=requested_mode, actual_mode=actual_mode, component_statuses=statuses,
            documents=documents, provenance_by_identity=provenance,
            selected_count=min(ranking_limit, len(documents)),
            input_fingerprint=fingerprint, warnings=warnings,
        )
        self.cancellation.raise_if_cancelled()
        if self.observer.on_checkpoint is not None:
            await record_checkpoint(self.observer, CheckpointDraft(
                step_key="select_candidates", idempotency_key=f"selection:{fingerprint}",
                state={**result.model_dump(mode="json"), "resume_from_stage": "rank"},
                workflow_version="m2.selection.v1",
            ))
        self._event("selection.completed", {
            "candidate_count": len(documents), "llm_gate_candidate_count": result.selected_count,
            "warning_count": len(warnings), "requested_mode": requested_mode, "actual_mode": actual_mode,
            "component_statuses": statuses,
        }, "selection")
        return result

    async def _rerank(self, question, documents, provenance, ranking_limit, warnings):
        if self.reranker is None or not documents:
            return documents, "disabled" if self.reranker is None else "skipped"
        selected = documents[:2 * ranking_limit]
        started = perf_counter()
        try:
            self.cancellation.raise_if_cancelled()
            result = await self.reranker.rerank(question, selected)
            self.cancellation.raise_if_cancelled()
            scores = {document_key(item.document): float(item.score) for item in result.items}
            if (
                len(result.items) != len(selected)
                or set(scores) != {document_key(doc) for doc in selected}
                or not all(math.isfinite(score) for score in scores.values())
            ):
                raise ValueError("Reranker must score every selected candidate exactly once.")
            ordered = sorted(selected, key=lambda doc: scores[document_key(doc)], reverse=True)
        except Exception as exc:
            code = "retrieval_rerank_failed_rrf_order_retained"
            warnings.append(code)
            self._event("selection.degraded", {
                "code": code, "candidate_count": len(selected), "error_type": type(exc).__name__, **failure_details(exc),
            }, "selection")
            return documents, "failed"
        for index, doc in enumerate(ordered, 1):
            provenance[document_key(doc)].update({
                "rerank_score": scores[document_key(doc)], "rerank_rank": index,
                "rerank_model": result.model, "rerank_provider": result.provider,
            })
        self._event("selection.rerank_completed", {
            "provider": result.provider, "model": result.model,
            "candidate_count": len(selected), "scored_count": len(result.items),
            "duration_ms": round((perf_counter() - started) * 1000),
        }, "selection")
        return [*ordered, *documents[len(selected):]], "succeeded"

    def _event(self, event_type: str, payload: dict, stage: str) -> None:
        self.cancellation.raise_if_cancelled()
        self.observer.on_event(CoreProgressEvent(event_type=event_type, stage=stage, payload=payload))
