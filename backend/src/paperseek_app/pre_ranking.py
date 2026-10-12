"""Submission and history routing for the three preliminary ranking modes."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from paperseek_app.configuration import (
    DECISION_ROUTE_DEFAULTS, EMBEDDING_ROUTE_DEFAULTS, RERANKER_ROUTE_DEFAULTS,
    PreRankingMode,
)


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


class DecisionRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["typesafe", "siliconflow"] = "typesafe"
    model: str = Field(default="", max_length=256)
    base_url: str = Field(default="", max_length=2048)


class RetrievalRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # An absent mode preserves existing saved runs and API clients with external routes.
    mode: PreRankingMode | None = None
    embedding: EmbeddingRouteInput = Field(default_factory=EmbeddingRouteInput)
    reranker: RerankerRouteInput = Field(default_factory=RerankerRouteInput)
    decision: DecisionRouteInput = Field(default_factory=DecisionRouteInput)


def pre_ranking_mode(retrieval: Mapping) -> PreRankingMode:
    mode = retrieval.get("mode")
    if mode is not None:
        if mode not in {"local_fusion", "embedding_rerank", "decision"}:
            raise ValueError("The preliminary ranking mode is not supported.")
        return mode
    embedding = retrieval.get("embedding") or {}
    reranker = retrieval.get("reranker") or {}
    embedding_provider = str(embedding.get("provider") or "local").strip().lower()
    reranker_provider = str(reranker.get("provider") or "").strip().lower()
    return "embedding_rerank" if (
        embedding_provider not in {"", "local"} or reranker_provider
    ) else "local_fusion"


def resolve_retrieval_route(retrieval: Mapping) -> dict:
    """Persist only active routes; credentials are never part of this snapshot."""
    mode = pre_ranking_mode(retrieval)
    resolved = {"mode": mode, "embedding": {"provider": "local", "model": "", "base_url": ""},
                "reranker": {"provider": "", "model": "", "base_url": ""}}
    if mode == "local_fusion":
        return resolved
    kinds = ("decision",) if mode == "decision" else ("embedding", "reranker")
    tables = {"embedding": EMBEDDING_ROUTE_DEFAULTS, "reranker": RERANKER_ROUTE_DEFAULTS,
              "decision": DECISION_ROUTE_DEFAULTS}
    for kind in kinds:
        requested = dict(retrieval.get(kind) or {})
        default_provider = {"decision": "typesafe", "embedding": "local", "reranker": ""}[kind]
        provider = str(requested.get("provider") or default_provider).strip().lower()
        if provider not in tables[kind]:
            raise ValueError(f"The {kind} provider is not supported.")
        model, base_url = tables[kind][provider]
        resolved[kind] = {"provider": provider,
                          "model": str(requested.get("model") or model).strip(),
                          "base_url": str(requested.get("base_url") or base_url).strip().rstrip("/")}
    return resolved
