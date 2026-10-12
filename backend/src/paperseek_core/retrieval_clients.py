from __future__ import annotations

import math
from typing import Any

import httpx

from paperseek_core.key_pool import ApiKeyPool
from paperseek_core.http_retry import MODEL_ATTEMPTS
from paperseek_core.model_http import post_model_json
from paperseek_core.models import PaperRecord, RetrievalEmbeddingResult, RetrievalRerankItem, RetrievalRerankResult
from paperseek_core.ports import CancellationToken
from paperseek_core.retrieval_fusion import document_text


def _model_names(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in value.replace(";", ",").split(",") if item.strip()))


class ExternalEmbeddingAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        cancellation: CancellationToken,
        *,
        provider: str,
        model: str,
        base_url: str,
        api_key: str,
    ) -> None:
        self.client = client
        self.cancellation = cancellation
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_keys = ApiKeyPool(api_key)

    async def embedding_scores(
        self, question: str, documents: list[PaperRecord], *, model: str | None = None,
    ) -> RetrievalEmbeddingResult:
        if not self.model or not self.base_url or not self.api_keys.available:
            raise RuntimeError("External embedding configuration is incomplete.")
        texts = [question, *[document_text(document)[:1800] for document in documents]]
        last_error: Exception | None = None
        # Incremental scoring must use the same model as the persisted scores.
        for selected_model in ([model] if model else _model_names(self.model)):
            try:
                if self.provider == "nvidia":
                    vectors = [*(await self._vectors(texts[:1], selected_model, input_type="query"))]
                    vectors.extend(await self._vectors(texts[1:], selected_model, input_type="passage"))
                else:
                    vectors = await self._vectors(texts, selected_model)
                if len(vectors) != len(texts):
                    raise RuntimeError("Embedding vector count does not match input count.")
                scores = [self._cosine(vectors[0], vector) for vector in vectors[1:]]
                if not all(math.isfinite(score) for score in scores):
                    raise RuntimeError("Embedding response contained non-finite scores.")
                return RetrievalEmbeddingResult(scores=scores, provider=self.provider, model=selected_model)
            except Exception as exc:
                last_error = exc
        raise RuntimeError("All configured embedding models failed.") from last_error

    async def _vectors(self, texts: list[str], model: str, *, input_type: str = "") -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), 64):
            self.cancellation.raise_if_cancelled()
            batch = texts[start:start + 64]
            body: dict[str, Any] = {"model": model, "input": batch, "encoding_format": "float"}
            if input_type:
                body["input_type"] = input_type
            response, _ = await post_model_json(self.client, self.cancellation, f"{self.base_url}/embeddings", body,
                                                 self.api_keys.attempts(MODEL_ATTEMPTS))
            response.raise_for_status()
            data = sorted(response.json().get("data") or [], key=lambda item: int(item["index"]))
            if [item["index"] for item in data] != list(range(len(batch))):
                raise RuntimeError("Embedding indexes do not match the requested batch.")
            vectors.extend([[float(value) for value in item["embedding"]] for item in data])
        return vectors

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise RuntimeError("Embedding dimensions do not match.")
        denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
            sum(value * value for value in right)
        )
        return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0

class ExternalRerankerAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        cancellation: CancellationToken,
        *,
        provider: str,
        model: str,
        base_url: str,
        api_key: str,
    ) -> None:
        self.client = client
        self.cancellation = cancellation
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_keys = ApiKeyPool(api_key)

    async def rerank(self, question: str, documents: list[PaperRecord]) -> RetrievalRerankResult:
        if not self.model or not self.base_url or not self.api_keys.available:
            raise RuntimeError("External reranker configuration is incomplete.")
        last_error: Exception | None = None
        for model in _model_names(self.model):
            try:
                items = []
                # A batch is a transport limit, not a cap on the candidate pool.
                # Retry the whole set on model fallback so scores never mix models.
                for start in range(0, len(documents), 200):
                    batch = documents[start:start + 200]
                    items.extend(await self._score_batch(question, batch, model))
                return RetrievalRerankResult(items=items, provider=self.provider, model=model)
            except Exception as exc:
                last_error = exc
        raise RuntimeError("All configured reranker models failed.") from last_error

    async def _score_batch(
        self, question: str, documents: list[PaperRecord], model: str,
    ) -> list[RetrievalRerankItem]:
        texts = [document_text(document)[:1800] for document in documents]
        if self.provider == "nvidia":
            url = self.base_url if self.base_url.endswith(("/reranking", "/ranking")) else f"{self.base_url}/reranking"
            body = {"model": model, "query": {"text": question}, "passages": [{"text": text} for text in texts]}
        else:
            url = f"{self.base_url}/rerank"
            body = {"model": model, "query": question, "documents": texts, "top_n": len(documents)}
        self.cancellation.raise_if_cancelled()
        # Both adapters use the same bounded key rotation and cancellation behavior.
        response, _ = await post_model_json(self.client, self.cancellation, url, body,
                                             self.api_keys.attempts(MODEL_ATTEMPTS))
        response.raise_for_status()
        payload = response.json()
        values = payload.get("rankings") if self.provider == "nvidia" else payload.get("results") or payload.get("data")
        scores = {}
        for value in values or []:
            index = value.get("index")
            if type(index) is not int or not 0 <= index < len(documents) or index in scores:
                raise RuntimeError("Reranker indexes do not match the requested batch.")
            score = float(value.get("logit", value.get("relevance_score", value.get("score"))))
            if not math.isfinite(score):
                raise RuntimeError("Reranker response contained non-finite scores.")
            scores[index] = score
        if len(scores) != len(documents):
            raise RuntimeError("Reranker score count does not match candidate count.")
        return [RetrievalRerankItem(document=documents[index], score=score) for index, score in scores.items()]
