from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from paperseek.disciplines import normalize_source_filter_values
from paperseek.source_metadata import supported_source_ids
from paperseek_core.budgets import DEFAULT_SEARCH_BUDGET, normalize_search_budget, search_budget_preset


_DEFAULT_WEB_BUDGET = search_budget_preset(DEFAULT_SEARCH_BUDGET)


def _clean_search_loop_backend(value: str) -> str:
    value = (value or "native").strip().lower() or "native"
    if value not in {"auto", "native"}:
        raise ValueError("must be one of auto or native")
    return value


class RuntimeConfigRequest(BaseModel):
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
    search_loop_backend: str = "native"
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


class SearchRequest(RuntimeConfigRequest):
    question: str = Field(min_length=1)
    query_portfolio_enabled: bool = True
    query_portfolio_max: int = Field(default=_DEFAULT_WEB_BUDGET.query_portfolio_max, ge=1, le=6)
    query_portfolio_limit: int = Field(default=_DEFAULT_WEB_BUDGET.query_portfolio_limit, ge=1, le=100)
    resume_run_id: Optional[str] = ""

    @field_validator("question")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("is required")
        return value


class DiagnosticRequest(RuntimeConfigRequest):
    question: Optional[str] = "machine learning"
