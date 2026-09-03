from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from paperseek_app.errors import RunError, RunNotFound, RunPersistenceError, RunStateError
from paperseek_app.models import (
    ArtifactRole,
    LeaseToken,
    PendingEvent,
    PersistedResult,
    RunDetail,
    RunStatus,
    RunVersions,
    StoredArtifact,
)
from paperseek_app.state import validate_transition
from paperseek_community.persistence.sqlite_support import (
    TERMINAL_STATUSES,
    json_dump as _json_dump,
    json_load as _json_load,
    parse_datetime as _datetime,
    timestamp as _timestamp,
)
from paperseek_core.models import FinalPaperResult, ResearchResult


class SQLiteResultHistoryRepository:
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



__all__ = ["SQLiteResultHistoryRepository"]
