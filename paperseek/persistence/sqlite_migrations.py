from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable


SQLITE_SCHEMA_VERSION = 2


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9_]+", table):
        raise ValueError(f"Invalid table name: {table}")
    if not re.fullmatch(r"[a-zA-Z0-9_]+", column):
        raise ValueError(f"Invalid column name: {column}")
    if not re.fullmatch(r"[a-zA-Z0-9_ ]+", definition):
        raise ValueError(f"Invalid column definition: {definition}")

    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migration_1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS search_runs (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            source TEXT,
            final_query TEXT,
            db TEXT,
            field TEXT,
            total INTEGER,
            iterations INTEGER,
            status TEXT NOT NULL,
            error_message TEXT,
            params_json TEXT,
            history_json TEXT,
            citation_map_json TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS search_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_type TEXT,
            stage TEXT,
            status TEXT,
            message TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES search_runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS search_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            rank INTEGER,
            paper_uid TEXT,
            source TEXT,
            title TEXT,
            authors_json TEXT,
            year INTEGER,
            venue TEXT,
            doi TEXT,
            url TEXT,
            abstract TEXT,
            citation_count INTEGER,
            relevance_score REAL,
            relevance_reason TEXT,
            raw_json TEXT,
            FOREIGN KEY(run_id) REFERENCES search_runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS search_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            stage TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES search_runs(id) ON DELETE CASCADE,
            UNIQUE(run_id, sequence)
        );

        CREATE INDEX IF NOT EXISTS idx_search_runs_created_at ON search_runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_search_events_run_id ON search_events(run_id);
        CREATE INDEX IF NOT EXISTS idx_search_results_run_id ON search_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_search_checkpoints_run_id ON search_checkpoints(run_id, sequence DESC);
        """
    )
    _ensure_column(conn, "search_runs", "history_json", "TEXT")
    _ensure_column(conn, "search_runs", "search_loop_json", "TEXT")
    _ensure_column(conn, "search_runs", "search_state_json", "TEXT")
    _ensure_column(conn, "search_runs", "ranking_steps_json", "TEXT")


def _migration_2(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "search_runs", "claimed_by", "TEXT")
    _ensure_column(conn, "search_runs", "lease_expires_at", "TEXT")
    _ensure_column(conn, "search_runs", "heartbeat_at", "TEXT")
    _ensure_column(conn, "search_runs", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_runs_lease ON search_runs(status, lease_expires_at)"
    )


_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migration_1,
    2: _migration_2,
}


def apply_sqlite_migrations(conn: sqlite3.Connection) -> int:
    current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current_version > SQLITE_SCHEMA_VERSION:
        raise RuntimeError(
            f"PaperSeek history schema {current_version} is newer than supported schema "
            f"{SQLITE_SCHEMA_VERSION}."
        )

    for version in range(current_version + 1, SQLITE_SCHEMA_VERSION + 1):
        _MIGRATIONS[version](conn)
        conn.execute(f"PRAGMA user_version = {version}")
    return SQLITE_SCHEMA_VERSION
