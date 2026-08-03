
from pathlib import Path
import inspect
import json
import logging
from queue import Empty, Queue
import re
import time
from threading import Event, Lock, Thread
from typing import Any, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from paperseek_core.budgets import (
    DEFAULT_SEARCH_BUDGET,
    apply_search_budget,
    normalize_search_budget,
    search_budget_preset,
)
from paperseek.client import ApiException
from paperseek.config import AgentConfig, default_api_type, default_base_url, default_model
from paperseek.diagnostics import run_doctor, smoke_source
from paperseek.disciplines import (
    list_discipline_fields,
    list_source_filter_options,
    normalize_source_filter_values,
    source_filter_label,
    source_filter_mode,
)
from paperseek.env_loader import load_env_file
from paperseek.history import HistoryStore, result_payload_from_search_result, safe_search_params_from_config
from paperseek.llm_client import LLMError, create_llm_client
from paperseek.providers import ProviderError
from paperseek.search_agent import PaperSeekAgent, SearchCancelled
from paperseek.source_metadata import list_source_metadata, supported_source_ids


STATIC_DIR = Path(__file__).parent / "static"
STREAM_HEARTBEAT_SECONDS = 10.0
STREAM_HEARTBEAT_PADDING = " " * 2048

load_env_file()

app = FastAPI(title="PaperSeek", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
logger = logging.getLogger("paperseek.web_app")
_CANCEL_LOCK = Lock()
_CANCEL_EVENTS: dict[str, Event] = {}
_DEFAULT_WEB_BUDGET = search_budget_preset(DEFAULT_SEARCH_BUDGET)


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
    "search_loop_backend": "Search Loop Backend",
}


def _clean_search_loop_backend(value: str) -> str:
    value = (value or "auto").strip().lower() or "auto"
    if value not in {"auto", "langgraph", "native"}:
        raise ValueError("must be one of auto, langgraph, native")
    return value


class SearchRequest(BaseModel):
    question: str = Field(min_length=1)
    data_source: str = "openalex"
    search_budget: str = DEFAULT_SEARCH_BUDGET
    wos_api_key: Optional[str] = ""
    openalex_api_key: Optional[str] = ""
    openalex_email: Optional[str] = ""
    crossref_email: Optional[str] = ""
    semantic_scholar_api_key: Optional[str] = ""
    pubmed_api_key: Optional[str] = ""
    pubmed_email: Optional[str] = ""
    pubmed_tool: Optional[str] = ""
    serper_api_key: Optional[str] = ""
    llm_api_key: Optional[str] = ""
    llm_provider: str = ""
    llm_api_type: str = ""
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_max_tokens: Optional[int] = Field(default=None, ge=0, le=8192)
    wos_db: str = "WOS"
    search_field: Optional[str] = ""
    discipline_fields: List[str] = Field(default_factory=list)
    client_timezone: Optional[str] = ""
    client_utc_offset_minutes: Optional[int] = None
    fetch_abstracts: bool = False
    expand_citations: bool = True
    target_min: int = Field(default=5, ge=0, le=50)
    target_max: int = Field(default=50, ge=1, le=50)
    max_iterations: int = Field(default=_DEFAULT_WEB_BUDGET.max_iterations, ge=1, le=36)
    search_loop_backend: str = "auto"
    retrieval_pool_max: int = Field(default=_DEFAULT_WEB_BUDGET.retrieval_pool_max, ge=1, le=10000)
    retrieval_pool_min: int = Field(default=5, ge=0, le=50)
    retrieval_lane_limit: int = Field(default=_DEFAULT_WEB_BUDGET.retrieval_lane_limit, ge=1, le=1000)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    query_portfolio_enabled: bool = True
    query_portfolio_max: int = Field(default=_DEFAULT_WEB_BUDGET.query_portfolio_max, ge=1, le=6)
    query_portfolio_limit: int = Field(default=_DEFAULT_WEB_BUDGET.query_portfolio_limit, ge=1, le=100)
    retrieval_embedding_provider: Optional[str] = ""
    retrieval_embedding_model: Optional[str] = ""
    retrieval_embedding_base_url: Optional[str] = ""
    retrieval_embedding_api_key: Optional[str] = ""
    retrieval_reranker_provider: Optional[str] = ""
    retrieval_reranker_model: Optional[str] = ""
    retrieval_reranker_base_url: Optional[str] = ""
    retrieval_reranker_api_key: Optional[str] = ""
    retrieval_crossref_enrichment: bool = False
    resume_run_id: Optional[str] = ""

    @field_validator("question")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("is required")
        return value

    @field_validator("llm_provider")
    @classmethod
    def clean_provider(cls, value: str) -> str:
        return (value or "").strip().lower()

    @field_validator("llm_api_type")
    @classmethod
    def clean_api_type(cls, value: str) -> str:
        return (value or "").strip().lower()

    @field_validator("search_loop_backend")
    @classmethod
    def clean_search_loop_backend(cls, value: str) -> str:
        return _clean_search_loop_backend(value)

    @field_validator("search_budget")
    @classmethod
    def clean_search_budget(cls, value: str) -> str:
        return normalize_search_budget(value)

    @field_validator("data_source")
    @classmethod
    def supported_source(cls, value: str) -> str:
        value = (value or "openalex").strip().lower()
        if value not in supported_source_ids():
            raise ValueError(f"must be one of {', '.join(supported_source_ids())}")
        return value

    @field_validator("discipline_fields", mode="before")
    @classmethod
    def clean_discipline_fields(cls, value) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @model_validator(mode="after")
    def normalize_filters_for_source(self):
        self.discipline_fields = list(normalize_source_filter_values(self.data_source, self.discipline_fields))
        return self


class DiagnosticRequest(BaseModel):
    question: Optional[str] = "machine learning"
    data_source: str = "openalex"
    search_budget: str = DEFAULT_SEARCH_BUDGET
    wos_api_key: Optional[str] = ""
    openalex_api_key: Optional[str] = ""
    openalex_email: Optional[str] = ""
    crossref_email: Optional[str] = ""
    semantic_scholar_api_key: Optional[str] = ""
    pubmed_api_key: Optional[str] = ""
    pubmed_email: Optional[str] = ""
    pubmed_tool: Optional[str] = ""
    serper_api_key: Optional[str] = ""
    llm_api_key: Optional[str] = ""
    llm_provider: str = ""
    llm_api_type: str = ""
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_max_tokens: Optional[int] = Field(default=None, ge=0, le=8192)
    wos_db: str = "WOS"
    search_field: Optional[str] = ""
    discipline_fields: List[str] = Field(default_factory=list)
    client_timezone: Optional[str] = ""
    client_utc_offset_minutes: Optional[int] = None
    fetch_abstracts: bool = False
    expand_citations: bool = True
    target_min: int = Field(default=5, ge=0, le=50)
    target_max: int = Field(default=50, ge=1, le=50)
    max_iterations: int = Field(default=_DEFAULT_WEB_BUDGET.max_iterations, ge=1, le=36)
    search_loop_backend: str = "auto"
    retrieval_pool_max: int = Field(default=_DEFAULT_WEB_BUDGET.retrieval_pool_max, ge=1, le=10000)
    retrieval_pool_min: int = Field(default=5, ge=0, le=50)
    retrieval_lane_limit: int = Field(default=_DEFAULT_WEB_BUDGET.retrieval_lane_limit, ge=1, le=1000)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    retrieval_embedding_provider: Optional[str] = ""
    retrieval_embedding_model: Optional[str] = ""
    retrieval_embedding_base_url: Optional[str] = ""
    retrieval_embedding_api_key: Optional[str] = ""
    retrieval_reranker_provider: Optional[str] = ""
    retrieval_reranker_model: Optional[str] = ""
    retrieval_reranker_base_url: Optional[str] = ""
    retrieval_reranker_api_key: Optional[str] = ""
    retrieval_crossref_enrichment: bool = False

    @field_validator("llm_provider")
    @classmethod
    def clean_provider(cls, value: str) -> str:
        return (value or "").strip().lower()

    @field_validator("llm_api_type")
    @classmethod
    def clean_api_type(cls, value: str) -> str:
        return (value or "").strip().lower()

    @field_validator("search_loop_backend")
    @classmethod
    def clean_search_loop_backend(cls, value: str) -> str:
        return _clean_search_loop_backend(value)

    @field_validator("search_budget")
    @classmethod
    def clean_search_budget(cls, value: str) -> str:
        return normalize_search_budget(value)

    @field_validator("data_source")
    @classmethod
    def supported_source(cls, value: str) -> str:
        value = (value or "openalex").strip().lower()
        if value not in supported_source_ids():
            raise ValueError(f"must be one of {', '.join(supported_source_ids())}")
        return value

    @field_validator("discipline_fields", mode="before")
    @classmethod
    def clean_discipline_fields(cls, value) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @model_validator(mode="after")
    def normalize_filters_for_source(self):
        self.discipline_fields = list(normalize_source_filter_values(self.data_source, self.discipline_fields))
        return self


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
        "search_loop_backend": config.search_loop_backend,
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
    config = AgentConfig.from_env()
    if payload.search_budget != config.search_budget:
        apply_search_budget(config, payload.search_budget)
    explicit_fields = payload.model_fields_set
    env_provider = config.llm_provider
    payload_provider = payload.llm_provider or config.llm_provider
    provider_changed = bool(payload.llm_provider and payload_provider != env_provider)
    config.data_source = payload.data_source
    config.wos_api_key = payload.wos_api_key or config.wos_api_key
    config.openalex_api_key = payload.openalex_api_key or config.openalex_api_key
    config.openalex_email = payload.openalex_email or config.openalex_email
    config.crossref_email = payload.crossref_email or config.crossref_email
    config.semantic_scholar_api_key = payload.semantic_scholar_api_key or getattr(config, "semantic_scholar_api_key", "")
    config.pubmed_api_key = payload.pubmed_api_key or getattr(config, "pubmed_api_key", "")
    config.pubmed_email = payload.pubmed_email or getattr(config, "pubmed_email", "")
    config.pubmed_tool = payload.pubmed_tool or getattr(config, "pubmed_tool", "paperseek") or "paperseek"
    config.serper_api_key = payload.serper_api_key or getattr(config, "serper_api_key", "")
    config.llm_api_key = payload.llm_api_key or config.llm_api_key
    config.llm_provider = payload_provider
    if payload.llm_api_type:
        config.llm_api_type = payload.llm_api_type
    elif provider_changed or not config.llm_api_type:
        config.llm_api_type = default_api_type(config.llm_provider)
    if payload.llm_model:
        config.llm_model = payload.llm_model
    elif provider_changed or not config.llm_model:
        config.llm_model = default_model(config.llm_provider)
    if payload.llm_base_url:
        config.llm_base_url = payload.llm_base_url
    elif provider_changed or not config.llm_base_url:
        config.llm_base_url = default_base_url(config.llm_provider, config.llm_api_type)
    if payload.llm_max_tokens is not None:
        config.llm_max_tokens = payload.llm_max_tokens
    config.wos_db = payload.wos_db or config.wos_db or "WOS"
    config.search_field = payload.search_field or config.search_field or ""
    config.discipline_fields = normalize_source_filter_values(config.data_source, payload.discipline_fields)
    config.fetch_abstracts = payload.fetch_abstracts
    config.expand_citations = payload.expand_citations
    config.target_min = payload.target_min
    config.target_max = payload.target_max
    if "max_iterations" in explicit_fields:
        config.max_iterations = payload.max_iterations
    config.search_loop_backend = _clean_search_loop_backend(getattr(payload, "search_loop_backend", "auto"))
    if "retrieval_pool_max" in explicit_fields:
        config.retrieval_pool_max = payload.retrieval_pool_max
    config.retrieval_pool_min = payload.retrieval_pool_min
    if "retrieval_lane_limit" in explicit_fields:
        config.retrieval_lane_limit = payload.retrieval_lane_limit
    config.retrieval_rrf_k = payload.retrieval_rrf_k
    config.query_portfolio_enabled = bool(
        getattr(payload, "query_portfolio_enabled", config.query_portfolio_enabled)
    )
    if "query_portfolio_max" in explicit_fields:
        config.query_portfolio_max = int(payload.query_portfolio_max)
    if "query_portfolio_limit" in explicit_fields:
        config.query_portfolio_limit = int(payload.query_portfolio_limit)
    config.retrieval_embedding_provider = (payload.retrieval_embedding_provider or config.retrieval_embedding_provider or "local").strip().lower()
    config.retrieval_embedding_model = payload.retrieval_embedding_model or config.retrieval_embedding_model
    config.retrieval_embedding_base_url = payload.retrieval_embedding_base_url or config.retrieval_embedding_base_url
    config.retrieval_embedding_api_key = payload.retrieval_embedding_api_key or config.retrieval_embedding_api_key
    config.retrieval_reranker_provider = (payload.retrieval_reranker_provider or config.retrieval_reranker_provider or "").strip().lower()
    config.retrieval_reranker_model = payload.retrieval_reranker_model or config.retrieval_reranker_model
    config.retrieval_reranker_base_url = payload.retrieval_reranker_base_url or config.retrieval_reranker_base_url
    config.retrieval_reranker_api_key = payload.retrieval_reranker_api_key or config.retrieval_reranker_api_key
    config.retrieval_crossref_enrichment = payload.retrieval_crossref_enrichment
    return config


def _history_store_from_payload(payload) -> HistoryStore:
    return HistoryStore(
        timezone_name=getattr(payload, "client_timezone", "") or None,
        utc_offset_minutes=getattr(payload, "client_utc_offset_minutes", None),
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


def _response_payload(result: dict, source: str) -> dict:
    return result_payload_from_search_result(result, source)


def _partial_payload_from_agent(agent: Any, question: str, source: str) -> Optional[dict]:
    if agent is None or not hasattr(agent, "partial_result_payload"):
        return None
    try:
        return _response_payload(agent.partial_result_payload(question), source)
    except Exception:
        return None


def _record_failure(store: HistoryStore, run_id: str, message: str, agent: Any = None, question: str = "", source: str = "") -> None:
    store.fail_run(run_id, message, payload=_partial_payload_from_agent(agent, question, source))


def _resume_checkpoint(store: HistoryStore, payload: SearchRequest) -> Optional[dict[str, Any]]:
    resume_run_id = str(payload.resume_run_id or "").strip()
    if not resume_run_id:
        return None
    checkpoint = store.latest_checkpoint(resume_run_id)
    if checkpoint is None:
        raise ValueError("The selected search run has no recoverable checkpoint.")
    return checkpoint["payload"]


def _search_with_runtime_hooks(
    agent: Any,
    question: str,
    *,
    event_handler: Optional[Any] = None,
    cancel_check: Optional[Any] = None,
    checkpoint_handler: Optional[Any] = None,
    resume_checkpoint: Optional[dict[str, Any]] = None,
):
    parameters = inspect.signature(agent.search).parameters
    kwargs = {"verbose": False}
    if "event_handler" in parameters and event_handler is not None:
        kwargs["event_handler"] = event_handler
    if "cancel_check" in parameters and cancel_check is not None:
        kwargs["cancel_check"] = cancel_check
    if "checkpoint_handler" in parameters and checkpoint_handler is not None:
        kwargs["checkpoint_handler"] = checkpoint_handler
    if "resume_checkpoint" in parameters and resume_checkpoint is not None:
        kwargs["resume_checkpoint"] = resume_checkpoint
    return agent.search(question, **kwargs)


def _register_cancel_event(run_id: str, cancel_event: Event) -> None:
    if not run_id:
        return
    with _CANCEL_LOCK:
        _CANCEL_EVENTS[run_id] = cancel_event


def _unregister_cancel_event(run_id: str, cancel_event: Event) -> None:
    if not run_id:
        return
    with _CANCEL_LOCK:
        if _CANCEL_EVENTS.get(run_id) is cancel_event:
            _CANCEL_EVENTS.pop(run_id, None)


@app.post("/api/search/{run_id}/cancel")
def cancel_search(run_id: str):
    with _CANCEL_LOCK:
        cancel_event = _CANCEL_EVENTS.get(run_id)
    if cancel_event is None:
        raise HTTPException(status_code=404, detail="Search run is not active.")
    cancel_event.set()
    return {"cancelled": run_id}


@app.get("/api/history/status")
def history_status():
    return HistoryStore().status()


@app.get("/api/history")
def history_list(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    store = HistoryStore()
    return {
        **store.status(),
        "history": store.list_runs(limit=limit, offset=offset),
    }


@app.get("/api/history/{run_id}")
def history_detail(run_id: str):
    store = HistoryStore()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="History run not found.")
    return run


@app.delete("/api/history/{run_id}")
def history_delete(run_id: str):
    store = HistoryStore()
    if not store.delete_run(run_id):
        raise HTTPException(status_code=404, detail="History run not found.")
    return {"deleted": run_id}


@app.delete("/api/history")
def history_clear(confirm: bool = Query(default=False)):
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to clear all local history.")
    store = HistoryStore()
    return {"deleted": store.clear()}


@app.post("/api/search")
def search(payload: SearchRequest):
    _validate_payload(payload)
    config = _config_from_payload(payload)
    store = _history_store_from_payload(payload)
    params = safe_search_params_from_config(config)
    if payload.resume_run_id:
        params["resume_from_run_id"] = payload.resume_run_id
    run_id = store.create_run(payload.question, params)
    agent = None

    try:
        config.validate()
        llm = create_llm_client(config)
        agent = PaperSeekAgent(config, llm)
        resume_checkpoint = _resume_checkpoint(store, payload)
        result = _search_with_runtime_hooks(
            agent,
            payload.question,
            checkpoint_handler=lambda checkpoint: store.save_checkpoint(run_id, checkpoint),
            resume_checkpoint=resume_checkpoint,
        )
        response = _response_payload(result, payload.data_source)
        if run_id:
            response["run_id"] = run_id
        store.complete_run(run_id, response)
    except ValueError as exc:
        _record_failure(store, run_id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMError as exc:
        _record_failure(store, run_id, str(exc), agent, payload.question, payload.data_source)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ApiException as exc:
        message = _friendly_api_error(exc)
        _record_failure(store, run_id, message, agent, payload.question, payload.data_source)
        raise HTTPException(status_code=502, detail=message) from exc
    except ProviderError as exc:
        message = _friendly_provider_error(exc)
        _record_failure(store, run_id, message, agent, payload.question, payload.data_source)
        raise HTTPException(status_code=502, detail=message) from exc
    except Exception as exc:
        message = "Search failed. Check the local server logs for details."
        logger.exception("Unhandled search failure.")
        _record_failure(store, run_id, message, agent, payload.question, payload.data_source)
        raise HTTPException(status_code=500, detail=message) from exc

    return response


@app.post("/api/search/stream")
def search_stream(payload: SearchRequest):
    _validate_payload(payload)

    def line(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    def generator():
        events: Queue = Queue()
        store = _history_store_from_payload(payload)
        run_id = ""
        cancel_event = Event()

        def send(event: dict):
            if event.get("type") != "result":
                store.record_event(run_id, event)
            events.put(event)

        def worker():
            nonlocal run_id
            agent = None
            try:
                config = _config_from_payload(payload)
                params = safe_search_params_from_config(config)
                if payload.resume_run_id:
                    params["resume_from_run_id"] = payload.resume_run_id
                run_id = store.create_run(payload.question, params)
                _register_cancel_event(run_id, cancel_event)
                if run_id:
                    send({"type": "run", "run_id": run_id})
                send({"type": "log", "message": "Backend request accepted: POST /api/search/stream -> HTTP 200 OK."})
                send({
                    "type": "log",
                    "message": (
                        f"Runtime config: source={config.data_source}; llm_provider={config.llm_provider}; "
                        f"api_type={config.llm_api_type}; model={config.llm_model}; target={config.target_min}-{config.target_max}; "
                        f"iterations={config.max_iterations}; search_budget={config.search_budget}."
                    ),
                })
                config.validate()
                send({"type": "log", "message": "Initializing LLM client."})
                llm = create_llm_client(config)
                send({"type": "log", "message": "Initializing source adapter."})
                agent = PaperSeekAgent(config, llm)
                resume_checkpoint = _resume_checkpoint(store, payload)
                result = _search_with_runtime_hooks(
                    agent,
                    payload.question,
                    event_handler=send,
                    cancel_check=cancel_event.is_set,
                    checkpoint_handler=lambda checkpoint: store.save_checkpoint(run_id, checkpoint),
                    resume_checkpoint=resume_checkpoint,
                )
                response = _response_payload(result, payload.data_source)
                if run_id:
                    response["run_id"] = run_id
                store.complete_run(run_id, response)
                send({"type": "result", "data": response})
                send({"type": "log", "message": "Run completed successfully."})
            except ValueError as exc:
                message = str(exc)
                _record_failure(store, run_id, message)
                send({"type": "error", "message": message})
            except LLMError as exc:
                message = str(exc)
                _record_failure(store, run_id, message, agent, payload.question, payload.data_source)
                send({"type": "error", "message": message})
            except ApiException as exc:
                message = _friendly_api_error(exc)
                _record_failure(store, run_id, message, agent, payload.question, payload.data_source)
                send({"type": "error", "message": message})
            except ProviderError as exc:
                message = _friendly_provider_error(exc)
                _record_failure(store, run_id, message, agent, payload.question, payload.data_source)
                send({"type": "error", "message": message})
            except SearchCancelled as exc:
                message = str(exc) or "Search cancelled by user."
                _record_failure(store, run_id, message, agent, payload.question, payload.data_source)
                send({"type": "cancelled", "message": message})
            except Exception:
                message = "Search failed. Check the local server logs for details."
                logger.exception("Unhandled streaming search failure.")
                _record_failure(store, run_id, message, agent, payload.question, payload.data_source)
                send({"type": "error", "message": message})
            finally:
                _unregister_cancel_event(run_id, cancel_event)
                events.put(None)

        Thread(target=worker, daemon=True).start()

        while True:
            try:
                item = events.get(timeout=STREAM_HEARTBEAT_SECONDS)
            except Empty:
                yield line({"type": "heartbeat", "ts": time.time(), "pad": STREAM_HEARTBEAT_PADDING})
                continue
            if item is None:
                break
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
