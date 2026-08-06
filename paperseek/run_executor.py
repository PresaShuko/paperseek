from __future__ import annotations

from collections.abc import Callable, Iterator
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4


class InProcessRun:
    def __init__(self, owner: "InProcessRunExecutor", *, buffer_events: bool = True) -> None:
        self._owner = owner
        self._events: Queue[dict[str, Any] | None] | None = Queue() if buffer_events else None
        self._cancel_event = Event()
        self._state_lock = Lock()
        self._owner_id = f"worker_{uuid4().hex}"
        self._run_id = ""
        self._closed = False

    @property
    def run_id(self) -> str:
        with self._state_lock:
            return self._run_id

    @property
    def owner_id(self) -> str:
        return self._owner_id

    def bind(self, run_id: str) -> None:
        run_id = str(run_id or "").strip()
        if not run_id:
            return
        with self._state_lock:
            if self._closed:
                return
            previous = self._run_id
            self._run_id = run_id
        if previous and previous != run_id:
            self._owner._unregister(previous, self)
        self._owner._register(run_id, self)

    def cancel(self) -> None:
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def emit(self, event: dict[str, Any]) -> bool:
        with self._state_lock:
            if self._closed:
                return False
            if self._events is not None:
                self._events.put(event)
            return True

    def start(self, worker: Callable[[], None]) -> None:
        Thread(target=worker, daemon=True).start()

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            run_id = self._run_id
        if run_id:
            self._owner._unregister(run_id, self)
        if self._events is not None:
            self._events.put(None)

    def iter_events(
        self,
        *,
        heartbeat_seconds: float,
        heartbeat_factory: Callable[[], dict[str, Any]],
    ) -> Iterator[dict[str, Any]]:
        if self._events is None:
            raise RuntimeError("This run does not buffer stream events.")
        while True:
            try:
                event = self._events.get(timeout=heartbeat_seconds)
            except Empty:
                yield heartbeat_factory()
                continue
            if event is None:
                return
            yield event


class InProcessRunExecutor:
    """Process-local ownership for active streamed runs."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active: dict[str, InProcessRun] = {}

    def create(self, *, buffer_events: bool = True) -> InProcessRun:
        return InProcessRun(self, buffer_events=buffer_events)

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            run = self._active.get(str(run_id or ""))
        if run is None:
            return False
        run.cancel()
        return True

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            return str(run_id or "") in self._active

    def _register(self, run_id: str, run: InProcessRun) -> None:
        with self._lock:
            self._active[run_id] = run

    def _unregister(self, run_id: str, run: InProcessRun) -> None:
        with self._lock:
            if self._active.get(run_id) is run:
                self._active.pop(run_id, None)
