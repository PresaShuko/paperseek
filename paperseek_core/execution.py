"""Execution primitives shared by long-running PaperSeek operations."""

from queue import Queue
from threading import Thread
from typing import Callable, TypeVar


T = TypeVar("T")


class SearchCancelled(RuntimeError):
    """Raised when a caller requests cooperative cancellation of a search run."""


def run_cancellable(
    operation: Callable[[], T],
    cancel_check: Callable[[], bool] | None = None,
    *,
    poll_interval: float = 0.1,
) -> T:
    """Run blocking work while allowing its caller to stop waiting promptly.

    Python cannot terminate a running network thread safely. The daemon worker
    may finish after cancellation, but its result is discarded and never
    reaches the search pipeline.
    """

    if cancel_check is None:
        return operation()
    if cancel_check():
        raise SearchCancelled("Search cancelled by user.")

    outcome: Queue[tuple[bool, object]] = Queue(maxsize=1)

    def invoke() -> None:
        try:
            outcome.put((True, operation()))
        except BaseException as exc:
            outcome.put((False, exc))

    worker = Thread(target=invoke, name="paperseek-blocking-call", daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(max(0.01, float(poll_interval)))
        if cancel_check():
            raise SearchCancelled("Search cancelled by user.")
    if cancel_check():
        raise SearchCancelled("Search cancelled by user.")

    succeeded, value = outcome.get_nowait()
    if succeeded:
        return value  # type: ignore[return-value]
    raise value  # type: ignore[misc]
