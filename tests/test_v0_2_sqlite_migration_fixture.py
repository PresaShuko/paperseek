import json
import sqlite3
from pathlib import Path

from paperseek.history import HistoryStore
from paperseek.persistence import SQLITE_SCHEMA_VERSION
from tests.helpers import run_cli


FIXTURE_SQL = Path(__file__).parent / "fixtures" / "migration" / "community_v0_2_1_history.sql"
V0_2_1_RELEASE_COMMIT = "009a585a7b89e0b8792e795adc62bfecda646ace"

EXPECTED_COLUMNS = {
    "search_runs": [
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
    ],
    "search_events": [
        "id",
        "run_id",
        "event_type",
        "stage",
        "status",
        "message",
        "payload_json",
        "created_at",
    ],
    "search_results": [
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
    ],
}


def _materialize_fixture(tmp_path: Path, name: str = "paperseek-v0.2.1.db") -> Path:
    db_path = tmp_path / name
    with sqlite3.connect(db_path) as conn:
        conn.executescript(FIXTURE_SQL.read_text(encoding="utf-8"))
    return db_path


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def test_v0_2_1_fixture_has_release_schema_integrity_and_representative_rows(tmp_path):
    fixture_text = FIXTURE_SQL.read_text(encoding="utf-8")
    assert V0_2_1_RELEASE_COMMIT in fixture_text
    assert "All rows are synthetic" in fixture_text
    assert "BEGIN PRIVATE KEY" not in fixture_text
    assert "Bearer " not in fixture_text
    assert "sk-" not in fixture_text

    db_path = _materialize_fixture(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0

        application_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert application_tables == set(EXPECTED_COLUMNS)
        for table, columns in EXPECTED_COLUMNS.items():
            assert _columns(conn, table) == columns

        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert indexes == {
            "idx_search_runs_created_at",
            "idx_search_events_run_id",
            "idx_search_results_run_id",
        }
        assert _columns(conn, "search_runs")[-1] == "finished_at"
        assert "search_checkpoints" not in application_tables
        assert "claimed_by" not in _columns(conn, "search_runs")

        assert conn.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM search_events").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM search_results").fetchone()[0] == 2
        assert dict(conn.execute("SELECT status, COUNT(*) FROM search_runs GROUP BY status")) == {
            "error": 1,
            "running": 1,
            "success": 1,
        }

        success = conn.execute(
            "SELECT params_json, history_json, citation_map_json "
            "FROM search_runs WHERE id = 'run_v02_fixture_success'"
        ).fetchone()
        params = json.loads(success[0])
        history = json.loads(success[1])
        citation_map = json.loads(success[2])
        assert params["data_source"] == "openalex"
        assert params["has_llm_api_key"] is False
        assert history == [
            {
                "action": "accept",
                "iteration": 1,
                "message": "Accepted two synthetic records.",
                "query": "reproducible metadata AND evidence synthesis",
                "total": 2,
            }
        ]
        assert citation_map["status"] == "complete"
        assert citation_map["edges"][0]["type"] == "references"


def test_current_history_read_api_opens_a_disposable_v0_2_1_copy(tmp_path):
    db_path = _materialize_fixture(tmp_path)
    store = HistoryStore(db_path=db_path, enabled=True)

    summaries = store.list_runs()
    success = store.get_run("run_v02_fixture_success")
    failed = store.get_run("run_v02_fixture_error")

    assert [(run["id"], run["status"]) for run in summaries] == [
        ("run_v02_fixture_running", "running"),
        ("run_v02_fixture_error", "error"),
        ("run_v02_fixture_success", "success"),
    ]
    assert success is not None
    assert success["params"]["data_source"] == "openalex"
    assert success["history"][0]["action"] == "accept"
    assert success["citation_map"]["edges"][0]["type"] == "references"
    assert [paper["uid"] for paper in success["ranked"]] == [
        "W-FIXTURE-1001",
        "W-FIXTURE-1002",
    ]
    assert success["event_count"] == 2
    assert success["checkpoint"] is None
    assert failed is not None
    assert failed["error_message"] == "Synthetic upstream timeout."

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SQLITE_SCHEMA_VERSION


def test_current_cli_history_list_and_show_read_a_disposable_v0_2_1_copy(tmp_path):
    db_path = _materialize_fixture(tmp_path)
    env = {
        "PAPERSEEK_CONFIG_FILE": str(tmp_path / "empty-config.json"),
        "PAPERSEEK_DOTENV_DISABLED": "1",
        "PAPERSEEK_HISTORY_DB": str(db_path),
        "PAPERSEEK_HISTORY_ENABLED": "true",
    }

    listed = run_cli("history", "list", "--json", env=env)
    assert listed.returncode == 0, listed.stderr
    list_payload = json.loads(listed.stdout)
    assert [run["id"] for run in list_payload["history"]] == [
        "run_v02_fixture_running",
        "run_v02_fixture_error",
        "run_v02_fixture_success",
    ]

    shown = run_cli("history", "show", "run_v02_fixture_success", "--json", env=env)
    assert shown.returncode == 0, shown.stderr
    show_payload = json.loads(shown.stdout)
    assert show_payload["status"] == "success"
    assert [paper["title"] for paper in show_payload["ranked"]] == [
        "Reproducible Metadata for Evidence Synthesis",
        "Auditable Study Records",
    ]
