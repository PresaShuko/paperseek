"""Ranking orchestration separated from the search agent."""

from dataclasses import dataclass, field
from typing import Any, Optional

from paperseek_core.execution import SearchCancelled
from paperseek_core.ranking import EmptyRankingBatchError, RankingBatchExecutor


@dataclass(frozen=True)
class RankingRunRequest:
    question: str
    documents: list
    ranking_context: dict[str, Any] = field(default_factory=dict)
    step_id: str = "llm_reranking"
    step_title: str = "LLM reranking"
    resume_scores: list = field(default_factory=list)
    completed_batch_ids: list[str] = field(default_factory=list)
    checkpoint_records: Optional[list] = None
    checkpoint_resume_stage: str = "pre_rank"


class RankingPipeline:
    """Coordinate ranking without owning search, provider, or UI state."""

    def __init__(self, host: Any):
        self.host = host

    def run(self, request: RankingRunRequest) -> list:
        documents = request.documents
        if not documents:
            return []
        host = self.host
        host._check_cancelled()
        if request.ranking_context:
            host.ranking_context = dict(request.ranking_context)

        batch_size = host._ranking_batch_size(len(documents))
        batches = [documents[index:index + batch_size] for index in range(0, len(documents), batch_size)]
        batch_ids = {
            index: host._ranking_batch_id(request.step_id, batch)
            for index, batch in enumerate(batches, 1)
        }
        completed_ids = set(request.completed_batch_ids)
        scores = list(request.resume_scores)
        checkpoint_records = list(request.checkpoint_records or documents)
        if len(batches) == 1:
            return self._run_single_batch(
                request,
                batches[0],
                batch_ids[1],
                completed_ids,
                scores,
                checkpoint_records,
            )
        return self._run_multiple_batches(
            request,
            batches,
            batch_ids,
            completed_ids,
            scores,
            checkpoint_records,
            batch_size,
        )

    def _run_single_batch(
        self,
        request: RankingRunRequest,
        documents: list,
        batch_id: str,
        completed_ids: set[str],
        scores: list,
        checkpoint_records: list,
    ) -> list:
        host = self.host
        if batch_id in completed_ids:
            host._emit_log("Resumed completed result-ranking batch 1/1 from checkpoint.")
            return host._rank_from_scores(documents, scores)
        host._emit_ranking_step(
            request.step_id,
            "processing",
            request.step_title,
            current=0,
            total=1,
            detail=f"Scoring {len(documents)} candidates in one LLM batch.",
        )
        try:
            host._check_cancelled()
            host._llm_request_log("result_ranking")
            ranking_llm = host._new_ranking_llm_client()
            scores = host._score_ranking_batch(request.question, documents, ranking_llm)
            host._check_cancelled()
            if documents and not scores:
                raise EmptyRankingBatchError("LLM ranking batch returned no valid score entries.")
            scores = host._attach_ranking_reasons(request.question, documents, scores, ranking_llm)
            host._llm_response_log("result_ranking")
        except SearchCancelled:
            raise
        except Exception as exc:
            rate_limited = host._is_rate_limit_error(exc)
            host._observe_ranking_batch_error(
                exc,
                step_id=request.step_id,
                batch_index=1,
                batch_count=1,
                concurrency=1,
                candidate_count=len(documents),
                rate_limited=rate_limited,
            )
            host._recover_ranking_failures(
                step_id=request.step_id,
                concurrency=1,
                next_concurrency=0,
                failed_batches=1,
                failed_candidates=len(documents),
                rate_limited=rate_limited,
            )
            host._emit_log(f"Result ranking batch failed; keeping local pre-ranking order: {exc}")
            host._emit_ranking_step(
                request.step_id,
                "skipped",
                request.step_title,
                current=0,
                total=1,
                detail="LLM ranking failed or timed out; keeping the local pre-ranking order.",
                candidate_count=len(documents),
            )
            return host._rank_from_scores(documents, [])

        completed_ids.add(batch_id)
        host._save_checkpoint(
            "ranking_batch",
            records=checkpoint_records,
            ranking_scores=scores,
            completed_batch_ids=sorted(completed_ids),
            metadata={
                "step_id": request.step_id,
                "resume_from_stage": request.checkpoint_resume_stage,
            },
        )
        host._emit_ranking_step(
            request.step_id,
            "complete",
            request.step_title,
            current=1,
            total=1,
            detail=f"Scored {len(documents)} candidates.",
            candidate_count=len(documents),
        )
        return host._rank_from_scores(documents, scores)

    def _run_multiple_batches(
        self,
        request: RankingRunRequest,
        batches: list[list],
        batch_ids: dict[int, str],
        completed_ids: set[str],
        scores: list,
        checkpoint_records: list,
        batch_size: int,
    ) -> list:
        host = self.host
        documents = request.documents
        initial_workers = host._ranking_concurrency()
        host._emit_ranking_step(
            request.step_id,
            "processing",
            request.step_title,
            current=0,
            total=len(batches),
            detail=(
                f"Scoring {len(documents)} candidates in {len(batches)} LLM batches; "
                f"concurrency={initial_workers}."
            ),
            concurrency=initial_workers,
            batch_size=batch_size,
            candidate_count=len(documents),
        )
        host._emit_log(
            f"Result ranking started in {len(batches)} batches; candidates={len(documents)}; "
            f"batch_size={batch_size}; concurrency={initial_workers}."
        )
        execution = RankingBatchExecutor(
            host,
            question=request.question,
            step_id=request.step_id,
            step_title=request.step_title,
            batch_size=batch_size,
            candidate_count=len(documents),
            checkpoint_records=checkpoint_records,
            checkpoint_resume_stage=request.checkpoint_resume_stage,
        ).execute(batches, batch_ids, completed_ids, scores)
        self._report_multiple_batch_outcome(request, execution, batches, batch_size, initial_workers)
        scores = execution.scores
        if scores:
            scores = host._attach_ranking_reasons(
                request.question,
                documents,
                scores,
                host._new_ranking_llm_client(),
            )
        return host._rank_from_scores(documents, scores)

    def _report_multiple_batch_outcome(
        self,
        request: RankingRunRequest,
        execution: Any,
        batches: list[list],
        batch_size: int,
        initial_workers: int,
    ) -> None:
        host = self.host
        documents = request.documents
        remaining = execution.remaining_batches
        if remaining:
            failed_docs = sum(len(batch) for _, batch in remaining)
            host._recover_ranking_failures(
                step_id=request.step_id,
                concurrency=execution.schedule[-1] if execution.schedule else initial_workers,
                next_concurrency=0,
                failed_batches=len(remaining),
                failed_candidates=failed_docs,
                rate_limited=False,
            )
            host._emit_log(
                f"{len(remaining)} result ranking batch(es) still failed at minimum concurrency=4; "
                "returning those candidates in source order with zero scores."
            )
            host._emit_ranking_step(
                request.step_id,
                "skipped" if not execution.scores else "complete",
                request.step_title,
                current=execution.completed_batches,
                total=len(batches),
                detail=(
                    f"{len(remaining)} batch(es), {failed_docs} candidates, failed even at concurrency=4; "
                    "keeping local pre-ranking order for those candidates."
                ),
                concurrency=4,
                batch_size=batch_size,
                candidate_count=len(documents),
            )
        if not execution.scores:
            if not remaining:
                host._recover_ranking_failures(
                    step_id=request.step_id,
                    concurrency=initial_workers,
                    next_concurrency=0,
                    failed_batches=len(batches),
                    failed_candidates=len(documents),
                    rate_limited=False,
                )
            host._emit_log("All result ranking batches failed; returning candidates in source order with zero scores.")
            host._emit_ranking_step(
                request.step_id,
                "skipped",
                request.step_title,
                current=execution.completed_batches,
                total=len(batches),
                detail="All LLM ranking batches failed or timed out; keeping the local pre-ranking order.",
                concurrency=4,
                batch_size=batch_size,
                candidate_count=len(documents),
            )
        elif not remaining:
            host._emit_ranking_step(
                request.step_id,
                "complete",
                request.step_title,
                current=len(batches),
                total=len(batches),
                detail=f"LLM scoring completed for {execution.completed_batches}/{len(batches)} batches.",
                concurrency=initial_workers,
                batch_size=batch_size,
                candidate_count=len(documents),
            )
