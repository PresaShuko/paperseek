from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from paperseek_app.errors import (
    ActiveRunExists,
    IdempotencyConflict,
    RunError,
    RunNotFound,
    RunOwnershipLost,
    RunPersistenceError,
    RunStateError,
)
from paperseek_app.models import (
    ArtifactRole,
    CleanupLease,
    DeletionReceipt,
    LeaseToken,
    PendingEvent,
    PersistedCheckpoint,
    PersistedEvent,
    PersistedResult,
    RunDetail,
    RunStatus,
    RunVersions,
    StoredArtifact,
)
from paperseek_app.state import validate_transition
from paperseek_community.persistence.migrate import database_url
from paperseek_core.models import CheckpointDraft, FinalPaperResult, ResearchResult


TERMINAL_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.COMPLETED_WITH_WARNINGS.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
}
MAX_RECOVERY_RECLAIMS = 3
MAX_ATTEMPTS = 1 + MAX_RECOVERY_RECLAIMS
MAX_CLEANUP_ATTEMPTS = 3


def _system_clock() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Run clock values must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_load(value: str) -> Any:
    return json.loads(value)


class SQLiteRunUnitOfWork:
    def __init__(
        self,
        database_path: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.clock = clock or _system_clock
        self.engine = self._create_engine()

    def _create_engine(self) -> Engine:
        engine = create_engine(
            database_url(self.database_path),
            connect_args={"check_same_thread": False, "timeout": 10},
        )

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA busy_timeout = 10000")
            cursor.close()

        return engine

    def close(self) -> None:
        self.engine.dispose()

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        try:
            with self.engine.begin() as connection:
                yield connection
        except RunError:
            raise
        except SQLAlchemyError as exc:
            raise RunPersistenceError("The run transaction could not be committed.") from exc

    def create_run(
        self,
        question: str,
        source: str,
        config_snapshot: dict,
        versions: RunVersions,
        deadline_for: timedelta,
    ) -> RunDetail:
        question = question.strip()
        source = source.strip()
        if not question or not source:
            raise ValueError("A run requires a question and source.")
        now_value = _utc(self.clock())
        if deadline_for <= timedelta(0):
            raise ValueError("A run deadline must be positive.")
        now = _timestamp(now_value)
        deadline_at = _timestamp(now_value + deadline_for)
        with self._transaction() as connection:
            run_id = self._insert_run(
                connection,
                question=question,
                source=source,
                config_snapshot=config_snapshot,
                versions=versions,
                owner_subject=None,
                now=now,
                deadline_at=deadline_at,
            )
        return self.get_run(run_id)

    def submit_run(
        self,
        subject: str,
        idempotency_key: str,
        request_digest: str,
        question: str,
        source: str,
        config_snapshot: dict,
        versions: RunVersions,
        deadline_for: timedelta,
    ) -> RunDetail:
        subject = subject.strip()
        idempotency_key = idempotency_key.strip()
        request_digest = request_digest.strip()
        question = question.strip()
        source = source.strip()
        if not all((subject, idempotency_key, request_digest, question, source)):
            raise ValueError("A public run submission requires complete identifiers and search input.")
        if deadline_for <= timedelta(0):
            raise ValueError("A run deadline must be positive.")
        now_value = _utc(self.clock())
        now = _timestamp(now_value)
        deadline_at = _timestamp(now_value + deadline_for)
        try:
            with self._transaction() as connection:
                prior = connection.execute(
                    text(
                        """
                        SELECT request_digest, run_id FROM run_submissions
                        WHERE subject = :subject AND idempotency_key = :idempotency_key
                        """
                    ),
                    {"subject": subject, "idempotency_key": idempotency_key},
                ).mappings().one_or_none()
                if prior is not None:
                    if prior["request_digest"] != request_digest:
                        raise IdempotencyConflict("The idempotency key belongs to another request.")
                    run_id = prior["run_id"]
                else:
                    active = self._active_run_for_subject(connection, subject)
                    if active is not None:
                        raise ActiveRunExists(active)
                    run_id = self._insert_run(
                        connection,
                        question=question,
                        source=source,
                        config_snapshot=config_snapshot,
                        versions=versions,
                        owner_subject=subject,
                        now=now,
                        deadline_at=deadline_at,
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO run_submissions (
                                subject, idempotency_key, request_digest, run_id, created_at
                            ) VALUES (
                                :subject, :idempotency_key, :request_digest, :run_id, :created_at
                            )
                            """
                        ),
                        {
                            "subject": subject,
                            "idempotency_key": idempotency_key,
                            "request_digest": request_digest,
                            "run_id": run_id,
                            "created_at": now,
                        },
                    )
        except RunPersistenceError:
            with self.engine.connect() as connection:
                prior = connection.execute(
                    text(
                        """
                        SELECT request_digest, run_id FROM run_submissions
                        WHERE subject = :subject AND idempotency_key = :idempotency_key
                        """
                    ),
                    {"subject": subject, "idempotency_key": idempotency_key},
                ).mappings().one_or_none()
                if prior is not None:
                    if prior["request_digest"] != request_digest:
                        raise IdempotencyConflict("The idempotency key belongs to another request.")
                    return self.get_run(prior["run_id"])
                active = self._active_run_for_subject(connection, subject)
                if active is not None:
                    raise ActiveRunExists(active)
            raise
        return self.get_run(run_id)

    @staticmethod
    def _active_run_for_subject(connection: Connection, subject: str) -> str | None:
        row = connection.execute(
            text(
                """
                SELECT id FROM runs
                WHERE owner_subject = :subject
                  AND deleted_at IS NULL
                  AND status IN ('queued', 'running', 'cancelling')
                ORDER BY created_at, id
                LIMIT 1
                """
            ),
            {"subject": subject},
        ).mappings().one_or_none()
        return row["id"] if row is not None else None

    @classmethod
    def _insert_run(
        cls,
        connection: Connection,
        *,
        question: str,
        source: str,
        config_snapshot: dict,
        versions: RunVersions,
        owner_subject: str | None,
        now: str,
        deadline_at: str,
    ) -> str:
        run_id = str(uuid4())
        connection.execute(
            text(
                """
                INSERT INTO runs (
                    id, owner_subject, question, source, status, config_json, current_step,
                    attempt, lease_generation, last_event_sequence,
                    workflow_version, engine_version, prompt_version,
                    config_schema_version, artifact_schema_version,
                    error_code, warning_codes_json, created_at, deadline_at, updated_at
                ) VALUES (
                    :id, :owner_subject, :question, :source, :status, :config_json, '',
                    0, 0, 1,
                    :workflow_version, :engine_version, :prompt_version,
                    :config_schema_version, :artifact_schema_version,
                    '', '[]', :now, :deadline_at, :now
                )
                """
            ),
            {
                "id": run_id,
                "owner_subject": owner_subject,
                "question": question,
                "source": source,
                "status": RunStatus.QUEUED.value,
                "config_json": _json_dump(config_snapshot),
                "workflow_version": versions.workflow_version,
                "engine_version": versions.engine_version,
                "prompt_version": versions.prompt_version,
                "config_schema_version": versions.config_schema_version,
                "artifact_schema_version": versions.artifact_schema_version,
                "now": now,
                "deadline_at": deadline_at,
            },
        )
        cls._insert_events(
            connection,
            run_id,
            1,
            [PendingEvent(event_type="run.created", stage="lifecycle", payload={"source": source})],
            now,
        )
        return run_id

    def claim_run(self, run_id: str, owner_id: str, lease_for: timedelta) -> LeaseToken:
        owner_id = owner_id.strip()
        if not owner_id:
            raise ValueError("A lease owner is required.")
        now_value = _utc(self.clock())
        now = _timestamp(now_value)
        expires_at = _timestamp(now_value + lease_for)
        rejected_code = ""
        row = None
        with self._transaction() as connection:
            candidate = connection.execute(
                text(
                    """
                    SELECT status, attempt, lease_expires_at, deadline_at
                    FROM runs WHERE id = :run_id
                    """
                ),
                {"run_id": run_id},
            ).mappings().one_or_none()
            if candidate is None:
                raise RunNotFound(f"Run {run_id} was not found.")
            if candidate["status"] in TERMINAL_STATUSES:
                raise RunStateError(f"Terminal run {run_id} cannot be claimed.")
            reclaim = (
                candidate["status"] == RunStatus.RUNNING.value
                and candidate["lease_expires_at"]
                and candidate["lease_expires_at"] <= now
            )
            if candidate["deadline_at"] <= now:
                rejected_code = "run_deadline_exceeded"
            elif reclaim and int(candidate["attempt"]) >= MAX_ATTEMPTS:
                rejected_code = "executor_recovery_exhausted"
            elif candidate["status"] != RunStatus.QUEUED.value and not reclaim:
                raise RunOwnershipLost(f"Run {run_id} already has a current lease.")

            if rejected_code:
                self._fail_unclaimable_run(connection, run_id, rejected_code, now)
            else:
                row = self._claim_candidate(
                    connection,
                    run_id,
                    owner_id,
                    expires_at,
                    now,
                )
        if rejected_code:
            raise RunStateError(f"Run {run_id} cannot be claimed: {rejected_code}.")
        assert row is not None
        return LeaseToken(
            run_id=run_id,
            owner_id=owner_id,
            lease_generation=int(row["lease_generation"]),
            expires_at=_datetime(row["lease_expires_at"]),
        )

    def claim_next_run(self, owner_id: str, lease_for: timedelta) -> LeaseToken | None:
        owner_id = owner_id.strip()
        if not owner_id:
            raise ValueError("A lease owner is required.")
        now_value = _utc(self.clock())
        now = _timestamp(now_value)
        expires_at = _timestamp(now_value + lease_for)
        row = None
        with self._transaction() as connection:
            while True:
                candidate = connection.execute(
                    text(
                        """
                        SELECT id, status, attempt, deadline_at
                        FROM runs
                        WHERE status = :queued
                           OR (status = :running AND lease_expires_at <= :now)
                        ORDER BY created_at, id
                        LIMIT 1
                        """
                    ),
                    {
                        "queued": RunStatus.QUEUED.value,
                        "running": RunStatus.RUNNING.value,
                        "now": now,
                    },
                ).mappings().one_or_none()
                if candidate is None:
                    break
                error_code = ""
                if candidate["deadline_at"] <= now:
                    error_code = "run_deadline_exceeded"
                elif (
                    candidate["status"] == RunStatus.RUNNING.value
                    and int(candidate["attempt"]) >= MAX_ATTEMPTS
                ):
                    error_code = "executor_recovery_exhausted"
                if error_code:
                    self._fail_unclaimable_run(
                        connection,
                        candidate["id"],
                        error_code,
                        now,
                    )
                    continue
                row = self._claim_candidate(
                    connection,
                    candidate["id"],
                    owner_id,
                    expires_at,
                    now,
                )
                break
        if row is None:
            return None
        return LeaseToken(
            run_id=row["id"],
            owner_id=owner_id,
            lease_generation=int(row["lease_generation"]),
            expires_at=_datetime(row["lease_expires_at"]),
        )

    def _claim_candidate(
        self,
        connection: Connection,
        run_id: str,
        owner_id: str,
        expires_at: str,
        now: str,
    ):
        row = connection.execute(
            text(
                """
                UPDATE runs
                SET status = :running,
                    attempt = attempt + 1,
                    lease_generation = lease_generation + 1,
                    lease_owner = :owner_id,
                    lease_expires_at = CASE
                        WHEN :expires_at < deadline_at THEN :expires_at
                        ELSE deadline_at
                    END,
                    started_at = COALESCE(started_at, :now),
                    updated_at = :now,
                    last_event_sequence = last_event_sequence + 1
                WHERE id = :run_id
                  AND deadline_at > :now
                  AND (
                    status = :queued
                    OR (status = :running AND lease_expires_at <= :now)
                  )
                RETURNING id, lease_generation, attempt,
                          last_event_sequence, lease_expires_at
                """
            ),
            {
                "running": RunStatus.RUNNING.value,
                "queued": RunStatus.QUEUED.value,
                "owner_id": owner_id,
                "expires_at": expires_at,
                "now": now,
                "run_id": run_id,
            },
        ).mappings().one_or_none()
        if row is None:
            self._raise_claim_rejected(connection, run_id)
        self._insert_events(
            connection,
            run_id,
            int(row["last_event_sequence"]),
            [
                PendingEvent(
                    event_type="run.claimed",
                    stage="lifecycle",
                    payload={
                        "attempt": int(row["attempt"]),
                        "lease_generation": int(row["lease_generation"]),
                    },
                )
            ],
            now,
        )
        return row

    def _fail_unclaimable_run(
        self,
        connection: Connection,
        run_id: str,
        error_code: str,
        now: str,
    ) -> None:
        row = connection.execute(
            text(
                """
                UPDATE runs
                SET status = :failed,
                    current_step = 'failed',
                    error_code = :error_code,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    finished_at = :now,
                    updated_at = :now,
                    last_event_sequence = last_event_sequence + 1
                WHERE id = :run_id
                  AND status IN (:queued, :running)
                RETURNING last_event_sequence
                """
            ),
            {
                "failed": RunStatus.FAILED.value,
                "queued": RunStatus.QUEUED.value,
                "running": RunStatus.RUNNING.value,
                "error_code": error_code,
                "now": now,
                "run_id": run_id,
            },
        ).mappings().one()
        self._insert_events(
            connection,
            run_id,
            int(row["last_event_sequence"]),
            [
                PendingEvent(
                    event_type="run.failed",
                    stage="lifecycle",
                    payload={"code": error_code},
                )
            ],
            now,
        )

    def renew_lease(self, lease: LeaseToken, lease_for: timedelta) -> LeaseToken:
        now_value = _utc(self.clock())
        now = _timestamp(now_value)
        expires_at = _timestamp(now_value + lease_for)
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    UPDATE runs
                    SET lease_expires_at = CASE
                            WHEN :expires_at < deadline_at THEN :expires_at
                            ELSE deadline_at
                        END,
                        updated_at = :now
                    WHERE id = :run_id
                      AND status = :running
                      AND lease_owner = :owner_id
                      AND lease_generation = :lease_generation
                      AND lease_expires_at > :now
                      AND deadline_at > :now
                    RETURNING lease_generation, lease_expires_at
                    """
                ),
                {
                    "expires_at": expires_at,
                    "now": now,
                    "run_id": lease.run_id,
                    "running": RunStatus.RUNNING.value,
                    "owner_id": lease.owner_id,
                    "lease_generation": lease.lease_generation,
                },
            ).mappings().one_or_none()
            if row is None:
                self._raise_write_rejected(connection, lease, now)
        return lease.model_copy(update={"expires_at": _datetime(row["lease_expires_at"])})

    def request_cancel(self, run_id: str) -> RunDetail:
        now = _timestamp(self.clock())
        with self._transaction() as connection:
            current = connection.execute(
                text("SELECT status FROM runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).scalar_one_or_none()
            if current is None:
                raise RunNotFound(f"Run {run_id} was not found.")
            status = RunStatus(current)
            if status in {RunStatus.CANCELLING, RunStatus.CANCELLED}:
                return self._get_run_in_transaction(connection, run_id)
            if status in {
                RunStatus.COMPLETED,
                RunStatus.COMPLETED_WITH_WARNINGS,
                RunStatus.FAILED,
            }:
                raise RunStateError(f"Terminal run {run_id} cannot be cancelled.")

            target = (
                RunStatus.CANCELLED
                if status is RunStatus.QUEUED
                else RunStatus.CANCELLING
            )
            validate_transition(status, target)
            finished_at = now if target is RunStatus.CANCELLED else None
            row = connection.execute(
                text(
                    """
                    UPDATE runs
                    SET status = :target,
                        current_step = :current_step,
                        cancel_requested_at = :now,
                        finished_at = COALESCE(:finished_at, finished_at),
                        lease_owner = CASE WHEN :target = :cancelled THEN NULL ELSE lease_owner END,
                        lease_expires_at = CASE WHEN :target = :cancelled THEN NULL ELSE lease_expires_at END,
                        updated_at = :now,
                        last_event_sequence = last_event_sequence + 1
                    WHERE id = :run_id AND status = :current
                    RETURNING last_event_sequence
                    """
                ),
                {
                    "target": target.value,
                    "current_step": target.value,
                    "now": now,
                    "finished_at": finished_at,
                    "cancelled": RunStatus.CANCELLED.value,
                    "run_id": run_id,
                    "current": status.value,
                },
            ).mappings().one_or_none()
            if row is None:
                raise RunOwnershipLost(f"Run {run_id} changed while cancellation was requested.")
            self._insert_events(
                connection,
                run_id,
                int(row["last_event_sequence"]),
                [
                    PendingEvent(
                        event_type=f"run.{target.value}",
                        stage="lifecycle",
                        payload={"requested_from": status.value},
                    )
                ],
                now,
            )
        return self.get_run(run_id)

    def complete_cancel(self, lease: LeaseToken) -> RunDetail:
        now = _timestamp(self.clock())
        with self._transaction() as connection:
            validate_transition(RunStatus.CANCELLING, RunStatus.CANCELLED)
            row = connection.execute(
                text(
                    """
                    UPDATE runs
                    SET status = :cancelled,
                        current_step = :cancelled,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        finished_at = :now,
                        updated_at = :now,
                        last_event_sequence = last_event_sequence + 1
                    WHERE id = :run_id
                      AND status = :cancelling
                      AND lease_owner = :owner_id
                      AND lease_generation = :lease_generation
                    RETURNING last_event_sequence
                    """
                ),
                {
                    "cancelled": RunStatus.CANCELLED.value,
                    "cancelling": RunStatus.CANCELLING.value,
                    "now": now,
                    "run_id": lease.run_id,
                    "owner_id": lease.owner_id,
                    "lease_generation": lease.lease_generation,
                },
            ).mappings().one_or_none()
            if row is None:
                self._raise_write_rejected(connection, lease, now)
            self._insert_events(
                connection,
                lease.run_id,
                int(row["last_event_sequence"]),
                [PendingEvent(event_type="run.cancelled", stage="lifecycle")],
                now,
            )
        return self.get_run(lease.run_id)

    def append_events_and_checkpoint(
        self,
        lease: LeaseToken,
        events: list[PendingEvent],
        checkpoint: CheckpointDraft | None,
        checkpoint_artifact: StoredArtifact | None,
    ) -> PersistedCheckpoint | None:
        if (checkpoint is None) != (checkpoint_artifact is None):
            raise RunPersistenceError(
                "A checkpoint and its recovery artifact must be committed together."
            )
        now = _timestamp(self.clock())
        persisted = None
        with self._transaction() as connection:
            end_sequence = self._reserve_sequences(connection, lease, len(events), now)
            start_sequence = end_sequence - len(events) + 1
            self._insert_events(connection, lease.run_id, start_sequence, events, now)
            if checkpoint is not None:
                run = connection.execute(
                    text(
                        """
                        SELECT attempt, lease_generation, workflow_version
                        FROM runs WHERE id = :run_id
                        """
                    ),
                    {"run_id": lease.run_id},
                ).mappings().one()
                if checkpoint.workflow_version != run["workflow_version"]:
                    raise RunStateError("Checkpoint workflow version is incompatible with the run.")
                existing = connection.execute(
                    text(
                        """
                        SELECT * FROM run_checkpoints
                        WHERE run_id = :run_id AND idempotency_key = :idempotency_key
                        """
                    ),
                    {
                        "run_id": lease.run_id,
                        "idempotency_key": checkpoint.idempotency_key,
                    },
                ).mappings().one_or_none()
                if existing is not None:
                    if (
                        existing["step_key"] != checkpoint.step_key
                        or existing["workflow_version"] != checkpoint.workflow_version
                        or int(existing["schema_version"]) != checkpoint.schema_version
                        or existing["state_artifact_id"] != checkpoint_artifact.id
                    ):
                        raise RunStateError("Checkpoint idempotency key has incompatible state.")
                    persisted = self._checkpoint(existing)
                else:
                    self._insert_artifacts(connection, lease.run_id, [checkpoint_artifact])
                    connection.execute(
                        text(
                            """
                            INSERT INTO run_checkpoints (
                                run_id, step_key, idempotency_key, event_sequence,
                                state_json, attempt, lease_generation,
                                workflow_version, schema_version, created_at,
                                state_artifact_id
                            ) VALUES (
                                :run_id, :step_key, :idempotency_key, :event_sequence,
                                :state_json, :attempt, :lease_generation,
                                :workflow_version, :schema_version, :created_at,
                                :state_artifact_id
                            )
                            """
                        ),
                        {
                            "run_id": lease.run_id,
                            "step_key": checkpoint.step_key,
                            "idempotency_key": checkpoint.idempotency_key,
                            "event_sequence": end_sequence,
                            "state_json": _json_dump({}),
                            "attempt": int(run["attempt"]),
                            "lease_generation": int(run["lease_generation"]),
                            "workflow_version": checkpoint.workflow_version,
                            "schema_version": checkpoint.schema_version,
                            "created_at": now,
                            "state_artifact_id": checkpoint_artifact.id,
                        },
                    )
                    persisted = PersistedCheckpoint(
                        run_id=lease.run_id,
                        step_key=checkpoint.step_key,
                        idempotency_key=checkpoint.idempotency_key,
                        event_sequence=end_sequence,
                        state={},
                        attempt=int(run["attempt"]),
                        lease_generation=int(run["lease_generation"]),
                        workflow_version=checkpoint.workflow_version,
                        schema_version=checkpoint.schema_version,
                        created_at=_datetime(now),
                        state_artifact_id=checkpoint_artifact.id,
                    )
                connection.execute(
                    text("UPDATE runs SET current_step = :step, updated_at = :now WHERE id = :run_id"),
                    {"step": checkpoint.step_key, "now": now, "run_id": lease.run_id},
                )
        return persisted

    def complete_run(
        self,
        lease: LeaseToken,
        events: list[PendingEvent],
        result: ResearchResult | None,
        artifacts: list[StoredArtifact],
    ) -> RunDetail:
        now = _timestamp(self.clock())
        result_count = len(result.ranked) if result is not None else 0
        warning_count = len(result.warnings) if result is not None else 0
        terminal_status = (
            RunStatus.COMPLETED_WITH_WARNINGS
            if warning_count
            else RunStatus.COMPLETED
        )
        terminal = PendingEvent(
            event_type=f"run.{terminal_status.value}",
            stage="lifecycle",
            payload={"result_count": result_count, "warning_count": warning_count},
        )
        all_events = [*events, terminal]
        with self._transaction() as connection:
            end_sequence = self._reserve_sequences(connection, lease, len(all_events), now)
            if result is None:
                raise RunPersistenceError("A completed run requires a final result.")
            final_artifacts = [
                item
                for item in artifacts
                if item.kind == "final_result"
                and item.role is ArtifactRole.COMPLETION_REQUIRED
            ]
            if len(final_artifacts) != 1:
                raise RunPersistenceError(
                    "A completed run requires one final-result artifact."
                )
            self._insert_artifacts(connection, lease.run_id, artifacts)
            final_artifact_id = final_artifacts[0].id
            validate_transition(RunStatus.RUNNING, terminal_status)
            self._insert_events(
                connection,
                lease.run_id,
                end_sequence - len(all_events) + 1,
                all_events,
                now,
            )
            connection.execute(text("DELETE FROM run_results WHERE run_id = :run_id"), {"run_id": lease.run_id})
            for rank, record in enumerate(result.ranked, 1):
                connection.execute(
                    text(
                        """
                        INSERT INTO run_results (
                            run_id, rank, record_json, record_artifact_id
                        ) VALUES (
                            :run_id, :rank, :record_json, :record_artifact_id
                        )
                        """
                    ),
                    {
                        "run_id": lease.run_id,
                        "rank": rank,
                        "record_json": _json_dump(record.model_dump(mode="json")),
                        "record_artifact_id": final_artifact_id,
                    },
                )
            updated = connection.execute(
                text(
                    """
                    UPDATE runs
                    SET status = :completed,
                        current_step = 'completed',
                        warning_codes_json = :warning_codes_json,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        finished_at = :now,
                        updated_at = :now
                    WHERE id = :run_id
                      AND status = :running
                      AND lease_owner = :owner_id
                      AND lease_generation = :lease_generation
                    """
                ),
                {
                    "completed": terminal_status.value,
                    "running": RunStatus.RUNNING.value,
                    "warning_codes_json": _json_dump(result.warnings),
                    "now": now,
                    "run_id": lease.run_id,
                    "owner_id": lease.owner_id,
                    "lease_generation": lease.lease_generation,
                },
            )
            if updated.rowcount != 1:
                raise RunOwnershipLost("The run lease was lost before completion.")
        return self.get_run(lease.run_id)

    def fail_run(
        self,
        lease: LeaseToken,
        events: list[PendingEvent],
        error_code: str,
    ) -> RunDetail:
        now = _timestamp(self.clock())
        terminal = PendingEvent(
            event_type="run.failed",
            stage="lifecycle",
            payload={"code": error_code},
        )
        all_events = [*events, terminal]
        with self._transaction() as connection:
            end_sequence = self._reserve_sequences(connection, lease, len(all_events), now)
            validate_transition(RunStatus.RUNNING, RunStatus.FAILED)
            self._insert_events(
                connection,
                lease.run_id,
                end_sequence - len(all_events) + 1,
                all_events,
                now,
            )
            updated = connection.execute(
                text(
                    """
                    UPDATE runs
                    SET status = :failed,
                        current_step = 'failed',
                        error_code = :error_code,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        finished_at = :now,
                        updated_at = :now
                    WHERE id = :run_id
                      AND status = :running
                      AND lease_owner = :owner_id
                      AND lease_generation = :lease_generation
                    """
                ),
                {
                    "failed": RunStatus.FAILED.value,
                    "running": RunStatus.RUNNING.value,
                    "error_code": error_code,
                    "now": now,
                    "run_id": lease.run_id,
                    "owner_id": lease.owner_id,
                    "lease_generation": lease.lease_generation,
                },
            )
            if updated.rowcount != 1:
                raise RunOwnershipLost("The run lease was lost before failure was committed.")
        return self.get_run(lease.run_id)

    def get_run(self, run_id: str) -> RunDetail:
        try:
            with self.engine.connect() as connection:
                row = connection.execute(
                    text(
                        """
                        SELECT r.*,
                               (SELECT COUNT(*) FROM run_results rr WHERE rr.run_id = r.id) AS result_count
                        FROM runs r
                        WHERE r.id = :run_id AND r.deleted_at IS NULL
                        """
                    ),
                    {"run_id": run_id},
                ).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise RunPersistenceError("The run could not be read.") from exc
        if row is None:
            raise RunNotFound(f"Run {run_id} was not found.")
        return self._run_detail(row)

    def _get_run_in_transaction(self, connection: Connection, run_id: str) -> RunDetail:
        row = connection.execute(
            text(
                """
                SELECT r.*,
                       (SELECT COUNT(*) FROM run_results rr WHERE rr.run_id = r.id) AS result_count
                FROM runs r WHERE r.id = :run_id
                """
            ),
            {"run_id": run_id},
        ).mappings().one()
        return self._run_detail(row)

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[PersistedEvent]:
        if after_sequence < 0 or (limit is not None and limit <= 0):
            raise ValueError("Event replay bounds are invalid.")
        statement = """
            SELECT e.*
            FROM run_events e
            JOIN runs r ON r.id = e.run_id
            WHERE e.run_id = :run_id
              AND e.sequence > :after_sequence
              AND r.deleted_at IS NULL
            ORDER BY e.sequence
        """
        parameters: dict[str, Any] = {
            "run_id": run_id,
            "after_sequence": after_sequence,
        }
        if limit is not None:
            statement += " LIMIT :limit"
            parameters["limit"] = limit
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(
                    text(statement),
                    parameters,
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise RunPersistenceError("Run events could not be read.") from exc
        return [
            PersistedEvent(
                run_id=row["run_id"],
                sequence=int(row["sequence"]),
                event_type=row["event_type"],
                stage=row["stage"],
                occurred_at=_datetime(row["occurred_at"]),
                schema_version=int(row["schema_version"]),
                payload=_json_load(row["payload_json"]),
            )
            for row in rows
        ]

    def get_checkpoint(self, run_id: str) -> PersistedCheckpoint | None:
        checkpoints = self.list_checkpoints(run_id)
        return checkpoints[-1] if checkpoints else None

    def list_checkpoints(self, run_id: str) -> list[PersistedCheckpoint]:
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(
                    text(
                        """
                        SELECT * FROM run_checkpoints
                        WHERE run_id = :run_id
                        ORDER BY event_sequence, id
                        """
                    ),
                    {"run_id": run_id},
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise RunPersistenceError("Run checkpoints could not be read.") from exc
        return [self._checkpoint(row) for row in rows]

    def get_results(
        self,
        run_id: str,
        *,
        after_rank: int = 0,
        limit: int | None = None,
    ) -> list[PersistedResult]:
        if after_rank < 0 or (limit is not None and limit <= 0):
            raise ValueError("Result page bounds are invalid.")
        statement = """
            SELECT rr.*
            FROM run_results rr
            JOIN runs r ON r.id = rr.run_id
            WHERE rr.run_id = :run_id
              AND rr.rank > :after_rank
              AND r.deleted_at IS NULL
            ORDER BY rr.rank
        """
        parameters: dict[str, Any] = {"run_id": run_id, "after_rank": after_rank}
        if limit is not None:
            statement += " LIMIT :limit"
            parameters["limit"] = limit
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(
                    text(statement),
                    parameters,
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise RunPersistenceError("Run results could not be read.") from exc
        return [
            PersistedResult(
                run_id=row["run_id"],
                rank=int(row["rank"]),
                record=FinalPaperResult.model_validate(_json_load(row["record_json"])),
                record_artifact_id=row["record_artifact_id"] or "",
            )
            for row in rows
        ]

    def list_history(
        self,
        *,
        before_created_at: datetime | None,
        before_id: str | None,
        limit: int,
    ) -> list[RunDetail]:
        if limit <= 0 or (before_created_at is None) != (before_id is None):
            raise ValueError("History page bounds are invalid.")
        cursor_clause = ""
        parameters: dict[str, Any] = {"limit": limit}
        if before_created_at is not None and before_id is not None:
            cursor_clause = """
                AND (
                    r.created_at < :before_created_at
                    OR (r.created_at = :before_created_at AND r.id < :before_id)
                )
            """
            parameters.update(
                {
                    "before_created_at": _timestamp(before_created_at),
                    "before_id": before_id,
                }
            )
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(
                    text(
                        f"""
                        SELECT r.*,
                               (SELECT COUNT(*) FROM run_results rr WHERE rr.run_id = r.id) AS result_count
                        FROM runs r
                        WHERE r.deleted_at IS NULL
                          AND r.status IN ('completed', 'completed_with_warnings', 'failed', 'cancelled')
                          {cursor_clause}
                        ORDER BY r.created_at DESC, r.id DESC
                        LIMIT :limit
                        """
                    ),
                    parameters,
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise RunPersistenceError("Run history could not be read.") from exc
        return [self._run_detail(row) for row in rows]

    def get_artifact(self, artifact_id: str) -> StoredArtifact:
        try:
            with self.engine.connect() as connection:
                row = connection.execute(
                    text(
                        """
                        SELECT a.*
                        FROM run_artifacts a
                        JOIN runs r ON r.id = a.run_id
                        WHERE a.id = :artifact_id AND r.deleted_at IS NULL
                        """
                    ),
                    {"artifact_id": artifact_id},
                ).mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise RunPersistenceError("The artifact metadata could not be read.") from exc
        if row is None:
            raise RunPersistenceError("The artifact metadata was not found.")
        return self._artifact(row)

    def list_artifacts(self, run_id: str) -> list[StoredArtifact]:
        try:
            with self.engine.connect() as connection:
                rows = connection.execute(
                    text(
                        """
                        SELECT a.*
                        FROM run_artifacts a
                        JOIN runs r ON r.id = a.run_id
                        WHERE a.run_id = :run_id AND r.deleted_at IS NULL
                        ORDER BY a.kind, a.schema_version, a.filename
                        """
                    ),
                    {"run_id": run_id},
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise RunPersistenceError("Run artifacts could not be read.") from exc
        return [self._artifact(row) for row in rows]

    def stage_run_deletion(self, run_id: str) -> DeletionReceipt:
        now = _timestamp(self.clock())
        with self._transaction() as connection:
            row = connection.execute(
                text("SELECT status, deleted_at FROM runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).mappings().one_or_none()
            if row is None:
                raise RunNotFound(f"Run {run_id} was not found.")
            if row["deleted_at"] is None and row["status"] not in TERMINAL_STATUSES:
                raise RunStateError("An active run cannot be deleted.")
            deleted_at = row["deleted_at"] or now
            if row["deleted_at"] is None:
                connection.execute(
                    text(
                        """
                        UPDATE runs
                        SET deleted_at = :deleted_at, updated_at = :deleted_at
                        WHERE id = :run_id AND deleted_at IS NULL
                        """
                    ),
                    {"run_id": run_id, "deleted_at": deleted_at},
                )
            connection.execute(
                text(
                    """
                    INSERT INTO run_cleanup_jobs (
                        run_id, status, attempt, lease_owner, lease_expires_at,
                        error_code, created_at, updated_at
                    ) VALUES (
                        :run_id, 'pending', 0, NULL, NULL, '', :now, :now
                    )
                    ON CONFLICT(run_id) DO NOTHING
                    """
                ),
                {"run_id": run_id, "now": now},
            )
        return DeletionReceipt(
            run_id=run_id,
            status="cleanup_pending",
            deleted_at=_datetime(deleted_at),
        )

    def claim_cleanup_job(
        self,
        owner_id: str,
        lease_for: timedelta,
    ) -> CleanupLease | None:
        owner_id = owner_id.strip()
        if not owner_id or lease_for <= timedelta(0):
            raise ValueError("Cleanup claims require an owner and positive lease.")
        now_value = _utc(self.clock())
        now = _timestamp(now_value)
        expires_at = _timestamp(now_value + lease_for)
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, run_id, attempt
                    FROM run_cleanup_jobs
                    WHERE attempt < :max_attempts
                      AND (
                          status IN ('pending', 'failed')
                          OR (status = 'running' AND lease_expires_at <= :now)
                      )
                    ORDER BY created_at, id
                    LIMIT 1
                    """
                ),
                {"max_attempts": MAX_CLEANUP_ATTEMPTS, "now": now},
            ).mappings().one_or_none()
            if row is None:
                return None
            attempt = int(row["attempt"]) + 1
            updated = connection.execute(
                text(
                    """
                    UPDATE run_cleanup_jobs
                    SET status = 'running',
                        attempt = :attempt,
                        lease_owner = :owner_id,
                        lease_expires_at = :expires_at,
                        error_code = '',
                        updated_at = :now
                    WHERE id = :job_id
                      AND attempt = :previous_attempt
                      AND (
                          status IN ('pending', 'failed')
                          OR (status = 'running' AND lease_expires_at <= :now)
                      )
                    """
                ),
                {
                    "attempt": attempt,
                    "owner_id": owner_id,
                    "expires_at": expires_at,
                    "now": now,
                    "job_id": int(row["id"]),
                    "previous_attempt": int(row["attempt"]),
                },
            )
            if updated.rowcount != 1:
                return None
        return CleanupLease(
            job_id=int(row["id"]),
            run_id=row["run_id"],
            owner_id=owner_id,
            attempt=attempt,
            expires_at=_datetime(expires_at),
        )

    def list_cleanup_artifacts(self, lease: CleanupLease) -> list[StoredArtifact]:
        now = _timestamp(self.clock())
        try:
            with self.engine.connect() as connection:
                current = connection.execute(
                    text(
                        """
                        SELECT id
                        FROM run_cleanup_jobs
                        WHERE id = :job_id
                          AND run_id = :run_id
                          AND status = 'running'
                          AND attempt = :attempt
                          AND lease_owner = :owner_id
                          AND lease_expires_at > :now
                        """
                    ),
                    {
                        "job_id": lease.job_id,
                        "run_id": lease.run_id,
                        "attempt": lease.attempt,
                        "owner_id": lease.owner_id,
                        "now": now,
                    },
                ).one_or_none()
                if current is None:
                    raise RunOwnershipLost("The cleanup lease was lost.")
                rows = connection.execute(
                    text(
                        """
                        SELECT * FROM run_artifacts
                        WHERE run_id = :run_id
                        ORDER BY kind, schema_version, filename
                        """
                    ),
                    {"run_id": lease.run_id},
                ).mappings().all()
        except RunError:
            raise
        except SQLAlchemyError as exc:
            raise RunPersistenceError("Cleanup artifacts could not be read.") from exc
        return [self._artifact(row) for row in rows]

    def complete_cleanup(self, lease: CleanupLease) -> None:
        now = _timestamp(self.clock())
        with self._transaction() as connection:
            current = connection.execute(
                text(
                    """
                    SELECT id
                    FROM run_cleanup_jobs
                    WHERE id = :job_id
                      AND run_id = :run_id
                      AND status = 'running'
                      AND attempt = :attempt
                      AND lease_owner = :owner_id
                      AND lease_expires_at > :now
                    """
                ),
                {
                    "job_id": lease.job_id,
                    "run_id": lease.run_id,
                    "attempt": lease.attempt,
                    "owner_id": lease.owner_id,
                    "now": now,
                },
            ).one_or_none()
            if current is None:
                raise RunOwnershipLost("The cleanup lease was lost before completion.")
            deleted = connection.execute(
                text("DELETE FROM runs WHERE id = :run_id AND deleted_at IS NOT NULL"),
                {"run_id": lease.run_id},
            )
            if deleted.rowcount != 1:
                raise RunOwnershipLost("The deleted run could not be finalized.")

    def fail_cleanup(self, lease: CleanupLease, error_code: str) -> None:
        now = _timestamp(self.clock())
        with self._transaction() as connection:
            updated = connection.execute(
                text(
                    """
                    UPDATE run_cleanup_jobs
                    SET status = 'failed',
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        error_code = :error_code,
                        updated_at = :now
                    WHERE id = :job_id
                      AND run_id = :run_id
                      AND status = 'running'
                      AND attempt = :attempt
                      AND lease_owner = :owner_id
                    """
                ),
                {
                    "error_code": error_code,
                    "now": now,
                    "job_id": lease.job_id,
                    "run_id": lease.run_id,
                    "attempt": lease.attempt,
                    "owner_id": lease.owner_id,
                },
            )
            if updated.rowcount != 1:
                raise RunOwnershipLost("The cleanup lease was lost before failure was recorded.")

    def _reserve_sequences(
        self,
        connection: Connection,
        lease: LeaseToken,
        count: int,
        now: str,
    ) -> int:
        row = connection.execute(
            text(
                """
                UPDATE runs
                SET last_event_sequence = last_event_sequence + :count,
                    updated_at = :now
                WHERE id = :run_id
                  AND status = :running
                  AND lease_owner = :owner_id
                  AND lease_generation = :lease_generation
                  AND lease_expires_at > :now
                RETURNING last_event_sequence
                """
            ),
            {
                "count": count,
                "now": now,
                "run_id": lease.run_id,
                "running": RunStatus.RUNNING.value,
                "owner_id": lease.owner_id,
                "lease_generation": lease.lease_generation,
            },
        ).mappings().one_or_none()
        if row is None:
            self._raise_write_rejected(connection, lease, now)
        return int(row["last_event_sequence"])

    @staticmethod
    def _insert_events(
        connection: Connection,
        run_id: str,
        start_sequence: int,
        events: list[PendingEvent],
        occurred_at: str,
    ) -> None:
        for offset, item in enumerate(events):
            connection.execute(
                text(
                    """
                    INSERT INTO run_events (
                        run_id, sequence, event_type, stage,
                        occurred_at, schema_version, payload_json
                    ) VALUES (
                        :run_id, :sequence, :event_type, :stage,
                        :occurred_at, :schema_version, :payload_json
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "sequence": start_sequence + offset,
                    "event_type": item.event_type,
                    "stage": item.stage,
                    "occurred_at": occurred_at,
                    "schema_version": item.schema_version,
                    "payload_json": _json_dump(item.payload),
                },
            )

    @staticmethod
    def _insert_artifacts(
        connection: Connection,
        run_id: str,
        artifacts: list[StoredArtifact],
    ) -> None:
        for artifact in artifacts:
            if artifact.run_id != run_id:
                raise RunPersistenceError("An artifact belongs to a different run.")
            connection.execute(
                text(
                    """
                    INSERT INTO run_artifacts (
                        id, run_id, kind, role, visibility, filename,
                        media_type, storage_key, sha256, size,
                        schema_version, created_at
                    ) VALUES (
                        :id, :run_id, :kind, :role, :visibility, :filename,
                        :media_type, :storage_key, :sha256, :size,
                        :schema_version, :created_at
                    )
                    """
                ),
                {
                    "id": artifact.id,
                    "run_id": artifact.run_id,
                    "kind": artifact.kind,
                    "role": artifact.role.value,
                    "visibility": artifact.visibility.value,
                    "filename": artifact.filename,
                    "media_type": artifact.media_type,
                    "storage_key": artifact.storage_key,
                    "sha256": artifact.sha256,
                    "size": artifact.size,
                    "schema_version": artifact.schema_version,
                    "created_at": _timestamp(artifact.created_at),
                },
            )

    @staticmethod
    def _raise_claim_rejected(connection: Connection, run_id: str) -> None:
        row = connection.execute(
            text("SELECT status FROM runs WHERE id = :run_id"),
            {"run_id": run_id},
        ).mappings().one_or_none()
        if row is None:
            raise RunNotFound(f"Run {run_id} was not found.")
        if row["status"] in TERMINAL_STATUSES:
            raise RunStateError(f"Terminal run {run_id} cannot be claimed.")
        raise RunOwnershipLost(f"Run {run_id} already has a current lease.")

    @staticmethod
    def _raise_write_rejected(connection: Connection, lease: LeaseToken, now: str) -> None:
        row = connection.execute(
            text(
                """
                SELECT status, lease_owner, lease_generation, lease_expires_at
                FROM runs WHERE id = :run_id
                """
            ),
            {"run_id": lease.run_id},
        ).mappings().one_or_none()
        if row is None:
            raise RunNotFound(f"Run {lease.run_id} was not found.")
        if row["status"] in TERMINAL_STATUSES:
            raise RunStateError(f"Terminal run {lease.run_id} cannot accept durable writes.")
        if (
            row["lease_owner"] != lease.owner_id
            or int(row["lease_generation"]) != lease.lease_generation
            or not row["lease_expires_at"]
            or row["lease_expires_at"] <= now
        ):
            raise RunOwnershipLost(f"Run {lease.run_id} lease ownership was lost.")
        raise RunOwnershipLost(f"Run {lease.run_id} rejected the durable write.")

    @staticmethod
    def _run_detail(row) -> RunDetail:
        return RunDetail(
            id=row["id"],
            question=row["question"],
            source=row["source"],
            status=RunStatus(row["status"]),
            config_snapshot=_json_load(row["config_json"]),
            current_step=row["current_step"],
            attempt=int(row["attempt"]),
            lease_generation=int(row["lease_generation"]),
            lease_owner=row["lease_owner"] or "",
            lease_expires_at=_datetime(row["lease_expires_at"]),
            last_event_sequence=int(row["last_event_sequence"]),
            error_code=row["error_code"],
            warnings=list(_json_load(row["warning_codes_json"])),
            created_at=_datetime(row["created_at"]),
            deadline_at=_datetime(row["deadline_at"]),
            started_at=_datetime(row["started_at"]),
            cancel_requested_at=_datetime(row["cancel_requested_at"]),
            finished_at=_datetime(row["finished_at"]),
            updated_at=_datetime(row["updated_at"]),
            result_count=int(row["result_count"]),
            versions=RunVersions(
                workflow_version=row["workflow_version"],
                engine_version=row["engine_version"],
                prompt_version=row["prompt_version"],
                config_schema_version=int(row["config_schema_version"]),
                artifact_schema_version=int(row["artifact_schema_version"]),
            ),
        )

    @staticmethod
    def _checkpoint(row) -> PersistedCheckpoint:
        return PersistedCheckpoint(
            run_id=row["run_id"],
            step_key=row["step_key"],
            idempotency_key=row["idempotency_key"],
            event_sequence=int(row["event_sequence"]),
            state=_json_load(row["state_json"]),
            attempt=int(row["attempt"]),
            lease_generation=int(row["lease_generation"]),
            workflow_version=row["workflow_version"],
            schema_version=int(row["schema_version"]),
            created_at=_datetime(row["created_at"]),
            state_artifact_id=row["state_artifact_id"] or "",
        )

    @staticmethod
    def _artifact(row) -> StoredArtifact:
        return StoredArtifact(
            id=row["id"],
            run_id=row["run_id"],
            kind=row["kind"],
            role=row["role"],
            visibility=row["visibility"],
            filename=row["filename"],
            media_type=row["media_type"],
            storage_key=row["storage_key"],
            sha256=row["sha256"],
            size=int(row["size"]),
            schema_version=int(row["schema_version"]),
            created_at=_datetime(row["created_at"]),
        )
