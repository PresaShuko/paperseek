from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from paperseek.config import (
    AgentConfig,
    default_api_type,
    default_base_url,
    default_model,
)
from paperseek.disciplines import normalize_source_filter_values
from paperseek_core.budgets import apply_search_budget


_SECRET_OR_ENDPOINT_FIELDS = {
    "wos_api_key",
    "openalex_api_key",
    "openalex_email",
    "crossref_email",
    "semantic_scholar_api_key",
    "pubmed_api_key",
    "pubmed_email",
    "pubmed_tool",
    "serper_api_key",
    "llm_api_key",
    "llm_model",
    "llm_base_url",
    "retrieval_embedding_model",
    "retrieval_embedding_base_url",
    "retrieval_embedding_api_key",
    "retrieval_reranker_model",
    "retrieval_reranker_base_url",
    "retrieval_reranker_api_key",
}


def normalize_search_loop_backend(value: Any) -> str:
    backend = str(value or "native").strip().lower() or "native"
    if backend not in {"auto", "native"}:
        raise ValueError("search_loop_backend must be one of auto or native")
    return backend


def compile_agent_config(
    overrides: Mapping[str, Any] | None = None,
    *,
    environment: AgentConfig | None = None,
) -> AgentConfig:
    """Compile environment settings and validated per-run overrides.

    Blank credentials and service endpoints do not erase environment-owned
    values. Callers include only fields that should participate in this run;
    this keeps interface-specific defaults outside the compiler.
    """

    config = replace(environment or AgentConfig.from_env())
    values = dict(overrides or {})

    budget = values.pop("search_budget", None)
    if budget:
        apply_search_budget(config, str(budget))

    provider = str(values.pop("llm_provider", "") or "").strip().lower()
    provider_changed = bool(provider and provider != config.llm_provider)
    if provider:
        config.llm_provider = provider

    api_type = str(values.pop("llm_api_type", "") or "").strip().lower()
    if api_type:
        config.llm_api_type = api_type
    elif provider_changed or not config.llm_api_type:
        config.llm_api_type = default_api_type(config.llm_provider)

    model_supplied = bool(values.get("llm_model"))
    base_url_supplied = bool(values.get("llm_base_url"))
    if provider_changed and not model_supplied:
        config.llm_model = default_model(config.llm_provider)
    if provider_changed and not base_url_supplied:
        config.llm_base_url = default_base_url(config.llm_provider, config.llm_api_type)

    data_source = str(values.pop("data_source", "") or "").strip().lower()
    if data_source:
        config.data_source = data_source

    discipline_supplied = "discipline_fields" in values
    discipline_fields = values.pop("discipline_fields", ())
    if discipline_supplied:
        config.discipline_fields = normalize_source_filter_values(config.data_source, discipline_fields)

    if "search_loop_backend" in values:
        config.search_loop_backend = normalize_search_loop_backend(values.pop("search_loop_backend"))

    for name, value in values.items():
        if not hasattr(config, name):
            continue
        if name in _SECRET_OR_ENDPOINT_FIELDS and value in (None, ""):
            continue
        if value is None:
            continue
        if name in {"retrieval_embedding_provider", "retrieval_reranker_provider"}:
            value = str(value).strip().lower()
        setattr(config, name, value)

    if not config.llm_model:
        config.llm_model = default_model(config.llm_provider)
    if not config.llm_base_url:
        config.llm_base_url = default_base_url(config.llm_provider, config.llm_api_type)
    return config
