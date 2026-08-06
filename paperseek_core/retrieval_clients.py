"""External embedding and reranking service adapters."""

from __future__ import annotations

import math
import re
from itertools import count
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

import requests

from paperseek_core.retrieval import document_key, document_text
from paperseek_core.domain.models import PaperCitation


_API_KEY_COUNTER_LOCK = Lock()
_API_KEY_COUNTERS: Dict[str, Any] = {}


def _split_api_keys(api_key: str) -> List[str]:
    keys = [item.strip() for item in re.split(r"[\s,;]+", api_key or "") if item.strip()]
    return list(dict.fromkeys(keys))


def _next_api_key(keys: List[str]) -> str:
    if not keys:
        return ""
    if len(keys) == 1:
        return keys[0]
    pool_key = "\0".join(keys)
    with _API_KEY_COUNTER_LOCK:
        key_counter = _API_KEY_COUNTERS.setdefault(pool_key, count())
        index = next(key_counter)
    return keys[index % len(keys)]


def _api_key_attempts(api_key: str, max_attempts: int = 3) -> List[str]:
    keys = _split_api_keys(api_key)
    if not keys:
        return [""]
    attempts = min(max(1, int(max_attempts or 1)), len(keys))
    return [_next_api_key(keys) for _ in range(attempts)]


def _retryable_status(status_code: int) -> bool:
    return status_code in (401, 403, 408, 409, 425, 429) or status_code >= 500


class ExternalRetrievalServices:
    """Own external embedding and reranking provider protocols."""

    def __init__(
        self,
        config: Any,
        *,
        run_cancellable: Callable[[Callable[[], Any]], Any],
        log: Callable[[str], None],
        ranking_step: Callable[..., None],
        metadata_by_key: Callable[[], Dict[str, Dict[str, Any]]],
    ) -> None:
        self.config = config
        self._run_cancellable = run_cancellable
        self._log = log
        self._ranking_step = ranking_step
        self._metadata_by_key = metadata_by_key

    def enrich_crossref(self, documents: list) -> list:
        if not getattr(self.config, "retrieval_crossref_enrichment", False):
            return documents
        enriched = 0
        headers = {"Accept": "application/json", "User-Agent": "paperseek/1.0"}
        for document in documents[:100]:
            identifiers = getattr(document, "identifiers", None)
            doi = getattr(identifiers, "doi", "") if identifiers is not None else ""
            if not doi:
                continue
            try:
                response = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=20)
                if response.status_code < 200 or response.status_code >= 300:
                    continue
                message = response.json().get("message") or {}
                cited = int(message.get("is-referenced-by-count") or 0)
                if cited and not getattr(document, "citations", None):
                    document.citations = [PaperCitation(db="Crossref", count=cited)]
                source = getattr(document, "source", None)
                if source is not None and not getattr(source, "publish_year", None):
                    year = self._crossref_year(message)
                    if year:
                        source.publish_year = year
                enriched += 1
            except Exception:
                continue
        self._log(f"Optional Crossref candidate enrichment completed: enriched={enriched}.")
        return documents

    @staticmethod
    def _crossref_year(message: dict) -> Optional[int]:
        for key in ("published-print", "published-online", "published", "issued"):
            parts = ((message.get(key) or {}).get("date-parts") or [])
            if parts and parts[0]:
                try:
                    return int(parts[0][0])
                except (TypeError, ValueError):
                    continue
        return None

    def embedding_scores(self, question: str, documents: list) -> Optional[List[float]]:
        provider = (getattr(self.config, "retrieval_embedding_provider", "local") or "local").strip().lower()
        if provider in ("", "local", "python"):
            return None
        if not documents:
            return []
        api_key = self.api_key("embedding", provider)
        base_url = self.base_url("embedding", provider)
        if not api_key or not base_url:
            self._log(
                "External embedding skipped: provider configured but API key or base URL is missing; "
                "using local hashing embeddings."
            )
            return None
        texts = [question] + [document_text(document)[:1800] for document in documents]
        for model in self.model_candidates("embedding", "qwen3-embedding:8b", provider):
            try:
                vectors = self._embedding_vectors(base_url, api_key, model, texts, provider=provider)
            except Exception as exc:
                self._log(f"External embedding failed for model={model}; trying fallback if available: {exc}")
                continue
            if len(vectors) != len(texts):
                self._log(
                    f"External embedding returned an unexpected vector count for model={model}; "
                    "trying fallback if available."
                )
                continue
            query_vector = vectors[0]
            self._log(
                f"External embedding completed: provider={provider}; model={model}; documents={len(documents)}."
            )
            return [self._dense_cosine(query_vector, vector) for vector in vectors[1:]]
        self._log("External embedding failed for all configured models; using local hashing embeddings.")
        return None

    @staticmethod
    def embedding_score_map(documents: list, scores: Optional[List[float]]) -> Dict[str, float]:
        if not scores or len(scores) != len(documents):
            return {}
        output = {}
        for document, score in zip(documents, scores):
            key = document_key(document)
            if key:
                output[key] = score
        return output

    def _post(
        self,
        url: str,
        api_key: str,
        headers_factory: Callable[[str], Dict[str, str]],
        payload: Dict[str, Any],
        *,
        timeout: int = 60,
        label: str = "External API",
    ):
        attempts = _api_key_attempts(api_key)
        last_error = None
        for attempt_index, key in enumerate(attempts, 1):
            try:
                response = self._run_cancellable(
                    lambda: requests.post(
                        url,
                        headers=headers_factory(key),
                        json=payload,
                        timeout=(10, timeout),
                    )
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt_index < len(attempts):
                    self._log(
                        f"{label} request failed; retrying with another key "
                        f"({attempt_index}/{len(attempts)}): {exc}"
                    )
                    continue
                raise
            if (
                response.status_code < 200 or response.status_code >= 300
            ) and attempt_index < len(attempts) and _retryable_status(response.status_code):
                self._log(
                    f"{label} request returned HTTP {response.status_code}; "
                    f"retrying with another key ({attempt_index}/{len(attempts)})."
                )
                last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
                continue
            return response
        if last_error:
            raise last_error
        return self._run_cancellable(
            lambda: requests.post(
                url,
                headers=headers_factory(""),
                json=payload,
                timeout=(10, timeout),
            )
        )

    def _embedding_vectors(
        self,
        base_url: str,
        api_key: str,
        model: str,
        texts: list,
        provider: str = "",
    ) -> List[List[float]]:
        if (provider or "").strip().lower() == "nvidia":
            return self._nvidia_embedding_vectors(base_url, api_key, model, texts)
        vectors: List[List[float]] = []
        url = f"{base_url.rstrip('/')}/embeddings"
        batch_size = 64
        for offset in range(0, len(texts), batch_size):
            batch = texts[offset:offset + batch_size]
            response = self._post(
                url,
                api_key,
                lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                {"model": model, "input": batch, "encoding_format": "float"},
                timeout=60,
                label="External embedding",
            )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            payload = response.json()
            data = payload.get("data") or []
            data = sorted(data, key=lambda item: int(item.get("index", 0))) if all(isinstance(item, dict) for item in data) else data
            for item in data:
                embedding = item.get("embedding") if isinstance(item, dict) else None
                if not isinstance(embedding, list):
                    raise RuntimeError("embedding response item has no embedding vector")
                vectors.append([float(value) for value in embedding])
        return vectors

    def _nvidia_embedding_vectors(
        self,
        base_url: str,
        api_key: str,
        model: str,
        texts: list,
    ) -> List[List[float]]:
        url = f"{base_url.rstrip('/')}/embeddings"

        def request_vectors(batch: list, input_type: str) -> List[List[float]]:
            response = self._post(
                url,
                api_key,
                lambda key: {
                    "Authorization": f"Bearer {key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                {"model": model, "input": batch, "input_type": input_type, "encoding_format": "float"},
                timeout=60,
                label="NVIDIA embedding",
            )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            payload = response.json()
            data = payload.get("data") or []
            data = sorted(data, key=lambda item: int(item.get("index", 0))) if all(isinstance(item, dict) for item in data) else data
            vectors = []
            for item in data:
                embedding = item.get("embedding") if isinstance(item, dict) else None
                if not isinstance(embedding, list):
                    raise RuntimeError("embedding response item has no embedding vector")
                vectors.append([float(value) for value in embedding])
            return vectors

        vectors: List[List[float]] = []
        if texts:
            vectors.extend(request_vectors(texts[:1], "query"))
        batch_size = 64
        for offset in range(1, len(texts), batch_size):
            vectors.extend(request_vectors(texts[offset:offset + batch_size], "passage"))
        return vectors

    def rerank(self, question: str, documents: list) -> list:
        provider = (getattr(self.config, "retrieval_reranker_provider", "") or "").strip().lower()
        if provider in ("", "none", "off") or not documents:
            return documents
        self._ranking_step(
            "external_reranker",
            "processing",
            "External reranker",
            current=0,
            total=max(1, min(200, len(documents))),
            detail=f"Calling {provider} reranker for the top {min(200, len(documents))} candidates.",
        )
        if provider == "modelscope":
            self._log("External reranker skipped: ModelScope API-Inference does not support rerank.")
            self._ranking_step(
                "external_reranker",
                "skipped",
                "External reranker",
                current=0,
                total=max(1, min(200, len(documents))),
                detail="ModelScope API-Inference does not support rerank; keeping RRF order.",
            )
            return documents
        api_key = self.api_key("reranker", provider)
        base_url = self.base_url("reranker", provider)
        if not api_key or not base_url:
            self._log("External reranker skipped: provider configured but API key or base URL is missing.")
            self._ranking_step(
                "external_reranker",
                "skipped",
                "External reranker",
                current=0,
                total=max(1, min(200, len(documents))),
                detail="Reranker API key or base URL is missing; keeping RRF order.",
            )
            return documents
        rerank_count = min(200, len(documents))
        texts = [document_text(document)[:1800] for document in documents[:rerank_count]]
        for model in self.model_candidates("reranker", "qwen3-reranker:8b", provider):
            try:
                if provider == "nvidia":
                    endpoint = base_url.rstrip("/")
                    if not (endpoint.endswith("/reranking") or endpoint.endswith("/ranking")):
                        endpoint = f"{endpoint}/reranking"
                    response = self._post(
                        endpoint,
                        api_key,
                        lambda key: {
                            "Authorization": f"Bearer {key}",
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                        {
                            "model": model,
                            "query": {"text": question},
                            "passages": [{"text": text} for text in texts],
                        },
                        timeout=60,
                        label="External reranker",
                    )
                else:
                    response = self._post(
                        f"{base_url.rstrip('/')}/rerank",
                        api_key,
                        lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        {"model": model, "query": question, "documents": texts, "top_n": rerank_count},
                        timeout=60,
                        label="External reranker",
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
                payload = response.json()
                results = (
                    payload.get("rankings") or []
                    if provider == "nvidia"
                    else payload.get("results") or payload.get("data") or []
                )
                ranked = []
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    index = item.get("index")
                    score = item.get("logit", item.get("relevance_score", item.get("score", 0)))
                    if isinstance(index, int) and 0 <= index < rerank_count:
                        ranked.append((float(score or 0), index))
                if not ranked:
                    raise RuntimeError("reranker response contained no indexed scores")
                ranked.sort(reverse=True)
                used = {index for _, index in ranked}
                metadata_by_key = self._metadata_by_key()
                for score, index in ranked:
                    key = document_key(documents[index])
                    if key:
                        metadata_by_key.setdefault(key, {})["rerank_score"] = float(score)
                reranked_docs = [documents[index] for _, index in ranked]
                reranked_docs.extend(documents[index] for index in range(rerank_count) if index not in used)
                reranked_docs.extend(documents[rerank_count:])
                self._log(
                    f"External reranker completed: provider={provider}; model={model}; reranked={rerank_count}."
                )
                self._ranking_step(
                    "external_reranker",
                    "complete",
                    "External reranker",
                    current=rerank_count,
                    total=max(1, rerank_count),
                    detail=f"{provider} reranker completed with model={model}.",
                    candidate_count=len(reranked_docs),
                )
                return reranked_docs
            except Exception as exc:
                self._log(f"External reranker failed for model={model}; trying fallback if available: {exc}")
        self._log("External reranker failed for all configured models; keeping RRF order.")
        self._ranking_step(
            "external_reranker",
            "error",
            "External reranker",
            current=0,
            total=max(1, rerank_count),
            detail="All configured reranker models failed; keeping RRF order.",
        )
        return documents

    def model_candidates(self, kind: str, default_model: str, provider: str = "") -> List[str]:
        raw = getattr(self.config, f"retrieval_{kind}_model", "") or default_model
        provider = (provider or "").strip().lower()
        if kind == "embedding" and provider == "modelscope":
            modelscope_models = "Qwen/Qwen3-Embedding-8B,Qwen/Qwen3-Embedding-4B"
            if raw in ("", default_model, "qwen3-embedding:8b,bge-large-zh:latest", "BAAI/bge-large-zh-v1.5"):
                raw = modelscope_models
        if kind == "embedding" and provider == "nvidia":
            if raw in ("", default_model, "qwen3-embedding:8b", "qwen3-embedding:8b,bge-large-zh:latest"):
                raw = "nvidia/nv-embedqa-e5-v5"
            elif raw == "nv-embed-v1":
                raw = "nvidia/nv-embed-v1"
        if kind == "embedding" and provider == "openrouter":
            if raw in ("", default_model, "qwen3-embedding:8b", "qwen3-embedding:8b,bge-large-zh:latest"):
                raw = "openai/text-embedding-3-small"
        if kind == "reranker" and provider == "nvidia":
            if raw in ("", default_model, "qwen3-reranker:8b", "BAAI/bge-reranker-v2-m3"):
                raw = "nv-rerank-qa-mistral-4b:1"
        if kind == "reranker" and provider == "openrouter":
            if raw in ("", default_model, "qwen3-reranker:8b", "BAAI/bge-reranker-v2-m3"):
                raw = "jinaai/jina-reranker-v2-base-multilingual"
        candidates = []
        for part in str(raw).replace(";", ",").split(","):
            value = part.strip()
            if value and value not in candidates:
                candidates.append(value)
        return candidates or [default_model]

    def api_key(self, kind: str, provider: str) -> str:
        attr = f"retrieval_{kind}_api_key"
        value = getattr(self.config, attr, "") or ""
        if value:
            return value
        if provider in (
            "cstcloud",
            "openai",
            "dashscope",
            "siliconflow",
            "openrouter",
            "huggingface",
            "nvidia",
            "zhipu",
            "volcengine",
            "modelscope",
            "custom",
        ):
            return getattr(self.config, "llm_api_key", "") or ""
        return ""

    def base_url(self, kind: str, provider: str) -> str:
        attr = f"retrieval_{kind}_base_url"
        value = getattr(self.config, attr, "") or ""
        if value:
            return value
        if kind == "reranker" and provider == "modelscope":
            return ""
        provider_urls = {
            "cstcloud": "https://uni-api.cstcloud.cn/v1",
            "openai": "https://api.openai.com/v1",
            "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "siliconflow": "https://api.siliconflow.cn/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "huggingface": "https://router.huggingface.co/v1",
            "nvidia": (
                "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking"
                if kind == "reranker"
                else "https://integrate.api.nvidia.com/v1"
            ),
            "zhipu": "https://open.bigmodel.cn/api/paas/v4",
            "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
            "modelscope": "https://api-inference.modelscope.cn/v1",
        }
        if provider in provider_urls:
            return provider_urls[provider]
        if provider == "custom":
            return getattr(self.config, "llm_base_url", "") or ""
        return ""

    @staticmethod
    def _dense_cosine(left: list, right: list) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
        right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return max(0.0, min(1.0, dot / (left_norm * right_norm)))
