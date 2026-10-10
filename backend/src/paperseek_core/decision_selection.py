"""Bounded decision batches, durable recovery, and rank fusion for preliminary selection."""
from __future__ import annotations

import asyncio
import hashlib
import json
from time import perf_counter

from paperseek_core.decision_prompt import PROMPT_VERSION, decision_question, decision_state
from paperseek_core.document_identity import document_key
from paperseek_core.execution import record_checkpoint
from paperseek_core.http_retry import failure_details
from paperseek_core.models import CheckpointDraft, CoreProgressEvent, DecisionBatchCheckpoint, PaperRecord
from paperseek_core.ports import CancellationToken, DecisionPort, WorkflowObserver

BATCH_SIZE = 8
CONCURRENCY = 2
FUSION_VERSION = "decision2-base1-rrf.v1"


def decision_signature(adapter: DecisionPort) -> dict:
    return {"provider": adapter.provider, "model": adapter.model, "base_url": adapter.base_url,
            "prompt_version": PROMPT_VERSION, "fusion_version": FUSION_VERSION,
            "batch_size": BATCH_SIZE, "candidate_policy": "local_top_2k.v1"}


async def select_with_decisions(
    adapter: DecisionPort, observer: WorkflowObserver, cancellation: CancellationToken, *,
    question: str, search_plan: str, documents: list[PaperRecord], provenance: dict,
    warnings: list[str], rrf_k: int, resume: list[DecisionBatchCheckpoint],
) -> tuple[list[PaperRecord], bool]:
    if not documents:
        return documents, True
    keys = [document_key(doc) for doc in documents]
    questions = {key: decision_question(doc) for key, doc in zip(keys, documents, strict=True)}
    state = decision_state(question, search_plan)
    fingerprint = hashlib.sha256(json.dumps(
        {"route": decision_signature(adapter), "state": state, "questions": questions},
        sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()
    batches = [keys[i:i + BATCH_SIZE] for i in range(0, len(keys), BATCH_SIZE)]
    saved = {row.batch_id: row for row in resume}
    if any(row.input_fingerprint != fingerprint for row in resume):
        raise ValueError("Decision checkpoints do not match their inputs or model route.")
    if any(batch_id not in {str(i) for i in range(len(batches))} for batch_id in saved):
        raise ValueError("Decision checkpoint contains an unknown batch.")
    results = {}
    for batch_id, row in saved.items():
        if set(row.result.scores) != set(batches[int(batch_id)]):
            raise ValueError("Decision checkpoint candidates do not match their batch.")
        results[batch_id] = row.result
    started = perf_counter()
    reused = sum(len(result.scores) for result in results.values())
    semaphore = asyncio.Semaphore(CONCURRENCY)
    failures: list[dict] = []

    def event(kind: str, **payload) -> None:
        cancellation.raise_if_cancelled()
        observer.on_event(CoreProgressEvent(event_type=f"selection.decision_{kind}", stage="selection", payload={
            "provider": adapter.provider, "model": adapter.model, "candidate_count": len(documents),
            "scored_count": sum(len(result.scores) for result in results.values()),
            "reused_count": reused, **payload,
        }))

    async def process(index: int, batch: list[str]) -> None:
        batch_id = str(index)
        if batch_id in results:
            return
        async with semaphore:
            # Stop submitting after an outage. Completed batches remain reusable on recovery.
            if failures:
                return
            cancellation.raise_if_cancelled()
            try:
                result = await adapter.score(state, {key: questions[key] for key in batch})
                if set(result.scores) != set(batch):
                    raise ValueError("Decision scores do not match the requested batch.")
            except Exception as exc:
                failures.append({"error_type": type(exc).__name__, "batch_id": batch_id, **failure_details(exc)})
                return
            cancellation.raise_if_cancelled()
            if observer.on_checkpoint is not None:
                checkpoint = DecisionBatchCheckpoint(input_fingerprint=fingerprint, batch_id=batch_id, result=result)
                # Storage failures must propagate, rather than masquerade as a model fallback.
                await record_checkpoint(observer, CheckpointDraft(
                    step_key="selection.decision", idempotency_key=f"decision:{fingerprint}:{batch_id}",
                    workflow_version="decision.v1", state=checkpoint.model_dump(mode="json"),
                ))
            results[batch_id] = result
            event("progress")

    event("started")
    async with asyncio.TaskGroup() as group:
        for index, batch in enumerate(batches):
            group.create_task(process(index, batch))
    cancellation.raise_if_cancelled()
    if failures:
        code = "retrieval_decision_failed_local_order_retained"
        warnings.append(code)
        event("degraded", code=code, **failures[0], actual_mode="local_fusion")
        return documents, False
    models = {result.model for result in results.values()}
    if len(models) != 1:
        warnings.append("retrieval_decision_model_changed_local_order_retained")
        event("degraded", code=warnings[-1], actual_mode="local_fusion")
        return documents, False
    ordered = _fuse_decision_ranks(documents, provenance, results, adapter.provider, rrf_k)
    event("completed", resolved_model=next(iter(models)), actual_mode="decision",
          input_tokens=sum(result.input_tokens for result in results.values()),
          output_tokens=sum(result.output_tokens for result in results.values()),
          duration_ms=round((perf_counter() - started) * 1000))
    return ordered, True


def _fuse_decision_ranks(documents, provenance, results, provider, rrf_k):
    keys = [document_key(doc) for doc in documents]
    model = next(iter(results.values())).model
    scores = {key: score for result in results.values() for key, score in result.scores.items()}
    model_order = sorted(keys, key=lambda key: scores[key].score, reverse=True)
    ranks = {}
    start = 0
    while start < len(model_order):
        end = start + 1
        while end < len(model_order) and scores[model_order[end]].score == scores[model_order[start]].score:
            end += 1
        # Midranks avoid promoting every member of a large tied/uncertain group.
        for key in model_order[start:end]:
            ranks[key] = (start + 1 + end) / 2
        start = end
    fused = {}
    for index, key in enumerate(keys, 1):
        fused[key] = 1 / (rrf_k + index) + 2 / (rrf_k + ranks[key])
        provenance[key].update({"decision_score": scores[key].score, "decision_confidence": scores[key].confidence,
                                "decision_rank": ranks[key], "decision_model": model,
                                "decision_provider": provider, "selection_rrf_score": fused[key]})
    ordered = sorted(documents, key=lambda doc: fused[document_key(doc)], reverse=True)
    return ordered
