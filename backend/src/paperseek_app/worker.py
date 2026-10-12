from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from paperseek_app.execution import CancellationScope, WorkflowExecution, run_blocking
from paperseek_app.errors import RunOwnershipLost, RunStateError
from paperseek_app.models import RunDetail, RunStatus
from paperseek_app.services import RunExecutionService
from paperseek_core.ports import CancellationToken

if TYPE_CHECKING:
    from paperseek_app.review.execution import ReviewExecutor


class RunExecutor:
    def __init__(
        self,
        service: RunExecutionService,
        resolve: Callable[[RunDetail, CancellationToken], WorkflowExecution],
        *,
        owner_id: str,
        lease_seconds: int = 60,
        heartbeat_seconds: float | None = None,
        cancellation_poll_seconds: float = 0.05,
        review_executor: ReviewExecutor | None = None,
    ) -> None:
        self.service = service
        self.resolve = resolve
        self.owner_id = owner_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = (
            heartbeat_seconds
            if heartbeat_seconds is not None
            else max(0.01, lease_seconds / 3)
        )
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("The heartbeat interval must be shorter than the lease.")
        self.cancellation_poll_seconds = cancellation_poll_seconds
        self.review_executor = review_executor

    async def run_once(self) -> RunDetail | None:
        lease = await run_blocking(self.service.claim_next_run, self.owner_id, self.lease_seconds)
        if lease is None:
            return None
        run = await run_blocking(self.service.get_run, lease.run_id)
        cancellation = CancellationScope()
        try:
            if run.kind == "review":
                if self.review_executor is None:
                    return await run_blocking(self.service.fail_claimed_run, lease, "review_executor_unavailable")
                return await self.review_executor.execute(
                    lease, run, cancellation, poll_seconds=self.cancellation_poll_seconds,
                    lease_seconds=self.lease_seconds, heartbeat_seconds=self.heartbeat_seconds,
                )
            try:
                resolve_task = asyncio.create_task(asyncio.to_thread(self.resolve, run, cancellation))
                try:
                    execution = await asyncio.shield(resolve_task)
                except asyncio.CancelledError:
                    execution = await resolve_task
                    if execution.close is not None:
                        await execution.close()
                    raise
            except Exception:
                return await run_blocking(self.service.fail_claimed_run, lease, "run_configuration_invalid")
            try:
                return await self.service.execute_claimed_workflow(
                    lease,
                    llm=execution.llm,
                    source=execution.source,
                    request=execution.request,
                    embedding=execution.embedding,
                    reranker=execution.reranker,
                    decision=execution.decision,
                    cancellation=cancellation,
                    cancellation_poll_seconds=self.cancellation_poll_seconds,
                    lease_seconds=self.lease_seconds,
                    heartbeat_seconds=self.heartbeat_seconds,
                    deadline_at=execution.deadline_at,
                )
            finally:
                if execution.close is not None:
                    await execution.close()
        except (RunOwnershipLost, RunStateError) as exc:
            detail = await run_blocking(self.service.get_run, lease.run_id)
            if isinstance(exc, RunStateError) and detail.status not in {
                RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS, RunStatus.CANCELLED, RunStatus.FAILED,
            }:
                raise
            return detail
