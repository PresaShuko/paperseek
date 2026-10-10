from __future__ import annotations

from contextlib import closing, redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from paperseek_app.services import RunQueryService, RunSubmissionService
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.cli import main as cli_main
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_community.persistence.legacy_v0_2 import (
    V02MigrationError,
    migrate_v0_2_database,
)


COMMUNITY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_SQL = COMMUNITY_ROOT / "tests" / "fixtures" / "migration" / "community_v0_2_1_history.sql"


def _materialize_fixture(directory: Path, text: str | None = None) -> Path:
    source = directory / "paperseek-v0.2.1.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.executescript(text or FIXTURE_SQL.read_text(encoding="utf-8"))
    return source


def _table_count(database: Path, table: str) -> int:
    with closing(sqlite3.connect(database)) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


class V02SQLiteMigrationContract(unittest.TestCase):
    def test_real_fixture_migrates_to_current_read_models_and_artifacts(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = _materialize_fixture(root)
            source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target = root / "v03" / "paperseek.db"
            backup = root / "backup" / "paperseek-v0.2.1.db"

            report = migrate_v0_2_database(source, target, backup)

            self.assertEqual(report["status"], "migrated")
            self.assertEqual(report["schema_version"], 11)
            self.assertEqual(report["runs_migrated"], 3)
            self.assertEqual(report["results_migrated"], 2)
            self.assertEqual(report["legacy_active_runs_closed"], 1)
            self.assertEqual(report["source_sha256"], hashlib.sha256(backup.read_bytes()).hexdigest())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_digest)
            self.assertEqual(_table_count(target, "legacy_migration_batches"), 1)
            self.assertEqual(_table_count(target, "legacy_migration_runs"), 3)
            with closing(sqlite3.connect(backup)) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

            with closing(sqlite3.connect(target)) as connection:
                rows = connection.execute(
                    "SELECT id, legacy_run_id, status, error_code FROM runs ORDER BY legacy_run_id"
                ).fetchall()
            by_legacy_id = {row[1]: row for row in rows}
            self.assertEqual(by_legacy_id["run_v02_fixture_success"][2:], ("completed", ""))
            self.assertEqual(by_legacy_id["run_v02_fixture_error"][2:], ("failed", "legacy_run_failed"))
            self.assertEqual(
                by_legacy_id["run_v02_fixture_running"][2:],
                ("failed", "legacy_active_run_not_resumable"),
            )

            uow = SQLiteRunUnitOfWork(target)
            service = RunQueryService(uow, FileArtifactStore(target.parent))
            try:
                history = service.get_history_page(page_size=50)
                self.assertEqual(len(history.items), 3)
                success_id = by_legacy_id["run_v02_fixture_success"][0]
                success = service.get_run(success_id)
                self.assertEqual(success.source, "openalex")
                self.assertEqual(success.result_count, 2)
                self.assertEqual(success.created_at.isoformat(), "2026-07-03T09:00:00+08:00")
                self.assertEqual(success.finished_at.isoformat(), "2026-07-03T09:01:30+08:00")
                self.assertTrue(success.config_snapshot["citation_enabled"])
                self.assertEqual(success.config_snapshot["field_ids"], [])
                self.assertEqual(success.config_snapshot["legacy_schema"], "v0.2")

                results = service.get_result_page(success_id, page_size=50).results
                self.assertEqual([item.record.uid for item in results], ["W-FIXTURE-1001", "W-FIXTURE-1002"])
                self.assertEqual(results[0].record.relevance_score, 9.0)
                citation = json.loads(service.get_citation_map(success_id).content)
                self.assertEqual(citation["edges"][0]["type"], "references")
                export = json.loads(service.get_export(success_id, "json").content)
                self.assertEqual(export["history"][0]["action"], "accept")
                self.assertEqual(len(export["ranked"]), 2)
                csv_text = service.get_export(success_id, "csv").content.decode("utf-8")
                self.assertIn("Reproducible Metadata for Evidence Synthesis", csv_text)
            finally:
                uow.close()

    def test_same_snapshot_is_idempotent_and_id_conflicts_keep_legacy_id(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "v03" / "paperseek.db"
            migrate_database(target)
            uow = SQLiteRunUnitOfWork(target)
            try:
                existing_id = RunSubmissionService(uow).create_run(
                    "Existing v0.3 run",
                    "openalex",
                ).id
            finally:
                uow.close()

            fixture = FIXTURE_SQL.read_text(encoding="utf-8").replace(
                "run_v02_fixture_success",
                existing_id,
            )
            source = _materialize_fixture(root, fixture)
            backup = root / "backup.db"

            first = migrate_v0_2_database(source, target, backup)
            run_count = _table_count(target, "runs")
            second = migrate_v0_2_database(source, target, backup)

            self.assertEqual(first["status"], "migrated")
            self.assertEqual(second["status"], "already_migrated")
            self.assertEqual(second["batch_id"], first["batch_id"])
            self.assertEqual(_table_count(target, "runs"), run_count)
            with closing(sqlite3.connect(target)) as connection:
                mapped = connection.execute(
                    "SELECT id, legacy_run_id FROM runs WHERE legacy_run_id = ?",
                    (existing_id,),
                ).fetchone()
            self.assertIsNotNone(mapped)
            self.assertNotEqual(mapped[0], existing_id)
            self.assertEqual(mapped[1], existing_id)

    def test_corrupt_or_current_schema_source_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "target.db"
            corrupt = root / "corrupt.db"
            corrupt.write_bytes(b"not a sqlite database")

            with self.assertRaises(V02MigrationError) as raised:
                migrate_v0_2_database(corrupt, target, root / "corrupt-backup.db")
            self.assertEqual(raised.exception.code, "invalid_v0_2_database")
            self.assertFalse(target.exists())
            self.assertFalse((root / "corrupt-backup.db").exists())

            current = root / "current.db"
            migrate_database(current)
            current_digest = hashlib.sha256(current.read_bytes()).hexdigest()
            with self.assertRaises(V02MigrationError) as raised:
                migrate_v0_2_database(current, target, root / "current-backup.db")
            self.assertEqual(raised.exception.code, "unsupported_source_schema")
            self.assertEqual(hashlib.sha256(current.read_bytes()).hexdigest(), current_digest)
            self.assertFalse(target.exists())

    def test_backup_conflict_and_import_failure_leave_source_and_target_recoverable(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = _materialize_fixture(root)
            source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target = root / "v03" / "paperseek.db"
            migrate_database(target)
            initial_runs = _table_count(target, "runs")
            conflicting_backup = root / "backup.db"
            with closing(sqlite3.connect(conflicting_backup)) as connection:
                connection.execute("CREATE TABLE unrelated(value TEXT)")

            with self.assertRaises(V02MigrationError) as raised:
                migrate_v0_2_database(source, target, conflicting_backup)
            self.assertEqual(raised.exception.code, "backup_conflict")
            self.assertEqual(_table_count(target, "runs"), initial_runs)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_digest)

            valid_backup = root / "valid-backup.db"
            with patch(
                "paperseek_community.persistence.legacy_v0_2.FileArtifactStore.put",
                side_effect=OSError("synthetic artifact failure"),
            ):
                with self.assertRaises(V02MigrationError) as raised:
                    migrate_v0_2_database(source, target, valid_backup)
            self.assertEqual(raised.exception.code, "migration_failed")
            self.assertEqual(_table_count(target, "runs"), initial_runs)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_digest)
            self.assertTrue(valid_backup.exists())
            with closing(sqlite3.connect(valid_backup)) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_backup_creation_failure_does_not_create_or_mutate_the_target(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = _materialize_fixture(root)
            source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target = root / "v03" / "paperseek.db"
            backup = root / "backup" / "paperseek-v0.2.1.db"

            with patch(
                "paperseek_community.persistence.legacy_v0_2._sqlite_backup",
                side_effect=OSError("synthetic backup failure"),
            ):
                with self.assertRaises(V02MigrationError) as raised:
                    migrate_v0_2_database(source, target, backup)

            self.assertEqual(raised.exception.code, "backup_failed")
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_digest)
            self.assertFalse(target.exists())
            self.assertFalse(backup.exists())

    def test_in_place_migration_removes_old_tables_and_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            database = _materialize_fixture(root)
            backup = root / "paperseek-v0.2.1.db.v0.2.backup"

            first = migrate_v0_2_database(database, database, backup)
            second = migrate_v0_2_database(database, database, backup)

            self.assertEqual(first["status"], "migrated")
            self.assertEqual(second["status"], "already_migrated")
            self.assertEqual(second["batch_id"], first["batch_id"])
            with closing(sqlite3.connect(database)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 11)
            self.assertFalse({"search_runs", "search_events", "search_results"} & tables)
            self.assertEqual(_table_count(database, "runs"), 3)
            self.assertEqual(_table_count(database, "legacy_migration_batches"), 1)
            self.assertEqual(_table_count(backup, "search_runs"), 3)

    def test_unmappable_values_are_reported_without_dropping_readable_history(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = _materialize_fixture(root)
            with closing(sqlite3.connect(source)) as connection:
                connection.execute(
                    "UPDATE search_runs SET params_json = '{', history_json = '[', "
                    "citation_map_json = '{' WHERE id = 'run_v02_fixture_success'"
                )
                connection.execute(
                    "UPDATE search_results SET authors_json = '[', raw_json = '{' WHERE id = 2"
                )
                connection.commit()
            target = root / "v03" / "paperseek.db"

            report = migrate_v0_2_database(source, target, root / "backup.db")

            self.assertEqual(report["runs_migrated"], 3)
            self.assertEqual(report["runs_skipped"], 0)
            self.assertEqual(report["results_migrated"], 2)
            self.assertEqual(report["results_unmapped"], 0)
            self.assertEqual(report["result_values_unmapped"], 2)
            self.assertEqual(report["unmapped_values"], 5)
            with closing(sqlite3.connect(target)) as connection:
                status, warnings_json = connection.execute(
                    "SELECT status, warning_codes_json FROM runs "
                    "WHERE legacy_run_id = 'run_v02_fixture_success'"
                ).fetchone()
            self.assertEqual(status, "completed_with_warnings")
            self.assertEqual(
                json.loads(warnings_json),
                [
                    "legacy_config_unmapped",
                    "legacy_history_unmapped",
                    "legacy_citation_map_unmapped",
                    "legacy_results_partially_unmapped",
                ],
            )

    def test_installed_cli_shape_reports_migration_and_idempotent_replay(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = _materialize_fixture(root)
            target = root / "data" / "paperseek.db"
            backup = root / "paperseek-v0.2.1.backup.db"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(
                    [
                        "migrate",
                        "--database",
                        str(target),
                        "--from-v0.2",
                        str(source),
                        "--backup",
                        str(backup),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "migrated")
            self.assertEqual(payload["schema_version"], 11)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main(
                    [
                        "migrate",
                        "--database",
                        str(target),
                        "--from-v0.2",
                        str(source),
                        "--backup",
                        str(backup),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "already_migrated")

    def test_documented_cli_shape_uses_in_place_target_and_automatic_backup(self):
        with tempfile.TemporaryDirectory() as raw:
            database = _materialize_fixture(Path(raw))
            automatic_backup = database.with_name(f"{database.name}.v0.2.backup")

            outputs = []
            for _ in range(2):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = cli_main(["migrate", "--from-v0.2", str(database)])
                self.assertEqual(exit_code, 0)
                outputs.append(json.loads(stdout.getvalue()))

            self.assertEqual([item["status"] for item in outputs], ["migrated", "already_migrated"])
            self.assertTrue(automatic_backup.exists())
            self.assertEqual(_table_count(database, "runs"), 3)

    def test_cli_migration_failure_is_stable_json_and_nonzero(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "corrupt.db"
            source.write_bytes(b"not sqlite")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = cli_main(["migrate", "--from-v0.2", str(source)])

            payload = json.loads(stderr.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["error_code"], "invalid_v0_2_database")
            self.assertNotIn("not sqlite", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
