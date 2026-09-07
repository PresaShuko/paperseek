from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paperseek_app.configuration import (
    LLM_PROVIDERS,
    SubmissionDefaults,
    resolve_llm_route,
    normalize_wos_db,
)
from paperseek_app.source_catalog import SOURCE_BY_ID


class LLMRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = ""
    api_type: str = ""
    base_url: str = ""
    model: str = ""


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""


class RunCredentialsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: CredentialInput = Field(default_factory=CredentialInput)
    source: CredentialInput = Field(default_factory=CredentialInput)
    embedding: CredentialInput = Field(default_factory=CredentialInput)
    reranker: CredentialInput = Field(default_factory=CredentialInput)


class EmbeddingRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = "local"
    model: str = ""
    base_url: str = ""


class RerankerRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = ""
    model: str = ""
    base_url: str = ""


class RetrievalRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding: EmbeddingRouteInput = Field(default_factory=EmbeddingRouteInput)
    reranker: RerankerRouteInput = Field(default_factory=RerankerRouteInput)
    crossref_metadata_enrichment: bool = False


class ServiceSelectionInput(BaseModel):
    """Non-secret selection; Hosted policy owns eligibility and credential resolution."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["paperseek", "third_party", "byok"]
    connection_id: UUID | None = None

    @model_validator(mode="after")
    def validate_connection(self) -> ServiceSelectionInput:
        if (self.mode == "third_party") != (self.connection_id is not None):
            raise ValueError("Only third-party service requires and accepts a connection.")
        return self


class RunConfigurationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = "openalex"
    search_budget: str = "fast"
    field_ids: list[str] = Field(default_factory=list, max_length=100)
    field_hint: str = Field(default="", max_length=500)
    citation_enabled: bool | None = None
    wos_db: str | None = Field(default=None, max_length=64)
    llm: LLMRouteInput = Field(default_factory=LLMRouteInput)
    retrieval: RetrievalRouteInput = Field(default_factory=RetrievalRouteInput)
    credentials: RunCredentialsInput = Field(default_factory=RunCredentialsInput)
    service: ServiceSelectionInput | None = None


class RunSubmission(RunConfigurationInput):
    question: str = Field(min_length=1, max_length=10_000)


class DiagnosticSubmission(RunConfigurationInput):
    pass


class SubmissionValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PreparedRunSubmission:
    question: str
    source: str
    config_snapshot: dict[str, object]
    request_digest: str


def _invalid(code: str, message: str) -> None:
    raise SubmissionValidationError(code, message)


def prepare_run_submission(
    submission: RunSubmission,
    settings: SubmissionDefaults,
) -> PreparedRunSubmission:
    question = submission.question.strip()
    if not question:
        _invalid("invalid_question", "The research question is required.")
    source = submission.source.strip().lower() or "openalex"
    search_budget = submission.search_budget.strip().lower() or "fast"
    source_definition = SOURCE_BY_ID.get(source)
    if source_definition is None:
        _invalid("unsupported_source", "The selected source is not supported.")
    if search_budget not in {"fast", "medium", "high", "max"}:
        _invalid(
            "unsupported_search_budget",
            "The selected search budget is not supported.",
        )
    embedding_provider = submission.retrieval.embedding.provider.strip().lower() or "local"
    reranker_provider = submission.retrieval.reranker.provider.strip().lower()
    if embedding_provider not in {
        "local",
        "cstcloud",
        "openai",
        "dashscope",
        "siliconflow",
        "openrouter",
        "nvidia",
        "zhipu",
        "volcengine",
        "modelscope",
        "custom",
    }:
        _invalid(
            "unsupported_retrieval_provider",
            "The embedding provider is not supported.",
        )
    if reranker_provider not in {
        "",
        "cstcloud",
        "openrouter",
        "nvidia",
        "siliconflow",
        "custom",
    }:
        _invalid(
            "unsupported_retrieval_provider",
            "The reranker provider is not supported.",
        )

    source_capabilities = source_definition.descriptor()["capabilities"]
    source_filter = source_capabilities["filter"]
    field_ids = list(
        dict.fromkeys(value.strip() for value in submission.field_ids if value.strip())
    )
    field_hint = submission.field_hint.strip()
    if source_filter["mode"] == "native":
        allowed_field_ids = {str(item["id"]) for item in source_filter["options"]}
        if field_hint or any(value not in allowed_field_ids for value in field_ids):
            _invalid(
                "unsupported_source_capability",
                "The submitted filter is not supported by the selected source.",
            )
    elif source_filter["mode"] == "text":
        if field_ids:
            _invalid(
                "unsupported_source_capability",
                "The submitted filter is not supported by the selected source.",
            )
    elif field_ids or field_hint:
        _invalid(
            "unsupported_source_capability",
            "The submitted filter is not supported by the selected source.",
        )
    citation_enabled = (
        bool(source_capabilities["citation_expansion"])
        if submission.citation_enabled is None
        else submission.citation_enabled
    )
    if citation_enabled and not source_capabilities["citation_expansion"]:
        _invalid(
            "unsupported_source_capability",
            "Citation expansion is not supported by the selected source.",
        )

    snapshot = {
        "question": question,
        "source": source,
        "search_budget": search_budget,
        "field_ids": field_ids,
        "field_hint": field_hint,
        "citation_enabled": citation_enabled,
        "wos_db": normalize_wos_db(submission.wos_db, settings.wos_db),
        "llm": resolve_llm_route(settings, submission.llm.model_dump()),
        "retrieval": {
            "crossref_metadata_enrichment": submission.retrieval.crossref_metadata_enrichment,
            "embedding": {
                "provider": embedding_provider,
                "model": submission.retrieval.embedding.model.strip(),
                "base_url": submission.retrieval.embedding.base_url.strip().rstrip("/"),
            },
            "reranker": {
                "provider": reranker_provider,
                "model": submission.retrieval.reranker.model.strip(),
                "base_url": submission.retrieval.reranker.base_url.strip().rstrip("/"),
            },
        },
    }
    if snapshot["llm"]["provider"] not in LLM_PROVIDERS:
        _invalid(
            "unsupported_llm_provider",
            "The selected LLM provider is not supported.",
        )
    if snapshot["llm"]["api_type"] not in {
        "openai_chat",
        "openai_responses",
        "anthropic_messages",
    }:
        _invalid(
            "unsupported_llm_api_type",
            "The selected LLM API type is not supported.",
        )
    if submission.service is not None:
        snapshot["service_mode"] = submission.service.mode
        if submission.service.connection_id is not None:
            snapshot["connection_id"] = str(submission.service.connection_id)
    digest = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return PreparedRunSubmission(
        question=question,
        source=source,
        config_snapshot=snapshot,
        request_digest=digest,
    )


__all__ = [
    "DiagnosticSubmission",
    "PreparedRunSubmission",
    "RunConfigurationInput",
    "RunSubmission",
    "SubmissionValidationError",
    "prepare_run_submission",
]
