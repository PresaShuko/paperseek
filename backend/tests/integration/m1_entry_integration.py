from __future__ import annotations

from contextlib import closing, redirect_stdout
from fastapi.testclient import TestClient
import io
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from paperseek_community.api import create_app
from paperseek_community.cli import main as cli_main
from paperseek_app import build_info


FIXTURE = Path(__file__).parents[1] / "contract" / "fixtures" / "m1_fixed_source.json"


class M1EntryIntegrationTest(unittest.TestCase):
    def test_cli_migrate_applies_the_current_alembic_head_idempotently(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "paperseek.db"
            outputs = []
            for _ in range(2):
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = cli_main(["migrate", "--database", str(database)])
                outputs.append(json.loads(output.getvalue()))
            with closing(sqlite3.connect(database)) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                artifact_table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='run_artifacts'"
                ).fetchone()
                cleanup_table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='run_cleanup_jobs'"
                ).fetchone()

        self.assertEqual(exit_code, 0)
        self.assertEqual(outputs, [{"schema_version": 6, "status": "migrated"}] * 2)
        self.assertEqual(version, 5)
        self.assertEqual(artifact_table, ("run_artifacts",))
        self.assertEqual(cleanup_table, ("run_cleanup_jobs",))

    def test_cli_creates_fixed_run_and_rest_and_cli_read_the_same_result(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "paperseek.db"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = cli_main(
                    [
                        "search",
                        fixture["question"],
                        "--database",
                        str(database),
                        "--source-fixture",
                        str(FIXTURE),
                    ]
                )
            cli_payload = json.loads(output.getvalue())
            with TestClient(create_app(database)) as client:
                detail = client.get(f"/api/v1/runs/{cli_payload['run_id']}")
                events = client.get(f"/api/v1/runs/{cli_payload['run_id']}/events")
                results = client.get(f"/api/v1/runs/{cli_payload['run_id']}/results")

        self.assertEqual(exit_code, 0)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(events.status_code, 200)
        self.assertEqual(results.status_code, 200)
        self.assertEqual(detail.json()["status"], fixture["expected"]["status"])
        self.assertEqual(cli_payload["status"], detail.json()["status"])
        self.assertEqual(cli_payload["results"], results.json()["results"])
        event_payloads = [
            json.loads(line[6:])
            for line in events.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(
            [event["sequence"] for event in event_payloads],
            list(range(1, len(event_payloads) + 1)),
        )

    def test_m1_openapi_exposes_only_the_read_side_of_the_fixed_slice(self):
        with tempfile.TemporaryDirectory() as temp:
            schema = create_app(Path(temp) / "paperseek.db").openapi()
        self.assertIn("/api/v1/runs/{run_id}", schema["paths"])
        self.assertIn("/api/v1/runs/{run_id}/events", schema["paths"])
        self.assertIn("/api/v1/runs/{run_id}/results", schema["paths"])
        self.assertIn("/api/v1/runs/{run_id}/citation-map", schema["paths"])
        self.assertIn("/api/v1/runs/{run_id}/artifacts", schema["paths"])
        self.assertIn("/api/v1/runs/{run_id}/export", schema["paths"])
        self.assertIn("/api/v1/history", schema["paths"])

    def test_build_info_matches_distribution_commit_and_public_openapi(self):
        with tempfile.TemporaryDirectory() as temp:
            schema = create_app(Path(temp) / "paperseek.db").openapi()
        canonical = json.dumps(
            schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        self.assertEqual(build_info.DISTRIBUTION, "paperseek")
        self.assertEqual(build_info.VERSION, "0.3.0")
        self.assertEqual(
            build_info.COMMUNITY_COMMIT,
            "5525a58bd72e5f1cd18b681a25d0eea72e6b24ef",
        )
        self.assertTrue(build_info.SOURCE_TREE_DIRTY)
        self.assertEqual(
            build_info.PUBLIC_OPENAPI_SHA256,
            hashlib.sha256(canonical).hexdigest().upper(),
        )


if __name__ == "__main__":
    unittest.main()
