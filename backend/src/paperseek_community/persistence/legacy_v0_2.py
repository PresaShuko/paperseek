from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from paperseek_app.models import (
    ArtifactRole,
    ArtifactVisibility,
    ArtifactWrite,
    RunVersions,
)
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.persistence.migrate import migrate_database
from paperseek_core.final_result import FinalResultAssembler
from paperseek_core.models import FinalPaperResult, ResearchResult


_V0_2_COLUMNS = {
    "search_runs": (
        "id",
        "question",
        "source",
        "final_query",
        "db",
        "field",
        "total",
        "iterations",
        "status",
        "error_message",
        "params_json",
        "history_json",
        "citation_map_json",
        "created_at",
        "started_at",
        "finished_at",
    ),
    "search_events": (
        "id",
        "run_id",
        "event_type",
        "stage",
        "status",
        "message",
        "payload_json",
        "created_at",
    ),
    "search_results": (
        "id",
        "run_id",
        "rank",
        "paper_uid",
        "source",
        "title",
        "authors_json",
        "year",
        "venue",
        "doi",
        "url",
        "abstract",
        "citation_count",
        "relevance_score",
        "relevance_reason",
        "raw_json",
    ),
}


class V02MigrationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def migrate_v0_2_database(
    source_path: Path | str,
    target_path: Path | str,
    backup_path: Path | str,
) -> dict[str, Any]:
    source = Path(source_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    backup = Path(backup_path).expanduser().resolve()
    if backup in {source, target}:
        raise V02MigrationError("backup_conflict", "The backup path must be separate from both databases.")

    if source == target:
        prior = _existing_in_place_report(source, backup)
        if prior is not None:
            return prior
    _validate_v0_2_database(source)
    backup_sha256 = _create_consistent_backup(source, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=".paperseek-v0-2-", dir=target.parent))
    stage_database = stage_root / target.name
    moved_artifacts: list[Path] = []
    try:
        if target.exists():
            _sqlite_backup(target, stage_database)
        schema_version = migrate_database(stage_database)
        prior = _existing_report(stage_database, backup_sha256)
        if prior is not None:
            return {**prior, "status": "already_migrated", "schema_version": schema_version}

        report = _import_snapshot(
            backup,
            stage_database,
            FileArtifactStore(stage_root),
            backup_sha256,
            schema_version,
            drop_legacy_tables=source == target,
        )
        _validate_current_database(stage_database, schema_version)
        moved_artifacts = _promote_artifacts(stage_root, target.parent)
        os.replace(stage_database, target)
        return report
    except V02MigrationError:
        _remove_promoted_artifacts(moved_artifacts)
        raise
    except Exception as exc:
        _remove_promoted_artifacts(moved_artifacts)
        raise V02MigrationError(
            "migration_failed",
            "The v0.2 migration could not be committed.",
        ) from exc
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def _readonly_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _validate_v0_2_database(path: Path) -> None:
    if not path.is_file():
        raise V02MigrationError("invalid_v0_2_database", "The v0.2 database does not exist.")
    try:
        with closing(_readonly_connection(path)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise V02MigrationError("invalid_v0_2_database", "The v0.2 database is corrupt.")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise V02MigrationError("invalid_v0_2_database", "The v0.2 database has invalid references.")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if version != 0 or tables != set(_V0_2_COLUMNS):
                raise V02MigrationError(
                    "unsupported_source_schema",
                    "The source is not a supported PaperSeek v0.2 database.",
                )
            for table, expected in _V0_2_COLUMNS.items():
                columns = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
                if columns != expected:
                    raise V02MigrationError(
                        "unsupported_source_schema",
                        "The source is not a supported PaperSeek v0.2 database.",
                    )
    except V02MigrationError:
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        raise V02MigrationError(
            "invalid_v0_2_database",
            "The v0.2 database could not be read.",
        ) from exc


def _create_consistent_backup(source: Path, backup: Path) -> str:
    backup.parent.mkdir(parents=True, exist_ok=True)
    temporary = backup.with_name(f".{backup.name}.{uuid4().hex}.tmp")
    try:
        _sqlite_backup(source, temporary, readonly_source=True)
        _validate_v0_2_database(temporary)
        digest = _sha256(temporary)
        if backup.exists():
            try:
                _validate_v0_2_database(backup)
            except V02MigrationError as exc:
                raise V02MigrationError(
                    "backup_conflict",
                    "The backup path already contains different data.",
                ) from exc
            if _sha256(backup) != digest:
                raise V02MigrationError(
                    "backup_conflict",
                    "The backup path already contains a different v0.2 snapshot.",
                )
            return digest
        os.replace(temporary, backup)
        return digest
    except V02MigrationError:
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        raise V02MigrationError(
            "backup_failed",
            "A consistent v0.2 backup could not be created.",
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _sqlite_backup(source: Path, destination: Path, *, readonly_source: bool = False) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = _readonly_connection(source) if readonly_source else sqlite3.connect(source)
    try:
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)
    finally:
        source_connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_report(database: Path, source_sha256: str) -> dict[str, Any] | None:
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute(
            "SELECT report_json FROM legacy_migration_batches WHERE source_sha256 = ?",
            (source_sha256,),
        ).fetchone()
    return json.loads(row[0]) if row is not None else None


def _existing_in_place_report(database: Path, backup: Path) -> dict[str, Any] | None:
    if not database.is_file() or not backup.is_file():
        return None
    try:
        _validate_v0_2_database(backup)
        backup_sha256 = _sha256(backup)
        report = _existing_report(database, backup_sha256)
        if report is None:
            return None
        schema_version = int(report["schema_version"])
        _validate_current_database(database, schema_version)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, sqlite3.DatabaseError):
        return None
    return {**report, "status": "already_migrated", "schema_version": schema_version}


def _import_snapshot(
    source: Path,
    target: Path,
    artifact_store: FileArtifactStore,
    source_sha256: str,
    schema_version: int,
    *,
    drop_legacy_tables: bool,
) -> dict[str, Any]:
    batch_id = str(uuid5(NAMESPACE_URL, f"paperseek:v0.2:{source_sha256}"))
    migrated_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    versions = RunVersions()
    report: dict[str, Any] = {
        "status": "migrated",
        "batch_id": batch_id,
        "source_sha256": source_sha256,
        "backup_sha256": source_sha256,
        "schema_version": schema_version,
        "runs_found": 0,
        "runs_migrated": 0,
        "runs_skipped": 0,
        "results_migrated": 0,
        "results_unmapped": 0,
        "result_values_unmapped": 0,
        "legacy_active_runs_closed": 0,
        "run_id_conflicts": 0,
        "unmapped_values": 0,
    }
    with closing(_readonly_connection(source)) as legacy, closing(sqlite3.connect(target)) as current:
        legacy.row_factory = sqlite3.Row
        current.row_factory = sqlite3.Row
        current.execute("PRAGMA foreign_keys = ON")
        current.execute("BEGIN IMMEDIATE")
        try:
            current.execute(
                "INSERT INTO legacy_migration_batches "
                "(id, source_sha256, backup_sha256, report_json, created_at) "
                "VALUES (?, ?, ?, '{}', ?)",
                (batch_id, source_sha256, source_sha256, migrated_at),
            )
            legacy_runs = legacy.execute("SELECT * FROM search_runs ORDER BY created_at, id").fetchall()
            report["runs_found"] = len(legacy_runs)
            for legacy_run in legacy_runs:
                try:
                    migrated = _migrate_run(
                        legacy,
                        current,
                        artifact_store,
                        legacy_run,
                        batch_id,
                        source_sha256,
                        migrated_at,
                        versions,
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    report["runs_skipped"] += 1
                    report["unmapped_values"] += 1
                    continue
                report["runs_migrated"] += 1
                report["results_migrated"] += migrated["results_migrated"]
                report["results_unmapped"] += migrated["results_unmapped"]
                report["result_values_unmapped"] += migrated["result_values_unmapped"]
                report["unmapped_values"] += migrated["unmapped_values"]
                report["legacy_active_runs_closed"] += migrated["active_closed"]
                report["run_id_conflicts"] += migrated["id_conflict"]
            if drop_legacy_tables:
                current.execute("DROP TABLE search_events")
                current.execute("DROP TABLE search_results")
                current.execute("DROP TABLE search_runs")
            current.execute(
                "UPDATE legacy_migration_batches SET report_json = ? WHERE id = ?",
                (_json_dump(report), batch_id),
            )
            current.commit()
        except Exception:
            current.rollback()
            raise
    return report


def _migrate_run(
    legacy: sqlite3.Connection,
    current: sqlite3.Connection,
    artifact_store: FileArtifactStore,
    legacy_run: sqlite3.Row,
    batch_id: str,
    source_sha256: str,
    migrated_at: str,
    versions: RunVersions,
) -> dict[str, int]:
    legacy_id = str(legacy_run["id"] or "").strip()
    question = str(legacy_run["question"] or "").strip()
    if not legacy_id or not question:
        raise ValueError("A legacy run requires an ID and question.")
    run_id, id_conflict = _target_run_id(current, legacy_id, source_sha256)
    params, params_valid = _json_object(legacy_run["params_json"])
    history, history_valid = _json_list(legacy_run["history_json"])
    citation_map, citation_valid = _json_object(legacy_run["citation_map_json"])
    source = str(legacy_run["source"] or params.get("data_source") or "unknown").strip().lower()
    created_at = _timestamp(legacy_run["created_at"])
    started_at = _optional_timestamp(legacy_run["started_at"])
    finished_at = _optional_timestamp(legacy_run["finished_at"])
    legacy_status = str(legacy_run["status"] or "").strip().lower()
    warnings: list[str] = []
    unmapped_values = 0
    if not params_valid:
        warnings.append("legacy_config_unmapped")
        unmapped_values += 1
    if not history_valid:
        warnings.append("legacy_history_unmapped")
        unmapped_values += 1
    if not citation_valid:
        warnings.append("legacy_citation_map_unmapped")
        unmapped_values += 1

    if legacy_status == "success":
        status = "completed"
        error_code = ""
    elif legacy_status == "error":
        status = "failed"
        error_code = "legacy_run_failed"
    elif legacy_status == "running":
        status = "failed"
        error_code = "legacy_active_run_not_resumable"
        finished_at = migrated_at
    else:
        status = "failed"
        error_code = "legacy_status_unmapped"
        finished_at = finished_at or migrated_at
        unmapped_values += 1

    records, results_unmapped, result_values_unmapped = _mapped_results(legacy, legacy_id, source)
    if results_unmapped or result_values_unmapped:
        warnings.append("legacy_results_partially_unmapped")
        unmapped_values += results_unmapped + result_values_unmapped
    if legacy_status == "success" and warnings:
        status = "completed_with_warnings"
    if legacy_status == "success" and not records and int(legacy_run["total"] or 0) > 0:
        if "legacy_results_partially_unmapped" not in warnings:
            warnings.append("legacy_results_unmapped")
        status = "completed_with_warnings"
        unmapped_values += 1

    updated_at = finished_at or started_at or created_at
    config = _mapped_config(params, legacy_run)
    current.execute(
        """
        INSERT INTO runs (
            id, owner_subject, legacy_run_id, question, source, status, config_json,
            current_step, attempt, lease_generation, lease_owner, lease_expires_at,
            last_event_sequence, workflow_version, engine_version, prompt_version,
            config_schema_version, artifact_schema_version, error_code,
            warning_codes_json, created_at, deadline_at, started_at,
            cancel_requested_at, finished_at, updated_at, deleted_at
        ) VALUES (
            ?, NULL, ?, ?, ?, ?, ?, ?, 0, 0, NULL, NULL, 1, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, NULL, ?, ?, NULL
        )
        """,
        (
            run_id,
            legacy_id,
            question,
            source,
            status,
            _json_dump(config),
            status,
            versions.workflow_version,
            versions.engine_version,
            versions.prompt_version,
            versions.config_schema_version,
            versions.artifact_schema_version,
            error_code,
            _json_dump(warnings),
            created_at,
            updated_at,
            started_at,
            finished_at,
            updated_at,
        ),
    )
    event_payload = {
        "legacy_status": legacy_status,
        "result_count": len(records),
        "warnings": warnings,
    }
    current.execute(
        "INSERT INTO run_events "
        "(run_id, sequence, event_type, stage, occurred_at, schema_version, payload_json) "
        "VALUES (?, 1, 'legacy.migrated', 'lifecycle', ?, 1, ?)",
        (run_id, updated_at, _json_dump(event_payload)),
    )

    if legacy_status == "success":
        artifacts = _migrated_artifacts(
            artifact_store,
            run_id,
            question,
            source,
            legacy_run,
            history,
            citation_map,
            records,
            warnings,
            versions.artifact_schema_version,
        )
        for artifact in artifacts:
            current.execute(
                """
                INSERT INTO run_artifacts (
                    id, run_id, kind, role, visibility, filename, media_type,
                    storage_key, sha256, size, schema_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    run_id,
                    artifact.kind,
                    artifact.role.value,
                    artifact.visibility.value,
                    artifact.filename,
                    artifact.media_type,
                    artifact.storage_key,
                    artifact.sha256,
                    artifact.size,
                    artifact.schema_version,
                    artifact.created_at.isoformat(timespec="microseconds"),
                ),
            )
        final_artifact_id = next(item.id for item in artifacts if item.kind == "final_result")
        for record in records:
            current.execute(
                "INSERT INTO run_results (run_id, rank, record_json, record_artifact_id) "
                "VALUES (?, ?, ?, ?)",
                (run_id, record.rank, _json_dump(record.model_dump(mode="json")), final_artifact_id),
            )

    current.execute(
        "INSERT INTO legacy_migration_runs "
        "(batch_id, legacy_run_id, run_id, outcome, warnings_json) VALUES (?, ?, ?, ?, ?)",
        (batch_id, legacy_id, run_id, status, _json_dump(warnings)),
    )
    return {
        "results_migrated": len(records),
        "results_unmapped": results_unmapped,
        "result_values_unmapped": result_values_unmapped,
        "unmapped_values": unmapped_values,
        "active_closed": int(legacy_status == "running"),
        "id_conflict": id_conflict,
    }


def _target_run_id(
    connection: sqlite3.Connection,
    legacy_run_id: str,
    source_sha256: str,
) -> tuple[str, int]:
    candidate = ""
    try:
        parsed = UUID(legacy_run_id)
        if str(parsed) == legacy_run_id.lower():
            candidate = str(parsed)
    except ValueError:
        pass
    if candidate and connection.execute("SELECT 1 FROM runs WHERE id = ?", (candidate,)).fetchone() is None:
        return candidate, 0
    counter = 0
    while True:
        suffix = f":{counter}" if counter else ""
        mapped = str(
            uuid5(
                NAMESPACE_URL,
                f"paperseek:v0.2:{source_sha256}:{legacy_run_id}{suffix}",
            )
        )
        if connection.execute("SELECT 1 FROM runs WHERE id = ?", (mapped,)).fetchone() is None:
            return mapped, 1
        counter += 1


def _mapped_config(params: dict[str, Any], run: sqlite3.Row) -> dict[str, Any]:
    fields = params.get("discipline_fields")
    field_ids = [str(item).strip() for item in fields if str(item).strip()] if isinstance(fields, list) else []
    hint = str(params.get("search_field") or run["field"] or "").strip()
    return {
        "legacy_schema": "v0.2",
        "field_ids": field_ids,
        "field_hint": hint,
        "citation_enabled": bool(params.get("expand_citations", False)),
    }


def _mapped_results(
    connection: sqlite3.Connection,
    legacy_run_id: str,
    run_source: str,
) -> tuple[list[FinalPaperResult], int, int]:
    rows = connection.execute(
        "SELECT * FROM search_results WHERE run_id = ? ORDER BY rank, id",
        (legacy_run_id,),
    ).fetchall()
    records: list[FinalPaperResult] = []
    unmapped = 0
    values_unmapped = 0
    used_ranks: set[int] = set()
    for position, row in enumerate(rows, 1):
        try:
            raw, raw_valid = _json_object(row["raw_json"])
            if not raw_valid:
                values_unmapped += 1
            authors, authors_valid = _json_list(row["authors_json"])
            if not authors_valid:
                authors = raw.get("authors") if isinstance(raw.get("authors"), list) else []
                values_unmapped += 1
            rank = _positive_int(row["rank"], position)
            while rank in used_ranks:
                rank += 1
                values_unmapped += 1
            used_ranks.add(rank)
            author_names = [str(item).strip() for item in authors if str(item).strip()]
            keywords = raw.get("keywords") or raw.get("keywords_text") or ""
            if isinstance(keywords, list):
                keywords = "; ".join(str(item) for item in keywords if item)
            links = raw.get("links") if isinstance(raw.get("links"), dict) else {}
            year = _optional_int(row["year"] if row["year"] is not None else raw.get("year"))
            citations = _nonnegative_int(row["citation_count"], raw.get("citation_count"), 0)
            score = _float(row["relevance_score"], raw.get("relevance_score"), raw.get("score"), 0.0)
            uid = str(row["paper_uid"] or raw.get("uid") or raw.get("id") or "").strip()
            url = str(row["url"] or raw.get("url") or raw.get("id") or uid).strip()
            venue = str(row["venue"] or raw.get("venue") or raw.get("source") or "").strip()
            reason = str(row["relevance_reason"] or raw.get("relevance_reason") or raw.get("reasoning") or "")
            document_types = raw.get("document_types")
            if not isinstance(document_types, list):
                document_types = [raw.get("publication_type")] if raw.get("publication_type") else []
            records.append(
                FinalPaperResult(
                    rank=rank,
                    source=venue,
                    id=str(raw.get("id") or url),
                    title=str(row["title"] or raw.get("title") or ""),
                    authors=author_names,
                    year=year,
                    venue=venue,
                    publication_type=str(raw.get("publication_type") or ""),
                    doi=str(row["doi"] or raw.get("doi") or ""),
                    url=url,
                    pdf_url=str(raw.get("pdf_url") or links.get("pdf") or ""),
                    abstract=str(row["abstract"] or raw.get("abstract") or ""),
                    keywords=str(keywords),
                    citation_count=citations,
                    relevance_score=score,
                    relevance_reason=reason,
                    source_rank=_positive_int(raw.get("source_rank"), rank),
                    retrieval_score=_float(raw.get("retrieval_score"), 0.0),
                    retrieval_lanes=[str(item) for item in raw.get("retrieval_lanes", [])]
                    if isinstance(raw.get("retrieval_lanes"), list)
                    else [],
                    source_raw_id=str(raw.get("source_raw_id") or uid),
                    links=links,
                    keywords_text=str(keywords),
                    authors_text="; ".join(author_names),
                    score=score,
                    provider=str(raw.get("provider") or row["source"] or run_source),
                    uid=uid,
                    publish_year=year,
                    document_types=[str(item) for item in document_types if item],
                    citations=str(citations),
                    reasoning=reason,
                )
            )
        except (TypeError, ValueError):
            unmapped += 1
    return records, unmapped, values_unmapped


def _migrated_artifacts(
    store: FileArtifactStore,
    run_id: str,
    question: str,
    source: str,
    legacy_run: sqlite3.Row,
    history: list[Any],
    citation_map: dict[str, Any],
    records: list[FinalPaperResult],
    warnings: list[str],
    schema_version: int,
):
    result = ResearchResult(
        question=question,
        search_intent="",
        search_plan={},
        source=source,
        final_query=str(legacy_run["final_query"] or ""),
        db=str(legacy_run["db"] or source.upper()),
        field=str(legacy_run["field"] or ""),
        total=int(legacy_run["total"] or len(records)),
        iterations=int(legacy_run["iterations"] or 0),
        history=[item for item in history if isinstance(item, dict)],
        citation_map=citation_map,
        ranked=records,
        warnings=warnings,
    )
    drafts = FinalResultAssembler().artifacts_for(result)
    return [
        store.put(
            ArtifactWrite(
                run_id=run_id,
                kind=draft.kind,
                role=ArtifactRole.COMPLETION_REQUIRED,
                visibility=ArtifactVisibility.USER,
                filename=draft.filename,
                media_type=draft.media_type,
                schema_version=schema_version,
                content=draft.content.encode("utf-8"),
            )
        )
        for draft in drafts
    ]


def _promote_artifacts(stage_root: Path, target_root: Path) -> list[Path]:
    staged_runs = stage_root / "artifacts" / "runs"
    if not staged_runs.exists():
        return []
    destination_root = target_root / "artifacts" / "runs"
    destination_root.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    for staged in sorted(staged_runs.iterdir()):
        destination = destination_root / staged.name
        if destination.exists():
            if _tree_hashes(destination) != _tree_hashes(staged):
                raise V02MigrationError(
                    "migration_failed",
                    "A migrated artifact key already contains different content.",
                )
            shutil.rmtree(staged)
            continue
        os.replace(staged, destination)
        moved.append(destination)
    return moved


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _remove_promoted_artifacts(paths: list[Path]) -> None:
    for path in reversed(paths):
        shutil.rmtree(path, ignore_errors=True)


def _validate_current_database(path: Path, schema_version: int) -> None:
    with closing(sqlite3.connect(path)) as connection:
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) != schema_version:
            raise V02MigrationError("migration_failed", "The migrated schema version is invalid.")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise V02MigrationError("migration_failed", "The migrated database is corrupt.")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise V02MigrationError("migration_failed", "The migrated database has invalid references.")


def _timestamp(value: Any) -> str:
    text = str(value or "").strip()
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("Legacy timestamps must include an offset.")
    return parsed.isoformat(timespec="microseconds")


def _optional_timestamp(value: Any) -> str | None:
    return _timestamp(value) if value else None


def _json_object(value: Any) -> tuple[dict[str, Any], bool]:
    if not value:
        return {}, True
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}, False
    return (parsed, True) if isinstance(parsed, dict) else ({}, False)


def _json_list(value: Any) -> tuple[list[Any], bool]:
    if not value:
        return [], True
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return [], False
    return (parsed, True) if isinstance(parsed, list) else ([], False)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _nonnegative_int(*values: Any) -> int:
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return 0


def _float(*values: Any) -> float:
    for value in values:
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["V02MigrationError", "migrate_v0_2_database"]
