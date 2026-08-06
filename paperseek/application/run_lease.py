from __future__ import annotations

from threading import Event, Lock, Thread
from typing import Optional

from paperseek.application.ports import RunStore


class RunOwnershipLost(RuntimeError):
    pass


class RunLease:
    """Renew one persisted run claim while synchronous search work is active."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        owner_id: str,
        *,
        lease_seconds: int = 60,
        heartbeat_interval_seconds: Optional[float] = None,
    ) -> None:
        self.store = store
        self.run_id = str(run_id or "").strip()
        self.owner_id = str(owner_id or "").strip()
        self.lease_seconds = max(5, min(int(lease_seconds or 60), 3600))
        default_interval = max(1.0, min(20.0, self.lease_seconds / 3.0))
        self.heartbeat_interval_seconds = max(
            0.01,
            float(heartbeat_interval_seconds or default_interval),
        )
        self._stop = Event()
        self._lost = Event()
        self._lock = Lock()
        self._thread: Optional[Thread] = None

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def claim(self) -> bool:
        if not self.run_id or not self.owner_id:
            return False
        claimed = self.store.claim_run(
            self.run_id,
            self.owner_id,
            lease_seconds=self.lease_seconds,
        )
        if not claimed:
            self._lost.set()
        return claimed

    def start_heartbeat(self) -> None:
        self.ensure_owned()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(
                target=self._heartbeat_loop,
                name=f"paperseek-lease-{self.run_id}",
                daemon=True,
            )
            self._thread.start()

    def stop_heartbeat(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self.heartbeat_interval_seconds + 0.5))

    def ensure_owned(self) -> None:
        if self.lost:
            raise RunOwnershipLost(
                "Search run ownership was lost before the operation completed."
            )

    def mark_lost(self) -> None:
        self._lost.set()
        self._stop.set()

    def release(self) -> bool:
        self.stop_heartbeat()
        if self.lost:
            return False
        return self.store.release_run(self.run_id, self.owner_id)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_interval_seconds):
            try:
                renewed = self.store.renew_run_lease(
                    self.run_id,
                    self.owner_id,
                    lease_seconds=self.lease_seconds,
                )
            except Exception:
                renewed = False
            if not renewed:
                self._lost.set()
                self._stop.set()
                return
