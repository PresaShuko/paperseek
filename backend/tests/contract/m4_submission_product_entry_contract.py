from __future__ import annotations

from contextlib import closing
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from paperseek_app.errors import ActiveRunExists, IdempotencyConflict
from paperseek_app.execution import WorkflowExecution
from paperseek_app.services import RunService
from paperseek_community.api import create_app
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.fixed_source import FixedLLMAdapter, FixedSourceAdapter
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_community.persistence.migrate import database_url
from paperseek_core.models import QueryLoopBudget, ResearchWorkflowRequest


FIXTURE = Path(__file__).parent / "fixtures" / "m1_fixed_source.json"


def _upgrade_to(database: Path, revision: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(files("paperseek_community.migrations")))
    config.set_main_option(
        "sqlalchemy.url",
        database_url(database).render_as_string(hide_password=False).replace("%", "%%"),
    )
    command.upgrade(config, revision)


def _execution(run, _cancellation) -> WorkflowExecution:
    source = FixedSourceAdapter.from_file(FIXTURE)
    return WorkflowExecution(
        llm=FixedLLMAdapter(source.fixture.llm_responses),
        source=source,
        abstracts=source,
        request=ResearchWorkflowRequest(
            question=run.question,
            query_budget=QueryLoopBudget(
                target_min=1,
                target_max=50,
                retrieval_pool_min=1,
                query_portfolio_enabled=False,
            ),
        ),
    )


class M4SubmissionProductEntryContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name)
        self.database = self.data_dir / "paperseek.db"
        migrate_database(self.database)
        self.uow = SQLiteRunUnitOfWork(self.database)
        self.addCleanup(self.uow.close)
        self.service = RunService(self.uow, FileArtifactStore(self.data_dir))

    def test_schema_six_preserves_v5_runs_and_adds_atomic_submission_records(self) -> None:
        database = self.data_dir / "upgrade-from-v5.db"
        _upgrade_to(database, "0005_m3_read_cleanup")
        with closing(sqlite3.connect(database)) as connection:
            before = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

        self.assertEqual(migrate_database(database), 6)
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], before)
            self.assertIn(
                "owner_subject",
                {row[1] for row in connection.execute("PRAGMA table_info(runs)")},
            )
            self.assertEqual(
                {row[1] for row in connection.execute("PRAGMA table_info(run_submissions)")},
                {"subject", "idempotency_key", "request_digest", "run_id", "created_at"},
            )

    def test_submission_is_atomic_idempotent_and_enforces_one_public_active_run(self) -> None:
        first = self.service.submit_run(
            subject="community",
            idempotency_key="submit-1",
            request_digest="digest-1",
            question="How should durable research runs recover?",
            source="openalex",
            config_snapshot={"search_budget": "fast"},
        )
        repeated = self.service.submit_run(
            subject="community",
            idempotency_key="submit-1",
            request_digest="digest-1",
            question="How should durable research runs recover?",
            source="openalex",
            config_snapshot={"search_budget": "fast"},
        )
        self.assertEqual(repeated.id, first.id)

        with self.assertRaises(IdempotencyConflict):
            self.service.submit_run(
                subject="community",
                idempotency_key="submit-1",
                request_digest="digest-2",
                question="Different request",
                source="arxiv",
            )
        with self.assertRaises(ActiveRunExists) as raised:
            self.service.submit_run(
                subject="community",
                idempotency_key="submit-2",
                request_digest="digest-2",
                question="Another request",
                source="arxiv",
            )
        self.assertEqual(raised.exception.run_id, first.id)

    def test_browser_credentials_are_encrypted_outside_run_state_and_deleted(self) -> None:
        run = self.service.create_run("Credential boundary", "openalex")
        store = EncryptedRunCredentialStore(self.database)
        secret = "m4-contract-secret-that-must-not-be-plain"
        store.save(run.id, {"llm": {"api_key": secret}, "source": {"api_key": "source-secret"}})

        self.assertEqual(store.resolve(run.id)["llm"]["api_key"], secret)
        self.assertNotIn(secret, self.database.read_bytes().decode("latin-1"))
        self.assertNotIn("api_key", json.dumps(self.service.get_run(run.id).config_snapshot))

        store.delete(run.id)
        self.assertEqual(store.resolve(run.id), {})

    def test_api_submission_executes_and_vue_spa_is_the_single_root(self) -> None:
        static_dir = self.data_dir / "static"
        static_dir.mkdir()
        (static_dir / "index.html").write_text(
            '<!doctype html><html><body><div id="app">Vue product entry</div></body></html>',
            encoding="utf-8",
        )
        with TestClient(
            create_app(
                self.database,
                execution_resolver=_execution,
                static_dir=static_dir,
            )
        ) as client:
            sources = client.get("/api/v1/sources")
            self.assertEqual(sources.status_code, 200)
            self.assertEqual(
                [item["id"] for item in sources.json()["sources"]],
                [
                    "openalex",
                    "arxiv",
                    "crossref",
                    "semanticscholar",
                    "pubmed",
                    "wos",
                    "googlescholar",
                    "paperhub",
                ],
            )

            response = client.post(
                "/api/v1/runs",
                headers={"Idempotency-Key": "browser-submit"},
                json={
                    "question": json.loads(FIXTURE.read_text(encoding="utf-8"))["question"],
                    "source": "openalex",
                    "search_budget": "fast",
                    "citation_enabled": True,
                },
            )
            self.assertEqual(response.status_code, 202)
            run_id = response.json()["id"]
            for _ in range(200):
                detail = client.get(f"/api/v1/runs/{run_id}").json()
                if detail["status"] in {"completed", "completed_with_warnings", "failed"}:
                    break
                time.sleep(0.01)
            self.assertEqual(detail["status"], "completed")
            self.assertEqual(client.get(f"/api/v1/runs/{run_id}/results").status_code, 200)
            self.assertIn("Vue product entry", client.get("/").text)
            self.assertIn("Vue product entry", client.get("/results").text)


if __name__ == "__main__":
    unittest.main()
