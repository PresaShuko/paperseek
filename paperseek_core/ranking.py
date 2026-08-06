"""Deterministic scheduling and output decoding for the ranking stage."""

import hashlib
import json
import math
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, Tuple

from paperseek_core.execution import SearchCancelled
from paperseek_core.harness.schemas import (
    RANKING_RETRY_LOWER_CONCURRENCY,
    RANKING_RETRY_SAME_TIER,
    RankingScoreEntry,
)


class EmptyRankingBatchError(RuntimeError):
    """Raised when an LLM ranking batch returns no usable scores."""


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
        documents: list,
        identity: Callable[[Any], str],
    ) -> str:
        candidate_ids = [str(getattr(document, "uid", "") or identity(document)) for document in documents]
        digest = hashlib.sha256("\0".join(candidate_ids).encode("utf-8")).hexdigest()[:20]
        return f"{step_id}:{digest}"


@dataclass(frozen=True)
class RankingOutputCodec:
    document_identity: Callable[[Any], str]

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

    def parse_scores(self, raw: str, documents: list) -> list:
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
                "uid": self.document_identity(documents[index - 1]),
                "score": score,
                "reasoning": "",
            })
        return output

    def parse_reasons(self, raw: str, identities: list[str]) -> dict[str, str]:
        pairs = self.json_object(raw).get("reasons")
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

    def match_scores(self, documents: list, scores: list) -> Tuple[list, list]:
        identities = [self.document_identity(document) for document in documents]
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
                    if identity and (uid.casefold() in identity.casefold() or identity.casefold() in uid.casefold())
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
                output.append(RankingScoreEntry.model_validate(item).model_dump())
            except (TypeError, ValueError):
                continue
        return output


@dataclass
class RankingBatchExecution:
    scores: list
    completed_ids: set[str]
    completed_batches: int
    remaining_batches: list[tuple[int, list]]
    schedule: list[int]


class RankingBatchExecutor:
    """Execute ranking batches with bounded concurrency and deterministic recovery."""

    def __init__(
        self,
        host: Any,
        *,
        question: str,
        step_id: str,
        step_title: str,
        batch_size: int,
        candidate_count: int,
        checkpoint_records: list,
        checkpoint_resume_stage: str,
    ):
        self.host = host
        self.question = question
        self.step_id = step_id
        self.step_title = step_title
        self.batch_size = batch_size
        self.candidate_count = candidate_count
        self.checkpoint_records = checkpoint_records
        self.checkpoint_resume_stage = checkpoint_resume_stage

    def execute(
        self,
        batches: list[list],
        batch_ids: dict[int, str],
        completed_ids: set[str],
        scores: list,
    ) -> RankingBatchExecution:
        host = self.host
        remaining_batches = [
            (index, batch)
            for index, batch in enumerate(batches, 1)
            if batch_ids[index] not in completed_ids
        ]
        completed_batches = len(batches) - len(remaining_batches)
        if completed_batches:
            host._emit_log(
                f"Resumed {completed_batches}/{len(batches)} completed result-ranking batches from checkpoint."
            )
        schedule = host._ranking_concurrency_schedule(len(batches))
        for tier_index, workers in enumerate(schedule):
            host._check_cancelled()
            if not remaining_batches:
                break
            if tier_index > 0:
                host._emit_log(
                    f"Retrying {len(remaining_batches)} failed result-ranking batch(es) with concurrency={workers}."
                )
            lower_tier_available = tier_index < len(schedule) - 1
            same_tier_retry_used = False
            while True:
                failed_batches = []
                empty_output_batches = []
                backoff_to_lower_tier = False
                worklist = list(remaining_batches)
                for start in range(0, len(worklist), workers):
                    host._check_cancelled()
                    chunk = worklist[start:start + workers]
                    executor = ThreadPoolExecutor(max_workers=workers)
                    try:
                        future_to_batch = {
                            executor.submit(
                                host._score_ranking_batch,
                                self.question,
                                batch,
                                host._new_ranking_llm_client(),
                            ): (index, batch)
                            for index, batch in chunk
                        }
                        pending = set(future_to_batch)
                        while pending:
                            done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                            host._check_cancelled()
                            if not done:
                                continue
                            for future in done:
                                host._check_cancelled()
                                index, batch = future_to_batch[future]
                                try:
                                    batch_scores = future.result()
                                    host._check_cancelled()
                                    if batch and not batch_scores:
                                        raise EmptyRankingBatchError(
                                            "LLM ranking batch returned no valid score entries."
                                        )
                                except SearchCancelled:
                                    raise
                                except Exception as exc:
                                    rate_limited = host._is_rate_limit_error(exc)
                                    empty_output = isinstance(exc, EmptyRankingBatchError)
                                    host._observe_ranking_batch_error(
                                        exc,
                                        step_id=self.step_id,
                                        batch_index=index,
                                        batch_count=len(batches),
                                        concurrency=workers,
                                        candidate_count=len(batch),
                                        rate_limited=rate_limited,
                                    )
                                    host._emit_log(
                                        f"Result ranking batch {index}/{len(batches)} failed at concurrency={workers}; "
                                        f"will retry if a lower concurrency tier is available: {exc}"
                                    )
                                    failed_batches.append((index, batch))
                                    if empty_output:
                                        empty_output_batches.append((index, batch))
                                    if lower_tier_available and rate_limited:
                                        backoff_to_lower_tier = True
                                    host._emit_ranking_step(
                                        self.step_id,
                                        "processing",
                                        self.step_title,
                                        current=completed_batches,
                                        total=len(batches),
                                        detail=(
                                            f"Batch {index}/{len(batches)} returned no valid scores at concurrency={workers}; retrying once at the same concurrency."
                                            if empty_output
                                            else f"Batch {index}/{len(batches)} failed at concurrency={workers}; retrying failed batches with lower concurrency."
                                        ),
                                        concurrency=workers,
                                        batch_size=self.batch_size,
                                        candidate_count=self.candidate_count,
                                    )
                                    continue
                                scores.extend(batch_scores)
                                completed_ids.add(batch_ids[index])
                                completed_batches += 1
                                host._emit_log(
                                    f"Result ranking batch {index}/{len(batches)} completed; "
                                    f"candidates={len(batch)}; scored={len(batch_scores)}."
                                )
                                host._emit_ranking_step(
                                    self.step_id,
                                    "processing",
                                    self.step_title,
                                    current=completed_batches,
                                    total=len(batches),
                                    detail=f"Completed batch {index}/{len(batches)} at concurrency={workers}.",
                                    concurrency=workers,
                                    batch_size=self.batch_size,
                                    candidate_count=self.candidate_count,
                                )
                                host._save_checkpoint(
                                    "ranking_batch",
                                    records=self.checkpoint_records,
                                    ranking_scores=scores,
                                    completed_batch_ids=sorted(completed_ids),
                                    metadata={
                                        "step_id": self.step_id,
                                        "resume_from_stage": self.checkpoint_resume_stage,
                                    },
                                )
                    except SearchCancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        executor = None
                        raise
                    finally:
                        if executor is not None:
                            executor.shutdown(wait=True)
                    if backoff_to_lower_tier:
                        failed_batches.extend(worklist[start + len(chunk):])
                        next_workers = schedule[tier_index + 1] if lower_tier_available else 0
                        failed_docs = sum(len(batch) for _, batch in failed_batches)
                        decision = host._recover_ranking_failures(
                            step_id=self.step_id,
                            concurrency=workers,
                            next_concurrency=next_workers,
                            failed_batches=len(failed_batches),
                            failed_candidates=failed_docs,
                            rate_limited=True,
                        )
                        host._emit_log(
                            f"Rate limit detected at concurrency={workers}; moving {len(failed_batches)} "
                            "failed or unsubmitted batch(es) to the next lower concurrency tier."
                        )
                        if decision.action != RANKING_RETRY_LOWER_CONCURRENCY:
                            break
                        break
                if (
                    failed_batches
                    and empty_output_batches
                    and not backoff_to_lower_tier
                    and not same_tier_retry_used
                    and len(empty_output_batches) == len(failed_batches)
                ):
                    failed_docs = sum(len(batch) for _, batch in failed_batches)
                    decision = host._recover_ranking_failures(
                        step_id=self.step_id,
                        concurrency=workers,
                        next_concurrency=workers,
                        failed_batches=len(failed_batches),
                        failed_candidates=failed_docs,
                        rate_limited=False,
                    )
                    if decision.action == RANKING_RETRY_SAME_TIER:
                        same_tier_retry_used = True
                        remaining_batches = failed_batches
                        host._emit_log(
                            f"Retrying {len(remaining_batches)} empty result-ranking batch(es) "
                            f"once more at concurrency={workers}."
                        )
                        continue
                break
            if failed_batches and lower_tier_available and not backoff_to_lower_tier:
                next_workers = schedule[tier_index + 1]
                failed_docs = sum(len(batch) for _, batch in failed_batches)
                host._recover_ranking_failures(
                    step_id=self.step_id,
                    concurrency=workers,
                    next_concurrency=next_workers,
                    failed_batches=len(failed_batches),
                    failed_candidates=failed_docs,
                    rate_limited=False,
                )
            remaining_batches = failed_batches

        return RankingBatchExecution(
            scores=scores,
            completed_ids=completed_ids,
            completed_batches=completed_batches,
            remaining_batches=remaining_batches,
            schedule=schedule,
        )
