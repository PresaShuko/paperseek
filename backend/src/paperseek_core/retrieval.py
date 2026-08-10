"""Capability-driven multi-lane retrieval with deterministic local fusion."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import blake2b
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from paperseek_core.errors import RetrievalSourceError
from paperseek_core.execution import NEVER_CANCELLED
from paperseek_core.models import (
    CheckpointDraft,
    CoreProgressEvent,
    PaperRecord,
    RetrievalRequest,
    RetrievalResult,
)
from paperseek_core.ports import (
    CancellationToken,
    EmbeddingPort,
    RerankPort,
    SourcePort,
    WorkflowObserver,
)
from paperseek_core.sources.contracts import SourceSearchRequest


class RetrievalLane:
    RELEVANCE = "relevance"
    SEMANTIC = "semantic"
    IMPACT = "impact"
    RECENT = "recent"
    LOCAL_QUALITY = "local_quality"
    CITATION = "citation_expansion"


LANE_WEIGHTS = {
    RetrievalLane.RELEVANCE: 1.0,
    RetrievalLane.SEMANTIC: 1.0,
    RetrievalLane.IMPACT: 0.9,
    RetrievalLane.RECENT: 0.8,
    RetrievalLane.LOCAL_QUALITY: 0.9,
    RetrievalLane.CITATION: 1.0,
}

RRF_COMPONENT_WEIGHT = 0.50
PRIMARY_LANE_PRIOR_WEIGHT = 0.15
EMBEDDING_COMPONENT_WEIGHT = 0.1225
BM25_COMPONENT_WEIGHT = 0.14
TERM_COVERAGE_WEIGHT = 0.0875

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+\-.]{1,}", re.I)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "paper",
    "papers",
    "research",
    "study",
    "studies",
    "the",
    "to",
    "with",
}


@dataclass
class FusedRetrievalResult:
    documents: list[PaperRecord]
    metadata_by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    lane_counts: dict[str, int] = field(default_factory=dict)
    total_candidates: int = 0


@dataclass
class _LaneOutcome:
    documents: list[PaperRecord]
    warnings: list[str] = field(default_factory=list)


def document_key(document: PaperRecord) -> str:
    identifiers = document.identifiers
    for name in ("doi", "openalex", "arxiv", "semanticscholar", "pmid"):
        normalized = _normalize_key(getattr(identifiers, name, "") if identifiers else "")
        if normalized:
            return f"{name}:{normalized}"
    uid = _normalize_key(document.uid)
    if uid:
        return f"uid:{uid}"
    title = _normalize_title(document.title)
    return f"title:{title}" if title else ""


def document_alias_keys(document: PaperRecord) -> tuple[str, ...]:
    aliases = []
    primary = document_key(document)
    if primary:
        aliases.append(primary)
    title = _normalize_title(document.title)
    if title:
        aliases.append(f"title:{title}")
    return tuple(dict.fromkeys(aliases))


def document_text(document: PaperRecord) -> str:
    parts = [value for value in (document.title, document.abstract) if value]
    if document.source:
        parts.extend(
            str(value)
            for value in (document.source.source_title, document.source.publish_year)
            if value
        )
    if document.keywords:
        parts.extend(value for value in document.keywords.author_keywords if value)
    if document.names:
        for author in document.names.authors:
            name = author.display_name or author.wos_standard
            if name:
                parts.append(name)
    parts.extend(value for value in document.types if value)
    return " ".join(str(value) for value in parts)


def dedupe_documents(documents: Sequence[PaperRecord]) -> list[PaperRecord]:
    output = []
    aliases_seen: set[str] = set()
    for document in documents:
        aliases = set(document_alias_keys(document))
        if not aliases or aliases & aliases_seen:
            continue
        aliases_seen.update(aliases)
        output.append(document)
    return output


def fuse_candidates_rrf(
    query: str,
    lane_results: Mapping[str, Sequence[PaperRecord]],
    *,
    pool_max: int = 3000,
    rrf_k: int = 60,
    embedding_scores_by_key: Mapping[str, float] | None = None,
) -> FusedRetrievalResult:
    pool_max = max(1, int(pool_max or 3000))
    rrf_k = max(1, int(rrf_k or 60))
    key_to_doc: dict[str, PaperRecord] = {}
    alias_to_key: dict[str, str] = {}
    lane_ranks: dict[str, dict[str, int]] = {}

    for lane, documents in lane_results.items():
        seen_in_lane = set()
        ranks: dict[str, int] = {}
        for document in documents or []:
            aliases = document_alias_keys(document)
            key = next((alias_to_key[alias] for alias in aliases if alias in alias_to_key), "")
            if not key:
                key = document_key(document)
            if not key:
                continue
            for alias in aliases:
                alias_to_key.setdefault(alias, key)
            if key in seen_in_lane:
                continue
            seen_in_lane.add(key)
            key_to_doc.setdefault(key, document)
            ranks[key] = len(ranks) + 1
        lane_ranks[lane] = ranks

    if not key_to_doc:
        return FusedRetrievalResult(
            documents=[],
            lane_counts={lane: 0 for lane in lane_results},
        )

    keys = list(key_to_doc)
    documents = [key_to_doc[key] for key in keys]
    texts = [document_text(document) for document in documents]
    bm25 = _bm25_scores(query, texts)
    query_vector = _hashed_vector(query)
    if embedding_scores_by_key:
        cosine = [
            max(0.0, min(1.0, float(embedding_scores_by_key.get(key, 0.0) or 0.0)))
            for key in keys
        ]
    else:
        cosine = [_cosine(query_vector, _hashed_vector(text)) for text in texts]
    coverage = [_term_coverage(query, text) for text in texts]
    bm25_norm = _normalize_scores(bm25)

    raw_rrf_scores = []
    source_ranks = []
    retrieval_lanes = []
    for key in keys:
        rrf_score = 0.0
        lanes = []
        source_rank = None
        for lane, ranks in lane_ranks.items():
            rank = ranks.get(key)
            if rank is None:
                continue
            lanes.append(lane)
            source_rank = rank if source_rank is None else min(source_rank, rank)
            rrf_score += LANE_WEIGHTS.get(lane, 0.8) / (rrf_k + rank)
        raw_rrf_scores.append(rrf_score)
        source_ranks.append(source_rank)
        retrieval_lanes.append(lanes)

    normalized_rrf_scores = _normalize_scores(raw_rrf_scores)
    scored = []
    metadata_by_key: dict[str, dict[str, Any]] = {}
    for index, key in enumerate(keys):
        relevance_rank = lane_ranks.get(RetrievalLane.RELEVANCE, {}).get(key)
        primary_prior = 1.0 / math.log2(relevance_rank + 1.0) if relevance_rank else 0.0
        final_score = (
            RRF_COMPONENT_WEIGHT * normalized_rrf_scores[index]
            + PRIMARY_LANE_PRIOR_WEIGHT * primary_prior
            + EMBEDDING_COMPONENT_WEIGHT * cosine[index]
            + BM25_COMPONENT_WEIGHT * bm25_norm[index]
            + TERM_COVERAGE_WEIGHT * coverage[index]
        )
        metadata_by_key[key] = {
            "source_rank": source_ranks[index] or index + 1,
            "retrieval_source_ranks": {
                lane: ranks[key]
                for lane, ranks in lane_ranks.items()
                if key in ranks
            },
            "retrieval_score": round(final_score, 6),
            "retrieval_lanes": retrieval_lanes[index],
            "retrieval_rrf_score": round(raw_rrf_scores[index], 6),
            "retrieval_rrf_normalized": round(normalized_rrf_scores[index], 6),
            "retrieval_primary_prior": round(primary_prior, 6),
            "retrieval_embedding_score": round(cosine[index], 6),
            "retrieval_bm25_score": round(bm25_norm[index], 6),
            "retrieval_term_coverage": round(coverage[index], 6),
        }
        scored.append((final_score, -(source_ranks[index] or index + 1), key))

    scored.sort(reverse=True)
    selected_keys = [key for _, _, key in scored[:pool_max]]
    return FusedRetrievalResult(
        documents=[key_to_doc[key] for key in selected_keys],
        metadata_by_key={key: metadata_by_key[key] for key in selected_keys},
        lane_counts={lane: len(ranks) for lane, ranks in lane_ranks.items()},
        total_candidates=len(key_to_doc),
    )


class RetrievalPipeline:
    def __init__(
        self,
        source: SourcePort,
        observer: WorkflowObserver,
        *,
        embedding: EmbeddingPort | None = None,
        reranker: RerankPort | None = None,
        cancellation: CancellationToken = NEVER_CANCELLED,
    ) -> None:
        self.source = source
        self.observer = observer
        self.embedding = embedding
        self.reranker = reranker
        self.cancellation = cancellation

    async def run(self, request: RetrievalRequest) -> RetrievalResult:
        self.cancellation.raise_if_cancelled()
        capabilities = self.source.capabilities
        capability_lanes = tuple(capabilities.lanes)
        limits = {
            lane: self._effective_lane_limit(request, lane)
            for lane in capability_lanes
        }
        completed = {
            lane
            for lane in request.completed_lanes
            if lane in capability_lanes
        }
        lane_results = {
            lane: list(request.resume_lane_results.get(lane, []))
            for lane in capability_lanes
            if lane in completed
        }
        warnings_by_lane: dict[str, list[str]] = {}
        errors_by_lane: dict[str, Exception] = {}
        lane_concurrency = max(
            1,
            min(len(capability_lanes) or 1, int(capabilities.lane_concurrency or 1)),
        )
        semaphore = asyncio.Semaphore(lane_concurrency)
        self._event(
            "retrieval.started",
            {
                "source": self.source.name,
                "lanes": list(capability_lanes),
                "lane_limits": limits,
                "lane_concurrency": lane_concurrency,
                "pool_max": request.pool_max,
            },
        )

        async def run_lane(lane: str) -> None:
            try:
                async with semaphore:
                    self.cancellation.raise_if_cancelled()
                    outcome = await self._collect_lane(request, lane, limits[lane])
                    self.cancellation.raise_if_cancelled()
            except Exception as exc:
                errors_by_lane[lane] = exc
                warnings_by_lane[lane] = [f"retrieval_lane_failed:{lane}"]
                self._event(
                    "retrieval.degraded",
                    {
                        "code": "retrieval_lane_failed",
                        "lane": lane,
                        "error_type": type(exc).__name__,
                    },
                )
                return
            lane_results[lane] = outcome.documents
            warnings_by_lane[lane] = outcome.warnings
            completed.add(lane)
            self._lane_checkpoint(request, lane, lane_results, completed, warnings_by_lane)
            self._event(
                "retrieval.progress",
                {
                    "lane": lane,
                    "completed_lanes": len(completed),
                    "lane_count": len(outcome.documents),
                    "candidate_count": sum(len(values) for values in lane_results.values()),
                },
            )

        async with asyncio.TaskGroup() as group:
            for lane in capability_lanes:
                if lane in completed:
                    continue
                self.cancellation.raise_if_cancelled()
                group.create_task(run_lane(lane))

        primary_error = errors_by_lane.get(RetrievalLane.RELEVANCE)
        if primary_error and not lane_results.get(RetrievalLane.RELEVANCE):
            self._event(
                "retrieval.failed",
                {
                    "code": "retrieval_primary_lane_failed",
                    "source": self.source.name,
                    "lane": RetrievalLane.RELEVANCE,
                    "error_type": type(primary_error).__name__,
                },
            )
            raise RetrievalSourceError("The primary retrieval lane failed without recoverable candidates.") from primary_error

        ordered_lane_results = {
            lane: lane_results[lane]
            for lane in capability_lanes
            if lane in lane_results
        }
        for lane, documents in request.supplemental_lanes.items():
            if documents:
                ordered_lane_results[lane] = dedupe_documents(documents)
        if not ordered_lane_results and request.primary_hits:
            ordered_lane_results[RetrievalLane.RELEVANCE] = list(request.primary_hits)

        warnings = self._ordered_lane_warnings(capability_lanes, warnings_by_lane)
        unique_documents = dedupe_documents(
            [
                document
                for documents in ordered_lane_results.values()
                for document in documents
            ]
        )
        embedding_scores_by_key: dict[str, float] = {}
        if self.embedding and unique_documents:
            try:
                self.cancellation.raise_if_cancelled()
                embedding_scores = await self.embedding.embedding_scores(
                    request.question,
                    unique_documents,
                )
                self.cancellation.raise_if_cancelled()
                if len(embedding_scores) != len(unique_documents):
                    raise ValueError("Embedding score count does not match candidate count.")
                embedding_scores_by_key = {
                    document_key(document): float(score)
                    for document, score in zip(unique_documents, embedding_scores)
                    if document_key(document)
                }
            except Exception as exc:
                warnings.append("retrieval_embedding_failed_local_similarity_retained")
                self._event(
                    "retrieval.degraded",
                    {
                        "code": "retrieval_embedding_failed_local_similarity_retained",
                        "error_type": type(exc).__name__,
                        "candidate_count": len(unique_documents),
                    },
                )

        fused = fuse_candidates_rrf(
            request.question,
            ordered_lane_results,
            pool_max=request.pool_max,
            rrf_k=request.rrf_k,
            embedding_scores_by_key=embedding_scores_by_key,
        )
        documents = list(fused.documents)
        provenance = {}
        for document in fused.documents:
            key = document_key(document)
            metadata = dict(fused.metadata_by_key.get(key, {}))
            metadata["origins"] = ["retrieval"]
            metadata["sources"] = [document.provider] if document.provider else []
            provenance[key] = metadata
        if self.reranker and documents:
            try:
                self.cancellation.raise_if_cancelled()
                reranked = await self.reranker.rerank(request.question, documents)
                self.cancellation.raise_if_cancelled()
                documents = self._apply_rerank(documents, reranked.items, provenance)
            except Exception as exc:
                warnings.append("retrieval_rerank_failed_rrf_order_retained")
                self._event(
                    "retrieval.degraded",
                    {
                        "code": "retrieval_rerank_failed_rrf_order_retained",
                        "error_type": type(exc).__name__,
                        "candidate_count": len(documents),
                    },
                )

        completed_lanes = [lane for lane in capability_lanes if lane in completed]
        result = RetrievalResult(
            documents=documents,
            provenance_by_identity=provenance,
            lane_counts=fused.lane_counts,
            total_candidates=fused.total_candidates,
            completed_lanes=completed_lanes,
            warnings=warnings,
        )
        self._fusion_checkpoint(request, result)
        self._event(
            "retrieval.completed",
            {
                "source": self.source.name,
                "candidate_count": len(documents),
                "total_candidates": fused.total_candidates,
                "lane_counts": fused.lane_counts,
                "warning_count": len(warnings),
            },
        )
        return result

    def _effective_lane_limit(self, request: RetrievalRequest, lane: str) -> int:
        ranking_limit = min(request.ranking_candidate_limit, request.pool_max)
        useful_depth = max(100, ranking_limit)
        if lane != RetrievalLane.RELEVANCE:
            useful_depth = max(100, int(math.ceil(ranking_limit / 4.0)))
        return max(
            1,
            min(
                request.lane_limit,
                self.source.capabilities.max_lane_limit,
                request.pool_max,
                useful_depth,
            ),
        )

    async def _collect_lane(
        self,
        request: RetrievalRequest,
        lane: str,
        limit: int,
    ) -> _LaneOutcome:
        initial = request.primary_hits if lane == RetrievalLane.RELEVANCE else []
        collected = dedupe_documents(initial)[:limit]
        if len(collected) >= limit:
            return _LaneOutcome(collected)

        default_page_size = min(100, limit)
        if collected and len(collected) < default_page_size:
            return _LaneOutcome(collected)
        page = 2 if collected else 1
        warnings = []
        while len(collected) < limit:
            self.cancellation.raise_if_cancelled()
            request_limit = min(
                self.source.capabilities.page_size(lane),
                limit - len(collected),
            )
            try:
                response = await self.source.search(
                    SourceSearchRequest(
                        query=request.question if lane == RetrievalLane.SEMANTIC else request.query,
                        limit=request_limit,
                        page=page,
                        lane=lane,
                        field_ids=request.field_ids,
                    )
                )
                self.cancellation.raise_if_cancelled()
            except Exception as exc:
                if not collected:
                    raise
                code = f"retrieval_page_failed_candidates_retained:{lane}"
                warnings.append(code)
                self._event(
                    "retrieval.degraded",
                    {
                        "code": "retrieval_page_failed_candidates_retained",
                        "lane": lane,
                        "page": page,
                        "retained_candidates": len(collected),
                        "error_type": type(exc).__name__,
                    },
                )
                break
            hits = list(response.hits)
            if not hits:
                break
            collected.extend(hits)
            page_size = max(1, int(response.metadata.limit or request_limit))
            total = int(response.metadata.total or 0)
            if self.source.capabilities.is_single_page(lane):
                break
            if len(hits) < page_size:
                break
            if total and len(collected) >= total:
                break
            page += 1
        return _LaneOutcome(dedupe_documents(collected)[:limit], warnings)

    @staticmethod
    def _apply_rerank(documents, items, provenance) -> list[PaperRecord]:
        key_to_document = {document_key(document): document for document in documents}
        aliases = {
            alias: document_key(document)
            for document in documents
            for alias in document_alias_keys(document)
        }
        ranked = []
        used = set()
        for item in sorted(items, key=lambda value: float(value.score), reverse=True):
            key = next(
                (aliases[alias] for alias in document_alias_keys(item.document) if alias in aliases),
                "",
            )
            if not key or key in used:
                continue
            used.add(key)
            provenance.setdefault(key, {})["rerank_score"] = float(item.score)
            ranked.append(key_to_document[key])
        if not ranked:
            raise ValueError("Reranker returned no candidates from the fused pool.")
        ranked.extend(document for document in documents if document_key(document) not in used)
        return ranked

    def _lane_checkpoint(
        self,
        request: RetrievalRequest,
        lane: str,
        lane_results: dict[str, list[PaperRecord]],
        completed: set[str],
        warnings_by_lane: dict[str, list[str]],
    ) -> None:
        self.cancellation.raise_if_cancelled()
        ordered_lanes = tuple(self.source.capabilities.lanes)
        state_results = {
            key: [document.model_dump(mode="json") for document in lane_results[key]]
            for key in ordered_lanes
            if key in lane_results
        }
        self.observer.on_checkpoint(
            CheckpointDraft(
                step_key="retrieve.lane",
                idempotency_key=self._lane_idempotency_key(request, lane),
                state={
                    "completed_lanes": [key for key in ordered_lanes if key in completed],
                    "lane_results": state_results,
                    "warnings": self._ordered_lane_warnings(ordered_lanes, warnings_by_lane),
                    "resume_from_stage": request.checkpoint_resume_stage,
                },
                workflow_version="m2.retrieval.v1",
            )
        )

    def _fusion_checkpoint(self, request: RetrievalRequest, result: RetrievalResult) -> None:
        self.cancellation.raise_if_cancelled()
        payload = {
            "source": self.source.name,
            "question": request.question,
            "query": request.query,
            "completed_lanes": result.completed_lanes,
            "pool_max": request.pool_max,
            "rrf_k": request.rrf_k,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.observer.on_checkpoint(
            CheckpointDraft(
                step_key="retrieve.fuse",
                idempotency_key=f"retrieval:fuse:{digest}",
                state={
                    "candidate_pool": [document.model_dump(mode="json") for document in result.documents],
                    "provenance_by_identity": result.provenance_by_identity,
                    "lane_counts": result.lane_counts,
                    "total_candidates": result.total_candidates,
                    "completed_lanes": result.completed_lanes,
                    "warnings": result.warnings,
                    "resume_from_stage": "post_retrieval",
                },
                workflow_version="m2.retrieval.v1",
            )
        )

    def _lane_idempotency_key(self, request: RetrievalRequest, lane: str) -> str:
        payload = {
            "source": self.source.name,
            "lane": lane,
            "query": request.question if lane == RetrievalLane.SEMANTIC else request.query,
            "limit": self._effective_lane_limit(request, lane),
            "field_ids": request.field_ids,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"retrieval:lane:{lane}:{digest}"

    @staticmethod
    def _ordered_lane_warnings(
        lanes: Sequence[str],
        warnings_by_lane: Mapping[str, Sequence[str]],
    ) -> list[str]:
        return [warning for lane in lanes for warning in warnings_by_lane.get(lane, ())]

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.cancellation.raise_if_cancelled()
        self.observer.on_event(
            CoreProgressEvent(event_type=event_type, stage="retrieval", payload=payload)
        )


def _normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return re.sub(r"\s+", "", text)


def _normalize_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if token.lower() not in _STOPWORDS
    ]


def _hashed_vector(text: str, dimensions: int = 512) -> dict[int, float]:
    tokens = _tokens(text)
    features: Iterable[str] = tokens
    char_features = []
    compact = re.sub(r"\s+", " ", (text or "").lower())
    if len(compact) >= 3:
        char_features = [
            compact[index:index + 3]
            for index in range(0, min(len(compact) - 2, 600))
        ]
    vector: dict[int, float] = {}
    for feature in list(features) + char_features:
        digest = blake2b(feature.encode("utf-8", errors="ignore"), digest_size=8).digest()
        slot = int.from_bytes(digest[:4], "little") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[slot] = vector.get(slot, 0.0) + sign
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm <= 0:
        return {}
    return {key: value / norm for key, value in vector.items()}


def _cosine(left: dict[int, float], right: dict[int, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    score = sum(value * right.get(key, 0.0) for key, value in left.items())
    return max(0.0, min(1.0, score))


def _bm25_scores(query: str, documents: Sequence[str]) -> list[float]:
    query_terms = _tokens(query)
    if not query_terms or not documents:
        return [0.0 for _ in documents]
    doc_tokens = [_tokens(document) for document in documents]
    doc_count = len(doc_tokens)
    avg_len = sum(len(tokens) for tokens in doc_tokens) / max(1, doc_count)
    doc_freq: dict[str, int] = {}
    for tokens in doc_tokens:
        for token in set(tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    scores = []
    k1 = 1.5
    b = 0.75
    for tokens in doc_tokens:
        term_freq: dict[str, int] = {}
        for token in tokens:
            term_freq[token] = term_freq.get(token, 0) + 1
        doc_len = len(tokens)
        score = 0.0
        for term in query_terms:
            tf = term_freq.get(term, 0)
            if tf <= 0:
                continue
            df = doc_freq.get(term, 0)
            idf = math.log(1 + ((doc_count - df + 0.5) / (df + 0.5)))
            denom = tf + k1 * (1 - b + b * doc_len / max(avg_len, 1.0))
            score += idf * ((tf * (k1 + 1)) / max(denom, 1e-9))
        scores.append(score)
    return scores


def _term_coverage(query: str, document: str) -> float:
    query_terms = set(_tokens(query))
    if not query_terms:
        return 0.0
    document_terms = set(_tokens(document))
    return len(query_terms & document_terms) / max(1, len(query_terms))


def _normalize_scores(scores: Sequence[float]) -> list[float]:
    if not scores:
        return []
    high = max(scores)
    low = min(scores)
    if high <= low:
        return [1.0 if high > 0 else 0.0 for _ in scores]
    return [(score - low) / (high - low) for score in scores]


__all__ = [
    "FusedRetrievalResult",
    "RetrievalLane",
    "RetrievalPipeline",
    "dedupe_documents",
    "document_alias_keys",
    "document_key",
    "document_text",
    "fuse_candidates_rrf",
]
