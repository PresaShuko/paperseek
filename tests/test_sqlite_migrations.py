import sqlite3

from paperseek.persistence import SQLITE_SCHEMA_VERSION, apply_sqlite_migrations


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_new_database_is_migrated_to_current_version():
    conn = sqlite3.connect(":memory:")
    try:
        version = apply_sqlite_migrations(conn)
        assert version == SQLITE_SCHEMA_VERSION
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SQLITE_SCHEMA_VERSION
        assert {"search_runs", "search_events", "search_results", "search_checkpoints"}.issubset(
            {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        )
    finally:
        conn.close()


def test_legacy_database_is_upgraded_without_losing_rows():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE search_runs (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT NOT NULL
            );
            INSERT INTO search_runs (id, question, status, created_at, started_at)
            VALUES ('run_legacy', 'legacy question', 'running', 'now', 'now');
            """
        )

        apply_sqlite_migrations(conn)

        assert conn.execute("SELECT question FROM search_runs WHERE id='run_legacy'").fetchone()[0] == "legacy question"
        assert {
            "history_json",
            "search_state_json",
            "ranking_steps_json",
            "claimed_by",
            "lease_expires_at",
            "heartbeat_at",
            "attempt_count",
        }.issubset(
            _columns(conn, "search_runs")
        )
    finally:
        conn.close()


def test_migrations_are_idempotent():
    conn = sqlite3.connect(":memory:")
    try:
        apply_sqlite_migrations(conn)
        apply_sqlite_migrations(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SQLITE_SCHEMA_VERSION
    finally:
        conn.close()
