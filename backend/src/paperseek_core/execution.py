from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from paperseek_core.ports import CancellationToken


class _NeverCancelled:
    @property
    def cancelled(self) -> bool:
        return False

    def raise_if_cancelled(self) -> None:
        return None

    async def wait(self) -> None:
        # A never-completing token is only used by direct core callers that do
        # not own a durable run lifecycle.
        import asyncio

        await asyncio.Event().wait()


NEVER_CANCELLED = _NeverCancelled()


@dataclass(frozen=True, slots=True)
class RequestContext:
    step_key: str
    cancellation: "CancellationToken" = NEVER_CANCELLED
    deadline_at: float | None = None
    provider: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["NEVER_CANCELLED", "RequestContext"]
