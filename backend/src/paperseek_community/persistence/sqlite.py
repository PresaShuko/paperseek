from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
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
from paperseek_community.persistence.sqlite_artifact_cleanup import SQLiteArtifactCleanupRepository
from paperseek_community.persistence.sqlite_event_checkpoint import SQLiteEventCheckpointRepository
from paperseek_community.persistence.sqlite_result_history import SQLiteResultHistoryRepository
from paperseek_community.persistence.sqlite_run_lease import SQLiteRunLeaseRepository
from paperseek_community.persistence.sqlite_support import (
    MAX_ATTEMPTS,
    MAX_CLEANUP_ATTEMPTS,
    TERMINAL_STATUSES,
    json_dump as _json_dump,
    json_load as _json_load,
    parse_datetime as _datetime,
    system_clock as _system_clock,
    timestamp as _timestamp,
    utc as _utc,
)
from paperseek_core.models import CheckpointDraft, FinalPaperResult, ResearchResult


class SQLiteRunUnitOfWork(
    SQLiteRunLeaseRepository,
    SQLiteEventCheckpointRepository,
    SQLiteResultHistoryRepository,
    SQLiteArtifactCleanupRepository,
):
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
