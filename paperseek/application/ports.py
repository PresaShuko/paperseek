from __future__ import annotations

from typing import Any, Optional, Protocol


class RunStore(Protocol):
    def create_run(self, question: str, params: Optional[dict[str, Any]] = None) -> str: ...

    def record_event(self, run_id: str, event: dict[str, Any]) -> None: ...

    def record_claimed_event(
        self,
        run_id: str,
        owner_id: str,
        event: dict[str, Any],
    ) -> bool: ...

    def save_checkpoint(self, run_id: str, checkpoint: dict[str, Any]) -> None: ...

    def save_claimed_checkpoint(
        self,
        run_id: str,
        owner_id: str,
        checkpoint: dict[str, Any],
    ) -> bool: ...

    def latest_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]: ...

    def claim_run(self, run_id: str, owner_id: str, lease_seconds: int = 60) -> bool: ...

    def renew_run_lease(self, run_id: str, owner_id: str, lease_seconds: int = 60) -> bool: ...

    def release_run(self, run_id: str, owner_id: str) -> bool: ...

    def cancel_run(self, run_id: str, message: str = "") -> bool: ...

    def cancel_claimed_run(
        self,
        run_id: str,
        owner_id: str,
        message: str = "",
    ) -> bool: ...

    def complete_run(self, run_id: str, payload: dict[str, Any]) -> None: ...

    def complete_claimed_run(
        self,
        run_id: str,
        owner_id: str,
        payload: dict[str, Any],
    ) -> bool: ...

    def fail_run(
        self,
        run_id: str,
        error_message: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> None: ...

    def fail_claimed_run(
        self,
        run_id: str,
        owner_id: str,
        error_message: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> bool: ...

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]: ...
