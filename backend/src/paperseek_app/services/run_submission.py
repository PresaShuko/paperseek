from __future__ import annotations

from datetime import timedelta

from paperseek_app.errors import RunNotFound
from paperseek_app.models import RunDetail, RunVersions
from paperseek_app.ports import RunUnitOfWork


class RunSubmissionService:
    def __init__(self, uow: RunUnitOfWork) -> None:
        self.uow = uow

    def create_run(
        self,
        question: str,
        source: str,
        config_snapshot: dict | None = None,
        *,
        deadline_seconds: int = 3600,
    ) -> RunDetail:
        if deadline_seconds <= 0:
            raise ValueError("A run deadline must be positive.")
        return self.uow.create_run(
            question,
            source,
            config_snapshot or {},
            RunVersions(),
            timedelta(seconds=deadline_seconds),
        )

    def submit_run(
        self,
        *,
        subject: str,
        idempotency_key: str,
        request_digest: str,
        question: str,
        source: str,
        config_snapshot: dict | None = None,
        deadline_seconds: int = 3600,
    ) -> RunDetail:
        if deadline_seconds <= 0:
            raise ValueError("A run deadline must be positive.")
        return self.uow.submit_run(
            subject,
            idempotency_key,
            request_digest,
            question,
            source,
            config_snapshot or {},
            RunVersions(),
            timedelta(seconds=deadline_seconds),
        )

    def request_cancel(self, run_id: str) -> RunDetail:
        if self.uow.get_run(run_id).kind != "research":
            raise RunNotFound(f"Run {run_id} was not found.")
        return self.uow.request_cancel(run_id)
