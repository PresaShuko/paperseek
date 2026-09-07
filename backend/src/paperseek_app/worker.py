from __future__ import annotations

from collections.abc import Callable

from paperseek_app.execution import CancellationScope, WorkflowExecution
from paperseek_app.errors import RunOwnershipLost
from paperseek_app.models import RunDetail
from paperseek_app.services import RunExecutionService
from paperseek_core.ports import CancellationToken


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

    async def run_once(self) -> RunDetail | None:
        lease = self.service.claim_next_run(self.owner_id, self.lease_seconds)
        if lease is None:
            return None
        run = self.service.get_run(lease.run_id)
        cancellation = CancellationScope()
        try:
            execution = self.resolve(run, cancellation)
        except Exception:
            return self.service.fail_claimed_run(lease, "run_configuration_invalid")
        try:
            try:
                return await self.service.execute_claimed_workflow(
                    lease,
                    llm=execution.llm,
                    source=execution.source,
                    request=execution.request,
                    abstracts=execution.abstracts,
                    candidate_metadata=execution.candidate_metadata,
                    embedding=execution.embedding,
                    reranker=execution.reranker,
                    cancellation=cancellation,
                    cancellation_poll_seconds=self.cancellation_poll_seconds,
                    lease_seconds=self.lease_seconds,
                    heartbeat_seconds=self.heartbeat_seconds,
                )
            finally:
                if execution.close is not None:
                    await execution.close()
        except RunOwnershipLost:
            return self.service.get_run(lease.run_id)
