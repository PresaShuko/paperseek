from __future__ import annotations

from typing import Any

from paperseek_community.persistence.sqlite_base import SQLiteRepositoryBase

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from paperseek_app.errors import RunPersistenceError, RunStateError
from paperseek_app.models import LeaseToken, PendingEvent, PersistedCheckpoint, PersistedEvent, StoredArtifact
from paperseek_community.persistence.sqlite_support import (
    json_dump as _json_dump,
    json_load as _json_load,
    parse_datetime as _datetime,
    timestamp as _timestamp,
)
from paperseek_core.models import CheckpointDraft


class SQLiteEventCheckpointRepository(SQLiteRepositoryBase):
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
            if checkpoint is None and events:
                connection.execute(text("UPDATE runs SET current_step=:step WHERE id=:run_id"),
                                   {"step": events[-1].stage, "run_id": lease.run_id})
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


__all__ = ["SQLiteEventCheckpointRepository"]
