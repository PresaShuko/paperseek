from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from paperseek_core.models import ResearchWorkflowRequest
from paperseek_core.ports import AbstractPort, CancellationToken, LLMPort, SourcePort


class CancellationScope:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError

    async def wait(self) -> None:
        await self._event.wait()


@dataclass(frozen=True, slots=True)
class WorkflowExecution:
    llm: LLMPort
    source: SourcePort
    request: ResearchWorkflowRequest
    abstracts: AbstractPort | None = None
    close: Callable[[], Awaitable[None]] | None = None


assert isinstance(CancellationScope(), CancellationToken)


__all__ = ["CancellationScope", "WorkflowExecution"]
