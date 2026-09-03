from __future__ import annotations

import asyncio
import math
from typing import Any

import httpx

from paperseek_community.key_pool import ApiKeyPool, retryable_key_status
from paperseek_core.models import PaperRecord, RetrievalRerankItem, RetrievalRerankResult
from paperseek_core.ports import CancellationToken
from paperseek_core.retrieval import document_text


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

    async def embedding_scores(self, question: str, documents: list[PaperRecord]) -> list[float]:
        if not self.model or not self.base_url or not self.api_keys.available:
            raise RuntimeError("External embedding configuration is incomplete.")
        texts = [question, *[document_text(document)[:1800] for document in documents]]
        last_error: Exception | None = None
        for model in self._models(self.model):
            try:
                if self.provider == "nvidia":
                    vectors = [*(await self._vectors(texts[:1], model, input_type="query"))]
                    vectors.extend(await self._vectors(texts[1:], model, input_type="passage"))
                else:
                    vectors = await self._vectors(texts, model)
                if len(vectors) != len(texts):
                    raise RuntimeError("Embedding vector count does not match input count.")
                return [self._cosine(vectors[0], vector) for vector in vectors[1:]]
            except Exception as exc:
                last_error = exc
        raise RuntimeError("All configured embedding models failed.") from last_error

    async def _vectors(self, texts: list[str], model: str, *, input_type: str = "") -> list[list[float]]:
        if not texts:
            return []
        body: dict[str, Any] = {"model": model, "input": texts, "encoding_format": "float"}
        if input_type:
            body["input_type"] = input_type
        response = await self._post(f"{self.base_url}/embeddings", body)
        data = response.json().get("data") or []
        data = sorted(data, key=lambda item: int(item.get("index", 0)))
        return [[float(value) for value in item["embedding"]] for item in data]

    async def _post(self, url: str, body: dict[str, Any]) -> httpx.Response:
        last_response: httpx.Response | None = None
        keys = self.api_keys.attempts()
        for index, api_key in enumerate(keys):
            try:
                response = await self._cancellable_post(url, body, api_key)
            except httpx.RequestError:
                if index + 1 < len(keys):
                    continue
                raise
            last_response = response
            if not retryable_key_status(response.status_code):
                response.raise_for_status()
                return response
            if index + 1 == len(keys):
                response.raise_for_status()
        assert last_response is not None
        return last_response

    async def _cancellable_post(self, url: str, body: dict[str, Any], api_key: str) -> httpx.Response:
        self.cancellation.raise_if_cancelled()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if self.provider == "nvidia":
            headers["Accept"] = "application/json"
        request = asyncio.create_task(self.client.post(
            url,
            json=body,
            headers=headers,
        ))
        cancelled = asyncio.create_task(self.cancellation.wait())
        try:
            done, _ = await asyncio.wait({request, cancelled}, return_when=asyncio.FIRST_COMPLETED)
            if cancelled in done:
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
                self.cancellation.raise_if_cancelled()
                raise asyncio.CancelledError
            return await request
        finally:
            for task in (request, cancelled):
                if not task.done():
                    task.cancel()
            await asyncio.gather(request, cancelled, return_exceptions=True)

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise RuntimeError("Embedding dimensions do not match.")
        denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
            sum(value * value for value in right)
        )
        return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0

    @staticmethod
    def _models(value: str) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value.replace(";", ",").split(",") if item.strip()))

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
        selected = documents[:200]
        texts = [document_text(document)[:1800] for document in selected]
        last_error: Exception | None = None
        for model in ExternalEmbeddingAdapter._models(self.model):
            try:
                if self.provider == "nvidia":
                    url = self.base_url if self.base_url.endswith(("/reranking", "/ranking")) else f"{self.base_url}/reranking"
                    body = {
                        "model": model,
                        "query": {"text": question},
                        "passages": [{"text": text} for text in texts],
                    }
                else:
                    url = f"{self.base_url}/rerank"
                    body = {"model": model, "query": question, "documents": texts, "top_n": len(selected)}
                self.cancellation.raise_if_cancelled()
                response = None
                keys = self.api_keys.attempts()
                for index, api_key in enumerate(keys):
                    try:
                        response = await ExternalEmbeddingAdapter._cancellable_post(self, url, body, api_key)
                    except httpx.RequestError:
                        if index + 1 < len(keys):
                            continue
                        raise
                    if not retryable_key_status(response.status_code):
                        break
                    if index + 1 == len(keys):
                        break
                assert response is not None
                response.raise_for_status()
                payload = response.json()
                values = payload.get("rankings") if self.provider == "nvidia" else payload.get("results") or payload.get("data")
                items = []
                for value in values or []:
                    index = value.get("index")
                    if isinstance(index, int) and 0 <= index < len(selected):
                        score = value.get("logit", value.get("relevance_score", value.get("score", 0)))
                        items.append(RetrievalRerankItem(document=selected[index], score=float(score or 0)))
                if not items:
                    raise RuntimeError("Reranker response contained no indexed scores.")
                return RetrievalRerankResult(items=items)
            except Exception as exc:
                last_error = exc
        raise RuntimeError("All configured reranker models failed.") from last_error
