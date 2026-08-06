
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Union
from zoneinfo import ZoneInfo

from paperseek.config import AgentConfig
from paperseek.persistence import apply_sqlite_migrations


DISABLED_VALUES = {"0", "false", "no", "off"}
SECRET_KEY_NAMES = {"api_key", "apikey", "authorization", "auth_token", "access_token", "secret", "password"}
SECRET_KEY_PARTS = ("authorization", "token", "secret", "password")
SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)bearer\s+([A-Za-z0-9._\-+/=]{8,})"),
    re.compile(r"\bsk-[A-Za-z0-9._\-]{8,}\b"),
    re.compile(r"\b(?:ghp|github_pat|hf|ms)-[A-Za-z0-9._\-]{12,}\b", re.IGNORECASE),
)
DEFAULT_TIMEZONE_NAME = "Asia/Shanghai"
DEFAULT_UTC_OFFSET_MINUTES = 8 * 60


def _parse_utc_offset_minutes(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    if minutes < -23 * 60 or minutes > 23 * 60:
        return None
    return minutes


def _parse_utc_offset_text(value: str) -> Optional[int]:
    text = str(value or "").strip().upper()
    if text in ("UTC", "Z", "ETC/UTC"):
        return 0
    if text.startswith("UTC"):
        text = text[3:]
    if not text:
        return None
    sign = 1
    if text[0] == "+":
        text = text[1:]
    elif text[0] == "-":
        sign = -1
        text = text[1:]
    else:
        return None
    pieces = text.split(":", 1)
    try:
        hours = int(pieces[0])
        minutes = int(pieces[1]) if len(pieces) == 2 else 0
    except ValueError:
        return None
    if hours < 0 or minutes < 0 or hours > 23 or minutes > 59:
        return None
    return sign * (hours * 60 + minutes)


def _fixed_timezone(minutes: int) -> timezone:
    return timezone(timedelta(minutes=minutes))


def _history_timezone(timezone_name: Optional[str] = None, utc_offset_minutes: Any = None):
    configured_name = (timezone_name or os.environ.get("PAPERSEEK_TIMEZONE", "") or "").strip()
    if configured_name and ZoneInfo is not None:
        try:
            return ZoneInfo(configured_name)
        except Exception:
            pass

    if configured_name in (DEFAULT_TIMEZONE_NAME, "Asia/Chongqing", "Asia/Harbin", "PRC"):
        return _fixed_timezone(DEFAULT_UTC_OFFSET_MINUTES)

    parsed_text = _parse_utc_offset_text(configured_name)
    if parsed_text is not None:
        return _fixed_timezone(parsed_text)

    parsed_minutes = _parse_utc_offset_minutes(utc_offset_minutes)
    if parsed_minutes is not None:
        return _fixed_timezone(parsed_minutes)

    return _fixed_timezone(DEFAULT_UTC_OFFSET_MINUTES)


def history_now(timezone_name: Optional[str] = None, utc_offset_minutes: Any = None) -> str:
    return datetime.now(_history_timezone(timezone_name, utc_offset_minutes)).isoformat(timespec="seconds")


def utc_now() -> str:
    """Backward-compatible name for persisted history timestamps."""
    return history_now()


def history_enabled() -> bool:
    return os.environ.get("PAPERSEEK_HISTORY_ENABLED", "true").strip().lower() not in DISABLED_VALUES


def history_data_dir() -> Path:
    configured = os.environ.get("PAPERSEEK_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".paperseek"


def history_db_path() -> Path:
    configured = os.environ.get("PAPERSEEK_HISTORY_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return history_data_dir() / "paperseek.db"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Optional[str], default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _is_secret_key(key: str) -> bool:
    normalized = str(key or "").lower().replace("-", "_")
    return (
        normalized in SECRET_KEY_NAMES
        or normalized.endswith("_key")
        or normalized.endswith("_apikey")
        or any(part in normalized for part in SECRET_KEY_PARTS)
    )


def _redact_secret_text(text: str) -> str:
    value = str(text or "")
    for pattern in SECRET_VALUE_PATTERNS:
        value = pattern.sub("[redacted]", value)
    return value


def redact_secrets(value: Any) -> Any:
    """Return a JSON-safe copy with obvious credential fields removed."""
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            output[key] = "[redacted]" if _is_secret_key(str(key)) else redact_secrets(item)
        return output
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _redact_secret_text(value)
    return value


def safe_search_params_from_config(config: AgentConfig) -> dict[str, Any]:
    """Persist only run-shaping settings, never raw user credentials."""
    return {
        "data_source": config.data_source,
        "search_budget": getattr(config, "search_budget", "fast"),
        "llm_thinking_enabled": bool(getattr(config, "llm_thinking_enabled", True)),
        "llm_provider": config.llm_provider,
        "llm_api_type": config.llm_api_type,
        "llm_model": config.llm_model,
        "llm_base_url": config.llm_base_url,
        "llm_max_tokens": getattr(config, "llm_max_tokens", 2048),
        "wos_db": config.wos_db,
        "search_field": config.search_field,
        "discipline_fields": list(getattr(config, "discipline_fields", ()) or []),
        "fetch_abstracts": config.fetch_abstracts,
        "expand_citations": config.expand_citations,
        "citation_seed_count": config.citation_seed_count,
        "citation_per_seed": config.citation_per_seed,
        "citation_max_records": config.citation_max_records,
        "target_min": config.target_min,
        "target_max": config.target_max,
        "max_iterations": config.max_iterations,
        "retrieval_pool_max": getattr(config, "retrieval_pool_max", 3000),
        "retrieval_pool_min": getattr(config, "retrieval_pool_min", 5),
        "retrieval_lane_limit": getattr(config, "retrieval_lane_limit", 500),
        "ranking_candidate_limit": getattr(config, "ranking_candidate_limit", 256),
        "retrieval_rrf_k": getattr(config, "retrieval_rrf_k", 60),
        "retrieval_embedding_provider": getattr(config, "retrieval_embedding_provider", "local"),
        "retrieval_embedding_model": getattr(config, "retrieval_embedding_model", ""),
        "retrieval_reranker_provider": getattr(config, "retrieval_reranker_provider", ""),
        "retrieval_reranker_model": getattr(config, "retrieval_reranker_model", ""),
        "retrieval_crossref_enrichment": getattr(config, "retrieval_crossref_enrichment", False),
        "query_portfolio_enabled": getattr(config, "query_portfolio_enabled", True),
        "query_portfolio_max": getattr(config, "query_portfolio_max", 3),
        "query_portfolio_limit": getattr(config, "query_portfolio_limit", 100),
        "search_loop_backend": getattr(config, "search_loop_backend", "auto"),
        "has_wos_api_key": bool(config.wos_api_key),
        "has_openalex_api_key": bool(config.openalex_api_key),
        "has_openalex_email": bool(config.openalex_email),
        "has_crossref_email": bool(config.crossref_email),
        "has_llm_api_key": bool(config.llm_api_key),
    }


def result_payload_from_search_result(result: dict[str, Any], source: str) -> dict[str, Any]:
    from paperseek.formatter import ranked_items_to_dict

    return {
        "question": result["question"],
        "search_intent": result.get("search_intent", ""),
        "search_plan": result.get("search_plan", {}),
        "query_view_selection": result.get("query_view_selection", []),
        "query_portfolio": result.get("query_portfolio", []),
        "source": result.get("source", source),
        "final_query": result["final_query"],
        "db": result["db"],
        "field": result["field"],
        "total": result["total"],
        "iterations": result["iterations"],
        "history": result.get("history", []),
        "search_loop": result.get("search_loop", {}),
        "search_state": result.get("search_state", {}),
        "citation_map": result.get("citation_map", {}),
        "ranking_steps": result.get("ranking_steps", []),
        "ranked": ranked_items_to_dict(result["ranked"]),
    }


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    return row[key] if key in row.keys() else default


def _authors_from_paper(paper: dict[str, Any]) -> list[str]:
    authors = paper.get("authors")
    if isinstance(authors, list):
        return [str(author) for author in authors if author]
    authors_text = paper.get("authors_text") or ""
    return [part.strip() for part in str(authors_text).split(";") if part.strip()]


class HistoryStore:
    def __init__(
        self,
        db_path: Optional[Union[Path, str]] = None,
        enabled: Optional[bool] = None,
        timezone_name: Optional[str] = None,
        utc_offset_minutes: Any = None,
    ):
        self.db_path = Path(db_path).expanduser() if db_path is not None else history_db_path()
        self._enabled = history_enabled() if enabled is None else enabled
        self._timezone_name = timezone_name
        self._utc_offset_minutes = utc_offset_minutes
        self._schema_ready = False
        self._checkpoint_schema_available = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "path": str(self.db_path),
        }

    def _now(self) -> str:
        return history_now(self._timezone_name, self._utc_offset_minutes)

    def _lease_deadline(self, lease_seconds: int) -> str:
        seconds = max(5, min(int(lease_seconds or 60), 3600))
        return (
            datetime.now(_history_timezone(self._timezone_name, self._utc_offset_minutes))
            + timedelta(seconds=seconds)
        ).isoformat(timespec="seconds")

    def _connect(self) -> sqlite3.Connection:
        if not self.enabled:
            raise RuntimeError("PaperSeek history is disabled.")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if not self._schema_ready:
            try:
                self._ensure_schema(conn)
            except sqlite3.OperationalError as exc:
                if "readonly" not in str(exc).lower() and "read-only" not in str(exc).lower():
                    conn.close()
                    raise
            self._checkpoint_schema_available = self._table_exists(conn, "search_checkpoints")
            self._schema_ready = True
        return conn

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table,),
        ).fetchone()
        return row is not None

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        apply_sqlite_migrations(conn)

    def create_run(self, question: str, params: Optional[dict[str, Any]] = None) -> str:
        if not self.enabled:
            return ""
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = self._now()
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO search_runs (
                        id, question, status, params_json, created_at, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, question, "running", _json_dumps(redact_secrets(params or {})), now, now),
                )
        except Exception:
            return ""
        return run_id

    def record_event(self, run_id: str, event: dict[str, Any]) -> None:
        self._record_event(run_id, event, owner_id="")

    def record_claimed_event(
        self,
        run_id: str,
        owner_id: str,
        event: dict[str, Any],
    ) -> bool:
        return self._record_event(
            run_id,
            event,
            owner_id=str(owner_id or "").strip(),
        )

    def _record_event(
        self,
        run_id: str,
        event: dict[str, Any],
        *,
        owner_id: str,
    ) -> bool:
        if not self.enabled or not run_id:
            return False
        safe_event = redact_secrets(event or {})
        now = self._now()
        try:
            with self._connection() as conn:
                if owner_id:
                    cursor = conn.execute(
                        """
                        INSERT INTO search_events (
                            run_id, event_type, stage, status, message, payload_json, created_at
                        )
                        SELECT ?, ?, ?, ?, ?, ?, ?
                        FROM search_runs
                        WHERE id = ? AND claimed_by = ? AND lease_expires_at > ?
                          AND status NOT IN ('success', 'cancelled')
                        """,
                        (
                            run_id,
                            str(safe_event.get("type", "")),
                            str(safe_event.get("stage", "")),
                            str(safe_event.get("status", "")),
                            str(safe_event.get("message", "")),
                            _json_dumps(safe_event),
                            now,
                            run_id,
                            owner_id,
                            now,
                        ),
                    )
                    return cursor.rowcount == 1
                conn.execute(
                    """
                    INSERT INTO search_events (
                        run_id, event_type, stage, status, message, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(safe_event.get("type", "")),
                        str(safe_event.get("stage", "")),
                        str(safe_event.get("status", "")),
                        str(safe_event.get("message", "")),
                        _json_dumps(safe_event),
                        now,
                    ),
                )
        except Exception:
            return False
        return True

    def save_checkpoint(self, run_id: str, checkpoint: dict[str, Any]) -> None:
        self._save_checkpoint(run_id, checkpoint, owner_id="")

    def save_claimed_checkpoint(
        self,
        run_id: str,
        owner_id: str,
        checkpoint: dict[str, Any],
    ) -> bool:
        return self._save_checkpoint(
            run_id,
            checkpoint,
            owner_id=str(owner_id or "").strip(),
        )

    def _save_checkpoint(
        self,
        run_id: str,
        checkpoint: dict[str, Any],
        *,
        owner_id: str,
    ) -> bool:
        if not self.enabled or not run_id:
            return False
        safe_checkpoint = redact_secrets(checkpoint or {})
        try:
            sequence = max(0, int(safe_checkpoint.get("sequence") or 0))
            stage = str(safe_checkpoint.get("stage") or "").strip()
        except (TypeError, ValueError):
            return False
        if not stage:
            return False
        now = self._now()
        try:
            with self._connection() as conn:
                if not self._checkpoint_schema_available:
                    return False
                if owner_id:
                    cursor = conn.execute(
                        """
                        INSERT INTO search_checkpoints (run_id, sequence, stage, payload_json, created_at)
                        SELECT ?, ?, ?, ?, ?
                        FROM search_runs
                        WHERE id = ? AND claimed_by = ? AND lease_expires_at > ?
                          AND status NOT IN ('success', 'cancelled')
                        ON CONFLICT(run_id, sequence) DO UPDATE SET
                            stage = excluded.stage,
                            payload_json = excluded.payload_json,
                            created_at = excluded.created_at
                        """,
                        (
                            run_id,
                            sequence,
                            stage,
                            _json_dumps(safe_checkpoint),
                            now,
                            run_id,
                            owner_id,
                            now,
                        ),
                    )
                    return cursor.rowcount == 1
                conn.execute(
                    """
                    INSERT INTO search_checkpoints (run_id, sequence, stage, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, sequence) DO UPDATE SET
                        stage = excluded.stage,
                        payload_json = excluded.payload_json,
                        created_at = excluded.created_at
                    """,
                    (run_id, sequence, stage, _json_dumps(safe_checkpoint), now),
                )
        except Exception:
            return False
        return True

    def latest_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        if not self.enabled or not run_id:
            return None
        try:
            with self._connection() as conn:
                if not self._checkpoint_schema_available:
                    return None
                row = conn.execute(
                    """
                    SELECT sequence, stage, payload_json, created_at
                    FROM search_checkpoints
                    WHERE run_id = ?
                    ORDER BY sequence DESC, id DESC
                    LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        payload = _json_loads(row["payload_json"], None)
        if not isinstance(payload, dict):
            return None
        return {
            "sequence": row["sequence"],
            "stage": row["stage"],
            "created_at": row["created_at"],
            "payload": payload,
        }

    def clear_checkpoints(self, run_id: str) -> None:
        if not self.enabled or not run_id:
            return
        try:
            with self._connection() as conn:
                if not self._checkpoint_schema_available:
                    return
                conn.execute("DELETE FROM search_checkpoints WHERE run_id = ?", (run_id,))
        except Exception:
            return

    def claim_run(self, run_id: str, owner_id: str, lease_seconds: int = 60) -> bool:
        owner = str(owner_id or "").strip()
        if not self.enabled or not run_id or not owner:
            return False
        now = self._now()
        expires_at = self._lease_deadline(lease_seconds)
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE search_runs
                SET claimed_by = ?, lease_expires_at = ?, heartbeat_at = ?,
                    status = 'running', error_message = NULL, finished_at = NULL,
                    attempt_count = CASE
                        WHEN claimed_by = ? AND lease_expires_at > ? THEN attempt_count
                        ELSE COALESCE(attempt_count, 0) + 1
                    END
                WHERE id = ?
                  AND status NOT IN ('success', 'cancelled')
                  AND (
                    claimed_by IS NULL OR claimed_by = '' OR claimed_by = ?
                    OR lease_expires_at IS NULL OR lease_expires_at <= ?
                  )
                """,
                (owner, expires_at, now, owner, now, run_id, owner, now),
            )
            return cursor.rowcount == 1

    def renew_run_lease(self, run_id: str, owner_id: str, lease_seconds: int = 60) -> bool:
        owner = str(owner_id or "").strip()
        if not self.enabled or not run_id or not owner:
            return False
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE search_runs
                SET lease_expires_at = ?, heartbeat_at = ?
                WHERE id = ? AND claimed_by = ?
                  AND lease_expires_at > ?
                  AND status NOT IN ('success', 'cancelled')
                """,
                (
                    self._lease_deadline(lease_seconds),
                    self._now(),
                    run_id,
                    owner,
                    self._now(),
                ),
            )
            return cursor.rowcount == 1

    def release_run(self, run_id: str, owner_id: str) -> bool:
        owner = str(owner_id or "").strip()
        if not self.enabled or not run_id or not owner:
            return False
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE search_runs
                SET claimed_by = NULL, lease_expires_at = NULL
                WHERE id = ? AND claimed_by = ?
                """,
                (run_id, owner),
            )
            return cursor.rowcount == 1

    def cancel_run(self, run_id: str, message: str = "") -> bool:
        return self._cancel_run(run_id, message, owner_id="")

    def cancel_claimed_run(
        self,
        run_id: str,
        owner_id: str,
        message: str = "",
    ) -> bool:
        return self._cancel_run(
            run_id,
            message,
            owner_id=str(owner_id or "").strip(),
        )

    def _cancel_run(self, run_id: str, message: str, *, owner_id: str) -> bool:
        if not self.enabled or not run_id:
            return False
        now = self._now()
        owner_clause = " AND claimed_by = ? AND lease_expires_at > ?" if owner_id else ""
        with self._connection() as conn:
            cursor = conn.execute(
                f"""
                UPDATE search_runs
                SET status = 'cancelled', error_message = ?, finished_at = ?,
                    claimed_by = NULL, lease_expires_at = NULL
                WHERE id = ? AND status NOT IN ('success', 'cancelled'){owner_clause}
                """,
                (
                    str(message or "Search cancelled by user."),
                    now,
                    run_id,
                    *((owner_id, now) if owner_id else ()),
                ),
            )
            return cursor.rowcount == 1

    def complete_run(self, run_id: str, payload: dict[str, Any]) -> None:
        self._complete_run(run_id, payload, owner_id="")

    def complete_claimed_run(self, run_id: str, owner_id: str, payload: dict[str, Any]) -> bool:
        return self._complete_run(run_id, payload, owner_id=str(owner_id or "").strip())

    def _complete_run(self, run_id: str, payload: dict[str, Any], *, owner_id: str) -> bool:
        if not self.enabled or not run_id:
            return False
        safe_payload = redact_secrets(payload or {})
        ranked = list(safe_payload.get("ranked") or [])
        now = self._now()
        owner_clause = " AND claimed_by = ? AND lease_expires_at > ?" if owner_id else ""
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    f"""
                    UPDATE search_runs
                    SET source = ?, final_query = ?, db = ?, field = ?, total = ?, iterations = ?,
                        status = ?, error_message = NULL, history_json = ?, search_loop_json = ?,
                        search_state_json = ?, citation_map_json = ?, ranking_steps_json = ?,
                        finished_at = ?, claimed_by = NULL, lease_expires_at = NULL
                    WHERE id = ?{owner_clause}
                    """,
                    (*(
                        safe_payload.get("source", ""),
                        safe_payload.get("final_query", ""),
                        safe_payload.get("db", ""),
                        safe_payload.get("field", ""),
                        _as_int(safe_payload.get("total")),
                        _as_int(safe_payload.get("iterations")),
                        "success",
                        _json_dumps(safe_payload.get("history") or []),
                        _json_dumps(safe_payload.get("search_loop") or {}),
                        _json_dumps(safe_payload.get("search_state") or {}),
                        _json_dumps(safe_payload.get("citation_map") or {}),
                        _json_dumps(safe_payload.get("ranking_steps") or []),
                        now,
                        run_id,
                    ), *((owner_id, now) if owner_id else ())),
                )
                if cursor.rowcount != 1:
                    return False
                conn.execute("DELETE FROM search_results WHERE run_id = ?", (run_id,))
                self._insert_results(conn, run_id, ranked)
                if self._checkpoint_schema_available:
                    conn.execute("DELETE FROM search_checkpoints WHERE run_id = ?", (run_id,))
        except Exception:
            return False
        return True

    def fail_run(self, run_id: str, error_message: str, payload: Optional[dict[str, Any]] = None) -> None:
        self._fail_run(run_id, error_message, payload, owner_id="")

    def fail_claimed_run(
        self,
        run_id: str,
        owner_id: str,
        error_message: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> bool:
        return self._fail_run(
            run_id,
            error_message,
            payload,
            owner_id=str(owner_id or "").strip(),
        )

    def _fail_run(
        self,
        run_id: str,
        error_message: str,
        payload: Optional[dict[str, Any]],
        *,
        owner_id: str,
    ) -> bool:
        if not self.enabled or not run_id:
            return False
        safe_payload = redact_secrets(payload or {})
        now = self._now()
        owner_clause = " AND claimed_by = ? AND lease_expires_at > ?" if owner_id else ""
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    f"""
                    UPDATE search_runs
                    SET source = COALESCE(NULLIF(?, ''), source),
                        final_query = COALESCE(NULLIF(?, ''), final_query),
                        db = COALESCE(NULLIF(?, ''), db),
                        field = COALESCE(NULLIF(?, ''), field),
                        total = COALESCE(?, total),
                        iterations = COALESCE(?, iterations),
                        status = ?,
                        error_message = ?,
                        history_json = COALESCE(?, history_json),
                        search_loop_json = COALESCE(?, search_loop_json),
                        search_state_json = COALESCE(?, search_state_json),
                        citation_map_json = COALESCE(?, citation_map_json),
                        ranking_steps_json = COALESCE(?, ranking_steps_json),
                        finished_at = ?, claimed_by = NULL, lease_expires_at = NULL
                    WHERE id = ?{owner_clause}
                    """,
                    (*(
                        safe_payload.get("source", ""),
                        safe_payload.get("final_query", ""),
                        safe_payload.get("db", ""),
                        safe_payload.get("field", ""),
                        _as_int(safe_payload.get("total")),
                        _as_int(safe_payload.get("iterations")),
                        "error",
                        str(error_message or ""),
                        _json_dumps(safe_payload.get("history")) if "history" in safe_payload else None,
                        _json_dumps(safe_payload.get("search_loop")) if "search_loop" in safe_payload else None,
                        _json_dumps(safe_payload.get("search_state")) if "search_state" in safe_payload else None,
                        _json_dumps(safe_payload.get("citation_map")) if "citation_map" in safe_payload else None,
                        _json_dumps(safe_payload.get("ranking_steps")) if "ranking_steps" in safe_payload else None,
                        now,
                        run_id,
                    ), *((owner_id, now) if owner_id else ())),
                )
                return cursor.rowcount == 1
        except Exception:
            return False

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
        with self._connection() as conn:
            checkpoint_columns = (
                "(SELECT COUNT(*) FROM search_checkpoints sc WHERE sc.run_id = r.id) AS checkpoint_count, "
                "(SELECT sc.stage FROM search_checkpoints sc WHERE sc.run_id = r.id ORDER BY sc.sequence DESC, sc.id DESC LIMIT 1) AS checkpoint_stage"
                if self._checkpoint_schema_available
                else "0 AS checkpoint_count, '' AS checkpoint_stage"
            )
            rows = conn.execute(
                f"""
                SELECT r.*,
                       (SELECT COUNT(*) FROM search_results sr WHERE sr.run_id = r.id) AS result_count,
                       (SELECT COUNT(*) FROM search_events se WHERE se.run_id = r.id) AS event_count,
                       {checkpoint_columns}
                FROM search_runs r
                ORDER BY r.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._run_row_to_dict(row, include_payload=False) for row in rows]

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None
        with self._connection() as conn:
            checkpoint_columns = (
                "(SELECT COUNT(*) FROM search_checkpoints sc WHERE sc.run_id = r.id) AS checkpoint_count, "
                "(SELECT sc.stage FROM search_checkpoints sc WHERE sc.run_id = r.id ORDER BY sc.sequence DESC, sc.id DESC LIMIT 1) AS checkpoint_stage"
                if self._checkpoint_schema_available
                else "0 AS checkpoint_count, '' AS checkpoint_stage"
            )
            row = conn.execute(
                f"""
                SELECT r.*,
                       (SELECT COUNT(*) FROM search_results sr WHERE sr.run_id = r.id) AS result_count,
                       (SELECT COUNT(*) FROM search_events se WHERE se.run_id = r.id) AS event_count,
                       {checkpoint_columns}
                FROM search_runs r
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            events = conn.execute(
                "SELECT * FROM search_events WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
            results = conn.execute(
                "SELECT * FROM search_results WHERE run_id = ? ORDER BY rank ASC, id ASC",
                (run_id,),
            ).fetchall()
        data = self._run_row_to_dict(row, include_payload=True)
        data["events"] = [self._event_row_to_dict(event) for event in events]
        data["ranked"] = [self._result_row_to_dict(result) for result in results]
        data["checkpoint"] = self.latest_checkpoint(run_id)
        return data

    def delete_run(self, run_id: str) -> bool:
        if not self.enabled:
            return False
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM search_runs WHERE id = ?", (run_id,))
            return cursor.rowcount > 0

    def clear(self) -> int:
        if not self.enabled:
            return 0
        with self._connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0]
            conn.execute("DELETE FROM search_runs")
        return int(count or 0)

    def _insert_results(self, conn: sqlite3.Connection, run_id: str, ranked: Iterable[dict[str, Any]]) -> None:
        for index, paper in enumerate(ranked, 1):
            if not isinstance(paper, dict):
                continue
            links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
            doi = str(paper.get("doi") or "")
            url = paper.get("url") or links.get("record") or links.get("landing_page") or (f"https://doi.org/{doi}" if doi else "")
            conn.execute(
                """
                INSERT INTO search_results (
                    run_id, rank, paper_uid, source, title, authors_json, year, venue, doi,
                    url, abstract, citation_count, relevance_score, relevance_reason, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    _as_int(paper.get("rank")) or index,
                    str(paper.get("uid") or paper.get("id") or doi or paper.get("title") or ""),
                    str(paper.get("provider") or paper.get("source_provider") or paper.get("source") or ""),
                    str(paper.get("title") or ""),
                    _json_dumps(_authors_from_paper(paper)),
                    _as_int(paper.get("publish_year") or paper.get("year")),
                    str(paper.get("source") or paper.get("venue") or ""),
                    doi,
                    str(url or ""),
                    str(paper.get("abstract") or ""),
                    _as_int(paper.get("citation_count") or paper.get("citations")),
                    _as_float(paper.get("relevance_score") if paper.get("relevance_score") is not None else paper.get("score")),
                    str(paper.get("relevance_reason") or paper.get("reasoning") or ""),
                    _json_dumps(paper),
                ),
            )

    def _run_row_to_dict(self, row: sqlite3.Row, include_payload: bool) -> dict[str, Any]:
        data = {
            "id": row["id"],
            "question": row["question"],
            "source": row["source"] or "",
            "final_query": row["final_query"] or "",
            "db": row["db"] or "",
            "field": row["field"] or "",
            "total": row["total"],
            "iterations": row["iterations"],
            "status": row["status"],
            "error_message": row["error_message"] or "",
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"] or "",
            "claimed_by": _row_value(row, "claimed_by", "") or "",
            "lease_expires_at": _row_value(row, "lease_expires_at", "") or "",
            "heartbeat_at": _row_value(row, "heartbeat_at", "") or "",
            "attempt_count": int(_row_value(row, "attempt_count", 0) or 0),
            "result_count": row["result_count"],
            "event_count": row["event_count"],
            "checkpoint_count": row["checkpoint_count"],
            "checkpoint_stage": row["checkpoint_stage"] or "",
            "resumable": bool(row["checkpoint_count"] and row["status"] != "success"),
        }
        if include_payload:
            data["params"] = _json_loads(row["params_json"], {})
            data["history"] = _json_loads(row["history_json"], [])
            data["search_loop"] = _json_loads(row["search_loop_json"], {})
            data["search_state"] = _json_loads(row["search_state_json"], {})
            data["citation_map"] = _json_loads(row["citation_map_json"], {})
            data["ranking_steps"] = _json_loads(row["ranking_steps_json"], [])
        return data

    def _event_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = _json_loads(row["payload_json"], {})
        return {
            "id": row["id"],
            "type": row["event_type"] or "",
            "stage": row["stage"] or "",
            "status": row["status"] or "",
            "message": row["message"] or "",
            "created_at": row["created_at"],
            "payload": payload,
        }

    def _result_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        raw = _json_loads(row["raw_json"], {})
        if isinstance(raw, dict) and raw:
            return raw
        return {
            "rank": row["rank"],
            "uid": row["paper_uid"] or "",
            "provider": row["source"] or "",
            "title": row["title"] or "",
            "authors": _json_loads(row["authors_json"], []),
            "publish_year": row["year"],
            "source": row["venue"] or "",
            "doi": row["doi"] or "",
            "url": row["url"] or "",
            "abstract": row["abstract"] or "",
            "citations": str(row["citation_count"] or ""),
            "citation_count": row["citation_count"] or 0,
            "score": row["relevance_score"],
            "reasoning": row["relevance_reason"] or "",
        }
