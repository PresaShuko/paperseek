from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from paperseek.application.ports import RunStore
from paperseek.application.run_lease import RunLease, RunOwnershipLost
from paperseek.config import AgentConfig
from paperseek.history import result_payload_from_search_result, safe_search_params_from_config


@dataclass
class SearchRunSession:
    store: RunStore
    config: AgentConfig
    question: str
    source: str
    resume_run_id: str = ""
    existing_run_id: str = ""
    run_metadata: dict[str, str] = field(default_factory=dict)
    owner_id: str = ""
    lease_seconds: int = 60
    heartbeat_interval_seconds: Optional[float] = None
    run_id: str = field(default="", init=False)
    agent: Any = field(default=None, init=False, repr=False)
    lease: Optional[RunLease] = field(default=None, init=False, repr=False)
    terminal_committed: bool = field(default=False, init=False)

    def start(self) -> str:
        existing_run_id = str(self.existing_run_id or "").strip()
        if existing_run_id:
            existing = self.store.get_run(existing_run_id)
            if existing is None:
                raise ValueError("The selected search run does not exist.")
            if str(existing.get("status") or "") in {"success", "cancelled"}:
                raise ValueError("A completed or cancelled search run cannot be resumed in place.")
            self.run_id = existing_run_id
            self.question = str(existing.get("question") or self.question)
        else:
            params = safe_search_params_from_config(self.config)
            if self.resume_run_id:
                params["resume_from_run_id"] = self.resume_run_id
            metadata = self._safe_run_metadata()
            if metadata:
                params["run_submission"] = metadata
            self.run_id = self.store.create_run(self.question, params)
        if self.run_id and self.owner_id:
            self.lease = RunLease(
                self.store,
                self.run_id,
                self.owner_id,
                lease_seconds=self.lease_seconds,
                heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            )
            if not self.lease.claim():
                raise RunOwnershipLost("Search run could not be claimed by this worker.")
        return self.run_id

    def invoke(
        self,
        agent: Any,
        *,
        event_handler: Optional[Callable[[dict[str, Any]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> dict[str, Any]:
        self.agent = agent
        parameters = inspect.signature(agent.search).parameters
        kwargs: dict[str, Any] = {"verbose": False}
        if "event_handler" in parameters and event_handler is not None:
            kwargs["event_handler"] = self._guarded_event_handler(event_handler)
        if "cancel_check" in parameters and (cancel_check is not None or self.lease is not None):
            kwargs["cancel_check"] = self._combined_cancel_check(cancel_check)
        if "checkpoint_handler" in parameters:
            kwargs["checkpoint_handler"] = self._save_checkpoint
        resume_checkpoint = self._resume_checkpoint()
        if "resume_checkpoint" in parameters and resume_checkpoint is not None:
            kwargs["resume_checkpoint"] = resume_checkpoint
        if self.lease is not None:
            self.lease.start_heartbeat()
        try:
            result = agent.search(self.question, **kwargs)
            self._ensure_owned()
            return result
        finally:
            if self.lease is not None:
                self.lease.stop_heartbeat()

    def response(self, result: dict[str, Any]) -> dict[str, Any]:
        payload = result_payload_from_search_result(result, self.source)
        if self.run_id:
            payload["run_id"] = self.run_id
        return payload

    def complete(self, payload: dict[str, Any]) -> None:
        if self.lease is None:
            self.store.complete_run(self.run_id, payload)
            self.terminal_committed = True
            return
        self._ensure_owned()
        if not self.store.complete_claimed_run(self.run_id, self.owner_id, payload):
            raise RunOwnershipLost("Search run ownership expired before results were committed.")
        self.terminal_committed = True

    def fail(self, message: str) -> bool:
        payload = self._partial_payload()
        if self.lease is None:
            self.store.fail_run(self.run_id, message, payload=payload)
            self.terminal_committed = True
            return True
        committed = self.store.fail_claimed_run(
            self.run_id,
            self.owner_id,
            message,
            payload=payload,
        )
        self.terminal_committed = committed
        return committed

    def cancel(self, message: str = "Search cancelled by user.") -> bool:
        if self.lease is None:
            committed = self.store.cancel_run(self.run_id, message)
        else:
            committed = self.store.cancel_claimed_run(
                self.run_id,
                self.owner_id,
                message,
            )
        self.terminal_committed = committed
        return committed

    @property
    def can_persist(self) -> bool:
        return not self.terminal_committed and (self.lease is None or not self.lease.lost)

    def record_event(self, event: dict[str, Any]) -> None:
        if not self.run_id or self.terminal_committed:
            return
        if self.lease is None:
            self.store.record_event(self.run_id, event)
            return
        self._ensure_owned()
        if not self.store.record_claimed_event(self.run_id, self.owner_id, event):
            self._ownership_rejected("event")

    def _guarded_event_handler(
        self,
        event_handler: Callable[[dict[str, Any]], None],
    ) -> Callable[[dict[str, Any]], None]:
        def guarded(event: dict[str, Any]) -> None:
            self._ensure_owned()
            event_handler(event)

        return guarded

    def _combined_cancel_check(
        self,
        cancel_check: Optional[Callable[[], bool]],
    ) -> Callable[[], bool]:
        return lambda: bool(
            (self.lease is not None and self.lease.lost)
            or (cancel_check is not None and cancel_check())
        )

    def _save_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        if self.lease is None:
            self.store.save_checkpoint(self.run_id, checkpoint)
            return
        self._ensure_owned()
        if not self.store.save_claimed_checkpoint(
            self.run_id,
            self.owner_id,
            checkpoint,
        ):
            self._ownership_rejected("checkpoint")

    def _ensure_owned(self) -> None:
        if self.lease is not None:
            self.lease.ensure_owned()

    def _ownership_rejected(self, operation: str) -> None:
        if self.lease is not None:
            self.lease.mark_lost()
        raise RunOwnershipLost(
            f"Search run ownership expired before the {operation} was persisted."
        )

    def _resume_checkpoint(self) -> Optional[dict[str, Any]]:
        resume_run_id = str(self.existing_run_id or self.resume_run_id or "").strip()
        if not resume_run_id:
            return None
        checkpoint = self.store.latest_checkpoint(resume_run_id)
        if checkpoint is None:
            raise ValueError("The selected search run has no recoverable checkpoint.")
        return checkpoint["payload"]

    def _partial_payload(self) -> Optional[dict[str, Any]]:
        if self.agent is None or not hasattr(self.agent, "partial_result_payload"):
            return None
        try:
            result = self.agent.partial_result_payload(self.question)
            return result_payload_from_search_result(result, self.source)
        except Exception:
            return None

    def _safe_run_metadata(self) -> dict[str, str]:
        allowed = {
            "interface",
            "operation",
            "source_run_id",
            "credential_resume_mode",
        }
        return {
            key: str(value)
            for key, value in self.run_metadata.items()
            if key in allowed and str(value or "").strip()
        }
