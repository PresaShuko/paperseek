"""Run one bounded operation while maintaining its lease and cancellation fence."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from paperseek_app.errors import ArtifactError, RunOwnershipLost, RunPersistenceError, RunStateError
from paperseek_app.execution import CancellationScope, run_blocking
from paperseek_app.models import LeaseToken, RunStatus
from paperseek_app.ports import RunUnitOfWork


async def run_leased_task[T](
    operation: Awaitable[T], *, uow: RunUnitOfWork, lease: LeaseToken, scope: CancellationScope,
    poll_seconds: float, lease_seconds: int, heartbeat_seconds: float,
    flush_progress: Callable[[], Awaitable[None]] | None = None,
) -> T:
    workflow_task = asyncio.ensure_future(operation)

    async def monitor() -> None:
        while True:
            status = (await run_blocking(uow.get_run, lease.run_id)).status
            if status in {RunStatus.CANCELLING, RunStatus.CANCELLED}:
                scope.cancel()
                return
            await asyncio.sleep(max(0.01, poll_seconds))

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(max(0.01, heartbeat_seconds))
            try:
                await run_blocking(uow.renew_lease, lease, timedelta(seconds=lease_seconds))
            except (RunOwnershipLost, RunStateError, RunPersistenceError) as exc:
                scope.cancel()
                raise RunOwnershipLost("The executor lost its run lease during renewal.") from exc

    async def publish_progress() -> None:
        while True:
            await asyncio.sleep(0.1)
            if flush_progress:
                await flush_progress()

    monitor_task = asyncio.create_task(monitor())
    heartbeat_task = asyncio.create_task(heartbeat())
    tasks = {workflow_task, monitor_task, heartbeat_task}
    progress_task = asyncio.create_task(publish_progress()) if flush_progress else None
    if progress_task:
        tasks.add(progress_task)
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if monitor_task in done:
            await monitor_task
            if scope.cancelled:
                raise asyncio.CancelledError
        if heartbeat_task in done:
            await heartbeat_task
        if progress_task and progress_task in done:
            await progress_task
        return await workflow_task
    except ExceptionGroup as exc:
        known, unknown = exc.split((RunPersistenceError, ArtifactError, RunOwnershipLost))
        if unknown is not None or known is None:
            raise
        error = known
        while isinstance(error, BaseExceptionGroup):
            error = error.exceptions[0]
        raise error from exc
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
