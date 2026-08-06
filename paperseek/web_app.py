
from pathlib import Path
import json
import logging
import re
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from paperseek.application import (
    RunOwnershipLost,
    SearchRunSession,
    stream_persisted_search,
    submit_background_search,
)
from paperseek.api.routes import build_history_router, build_runs_router
from paperseek.api.schemas import DiagnosticRequest, SearchRequest
from paperseek.client import ApiException
from paperseek.config import AgentConfig
from paperseek.config_compiler import compile_agent_config
from paperseek.diagnostics import run_doctor, smoke_source
from paperseek.disciplines import (
    list_discipline_fields,
    list_source_filter_options,
    source_filter_label,
    source_filter_mode,
)
from paperseek.env_loader import load_env_file
from paperseek.history import HistoryStore
from paperseek.llm_client import LLMError, create_llm_client
from paperseek.providers import ProviderError
from paperseek.run_executor import InProcessRunExecutor
from paperseek.search_agent import PaperSeekAgent
from paperseek.source_metadata import list_source_metadata, supported_source_ids


STATIC_DIR = Path(__file__).parent / "static"
STREAM_HEARTBEAT_SECONDS = 10.0
STREAM_HEARTBEAT_PADDING = " " * 2048

load_env_file()

app = FastAPI(title="PaperSeek", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
logger = logging.getLogger("paperseek.web_app")
_RUN_EXECUTOR = InProcessRunExecutor()


FIELD_LABELS = {
    "question": "Research Question",
    "data_source": "Data Source",
    "wos_api_key": "WoS API Key",
    "openalex_api_key": "OpenAlex API Key",
    "openalex_email": "OpenAlex Email",
    "crossref_email": "Crossref Email",
    "semantic_scholar_api_key": "Semantic Scholar API Key",
    "pubmed_api_key": "PubMed API Key",
    "pubmed_email": "PubMed Email",
    "pubmed_tool": "PubMed Tool",
    "serper_api_key": "Serper API Key",
    "llm_api_key": "LLM API Key",
    "llm_api_type": "LLM API Type",
    "discipline_fields": "Discipline Fields",
    "expand_citations": "Expand Citations",
    "target_min": "Min Results",
    "target_max": "Max Results",
    "max_iterations": "Iterations",
    "search_budget": "Search Budget",
}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, exc: RequestValidationError):
    messages = []
    for error in exc.errors():
        loc = error.get("loc", [])
        field = loc[-1] if loc else ""
        label = FIELD_LABELS.get(field, str(field))
        error_type = error.get("type", "")
        msg = str(error.get("msg", "invalid value")).replace("Value error, ", "")
        if error_type == "value_error":
            if "is required" in msg:
                messages.append(f"{label} is required.")
            else:
                messages.append(f"{label}: {msg}.")
        elif error_type == "string_too_short":
            messages.append(f"{label} is required.")
        elif "greater_than_equal" in error_type or "less_than_equal" in error_type:
            messages.append(f"{label} is outside the allowed range.")
        else:
            messages.append(f"{label}: {msg}.")
    return JSONResponse(status_code=422, content={"detail": " ".join(messages) or "Invalid request."})


def _compact_text(value, max_chars: int = 700) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?i)(x-apikey|api[_-]?key|authorization)\s*[:=]\s*[^,\s}]+", r"\1: [redacted]", text)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "..."
    return text


def _friendly_api_error(exc: ApiException) -> str:
    body = _compact_text(exc.body or exc.data)
    query = _compact_text(getattr(exc, "query", ""), max_chars=450)
    iteration = getattr(exc, "iteration", None)
    context = f" Iteration: {iteration}." if iteration else ""
    query_context = f" Query: {query}" if query else ""

    if "please use https" in body.lower():
        return "WoS Starter API now requires HTTPS. The client has been updated; restart the web server and try again."
    if exc.status == 401:
        return f"WoS API authorization failed. Check that the WoS API Key is valid and has Starter API access.{context}{query_context}"
    if exc.status == 403:
        return f"WoS API access was forbidden. Check whether this key is allowed to use Web of Science Starter API.{context}{query_context}"
    if exc.status == 400:
        suffix = f" Response: {body}" if body else ""
        return f"WoS rejected the generated query. Try a simpler question or increase the iteration count.{context}{query_context}{suffix}"
    if exc.status == 512:
        suffix = f" Response: {body}" if body else " No response body was returned."
        return (
            "Clarivate returned HTTP 512, a non-standard upstream/server error from the WoS API. "
            "This is usually not caused by the local web UI. Retry once; if it repeats, simplify the query or reduce special characters."
            f"{context}{query_context}{suffix}"
        )
    suffix = f" Response: {body}" if body else ""
    return f"WoS API request failed with status {exc.status or 'unknown'}.{context}{query_context}{suffix}"


def _friendly_provider_error(exc: ProviderError) -> str:
    body = _compact_text(exc.body)
    message = _compact_text(str(exc), max_chars=700)
    query = _compact_text(exc.query, max_chars=450)
    query_context = f" Query: {query}" if query else ""
    suffix = f" Response: {body}" if body else (f" Details: {message}" if message else "")
    status = exc.status or "unknown"
    return f"{exc.source.title()} API request failed with status {status}.{query_context}{suffix}"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/sources")
def sources():
    return {"sources": list_source_metadata()}


@app.get("/api/disciplines")
def disciplines():
    sources = {}
    for source in supported_source_ids():
        sources[source] = {
            "mode": source_filter_mode(source),
            "label": source_filter_label(source),
            "options": list_source_filter_options(source),
        }
    return {"disciplines": list_discipline_fields(), "sources": sources}


@app.get("/api/config/defaults")
def config_defaults():
    config = AgentConfig.from_env()
    return {
        "data_source": config.data_source,
        "search_budget": config.search_budget,
        "llm_provider": config.llm_provider,
        "llm_api_type": config.llm_api_type,
        "llm_model": config.llm_model,
        "llm_base_url": config.llm_base_url,
        "llm_max_tokens": config.llm_max_tokens,
        "target_min": config.target_min,
        "target_max": config.target_max,
        "max_iterations": config.max_iterations,
        "query_portfolio_enabled": config.query_portfolio_enabled,
        "query_portfolio_max": config.query_portfolio_max,
        "query_portfolio_limit": config.query_portfolio_limit,
        "discipline_fields": list(getattr(config, "discipline_fields", ()) or []),
        "expand_citations": config.expand_citations,
        "fetch_abstracts": config.fetch_abstracts,
        "has_wos_api_key": bool(config.wos_api_key),
        "has_openalex_api_key": bool(config.openalex_api_key),
        "has_openalex_email": bool(config.openalex_email),
        "has_crossref_email": bool(config.crossref_email),
        "has_semantic_scholar_api_key": bool(getattr(config, "semantic_scholar_api_key", "")),
        "has_pubmed_api_key": bool(getattr(config, "pubmed_api_key", "")),
        "has_pubmed_email": bool(getattr(config, "pubmed_email", "")),
        "has_serper_api_key": bool(getattr(config, "serper_api_key", "")),
        "has_llm_api_key": bool(config.llm_api_key),
    }


def _validate_payload(payload: SearchRequest):
    if payload.target_min > payload.target_max:
        raise HTTPException(status_code=400, detail="Target minimum cannot exceed target maximum.")
    env_config = AgentConfig.from_env()
    if payload.data_source == "wos" and not ((payload.wos_api_key or "").strip() or env_config.wos_api_key):
        raise HTTPException(status_code=400, detail="WoS API Key is required for WoS searches.")


def _config_from_payload(payload: SearchRequest) -> AgentConfig:
    environment = AgentConfig.from_env()
    explicit_fields = payload.model_fields_set
    overrides = {
        "data_source": payload.data_source,
        "wos_api_key": payload.wos_api_key,
        "openalex_api_key": payload.openalex_api_key,
        "openalex_email": payload.openalex_email,
        "crossref_email": payload.crossref_email,
        "semantic_scholar_api_key": payload.semantic_scholar_api_key,
        "pubmed_api_key": payload.pubmed_api_key,
        "pubmed_email": payload.pubmed_email,
        "pubmed_tool": payload.pubmed_tool,
        "serper_api_key": payload.serper_api_key,
        "llm_api_key": payload.llm_api_key,
        "llm_provider": payload.llm_provider,
        "llm_api_type": payload.llm_api_type,
        "llm_model": payload.llm_model,
        "llm_base_url": payload.llm_base_url,
        "wos_db": payload.wos_db,
        "discipline_fields": payload.discipline_fields,
        "fetch_abstracts": payload.fetch_abstracts,
        "expand_citations": payload.expand_citations,
        "target_min": payload.target_min,
        "target_max": payload.target_max,
        "retrieval_pool_min": payload.retrieval_pool_min,
        "retrieval_rrf_k": payload.retrieval_rrf_k,
        "retrieval_embedding_model": payload.retrieval_embedding_model,
        "retrieval_embedding_base_url": payload.retrieval_embedding_base_url,
        "retrieval_embedding_api_key": payload.retrieval_embedding_api_key,
        "retrieval_reranker_model": payload.retrieval_reranker_model,
        "retrieval_reranker_base_url": payload.retrieval_reranker_base_url,
        "retrieval_reranker_api_key": payload.retrieval_reranker_api_key,
        "retrieval_crossref_enrichment": payload.retrieval_crossref_enrichment,
    }
    if payload.search_budget != environment.search_budget:
        overrides["search_budget"] = payload.search_budget
    if payload.llm_max_tokens is not None:
        overrides["llm_max_tokens"] = payload.llm_max_tokens
    if payload.search_field:
        overrides["search_field"] = payload.search_field
    if "max_iterations" in explicit_fields:
        overrides["max_iterations"] = payload.max_iterations
    if "retrieval_pool_max" in explicit_fields:
        overrides["retrieval_pool_max"] = payload.retrieval_pool_max
    if "retrieval_lane_limit" in explicit_fields:
        overrides["retrieval_lane_limit"] = payload.retrieval_lane_limit
    if "query_portfolio_max" in explicit_fields:
        overrides["query_portfolio_max"] = int(payload.query_portfolio_max)
    if "query_portfolio_limit" in explicit_fields:
        overrides["query_portfolio_limit"] = int(payload.query_portfolio_limit)
    if isinstance(payload, SearchRequest):
        overrides["query_portfolio_enabled"] = payload.query_portfolio_enabled
    if payload.retrieval_embedding_provider:
        overrides["retrieval_embedding_provider"] = payload.retrieval_embedding_provider
    if payload.retrieval_reranker_provider:
        overrides["retrieval_reranker_provider"] = payload.retrieval_reranker_provider
    return compile_agent_config(overrides, environment=environment)


def _history_store_from_payload(payload) -> HistoryStore:
    return HistoryStore(
        timezone_name=getattr(payload, "client_timezone", "") or None,
        utc_offset_minutes=getattr(payload, "client_utc_offset_minutes", None),
    )


def _run_store_from_request(_request) -> HistoryStore:
    return HistoryStore()


def _submit_v1_run(request: Request, payload: SearchRequest, mode: str, source_run_id: str) -> dict:
    _validate_payload(payload)
    store = _run_store_from_request(request)
    if mode == "resume":
        source_run = store.get_run(source_run_id)
        expected_source = str(
            ((source_run or {}).get("params") or {}).get("data_source")
            or (source_run or {}).get("source")
            or ""
        ).strip().lower()
        if expected_source and payload.data_source != expected_source:
            raise HTTPException(
                status_code=409,
                detail="Resume must use the same data source as the saved checkpoint.",
            )

    config = _config_from_payload(payload)
    config.validate()

    def session_factory(owner_id: str) -> SearchRunSession:
        return SearchRunSession(
            store,
            config,
            payload.question,
            payload.data_source,
            existing_run_id=source_run_id if mode == "resume" else "",
            run_metadata={
                "interface": "api_v1",
                "operation": mode,
                "source_run_id": source_run_id,
                "credential_resume_mode": "request_or_environment",
            },
            owner_id=owner_id,
        )

    try:
        run_id = submit_background_search(
            _RUN_EXECUTOR,
            session_factory,
            lambda _persist: PaperSeekAgent(config, create_llm_client(config)),
            error_formatter=lambda exc: (
                _friendly_api_error(exc)
                if isinstance(exc, ApiException)
                else _friendly_provider_error(exc)
                if isinstance(exc, ProviderError)
                else str(exc)
            ),
            run_event={"operation": mode, "source_run_id": source_run_id},
        )
    except RunOwnershipLost as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "run_id": run_id,
        "status": "running",
        "source_run_id": source_run_id,
    }


app.include_router(
    build_runs_router(
        _run_store_from_request,
        _RUN_EXECUTOR,
        submitter=_submit_v1_run,
    )
)
app.include_router(
    build_history_router(
        _run_store_from_request,
        clear_confirmation_detail="Pass confirm=true to clear all local history.",
    )
)


@app.post("/api/diagnostics")
def diagnostics(payload: DiagnosticRequest):
    config = _config_from_payload(payload)
    return run_doctor(config)


@app.post("/api/smoke")
def smoke(payload: DiagnosticRequest):
    config = _config_from_payload(payload)
    query = (payload.question or "machine learning").strip() or "machine learning"
    return smoke_source(config, query=query, limit=1)


@app.post("/api/search/{run_id}/cancel")
def cancel_search(run_id: str):
    if not _RUN_EXECUTOR.cancel(run_id):
        raise HTTPException(status_code=404, detail="Search run is not active.")
    return {"cancelled": run_id}


@app.post("/api/search")
def search(payload: SearchRequest):
    _validate_payload(payload)
    config = _config_from_payload(payload)
    store = _history_store_from_payload(payload)
    session = SearchRunSession(
        store,
        config,
        payload.question,
        payload.data_source,
        resume_run_id=payload.resume_run_id or "",
    )
    session.start()

    try:
        config.validate()
        llm = create_llm_client(config)
        result = session.invoke(PaperSeekAgent(config, llm))
        response = session.response(result)
        session.complete(response)
    except ValueError as exc:
        session.fail(str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMError as exc:
        session.fail(str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ApiException as exc:
        message = _friendly_api_error(exc)
        session.fail(message)
        raise HTTPException(status_code=502, detail=message) from exc
    except ProviderError as exc:
        message = _friendly_provider_error(exc)
        session.fail(message)
        raise HTTPException(status_code=502, detail=message) from exc
    except Exception as exc:
        message = "Search failed. Check the local server logs for details."
        logger.exception("Unhandled search failure.")
        session.fail(message)
        raise HTTPException(status_code=500, detail=message) from exc

    return response


@app.post("/api/search/stream")
def search_stream(payload: SearchRequest):
    _validate_payload(payload)
    store = _history_store_from_payload(payload)

    def line(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    def session_factory(config: AgentConfig, owner_id: str) -> SearchRunSession:
        return SearchRunSession(
            store,
            config,
            payload.question,
            payload.data_source,
            resume_run_id=payload.resume_run_id or "",
            owner_id=owner_id,
        )

    def startup_events(config: AgentConfig):
        return [
            {"type": "log", "message": "Backend request accepted: POST /api/search/stream -> HTTP 200 OK."},
            {
                "type": "log",
                "message": (
                    f"Runtime config: source={config.data_source}; llm_provider={config.llm_provider}; "
                    f"api_type={config.llm_api_type}; model={config.llm_model}; target={config.target_min}-{config.target_max}; "
                    f"iterations={config.max_iterations}; search_budget={config.search_budget}."
                ),
            },
        ]

    def error_event(exc: Exception, _config: AgentConfig | None) -> dict:
        if isinstance(exc, ApiException):
            message = _friendly_api_error(exc)
        elif isinstance(exc, ProviderError):
            message = _friendly_provider_error(exc)
        elif isinstance(exc, (ValueError, LLMError)):
            message = str(exc)
        else:
            logger.exception("Unhandled streaming search failure.")
            message = "Search failed. Check the local server logs for details."
        return {"type": "error", "message": message}

    def generator():
        for item in stream_persisted_search(
            _RUN_EXECUTOR,
            lambda: _config_from_payload(payload),
            session_factory,
            lambda config, _send: PaperSeekAgent(config, create_llm_client(config)),
            startup_events=startup_events,
            error_event_factory=error_event,
            heartbeat_seconds=STREAM_HEARTBEAT_SECONDS,
            heartbeat_factory=lambda: {"type": "heartbeat", "ts": time.time(), "pad": STREAM_HEARTBEAT_PADDING},
        ):
            yield line(item)

    return StreamingResponse(
        generator(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def main():
    uvicorn.run("paperseek.web_app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
