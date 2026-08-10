"""Deterministic LLM ranking, recovery, and checkpoint semantics."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable

from paperseek_core.execution import NEVER_CANCELLED
from paperseek_core.models import (
    CheckpointDraft,
    CoreProgressEvent,
    PaperRecord,
    RankedPaper,
    RankingRequest,
    RankingResult,
    RankingScore,
)
from paperseek_core.ports import CancellationToken, LLMPort, WorkflowObserver
from paperseek_core.prompts import SYSTEM_RANKING_REASONS, SYSTEM_RESULT_RANKING


class EmptyRankingBatchError(RuntimeError):
    """Raised when an LLM ranking batch returns no usable scores."""


def _normalize_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().casefold())


def _normalize_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def document_key(document: PaperRecord) -> str:
    identifiers = document.identifiers
    for name in ("doi", "openalex", "arxiv", "semanticscholar", "pmid"):
        normalized = _normalize_key(getattr(identifiers, name, "") if identifiers else "")
        if normalized:
            return f"{name}:{normalized}"
    uid = _normalize_key(document.uid)
    if uid:
        return f"uid:{uid}"
    title = _normalize_title(document.title)
    return f"title:{title}" if title else ""


def document_identity(document: PaperRecord) -> str:
    return str(document.uid or document_key(document) or "").strip()


def describe_document(document: PaperRecord, index: int, *, abstract_limit: int = 1200) -> str:
    parts = [f"{index}. UID: {document.uid or document_key(document)}"]
    if document.provider:
        parts.append(f"   Provider: {document.provider}")
    if document.title:
        parts.append(f"   Title: {document.title}")
    if document.types:
        parts.append(f"   Document types: {'; '.join(document.types[:5])}")
    if document.source:
        source_parts = []
        if document.source.source_title:
            source_parts.append(document.source.source_title)
        if document.source.publish_year:
            source_parts.append(str(document.source.publish_year))
        if document.source.volume:
            source_parts.append(f"V{document.source.volume}")
        if document.source.issue:
            source_parts.append(f"I{document.source.issue}")
        if source_parts:
            parts.append(f"   Source: {', '.join(source_parts)}")
    if document.names and document.names.authors:
        authors = [
            author.display_name or author.wos_standard or ""
            for author in document.names.authors[:5]
        ]
        parts.append(f"   Authors: {', '.join(author for author in authors if author)}")
    if document.keywords and document.keywords.author_keywords:
        parts.append(f"   Keywords: {'; '.join(document.keywords.author_keywords[:8])}")
    if document.abstract:
        parts.append(f"   Abstract: {document.abstract[:max(200, int(abstract_limit or 1200))]}")
    return "\n".join(parts)


@dataclass(frozen=True)
class RankingBatchScheduler:
    batch_size_value: Any = 256
    concurrency_value: Any = 16

    def batch_size(self, total_documents: int) -> int:
        try:
            configured = max(1, int(self.batch_size_value or 256))
        except (TypeError, ValueError):
            configured = 256
        return min(configured, max(1, int(total_documents or 0)))

    def concurrency(self) -> int:
        try:
            return min(32, max(4, int(self.concurrency_value or 16)))
        except (TypeError, ValueError):
            return 16

    def concurrency_schedule(self) -> list[int]:
        configured = self.concurrency()
        schedule = [tier for tier in (32, 16, 8, 4) if tier <= configured]
        if configured not in schedule:
            schedule.insert(0, configured)
        if 4 not in schedule:
            schedule.append(4)
        return schedule

    @staticmethod
    def batch_id(
        step_id: str,
        documents: list[PaperRecord],
        identity: Callable[[PaperRecord], str] = document_identity,
    ) -> str:
        candidate_ids = [str(document.uid or identity(document)) for document in documents]
        digest = hashlib.sha256("\0".join(candidate_ids).encode("utf-8")).hexdigest()[:20]
        return f"{step_id}:{digest}"


@dataclass(frozen=True)
class RankingOutputCodec:
    identity: Callable[[PaperRecord], str] = document_identity

    @staticmethod
    def json_object(raw: str) -> dict:
        text = str(raw or "").strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return {}
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                return {}

    def parse_scores(self, raw: str, documents: list[PaperRecord]) -> list[dict[str, Any]]:
        pairs = self.json_object(raw).get("scores")
        if not isinstance(pairs, list):
            return []
        output = []
        seen = set()
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                index = int(pair[0])
                score = float(pair[1])
            except (TypeError, ValueError):
                continue
            if index < 1 or index > len(documents) or index in seen or not math.isfinite(score):
                continue
            seen.add(index)
            output.append({
                "uid": self.identity(documents[index - 1]),
                "score": score,
                "reasoning": "",
            })
        return output

    @staticmethod
    def parse_reasons(raw: str, identities: list[str]) -> dict[str, str]:
        pairs = RankingOutputCodec.json_object(raw).get("reasons")
        if not isinstance(pairs, list):
            return {}
        output = {}
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                index = int(pair[0])
            except (TypeError, ValueError):
                continue
            reason = re.sub(r"\s+", " ", str(pair[1] or "")).strip()
            if 1 <= index <= len(identities) and reason:
                output[identities[index - 1]] = reason
        return output

    def match_scores(
        self,
        documents: list[PaperRecord],
        scores: Any,
    ) -> tuple[list[dict[str, Any]], list[PaperRecord]]:
        identities = [self.identity(document) for document in documents]
        exact = {identity.casefold(): index for index, identity in enumerate(identities) if identity}
        matched_indexes = set()
        matched_scores = []
        for entry in self.validated_scores(scores):
            uid = str(entry.get("uid") or "").strip()
            if not uid:
                continue
            index = exact.get(uid.casefold())
            if index is None:
                candidates = [
                    candidate_index
                    for candidate_index, identity in enumerate(identities)
                    if identity
                    and (uid.casefold() in identity.casefold() or identity.casefold() in uid.casefold())
                ]
                if len(candidates) == 1:
                    index = candidates[0]
            if index is None or index in matched_indexes:
                continue
            normalized = dict(entry)
            normalized["uid"] = identities[index]
            matched_scores.append(normalized)
            matched_indexes.add(index)
        missing = [
            document
            for index, document in enumerate(documents)
            if index not in matched_indexes
        ]
        return matched_scores, missing

    @staticmethod
    def validated_scores(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        output = []
        for item in value:
            try:
                output.append(RankingScore.model_validate(item).model_dump())
            except (TypeError, ValueError):
                continue
        return output


class RankingScorer:
    def __init__(self, llm: LLMPort):
        self.llm = llm
        self.codec = RankingOutputCodec()
        self.missing_reason_count = 0

    async def score_batch(
        self,
        question: str,
        documents: list[PaperRecord],
        plan_context: str,
    ) -> list[dict[str, Any]]:
        try:
            scores = await self.request_compact_scores(question, documents, plan_context)
        except Exception as exc:
            if not self.should_retry_in_chunks(exc):
                raise
            scores = await self.request_scores_in_chunks(question, documents, plan_context)
        matched, missing = self.codec.match_scores(documents, scores)
        if missing:
            scores = await self.request_scores_in_chunks(question, documents, plan_context)
            matched, missing = self.codec.match_scores(documents, scores)
            if missing:
                raise EmptyRankingBatchError(
                    f"Chunked score-only ranking omitted {len(missing)}/{len(documents)} candidate(s)."
                )
        return matched

    async def attach_reasons(
        self,
        question: str,
        documents: list[PaperRecord],
        scores: list[dict[str, Any]],
        plan_context: str,
    ) -> list[dict[str, Any]]:
        reason_documents = self.reason_documents(documents, scores)
        reason_by_uid: dict[str, str] = {}
        self.missing_reason_count = 0
        for start in range(0, len(reason_documents), 64):
            batch = reason_documents[start:start + 64]
            try:
                reason_by_uid.update(
                    await self.request_reasons(question, batch, scores, plan_context)
                )
            except Exception:
                pass
        self.missing_reason_count = sum(
            document_identity(document) not in reason_by_uid
            for document in reason_documents
        )
        for entry in scores:
            entry["reasoning"] = reason_by_uid.get(str(entry.get("uid") or ""), "")
        return scores

    @staticmethod
    def should_retry_in_chunks(exc: Exception) -> bool:
        text = str(exc or "").casefold()
        if "429" in text or "rate_limit" in text or "too many requests" in text:
            return False
        return any(
            marker in text
            for marker in (
                "context length",
                "context_length",
                "maximum context",
                "max token",
                "too many tokens",
                "truncat",
                "json",
                "message content",
                "did not contain",
                "empty response",
                "timed out",
                "timeout",
                "http 500",
                "http 502",
                "http 503",
                "http 504",
                "api error (500)",
                "api error (502)",
                "api error (503)",
                "api error (504)",
                "upstream transport failure",
                "upstream proxy failed",
                "proxy_error",
                "network error",
                "connection reset",
            )
        )

    async def request_compact_scores(
        self,
        question: str,
        documents: list[PaperRecord],
        plan_context: str,
    ) -> list[dict[str, Any]]:
        descriptions = []
        for index, document in enumerate(documents, 1):
            description = describe_document(document, index, abstract_limit=500)
            descriptions.append(
                re.sub(rf"^{index}\. UID:.*$", f"{index}.", description, count=1, flags=re.MULTILINE)
            )
        papers_text = "\n\n".join(descriptions)
        messages = [
            {"role": "system", "content": SYSTEM_RESULT_RANKING},
            {
                "role": "user",
                "content": (
                    f"Research question: {question}\n\n"
                    f"Stable SearchPlan:\n{plan_context}\n\n"
                    f"Papers:\n\n{papers_text}\n\n"
                    'Return only {"scores":[[index,score],...]} with one pair for every index.'
                ),
            },
        ]
        raw = await self.llm.chat_json(messages, temperature=0.0, max_tokens=4096)
        return self.codec.parse_scores(raw, documents)

    async def request_scores_in_chunks(
        self,
        question: str,
        documents: list[PaperRecord],
        plan_context: str,
        chunk_size: int = 64,
    ) -> list[dict[str, Any]]:
        scores = []
        for start in range(0, len(documents), chunk_size):
            batch = documents[start:start + chunk_size]
            batch_scores = await self.request_compact_scores(question, batch, plan_context)
            matched, missing = self.codec.match_scores(batch, batch_scores)
            if missing:
                raise EmptyRankingBatchError(
                    f"Score-only chunk {start // chunk_size + 1} omitted {len(missing)}/{len(batch)} candidate(s)."
                )
            scores.extend(matched)
        return scores

    def reason_documents(
        self,
        documents: list[PaperRecord],
        scores: list[dict[str, Any]],
    ) -> list[PaperRecord]:
        score_by_uid = {
            str(entry.get("uid") or ""): float(entry.get("score") or 0)
            for entry in scores
        }
        ordered = sorted(
            documents,
            key=lambda document: score_by_uid.get(document_identity(document), 0),
            reverse=True,
        )
        if len(ordered) < 50:
            return ordered
        high_scores = [
            document
            for document in ordered
            if score_by_uid.get(document_identity(document), 0) >= 5
        ]
        return high_scores if len(high_scores) > 50 else ordered[:50]

    async def request_reasons(
        self,
        question: str,
        documents: list[PaperRecord],
        scores: list[dict[str, Any]],
        plan_context: str,
    ) -> dict[str, str]:
        score_by_uid = {
            str(entry.get("uid") or ""): entry.get("score", 0)
            for entry in scores
        }
        descriptions = []
        identities = []
        for index, document in enumerate(documents, 1):
            identity = document_identity(document)
            identities.append(identity)
            description = describe_document(document, index, abstract_limit=700)
            descriptions.append(
                re.sub(
                    rf"^{index}\. UID:.*$",
                    f"{index}. Score: {score_by_uid.get(identity, 0)}",
                    description,
                    count=1,
                    flags=re.MULTILINE,
                )
            )
        retained_text = "\n\n".join(descriptions)
        messages = [
            {"role": "system", "content": SYSTEM_RANKING_REASONS},
            {
                "role": "user",
                "content": (
                    f"Research question: {question}\n\n"
                    f"Stable SearchPlan:\n{plan_context}\n\n"
                    f"Retained papers:\n\n{retained_text}\n\n"
                    'Return only {"reasons":[[index,"reason"],...]}.'
                ),
            },
        ]
        max_tokens = min(8192, max(2048, len(documents) * 96))
        raw = await self.llm.chat_json(messages, temperature=0.0, max_tokens=max_tokens)
        return self.codec.parse_reasons(raw, identities)


class RankingPipeline:
    def __init__(
        self,
        llm: LLMPort,
        observer: WorkflowObserver,
        *,
        cancellation: CancellationToken = NEVER_CANCELLED,
    ):
        self.llm = llm
        self.observer = observer
        self.cancellation = cancellation
        self.codec = RankingOutputCodec()
        self.scorer = RankingScorer(llm)

    async def run(self, request: RankingRequest) -> RankingResult:
        self.cancellation.raise_if_cancelled()
        documents = list(request.documents)
        if not documents:
            return RankingResult()

        scheduler = RankingBatchScheduler(request.batch_size, request.concurrency)
        batch_size = scheduler.batch_size(len(documents))
        batches = [documents[index:index + batch_size] for index in range(0, len(documents), batch_size)]
        batch_ids = {
            index: scheduler.batch_id(request.step_id, batch)
            for index, batch in enumerate(batches, 1)
        }
        completed_ids = set(request.completed_batch_ids)
        scores = self.codec.validated_scores(request.resume_scores)
        self._event(
            "ranking.started",
            {
                "candidate_count": len(documents),
                "batch_count": len(batches),
                "batch_size": batch_size,
                "concurrency": scheduler.concurrency(),
            },
        )

        if len(batches) == 1:
            warnings = await self._run_single_batch(
                request,
                batches[0],
                batch_ids[1],
                completed_ids,
                scores,
            )
        else:
            scores, warnings = await self._run_multiple_batches(
                request,
                batches,
                batch_ids,
                completed_ids,
                scores,
                scheduler,
            )

        items = self._rank_from_scores(documents, scores, request.provenance_by_identity)
        self._event(
            "ranking.completed",
            {
                "candidate_count": len(documents),
                "scored_count": len(scores),
                "warning_count": len(warnings),
            },
        )
        return RankingResult(
            items=items,
            scores=[RankingScore.model_validate(score) for score in scores],
            completed_batch_ids=sorted(completed_ids),
            warnings=warnings,
        )

    async def _run_single_batch(
        self,
        request: RankingRequest,
        documents: list[PaperRecord],
        batch_id: str,
        completed_ids: set[str],
        scores: list[dict[str, Any]],
    ) -> list[str]:
        if batch_id in completed_ids:
            return []
        try:
            self.cancellation.raise_if_cancelled()
            batch_scores = await self.scorer.score_batch(
                request.question,
                documents,
                request.plan_context,
            )
            self.cancellation.raise_if_cancelled()
            if documents and not batch_scores:
                raise EmptyRankingBatchError("LLM ranking batch returned no valid score entries.")
            batch_scores, warnings = await self._attach_reasons(
                request.question,
                documents,
                batch_scores,
                request.plan_context,
            )
        except Exception as exc:
            self._degraded(exc, failed_batches=1, failed_candidates=len(documents))
            return ["ranking_failed_local_order_retained"]

        scores.extend(batch_scores)
        completed_ids.add(batch_id)
        self._checkpoint(request, batch_id, scores, completed_ids)
        self._event(
            "ranking.batch_completed",
            {"batch_index": 1, "batch_count": 1, "candidate_count": len(documents)},
        )
        return warnings

    async def _run_multiple_batches(
        self,
        request: RankingRequest,
        batches: list[list[PaperRecord]],
        batch_ids: dict[int, str],
        completed_ids: set[str],
        scores: list[dict[str, Any]],
        scheduler: RankingBatchScheduler,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        remaining = [
            (index, batch)
            for index, batch in enumerate(batches, 1)
            if batch_ids[index] not in completed_ids
        ]
        schedule = scheduler.concurrency_schedule()
        for tier_index, workers in enumerate(schedule):
            self.cancellation.raise_if_cancelled()
            if not remaining:
                break
            lower_tier_available = tier_index < len(schedule) - 1
            same_tier_retry_used = False
            while True:
                failed: list[tuple[int, list[PaperRecord]]] = []
                empty_failures = 0
                rate_limited = False
                worklist = list(remaining)
                for start in range(0, len(worklist), workers):
                    self.cancellation.raise_if_cancelled()
                    chunk = worklist[start:start + workers]

                    async def score(batch: list[PaperRecord]):
                        try:
                            result = await self.scorer.score_batch(
                                request.question,
                                batch,
                                request.plan_context,
                            )
                            self.cancellation.raise_if_cancelled()
                            return result
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            return exc

                    tasks = []
                    async with asyncio.TaskGroup() as group:
                        for _, batch in chunk:
                            self.cancellation.raise_if_cancelled()
                            tasks.append(group.create_task(score(batch)))
                    outcomes = [task.result() for task in tasks]
                    for (index, batch), outcome in zip(chunk, outcomes):
                        if isinstance(outcome, asyncio.CancelledError):
                            raise outcome
                        if isinstance(outcome, Exception):
                            failed.append((index, batch))
                            empty_failures += isinstance(outcome, EmptyRankingBatchError)
                            rate_limited = rate_limited or self._is_rate_limit_error(outcome)
                            self._event(
                                "ranking.batch_failed",
                                {
                                    "batch_index": index,
                                    "batch_count": len(batches),
                                    "candidate_count": len(batch),
                                    "concurrency": workers,
                                    "rate_limited": self._is_rate_limit_error(outcome),
                                },
                            )
                            continue
                        scores.extend(outcome)
                        completed_ids.add(batch_ids[index])
                        self._checkpoint(request, batch_ids[index], scores, completed_ids)
                        self._event(
                            "ranking.batch_completed",
                            {
                                "batch_index": index,
                                "batch_count": len(batches),
                                "candidate_count": len(batch),
                                "concurrency": workers,
                            },
                        )
                    if rate_limited and lower_tier_available:
                        failed.extend(worklist[start + len(chunk):])
                        break
                if (
                    failed
                    and empty_failures == len(failed)
                    and not rate_limited
                    and not same_tier_retry_used
                ):
                    same_tier_retry_used = True
                    remaining = failed
                    continue
                remaining = failed
                break

        warnings = []
        if remaining:
            failed_candidates = sum(len(batch) for _, batch in remaining)
            self._degraded(
                EmptyRankingBatchError("One or more ranking batches failed."),
                failed_batches=len(remaining),
                failed_candidates=failed_candidates,
            )
            warnings.append(
                "ranking_partial_failure_local_order_retained"
                if scores
                else "ranking_failed_local_order_retained"
            )
        if scores:
            scores, reason_warnings = await self._attach_reasons(
                request.question,
                list(request.documents),
                scores,
                request.plan_context,
            )
            warnings.extend(reason_warnings)
        return scores, warnings

    async def _attach_reasons(
        self,
        question: str,
        documents: list[PaperRecord],
        scores: list[dict[str, Any]],
        plan_context: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        scores = await self.scorer.attach_reasons(
            question,
            documents,
            scores,
            plan_context,
        )
        self.cancellation.raise_if_cancelled()
        if not self.scorer.missing_reason_count:
            return scores, []
        self._event(
            "ranking.degraded",
            {
                "code": "ranking_reasons_missing",
                "missing_reason_count": self.scorer.missing_reason_count,
            },
        )
        return scores, ["ranking_reasons_missing"]

    def _checkpoint(
        self,
        request: RankingRequest,
        batch_id: str,
        scores: list[dict[str, Any]],
        completed_ids: set[str],
    ) -> None:
        self.cancellation.raise_if_cancelled()
        self.observer.on_checkpoint(
            CheckpointDraft(
                step_key="rank_results.batch",
                idempotency_key=batch_id,
                state={
                    "ranking_scores": self.codec.validated_scores(scores),
                    "completed_batch_ids": sorted(completed_ids),
                    "resume_from_stage": request.checkpoint_resume_stage,
                },
                workflow_version="m2.ranking.v1",
            )
        )

    def _rank_from_scores(
        self,
        documents: list[PaperRecord],
        scores: list[dict[str, Any]],
        provenance_by_identity: dict[str, dict[str, Any]],
    ) -> list[RankedPaper]:
        valid_scores, missing_documents = self.codec.match_scores(documents, scores)
        identity_to_document = {
            document_identity(document): document
            for document in documents
            if document_identity(document)
        }
        ranked = []
        for entry in valid_scores:
            document = identity_to_document.get(entry["uid"])
            if document is None:
                continue
            ranked.append(
                RankedPaper(
                    document=document,
                    score=entry.get("score", 0),
                    reasoning=entry.get("reasoning", ""),
                    provenance=self._provenance(document, provenance_by_identity),
                )
            )
        for document in missing_documents:
            ranked.append(
                RankedPaper(
                    document=document,
                    provenance=self._provenance(document, provenance_by_identity),
                )
            )
        return sorted(ranked, key=lambda item: float(item.score or 0), reverse=True)

    @staticmethod
    def _provenance(
        document: PaperRecord,
        provenance_by_identity: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return dict(
            provenance_by_identity.get(document_identity(document))
            or provenance_by_identity.get(document_key(document))
            or {}
        )

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc or "").casefold()
        return "429" in text or "rate_limit" in text or "too many requests" in text

    def _degraded(self, exc: Exception, *, failed_batches: int, failed_candidates: int) -> None:
        self._event(
            "ranking.degraded",
            {
                "code": "ranking_failed_local_order_retained",
                "error_type": type(exc).__name__,
                "failed_batches": failed_batches,
                "failed_candidates": failed_candidates,
            },
        )

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.cancellation.raise_if_cancelled()
        self.observer.on_event(
            CoreProgressEvent(event_type=event_type, stage="ranking", payload=payload)
        )


__all__ = [
    "EmptyRankingBatchError",
    "RankingBatchScheduler",
    "RankingOutputCodec",
    "RankingPipeline",
    "RankingRequest",
    "RankingScorer",
    "SYSTEM_RESULT_RANKING",
]
