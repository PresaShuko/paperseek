from __future__ import annotations

from paperseek_app.pre_ranking import resolve_retrieval_route

from collections.abc import Mapping
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit

from paperseek_app.configuration import LLM_PROVIDERS, EMBEDDING_ROUTE_DEFAULTS, RERANKER_ROUTE_DEFAULTS, normalize_wos_db, resolve_llm_route
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_community.credential_resolution import resolve_model_credentials
from paperseek_app.source_catalog import SOURCE_BY_ID
from paperseek_community.legacy_settings import classify_legacy_environment


LLM_API_TYPES = {"openai_chat", "openai_responses", "anthropic_messages"}
EMBEDDING_PROVIDERS = frozenset(EMBEDDING_ROUTE_DEFAULTS)
RERANKER_PROVIDERS = frozenset(RERANKER_ROUTE_DEFAULTS)


def community_doctor_report(
    database_path: Path | str,
    settings: CommunityDeploymentSettings,
    *,
    source: str,
    wos_db: str | None = None,
) -> dict[str, object]:
    database = Path(database_path).expanduser().resolve()
    checks = [
        _check(
            "environment.python",
            "pass" if sys.version_info >= (3, 12) else "fail",
            "info" if sys.version_info >= (3, 12) else "error",
            "Python 3.12 or newer is available."
            if sys.version_info >= (3, 12)
            else "PaperSeek requires Python 3.12 or newer.",
        )
    ]
    nearest = database.parent
    while not nearest.exists() and nearest != nearest.parent:
        nearest = nearest.parent
    writable = nearest.is_dir() and os.access(nearest, os.W_OK)
    checks.append(
        _check(
            "storage.directory",
            "pass" if writable else "fail",
            "info" if writable else "error",
            "The database directory is writable or can be created."
            if writable
            else "The database directory cannot be created or written.",
            [] if writable else ["Choose a writable --database location."],
        )
    )
    legacy = classify_legacy_environment()
    if legacy["mappable_settings"]:
        checks.append(
            _check(
                "configuration.legacy_settings",
                "warning",
                "warning",
                "Legacy settings require a one-time migration.",
                [
                    "Run paperseek migrate --legacy-env OLD.env --output-env NEW.env."
                ],
                {
                    **legacy,
                    "error_code": "legacy_settings_detected",
                },
            )
        )
    database_ok = writable
    database_summary = "A new SQLite database can be created when PaperSeek starts."
    if database.exists():
        try:
            uri = f"file:{database.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                database_ok = connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
            database_summary = (
                "The SQLite database passed its integrity check."
                if database_ok
                else "The SQLite database failed its integrity check."
            )
        except sqlite3.Error:
            database_ok = False
            database_summary = "The SQLite database could not be opened read-only."
    checks.append(
        _check(
            "database.access",
            "pass" if database_ok else "fail",
            "info" if database_ok else "error",
            database_summary,
            [] if database_ok else ["Restore the database or choose another --database path."],
        )
    )
    configuration = {
        "source": source,
        "wos_db": normalize_wos_db(wos_db, settings.wos_db),
        "llm": {},
        "retrieval": {},
        "credentials": {},
    }
    checks.extend(run_configuration_diagnostics(configuration, settings)["checks"])
    summary = {
        status: sum(check["status"] == status for check in checks)
        for status in ("pass", "warning", "fail")
    }
    status = "fail" if summary["fail"] else "warning" if summary["warning"] else "pass"
    return {
        "ok": status != "fail",
        "status": status,
        "network": "not_run",
        "checks": checks,
        "summary": summary,
    }


def run_configuration_diagnostics(
    configuration: Mapping[str, object],
    settings: CommunityDeploymentSettings,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    source = str(configuration.get("source") or "openalex").strip().lower()
    llm = _mapping(configuration.get("llm"))
    try:
        retrieval = resolve_retrieval_route(_mapping(configuration.get("retrieval")))
    except ValueError:
        retrieval = {}
        checks.append(_check("retrieval.mode", "fail", "error", "The preliminary ranking configuration is invalid."))
    credentials = _mapping(configuration.get("credentials"))
    source_credentials = _mapping(credentials.get("source"))

    source_definition = SOURCE_BY_ID.get(source)
    if source_definition is None:
        checks.append(_check(
            "source.supported", "fail", "error", "The selected data source is not supported.",
            ["Choose one of the data sources returned by /api/v1/sources."],
        ))
    else:
        checks.append(_check(
            "source.supported", "pass", "info", f"{source_definition.label} is supported.",
        ))
        source_key = str(source_credentials.get("api_key") or _source_key(source, settings)).strip()
        requirement = source_definition.api_key
        if requirement == "required" and not source_key:
            checks.append(_check(
                "source.credentials", "fail", "error", "The selected source requires a credential.",
                [source_definition.credential_guidance_label or "Configure the source credential."],
            ))
        elif requirement in {"recommended", "optional"} and not source_key:
            checks.append(_check(
                "source.credentials", "warning", "warning",
                f"A source credential is {requirement} but is not configured.",
                [source_definition.credential_guidance_label or "Configure the source credential if available."],
            ))
        else:
            checks.append(_check(
                "source.credentials", "pass", "info",
                "The source credential requirement is satisfied or no credential is required.",
            ))
        if source_definition.status == "temporarily_unavailable":
            checks.append(_check(
                "source.status", "warning", "warning",
                f"{source_definition.label} is currently marked temporarily unavailable.",
                ["Choose another source if the service is unavailable."],
            ))
        if source == "wos":
            wos_db = normalize_wos_db(configuration.get("wos_db"), settings.wos_db)
            checks.append(_check(
                "source.wos_database",
                "pass",
                "info",
                "The WoS database selector is configured.",
                details={"database": wos_db},
            ))

    route = resolve_llm_route(settings, dict(llm))
    model_keys = resolve_model_credentials(settings, route, retrieval, credentials)
    provider = route["provider"].strip().lower()
    api_type = route["api_type"].strip().lower()
    if provider in LLM_PROVIDERS:
        checks.append(_check("llm.provider", "pass", "info", f"LLM provider '{provider}' is supported."))
    else:
        checks.append(_check(
            "llm.provider", "fail", "error", "The selected LLM provider is not supported.",
            ["Choose a supported LLM provider."],
        ))
    if api_type in LLM_API_TYPES:
        checks.append(_check("llm.api_type", "pass", "info", f"LLM API type '{api_type}' is supported."))
    else:
        checks.append(_check(
            "llm.api_type", "fail", "error", "The selected LLM API type is not supported.",
            ["Choose OpenAI Chat, OpenAI Responses, or Anthropic Messages."],
        ))
    llm_key = model_keys["llm"]
    if provider != "ollama" and not llm_key:
        checks.append(_check(
            "llm.api_key", "fail", "error", "An LLM credential is required unless provider is Ollama.",
            ["Configure the LLM API key or choose Ollama for a local endpoint."],
        ))
    else:
        checks.append(_check("llm.api_key", "pass", "info", "The LLM credential requirement is satisfied."))
    checks.append(_url_check("llm.base_url", route["base_url"], provider))

    embedding = _mapping(retrieval.get("embedding"))
    embedding_provider = str(embedding.get("provider") or "local").strip().lower()
    embedding_key = model_keys["embedding"]
    checks.append(_retrieval_check(
        "retrieval.embedding",
        embedding_provider,
        str(embedding.get("model") or "").strip(),
        str(embedding.get("base_url") or "").strip(),
        embedding_key,
        allowed=EMBEDDING_PROVIDERS,
        disabled={"local"},
        disabled_summary="Local embedding is enabled and needs no external credential.",
    ))

    reranker = _mapping(retrieval.get("reranker"))
    reranker_provider = str(reranker.get("provider") or "").strip().lower()
    reranker_key = model_keys["reranker"]
    checks.append(_retrieval_check(
        "retrieval.reranker",
        reranker_provider,
        str(reranker.get("model") or "").strip(),
        str(reranker.get("base_url") or "").strip(),
        reranker_key,
        allowed=RERANKER_PROVIDERS,
        disabled={""},
        disabled_summary="External reranking is off; the existing local order is retained.",
    ))

    if retrieval.get("mode") == "decision":
        decision = retrieval["decision"]
        checks.append(_retrieval_check(
            "retrieval.decision", decision["provider"], decision["model"], decision["base_url"],
            model_keys["decision"],
            allowed={"siliconflow", "typesafe"}, disabled=set(), disabled_summary="",
        ))

    summary = {status: sum(check["status"] == status for check in checks) for status in ("pass", "warning", "fail")}
    status = "fail" if summary["fail"] else "warning" if summary["warning"] else "pass"
    return {"ok": status != "fail", "status": status, "checks": checks, "summary": summary}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _source_key(source: str, settings: CommunityDeploymentSettings) -> str:
    from paperseek_community.composition import deployment_source_key

    return deployment_source_key(source, settings)


def _check(
    check_id: str,
    status: str,
    severity: str,
    summary: str,
    actions: list[str] | None = None,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": check_id,
        "status": status,
        "severity": severity,
        "summary": summary,
        "actions": actions or [],
        "details": details or {},
        "ok": status != "fail",
    }


def _url_check(check_id: str, value: str, provider: str) -> dict[str, object]:
    url = value.strip()
    if not url:
        return _check(check_id, "warning", "warning", "The base URL is empty; deployment defaults will be used.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return _check(
            check_id, "fail", "error", "The base URL must use http:// or https://.",
            ["Correct the endpoint URL."],
        )
    local = parsed.hostname.lower() in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not local:
        return _check(
            check_id, "warning", "warning", "A remote model endpoint is not using HTTPS.",
            ["Use HTTPS for remote model providers."],
        )
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    redacted = f"{parsed.scheme}://{host}{parsed.path}".rstrip("/")
    return _check(check_id, "pass", "info", f"The base URL looks valid for '{provider}'.", details={"base_url": redacted})


def _retrieval_check(
    check_id: str,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    *,
    allowed: set[str],
    disabled: set[str],
    disabled_summary: str,
) -> dict[str, object]:
    if provider not in allowed:
        return _check(check_id, "fail", "error", "The selected retrieval provider is not supported.")
    if provider in disabled:
        return _check(check_id, "pass", "info", disabled_summary)
    if not model or not base_url or not api_key:
        return _check(
            check_id, "fail", "error", "External retrieval requires model, base URL, and a credential.",
            ["Complete the external retrieval configuration or use the local/off default."],
        )
    endpoint = _url_check(check_id, base_url, provider)
    if endpoint["status"] == "fail":
        return endpoint
    return _check(check_id, endpoint["status"], endpoint["severity"], "External retrieval configuration is complete.", endpoint["actions"], endpoint["details"])
