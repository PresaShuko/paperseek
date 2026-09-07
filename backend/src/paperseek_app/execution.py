from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from paperseek_core.models import ResearchWorkflowRequest
from paperseek_core.ports import AbstractPort, CandidateMetadataPort, CancellationToken, EmbeddingPort, LLMPort, RerankPort, SourcePort, WorkflowObserver
from paperseek_core.workflow import ResearchWorkflow


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
    candidate_metadata: CandidateMetadataPort | None = None
    embedding: EmbeddingPort | None = None
    reranker: RerankPort | None = None
    close: Callable[[], Awaitable[None]] | None = None

    async def run(self, observer: WorkflowObserver, cancellation: CancellationToken):
        return await ResearchWorkflow(
            llm=self.llm, source=self.source, observer=observer, abstracts=self.abstracts,
            candidate_metadata=self.candidate_metadata, embedding=self.embedding,
            reranker=self.reranker, cancellation=cancellation,
        ).run(self.request)


assert isinstance(CancellationScope(), CancellationToken)


__all__ = ["CancellationScope", "WorkflowExecution"]
