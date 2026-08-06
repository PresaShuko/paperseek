"""Checkpoint validation, restoration, and persistence coordination."""

from __future__ import annotations

from typing import Optional

from paperseek_core.checkpoints import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointError,
    paper_records_from_checkpoint,
    paper_records_to_checkpoint,
    scrub_checkpoint_value,
)
from paperseek_core.execution import SearchCancelled
from paperseek_core.harness import SearchCheckpoint, SearchRunState
from paperseek_core.planning import SearchPlan


class CheckpointCoordinator:
    def __init__(self, host) -> None:
        self._host = host

    def validate(self, question: str, payload: Optional[dict]) -> Optional[SearchCheckpoint]:
        host = self._host
        if not payload:
            return None
        try:
            checkpoint = SearchCheckpoint.model_validate(payload)
        except Exception as exc:
            raise CheckpointError(f"checkpoint_corrupt: {exc}") from exc
        if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointError(
                f"checkpoint_corrupt: unsupported schema version {checkpoint.schema_version}"
            )
        if checkpoint.question.strip() != question.strip():
            raise CheckpointError("checkpoint_corrupt: research question does not match the resumed request")
        if checkpoint.source != host.data_source:
            raise CheckpointError("checkpoint_corrupt: data source does not match the resumed request")
        return checkpoint

    def restore(self, checkpoint: SearchCheckpoint) -> None:
        host = self._host
        host.search_intent = checkpoint.search_intent
        host.search_plan = SearchPlan.model_validate(checkpoint.search_plan) if checkpoint.search_plan else None
        host.query_view_selection = list(checkpoint.query_view_selection)
        host.query_portfolio = list(checkpoint.query_portfolio)
        host.query_iteration_results = []
        for item in checkpoint.query_iteration_results:
            if not isinstance(item, dict):
                continue
            try:
                records = paper_records_from_checkpoint(item.get("records") or [])
            except Exception:
                continue
            host.query_iteration_results.append(
                {
                    "iteration": int(item.get("iteration") or 0),
                    "query": str(item.get("query") or ""),
                    "total": int(item.get("total") or 0),
                    "records": records,
                }
            )
        host.search_run_state = (
            SearchRunState.model_validate(checkpoint.search_state)
            if checkpoint.search_state
            else SearchRunState(
                question=checkpoint.question,
                source=checkpoint.source,
                current_query=checkpoint.current_query,
                search_plan=checkpoint.search_plan,
            )
        )
        host.current_query = checkpoint.current_query
        host.last_total = int(checkpoint.total or 0)
        host.last_iteration = int(checkpoint.iteration or 0)
        host.iteration_history = list(checkpoint.history)
        host.citation_map = dict(checkpoint.citation_map or host._empty_citation_map())
        host.ranking_steps = {
            str(step.get("id") or step.get("step_id") or index): dict(step)
            for index, step in enumerate(checkpoint.ranking_steps)
            if isinstance(step, dict)
        }

    def save(
        self,
        stage: str,
        *,
        records: Optional[list] = None,
        ranking_scores: Optional[list] = None,
        completed_batch_ids: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        host = self._host
        host._check_cancelled()
        if not host.checkpoint_handler:
            return
        host.checkpoint_sequence += 1
        checkpoint = SearchCheckpoint(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            sequence=host.checkpoint_sequence,
            stage=stage,
            question=host.run_question,
            source=host.data_source,
            current_query=host.current_query,
            total=int(host.last_total or 0),
            iteration=int(host.last_iteration or 0),
            search_intent=host.search_intent,
            search_plan=host.search_plan.model_dump() if host.search_plan else {},
            query_view_selection=list(host.query_view_selection),
            query_portfolio=list(host.query_portfolio),
            history=list(host.iteration_history or []),
            search_state=host._search_state_payload(),
            records=paper_records_to_checkpoint(records or []),
            query_iteration_results=[
                {
                    "iteration": int(item.get("iteration") or 0),
                    "query": str(item.get("query") or ""),
                    "total": int(item.get("total") or 0),
                    "records": paper_records_to_checkpoint(item.get("records") or []),
                }
                for item in host.query_iteration_results
                if isinstance(item, dict) and item.get("records")
            ],
            citation_map=dict(host.citation_map or {}),
            ranking_steps=list(host.ranking_steps.values()),
            ranking_scores=list(ranking_scores or []),
            completed_batch_ids=list(completed_batch_ids or []),
            metadata=dict(metadata or {}),
        )
        try:
            host._check_cancelled()
            host.checkpoint_handler(scrub_checkpoint_value(checkpoint.model_dump()))
        except SearchCancelled:
            raise
        except Exception as exc:
            host._emit_log(f"Checkpoint persistence failed; search will continue without this snapshot: {exc}")
        host._check_cancelled()
