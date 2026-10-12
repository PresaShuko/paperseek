"""SQLite ownership of analysis metadata; large inputs/results live in files."""

from sqlalchemy import text

from paperseek_app.bibliometrics.models import (
    AnalysisError,
    AnalysisPage,
    AnalysisRecord,
    AnalysisSummary,
)
from paperseek_app.models import StoredArtifact
from paperseek_community.persistence.sqlite_base import SQLiteRepositoryBase


class SQLiteAnalysisStore(SQLiteRepositoryBase):
    @staticmethod
    def _record(row):
        if row is None or row["record_json"] == "{}":
            raise AnalysisError("analysis_not_found", 404)
        return AnalysisRecord.model_validate_json(row["record_json"]).model_copy(
            update={"title": row["title"]}
        )

    def find_analysis(self, key: str):
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT * FROM bibliometric_analyses WHERE idempotency_key=:key"
                    ),
                    {"key": key},
                )
                .mappings()
                .one_or_none()
            )
            if row is not None and row["deleted_at"]:
                raise AnalysisError("analysis_idempotency_conflict")
            return self._record(row) if row else None

    def create_analysis(self, record: AnalysisRecord, key: str):
        with self._transaction() as connection:
            connection.execute(
                text("""INSERT INTO bibliometric_analyses
                (id,source_run_id,title,paper_count,scope,created_at,record_json,idempotency_key)
                VALUES (:id,:source,:title,:count,:scope,:created,:record,:key)
                ON CONFLICT(idempotency_key) DO NOTHING"""),
                {
                    "id": record.id,
                    "source": record.source_run_id,
                    "title": record.title,
                    "count": record.paper_count,
                    "scope": record.scope,
                    "created": record.created_at.isoformat(),
                    "record": record.model_dump_json(),
                    "key": key,
                },
            )
        return self.find_analysis(key)

    def get_analysis(self, identity: str):
        with self.engine.connect() as connection:
            return self._record(
                connection.execute(
                    text(
                        "SELECT * FROM bibliometric_analyses WHERE id=:id AND deleted_at IS NULL"
                    ),
                    {"id": identity},
                )
                .mappings()
                .one_or_none()
            )

    def list_analyses(self, query: str, offset: int, limit: int):
        where = "deleted_at IS NULL AND instr(paperseek_casefold(title),:query)>0"
        params = {"query": query.strip().casefold(), "offset": offset, "limit": limit}
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            total = connection.execute(
                text(f"SELECT count(*) FROM bibliometric_analyses WHERE {where}"),
                params,
            ).scalar_one()
            rows = (
                connection.execute(
                    text(
                        f"SELECT id,source_run_id,title,paper_count,scope,created_at FROM bibliometric_analyses WHERE {where} ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        return AnalysisPage(
            items=[AnalysisSummary.model_validate(dict(row)) for row in rows],
            total_count=total,
            next_offset=offset + limit if offset + limit < total else None,
        )

    def rename_analysis(self, identity: str, title: str):
        with self._transaction() as connection:
            if not connection.execute(
                text(
                    "UPDATE bibliometric_analyses SET title=:title WHERE id=:id AND deleted_at IS NULL"
                ),
                {"id": identity, "title": title},
            ).rowcount:
                raise AnalysisError("analysis_not_found", 404)

    def cache_network(self, identity: str, key: str, artifact: StoredArtifact):
        with self._transaction() as connection:
            connection.execute(
                text("UPDATE bibliometric_analyses SET id=id WHERE id=:id"),
                {"id": identity},
            )
            record = self._record(
                connection.execute(
                    text(
                        "SELECT * FROM bibliometric_analyses WHERE id=:id AND deleted_at IS NULL"
                    ),
                    {"id": identity},
                )
                .mappings()
                .one_or_none()
            )
            if key in record.networks:
                return record.networks[key]
            if key not in record.networks and len(record.networks) >= 20:
                raise AnalysisError("analysis_network_cache_full", 422)
            updated = record.model_copy(
                update={"networks": {**record.networks, key: artifact}}
            )
            connection.execute(
                text(
                    "UPDATE bibliometric_analyses SET record_json=:record WHERE id=:id"
                ),
                {"id": identity, "record": updated.model_dump_json()},
            )
        return artifact

    def mark_analysis_deleted(self, identity: str):
        with self._transaction() as connection:
            row = (
                connection.execute(
                    text(
                        "UPDATE bibliometric_analyses SET deleted_at=coalesce(deleted_at,:now) WHERE id=:id RETURNING *"
                    ),
                    {"id": identity, "now": self.clock().isoformat()},
                )
                .mappings()
                .one_or_none()
            )
            return self._record(row)

    def pending_analysis_deletions(self):
        with self.engine.connect() as connection:
            return [
                self._record(row)
                for row in connection.execute(
                    text(
                        "SELECT * FROM bibliometric_analyses WHERE deleted_at IS NOT NULL AND record_json <> '{}' LIMIT 100"
                    )
                ).mappings()
            ]

    def purge_analysis(self, identity: str):
        with self._transaction() as connection:
            # Keep only a small idempotency tombstone so a delayed create retry
            # cannot recreate an analysis that the user already deleted.
            connection.execute(
                text("""UPDATE bibliometric_analyses SET record_json='{}', title='',
                source_run_id='', paper_count=0, scope='' WHERE id=:id AND deleted_at IS NOT NULL"""),
                {"id": identity},
            )
