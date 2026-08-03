from dataclasses import dataclass, field
import time
from typing import Any, Callable, Iterable, Mapping

from paperseek_core.harness.schemas import FrontierAction


@dataclass
class ToolExecution:
    """Normalized result of one frontier action."""

    action: FrontierAction
    status: str
    records: list[Any] = field(default_factory=list)
    total: int = 0
    elapsed_ms: int = 0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolExecutor:
    """Dispatch frontier actions to existing provider-facing handlers.

    Handlers may return ``ToolExecution``, a provider result with ``hits`` and
    ``metadata.total``, a mapping containing ``records``, or an iterable of
    records. The executor owns normalization and error isolation only; provider
    semantics remain in the handlers supplied by ``PaperSeekAgent``.
    """

    def __init__(
        self,
        handlers: Mapping[str, Callable[[FrontierAction], Any]] | None = None,
        *,
        passthrough_exceptions: tuple[type[BaseException], ...] = (),
    ):
        self.handlers = dict(handlers or {})
        self.passthrough_exceptions = tuple(passthrough_exceptions or ())

    @property
    def supported_actions(self) -> frozenset[str]:
        return frozenset(self.handlers)

    def execute(self, action: FrontierAction) -> ToolExecution:
        handler = self.handlers.get(action.action_type)
        if handler is None:
            return ToolExecution(
                action=action,
                status="skipped",
                error=f"unsupported_action:{action.action_type}",
            )

        started = time.perf_counter()
        try:
            value = handler(action)
        except self.passthrough_exceptions:
            raise
        except Exception as exc:
            return ToolExecution(
                action=action,
                status="failed",
                elapsed_ms=_elapsed_ms(started),
                error=f"{exc.__class__.__name__}: {exc}",
            )
        return self._normalize(action, value, started)

    @staticmethod
    def _normalize(action: FrontierAction, value: Any, started: float) -> ToolExecution:
        if isinstance(value, ToolExecution):
            if value.elapsed_ms:
                return value
            value.elapsed_ms = _elapsed_ms(started)
            return value

        records: list[Any]
        total = 0
        metadata: dict[str, Any] = {}
        if value is None:
            records = []
        elif hasattr(value, "hits"):
            records = list(getattr(value, "hits", []) or [])
            result_metadata = getattr(value, "metadata", None)
            total = int(getattr(result_metadata, "total", 0) or 0)
        elif isinstance(value, Mapping):
            records = list(value.get("records") or value.get("hits") or [])
            total = int(value.get("total") or len(records))
            metadata = {
                str(key): item
                for key, item in value.items()
                if key not in {"records", "hits", "total"}
            }
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            records = list(value)
        else:
            records = [value]
        return ToolExecution(
            action=action,
            status="done",
            records=records,
            total=total or len(records),
            elapsed_ms=_elapsed_ms(started),
            metadata=metadata,
        )


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000)))


__all__ = ["ToolExecution", "ToolExecutor"]
