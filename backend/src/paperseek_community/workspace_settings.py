"""Saved model connections, data-source settings and workspace defaults.

Keys are encrypted with the Community master key and never leave the server in
plaintext; submissions name a saved connection and receive a per-run copy.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import httpx
from pydantic import BaseModel, ConfigDict, Field

from paperseek_app.configuration import (
    DECISION_ROUTE_DEFAULTS,
    EMBEDDING_ROUTE_DEFAULTS,
    LLM_ROUTE_DEFAULTS,
    RERANKER_ROUTE_DEFAULTS,
)
from paperseek_app.source_catalog import SOURCE_BY_ID, SOURCES
from paperseek_app.submission import RunSubmission
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.model_transport import create_http_client
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_core.decision_prompt import decision_question, decision_state
from paperseek_core.execution import RequestContext
from paperseek_core.models import PaperRecord
from paperseek_core.sources import AsyncHttpTransport
from paperseek_core.sources.contracts import SourceError, SourceSearchRequest

ConnectionKind = Literal["llm", "embedding", "reranker", "decision"]
PreRankingMode = Literal["local_fusion", "embedding_rerank", "decision"]
LLM_API_TYPES = ("openai_chat", "openai_responses", "anthropic_messages")
SOURCE_OPTIONS = {
    "openalex": ("openalex_email",),
    "crossref": ("crossref_email",),
    "pubmed": ("pubmed_tool", "pubmed_email"),
    "wos": ("wos_db",),
}
KEY_VERSION = 1


class SettingsError(ValueError):
    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    kind: ConnectionKind
    provider: str = Field(min_length=1, max_length=64)
    api_type: str = Field(default="", max_length=64)
    base_url: str = Field(default="", max_length=2048)
    model: str = Field(default="", max_length=256)
    # None keeps the stored key on update; an empty string clears it.
    api_key: str | None = Field(default=None, max_length=4096, repr=False)


class ConnectionTestInput(ConnectionInput):
    id: str = Field(default="", max_length=64)


class DefaultsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_llm: str | None = Field(default=None, max_length=64)
    review_llm: str | None = Field(default=None, max_length=64)
    pre_ranking: PreRankingMode | None = None
    embedding: str | None = Field(default=None, max_length=64)
    reranker: str | None = Field(default=None, max_length=64)
    decision: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=64)


class SourceSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    options: dict[str, str] | None = None


class TestOutput(BaseModel):
    status: Literal["untested", "ok", "failed"]
    latency_ms: int | None = None
    code: str = ""
    tested_at: str | None = None


class ProbeOutput(BaseModel):
    ok: bool
    latency_ms: int | None = None
    code: str = ""


class ConnectionOutput(BaseModel):
    id: str
    kind: ConnectionKind
    provider: str
    api_type: str
    base_url: str
    model: str
    has_key: bool
    requires_key: bool
    test: TestOutput
    created_at: str
    updated_at: str


class SourceSettingOutput(BaseModel):
    id: str
    has_key: bool
    key_origin: Literal["", "settings", "environment"]
    usable: bool
    options: dict[str, str]
    test: TestOutput


class DefaultsOutput(BaseModel):
    search_llm: str
    review_llm: str
    pre_ranking: PreRankingMode
    embedding: str
    reranker: str
    decision: str
    source: str


class WorkspaceSettingsOutput(BaseModel):
    connections: list[ConnectionOutput]
    sources: list[SourceSettingOutput]
    defaults: DefaultsOutput


class SecretsClearOutput(BaseModel):
    connections: int
    source_keys: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _provider_table(kind: str) -> dict:
    return {
        "llm": LLM_ROUTE_DEFAULTS,
        "embedding": {key: value for key, value in EMBEDDING_ROUTE_DEFAULTS.items() if key != "local"},
        "reranker": {key: value for key, value in RERANKER_ROUTE_DEFAULTS.items() if key},
        "decision": DECISION_ROUTE_DEFAULTS,
    }[kind]


def normalize_route(kind: str, provider: str, api_type: str, base_url: str, model: str) -> dict[str, str]:
    """Fill provider presets and reject endpoints a run would refuse."""
    provider = provider.strip().lower()
    table = _provider_table(kind)
    if provider not in table:
        raise SettingsError("connection_provider_unsupported")
    if kind == "llm":
        default_api_type, default_base_url, default_model = table[provider]
        api_type = api_type.strip().lower() or default_api_type
        if api_type not in LLM_API_TYPES:
            raise SettingsError("connection_api_type_unsupported")
    else:
        default_model, default_base_url = table[provider]
        api_type = ""
    route = {
        "provider": provider,
        "api_type": api_type,
        "base_url": (base_url.strip() or default_base_url).rstrip("/"),
        "model": model.strip() or default_model,
    }
    url = urlsplit(route["base_url"])
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username
            or url.password or url.query or url.fragment):
        raise SettingsError("connection_base_url_invalid")
    if not route["model"]:
        raise SettingsError("connection_model_required")
    return route


def requires_key(kind: str, provider: str) -> bool:
    return not (kind == "llm" and provider == "ollama")


class WorkspaceSettingsStore:
    def __init__(self, database_path: Path | str, credentials: EncryptedRunCredentialStore) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.credentials = credentials

    # -- storage helpers -------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _encrypt(self, scope: str, value: str) -> tuple[bytes | None, bytes | None]:
        if not value:
            return None, None
        nonce = os.urandom(12)
        aad = f"paperseek.workspace_settings|{scope}|{KEY_VERSION}".encode()
        return AESGCM(self.credentials.master_key()).encrypt(nonce, value.encode("utf-8"), aad), nonce

    def _decrypt(self, scope: str, ciphertext: bytes | None, nonce: bytes | None) -> str:
        if not ciphertext or not nonce:
            return ""
        aad = f"paperseek.workspace_settings|{scope}|{KEY_VERSION}".encode()
        return AESGCM(self.credentials.master_key()).decrypt(nonce, ciphertext, aad).decode("utf-8")

    @staticmethod
    def _test(row: sqlite3.Row) -> dict[str, object]:
        return {
            "status": row["test_status"],
            "latency_ms": row["test_latency_ms"],
            "code": row["test_code"],
            "tested_at": row["tested_at"],
        }

    # -- model connections -----------------------------------------------
    def _connection_rows(self) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            return connection.execute("SELECT * FROM model_connections ORDER BY created_at, rowid").fetchall()

    def _public_connection(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "provider": row["provider"],
            "api_type": row["api_type"],
            "base_url": row["base_url"],
            "model": row["model"],
            "has_key": bool(row["ciphertext"]),
            "requires_key": requires_key(row["kind"], row["provider"]),
            "test": self._test(row),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row(self, connection_id: str) -> sqlite3.Row:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM model_connections WHERE id = ?", (connection_id,)).fetchone()
        if row is None:
            raise SettingsError("connection_not_found", 404)
        return row

    def connection(self, connection_id: str) -> dict[str, object]:
        return self._public_connection(self._row(connection_id))

    def connection_secret(self, connection_id: str, kind: str | None = None) -> tuple[dict[str, str], str]:
        row = self._row(connection_id)
        if kind is not None and row["kind"] != kind:
            raise SettingsError("connection_kind_mismatch")
        route = {key: row[key] for key in ("provider", "api_type", "base_url", "model")}
        return route, self._decrypt(f"connection|{row['id']}", row["ciphertext"], row["nonce"])

    def create_connection(self, request: ConnectionInput) -> dict[str, object]:
        route = normalize_route(request.kind, request.provider, request.api_type, request.base_url, request.model)
        key = (request.api_key or "").strip()
        if requires_key(request.kind, route["provider"]) and not key:
            raise SettingsError("connection_key_required")
        connection_id = str(uuid4())
        ciphertext, nonce = self._encrypt(f"connection|{connection_id}", key)
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO model_connections (id, kind, provider, api_type, base_url, model,
                   ciphertext, nonce, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (connection_id, request.kind, route["provider"], route["api_type"], route["base_url"],
                 route["model"], ciphertext, nonce, now, now),
            )
            connection.commit()
        return self._public_connection(self._row(connection_id))

    def update_connection(self, connection_id: str, request: ConnectionInput) -> dict[str, object]:
        row = self._row(connection_id)
        if request.kind != row["kind"]:
            raise SettingsError("connection_kind_mismatch")
        route = normalize_route(request.kind, request.provider, request.api_type, request.base_url, request.model)
        same_endpoint = route["provider"] == row["provider"] and route["base_url"] == row["base_url"]
        if request.api_key is None and not same_endpoint and requires_key(request.kind, route["provider"]):
            # A stored key never follows a connection to a different endpoint.
            raise SettingsError("connection_key_required")
        key = (request.api_key if request.api_key is not None else
               self._decrypt(f"connection|{connection_id}", row["ciphertext"], row["nonce"])).strip()
        if requires_key(request.kind, route["provider"]) and not key:
            raise SettingsError("connection_key_required")
        ciphertext, nonce = self._encrypt(f"connection|{connection_id}", key)
        changed = key != self._decrypt(f"connection|{connection_id}", row["ciphertext"], row["nonce"]) or any(
            route[name] != row[name] for name in route
        )
        with closing(self._connect()) as connection:
            connection.execute(
                f"""UPDATE model_connections SET provider = ?, api_type = ?, base_url = ?, model = ?,
                   ciphertext = ?, nonce = ?, updated_at = ?
                   {", test_status = 'untested', test_latency_ms = NULL, test_code = '', tested_at = NULL" if changed else ""}
                   WHERE id = ?""",
                (route["provider"], route["api_type"], route["base_url"], route["model"],
                 ciphertext, nonce, _now(), connection_id),
            )
            connection.commit()
        return self._public_connection(self._row(connection_id))

    def delete_connection(self, connection_id: str, replacement: str = "") -> None:
        row = self._row(connection_id)
        defaults = self._stored_defaults()
        roles = [name for name in ("search_llm", "review_llm", "embedding", "reranker", "decision")
                 if self.defaults()[name] == connection_id]
        if roles:
            others = [item for item in self._connection_rows() if item["kind"] == row["kind"] and item["id"] != connection_id]
            if replacement:
                if not any(item["id"] == replacement for item in others):
                    raise SettingsError("connection_replacement_invalid")
            elif others:
                raise SettingsError("connection_in_use", 409)
            for name in roles:
                defaults[name] = replacement
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM model_connections WHERE id = ?", (connection_id,))
            self._write_defaults(connection, defaults)
            connection.commit()

    def clear_secrets(self) -> dict[str, int]:
        """Delete every saved model connection and data-source key; source options stay."""
        defaults = self._stored_defaults()
        for name in ("search_llm", "review_llm", "embedding", "reranker", "decision"):
            defaults.pop(name, None)
        # Without connections, only the built-in pre-ranking remains usable.
        defaults["pre_ranking"] = "local_fusion"
        with closing(self._connect()) as connection:
            connections = connection.execute("SELECT COUNT(*) FROM model_connections").fetchone()[0]
            sources = connection.execute("SELECT COUNT(*) FROM source_settings WHERE ciphertext IS NOT NULL").fetchone()[0]
            connection.execute("DELETE FROM model_connections")
            connection.execute("""UPDATE source_settings SET ciphertext = NULL, nonce = NULL, test_status = 'untested',
                test_latency_ms = NULL, test_code = '', tested_at = NULL WHERE ciphertext IS NOT NULL""")
            self._write_defaults(connection, defaults)
            connection.commit()
        return {"connections": connections, "source_keys": sources}

    def record_connection_test(self, connection_id: str, result: dict[str, object]) -> None:
        self._record_test("model_connections", "id", connection_id, result)

    def _record_test(self, table: str, column: str, identity: str, result: dict[str, object]) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                f"""UPDATE {table} SET test_status = ?, test_latency_ms = ?, test_code = ?, tested_at = ?
                   WHERE {column} = ?""",
                ("ok" if result["ok"] else "failed", result.get("latency_ms"), result.get("code") or "",
                 _now(), identity),
            )
            connection.commit()

    # -- defaults ----------------------------------------------------------
    def _stored_defaults(self) -> dict[str, str]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT value_json FROM workspace_settings WHERE key = 'defaults'").fetchone()
        value = json.loads(row["value_json"]) if row else {}
        return {str(key): str(item) for key, item in value.items() if isinstance(item, str)}

    @staticmethod
    def _write_defaults(connection: sqlite3.Connection, defaults: dict[str, str]) -> None:
        connection.execute(
            """INSERT INTO workspace_settings (key, value_json) VALUES ('defaults', ?)
               ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json""",
            (json.dumps(defaults, sort_keys=True),),
        )

    def defaults(self) -> dict[str, str]:
        """Stored choices, falling back to the first saved connection of each kind."""
        stored = self._stored_defaults()
        rows = self._connection_rows()
        ids = {kind: [row["id"] for row in rows if row["kind"] == kind] for kind in ("llm", "embedding", "reranker", "decision")}

        def pick(name: str, kind: str) -> str:
            value = stored.get(name, "")
            return value if value in ids[kind] else (ids[kind][0] if ids[kind] else "")

        usable = [source["id"] for source in self.sources() if source["usable"]]
        source = stored.get("source", "")
        if source not in usable:
            source = "openalex" if "openalex" in usable else (usable[0] if usable else "")
        mode = stored.get("pre_ranking", "local_fusion")
        return {
            "search_llm": pick("search_llm", "llm"),
            "review_llm": pick("review_llm", "llm"),
            "pre_ranking": mode if mode in {"local_fusion", "embedding_rerank", "decision"} else "local_fusion",
            "embedding": pick("embedding", "embedding"),
            "reranker": pick("reranker", "reranker"),
            "decision": pick("decision", "decision"),
            "source": source,
        }

    def save_defaults(self, request: DefaultsInput) -> dict[str, str]:
        stored = self._stored_defaults()
        rows = {row["id"]: row["kind"] for row in self._connection_rows()}
        kinds = {"search_llm": "llm", "review_llm": "llm", "embedding": "embedding",
                 "reranker": "reranker", "decision": "decision"}
        for name, value in request.model_dump(exclude_none=True).items():
            if name in kinds and value and rows.get(value) != kinds[name]:
                raise SettingsError("connection_not_found", 404)
            if name == "source" and value and not any(item["id"] == value and item["usable"] for item in self.sources()):
                raise SettingsError("source_unavailable")
            stored[name] = value
        with closing(self._connect()) as connection:
            self._write_defaults(connection, stored)
            connection.commit()
        return self.defaults()

    # -- data sources ------------------------------------------------------
    def _source_rows(self) -> dict[str, sqlite3.Row]:
        with closing(self._connect()) as connection:
            return {row["source_id"]: row for row in connection.execute("SELECT * FROM source_settings")}

    def sources(self, deployment: CommunityDeploymentSettings | None = None) -> list[dict[str, object]]:
        from paperseek_community.composition import deployment_source_key

        rows = self._source_rows()
        result = []
        for definition in SOURCES:
            row = rows.get(definition.id)
            stored_key = bool(row and row["ciphertext"])
            environment_key = bool(deployment and deployment_source_key(definition.id, deployment))
            has_key = stored_key or environment_key
            options = json.loads(row["options_json"]) if row else {}
            result.append({
                "id": definition.id,
                "has_key": has_key,
                "key_origin": "settings" if stored_key else "environment" if environment_key else "",
                "usable": definition.api_key != "required" or has_key,
                "options": {name: str(options.get(name, "")) for name in SOURCE_OPTIONS.get(definition.id, ())},
                "test": self._test(row) if row else {"status": "untested", "latency_ms": None, "code": "", "tested_at": None},
            })
        return result

    def source_secret(self, source_id: str) -> tuple[str, dict[str, str]]:
        row = self._source_rows().get(source_id)
        if row is None:
            return "", {}
        options = json.loads(row["options_json"])
        return self._decrypt(f"source|{source_id}", row["ciphertext"], row["nonce"]), {
            str(key): str(value) for key, value in options.items()
        }

    def save_source(self, source_id: str, request: SourceSettingsInput) -> None:
        definition = SOURCE_BY_ID.get(source_id)
        if definition is None:
            raise SettingsError("source_not_found", 404)
        current_key, current_options = self.source_secret(source_id)
        key = current_key if request.api_key is None else request.api_key.strip()
        if key and definition.api_key == "not_required":
            raise SettingsError("source_key_not_supported")
        options = dict(current_options)
        if request.options is not None:
            allowed = SOURCE_OPTIONS.get(source_id, ())
            if any(name not in allowed for name in request.options):
                raise SettingsError("source_option_unsupported")
            options.update({name: value.strip()[:320] for name, value in request.options.items()})
        ciphertext, nonce = self._encrypt(f"source|{source_id}", key)
        changed = key != current_key or options != current_options
        with closing(self._connect()) as connection:
            connection.execute(
                f"""INSERT INTO source_settings (source_id, ciphertext, nonce, options_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(source_id) DO UPDATE SET ciphertext = excluded.ciphertext,
                   nonce = excluded.nonce, options_json = excluded.options_json, updated_at = excluded.updated_at
                   {", test_status = 'untested', test_latency_ms = NULL, test_code = '', tested_at = NULL" if changed else ""}""",
                (source_id, ciphertext, nonce, json.dumps(options, sort_keys=True), _now()),
            )
            connection.commit()

    def record_source_test(self, source_id: str, result: dict[str, object]) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO source_settings (source_id, updated_at) VALUES (?, ?)", (source_id, _now()),
            )
            connection.commit()
        self._record_test("source_settings", "source_id", source_id, result)

    # -- composite views ---------------------------------------------------
    def snapshot(self, deployment: CommunityDeploymentSettings) -> dict[str, object]:
        return {
            "connections": [self._public_connection(row) for row in self._connection_rows()],
            "sources": self.sources(deployment),
            "defaults": self.defaults(),
        }

    def apply_to_submission(self, submission: RunSubmission) -> RunSubmission:
        """Replace saved-connection ids with routes and per-run keys."""
        data = submission.model_dump(mode="python")
        selection = data.pop("connections", None) or {}
        credentials = data["credentials"]
        if selection.get("llm"):
            route, key = self.connection_secret(selection["llm"], "llm")
            data["llm"] = route
            credentials["llm"]["api_key"] = key
        retrieval = data["retrieval"]
        mode = retrieval.get("mode")
        kinds = ("embedding", "reranker") if mode == "embedding_rerank" else ("decision",) if mode == "decision" else ()
        for kind in kinds:
            if selection.get(kind):
                route, key = self.connection_secret(selection[kind], kind)
                retrieval[kind] = {"provider": route["provider"], "model": route["model"], "base_url": route["base_url"]}
                credentials[kind]["api_key"] = key
        key, options = self.source_secret(data["source"])
        if not credentials["source"]["api_key"]:
            credentials["source"]["api_key"] = key
        contacts = data["source_contacts"]
        for name in ("openalex_email", "crossref_email", "pubmed_email"):
            if not contacts.get(name) and options.get(name):
                contacts[name] = options[name]
        if options.get("pubmed_tool") and contacts.get("pubmed_tool") in {"", "paperseek"}:
            contacts["pubmed_tool"] = options["pubmed_tool"]
        if not data.get("wos_db") and options.get("wos_db"):
            data["wos_db"] = options["wos_db"]
        return RunSubmission.model_validate(data)


# -- connectivity probes -------------------------------------------------------
PROBE_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def _probe_code(exc: BaseException) -> str:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "timeout"
    if isinstance(exc, httpx.RequestError):
        return "connection_failed"
    return "request_failed"


async def probe_connection(kind: str, route: dict[str, str], api_key: str) -> dict[str, object]:
    """One small real request; any 2xx answer proves endpoint, model and key."""
    base = route["base_url"].rstrip("/")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    prompt = "Reply with OK."
    requests: list[tuple[str, dict]] = []
    if kind == "llm" and route["api_type"] == "anthropic_messages":
        headers = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
        requests = [(f"{base}/v1/messages", {"model": route["model"], "max_tokens": 16,
                                            "messages": [{"role": "user", "content": prompt}]})]
    elif kind == "llm" and route["api_type"] == "openai_responses":
        body = {"model": route["model"], "input": prompt, "max_output_tokens": 16}
        requests = [(f"{base}/responses", body), (f"{base}/responses", {"model": route["model"], "input": prompt})]
    elif kind == "llm":
        body = {"model": route["model"], "messages": [{"role": "user", "content": prompt}], "max_tokens": 16}
        requests = [(f"{base}/chat/completions", body),
                    (f"{base}/chat/completions", {key: value for key, value in body.items() if key != "max_tokens"})]
    elif kind == "embedding":
        model = route["model"].replace(";", ",").split(",")[0].strip()
        body = {"model": model, "input": ["connectivity check"], "encoding_format": "float"}
        if route["provider"] == "nvidia":
            body["input_type"] = "query"
        requests = [(f"{base}/embeddings", body)]
    elif kind == "reranker":
        model = route["model"].replace(";", ",").split(",")[0].strip()
        if route["provider"] == "nvidia":
            url = base if base.endswith(("/reranking", "/ranking")) else f"{base}/reranking"
            requests = [(url, {"model": model, "query": {"text": "connectivity check"},
                               "passages": [{"text": "connectivity check"}]})]
        else:
            requests = [(f"{base}/rerank", {"model": model, "query": "connectivity check",
                                             "documents": ["connectivity check"], "top_n": 1})]
    else:
        requests = [(f"{base}/systemone", {
            "model": route["model"],
            "state": decision_state("connectivity check", ""),
            "questions": {"probe": decision_question(PaperRecord(uid="probe", title="Connectivity check"))},
        })]
    started = time.perf_counter()
    try:
        async with create_http_client([route]) as client:
            for index, (url, body) in enumerate(requests):
                response = await client.post(url, json=body, headers=headers, timeout=PROBE_TIMEOUT)
                if response.status_code not in {400, 422} or index == len(requests) - 1:
                    break
    except Exception as exc:  # noqa: BLE001 - every failure is reported, never raised
        return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "code": _probe_code(exc)}
    latency = int((time.perf_counter() - started) * 1000)
    if 200 <= response.status_code < 300:
        return {"ok": True, "latency_ms": latency, "code": ""}
    return {"ok": False, "latency_ms": latency, "code": f"http_{response.status_code}"}


async def probe_source(
    source_id: str, api_key: str, options: dict[str, str], settings: CommunityDeploymentSettings,
) -> dict[str, object]:
    from paperseek_community.composition import build_source

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
            transport = AsyncHttpTransport(client=client, context=RequestContext(
                step_key="settings.source_test", deadline_at=time.monotonic() + 30,
            ))
            source = build_source(
                source_id, transport, api_key,
                wos_db=options.get("wos_db") or settings.wos_db,
                contacts={key: value for key, value in options.items() if key != "wos_db"},
                settings=settings,
            )
            await source.search(SourceSearchRequest(query="machine learning", limit=1))
    except SourceError as exc:
        code = f"http_{exc.status}" if exc.status else str(getattr(exc, "failure_kind", "") or "request_failed")
        return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "code": code}
    except Exception as exc:  # noqa: BLE001 - every failure is reported, never raised
        return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "code": _probe_code(exc)}
    return {"ok": True, "latency_ms": int((time.perf_counter() - started) * 1000), "code": ""}
