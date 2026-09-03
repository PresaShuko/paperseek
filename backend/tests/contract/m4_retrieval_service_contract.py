from __future__ import annotations

import asyncio
import unittest

import httpx

from paperseek_app.execution import CancellationScope
from paperseek_community.retrieval_services import ExternalEmbeddingAdapter, ExternalRerankerAdapter
from paperseek_core.models import PaperRecord


class FakeClient:
    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def post(self, url: str, *, json: dict, headers: dict) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "headers": headers})
        status, payload = self.responses.pop(0)
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))


class BlockingClient:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def post(self, url: str, *, json: dict, headers: dict) -> httpx.Response:
        del url, json, headers
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def record(uid: str, title: str) -> PaperRecord:
    return PaperRecord(uid=uid, title=title)


class M4RetrievalServiceContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_openai_compatible_embedding_scores_and_model_fallback(self) -> None:
        client = FakeClient([
            (500, {"error": "synthetic"}),
            (200, {"data": [
                {"index": 0, "embedding": [1.0, 0.0]},
                {"index": 1, "embedding": [1.0, 0.0]},
                {"index": 2, "embedding": [0.0, 1.0]},
            ]}),
        ])
        adapter = ExternalEmbeddingAdapter(
            client, CancellationScope(), provider="cstcloud",
            model="first-model,second-model", base_url="https://embedding.example/v1", api_key="fixture-key",
        )

        scores = await adapter.embedding_scores("graph", [record("a", "graph"), record("b", "policy")])

        self.assertEqual(scores, [1.0, 0.0])
        self.assertEqual([call["json"]["model"] for call in client.calls], ["first-model", "second-model"])
        self.assertEqual(client.calls[-1]["url"], "https://embedding.example/v1/embeddings")
        self.assertEqual(client.calls[-1]["json"]["encoding_format"], "float")
        self.assertEqual(client.calls[-1]["headers"]["Authorization"], "Bearer fixture-key")

    async def test_embedding_rotates_key_pool_on_retryable_status(self) -> None:
        client = FakeClient([
            (429, {"error": "synthetic"}),
            (200, {"data": [
                {"index": 0, "embedding": [1.0, 0.0]},
                {"index": 1, "embedding": [1.0, 0.0]},
            ]}),
        ])
        adapter = ExternalEmbeddingAdapter(
            client, CancellationScope(), provider="cstcloud",
            model="fixture-model", base_url="https://embedding.example/v1", api_key="key-a,key-b",
        )

        self.assertEqual(await adapter.embedding_scores("graph", [record("a", "graph")]), [1.0])
        self.assertEqual(
            [call["headers"]["Authorization"] for call in client.calls],
            ["Bearer key-a", "Bearer key-b"],
        )

    async def test_stop_cancels_blocked_external_request(self) -> None:
        client = BlockingClient()
        cancellation = CancellationScope()
        adapter = ExternalEmbeddingAdapter(
            client, cancellation, provider="cstcloud",
            model="fixture-model", base_url="https://embedding.example/v1", api_key="fixture-key",
        )
        task = asyncio.create_task(adapter.embedding_scores("graph", [record("a", "graph")]))
        await client.started.wait()

        cancellation.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        self.assertTrue(client.cancelled)

    async def test_nvidia_reranker_maps_indexed_scores(self) -> None:
        client = FakeClient([(200, {"rankings": [
            {"index": 1, "logit": 0.95},
            {"index": 0, "logit": 0.2},
        ]})])
        adapter = ExternalRerankerAdapter(
            client, CancellationScope(), provider="nvidia",
            model="nv-rerank-qa-mistral-4b:1",
            base_url="https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking",
            api_key="fixture-key",
        )
        documents = [record("a", "First"), record("b", "Second")]

        result = await adapter.rerank("question", documents)

        self.assertEqual([(item.document.uid, item.score) for item in result.items], [("b", 0.95), ("a", 0.2)])
        self.assertEqual(client.calls[0]["json"]["query"], {"text": "question"})
        self.assertEqual(client.calls[0]["json"]["passages"], [{"text": "First"}, {"text": "Second"}])


if __name__ == "__main__":
    unittest.main()
