from __future__ import annotations

import asyncio
import httpx
import json
from pathlib import Path
import unittest

from paperseek_core.enrichment import AbstractEnrichmentPipeline
from paperseek_core.final_result import FinalResultAssembler
from paperseek_core.models import (
    AbstractEnrichmentRequest,
    AbstractFetchRequest,
    AbstractFetchResult,
    PaperCitation,
    PaperIdentifiers,
    PaperKeywords,
    PaperLinks,
    PaperNames,
    PaperRecord,
    PaperSource,
    QueryLoopBudget,
    RankedPaper,
    ResearchAssemblyRequest,
    ResearchWorkflowRequest,
    RetrievalRerankItem,
    RetrievalRerankResult,
    SearchPlan,
)
from paperseek_core.ports import AbstractPort
from paperseek_core.sources.contracts import (
    SourceCapabilities,
    SourceSearchMetadata,
    SourceSearchResult,
)
from paperseek_core.sources.openalex import OpenAlexSource
from paperseek_core.sources.crossref import CrossrefSource
from paperseek_core.sources.http import AsyncHttpTransport
from paperseek_core.workflow import ResearchWorkflow


ROOT = Path(__file__).resolve().parents[3]
M0 = ROOT / "tests" / "fixtures" / "golden_search"
FIXTURE = Path(__file__).parent / "fixtures" / "m2_enrichment_characterization.json"


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []
        self.checkpoints = []

    def on_event(self, event) -> None:
        self.events.append(event)

    def on_checkpoint(self, checkpoint) -> None:
        self.checkpoints.append(checkpoint)


class FixtureAbstractPort:
    def __init__(self) -> None:
        self.calls: list[AbstractFetchRequest] = []

    async def fetch_abstract(self, request: AbstractFetchRequest) -> AbstractFetchResult:
        self.calls.append(request)
        if request.doi.endswith("success"):
            return AbstractFetchResult(
                doi=request.doi,
                abstract="Updated & verified abstract with sufficient detail.",
                found=True,
            )
        if request.doi.endswith("failure"):
            raise RuntimeError("private upstream failure body")
        return AbstractFetchResult(doi=request.doi)


def record(uid: str, doi: str, abstract: str) -> PaperRecord:
    return PaperRecord(
        uid=uid,
        title=uid,
        identifiers=PaperIdentifiers(doi=doi),
        abstract=abstract,
        provider="fixture",
    )


class M2AbstractEnrichmentContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_characterized_success_failure_skip_warning_and_batch_checkpoint(self) -> None:
        characterized = json.loads(FIXTURE.read_text(encoding="utf-8"))
        source = FixtureAbstractPort()
        observer = RecordingObserver()
        items = [
            RankedPaper(document=record("success", "10.5555/success", "provider success"), score=9),
            RankedPaper(document=record("failure", "10.5555/failure", "provider failure"), score=8),
            RankedPaper(document=record("missing", "", "provider missing"), score=7),
        ]

        result = await AbstractEnrichmentPipeline(source, observer).run(
            AbstractEnrichmentRequest(items=items, batch_size=2, concurrency=2)
        )

        self.assertIsInstance(source, AbstractPort)
        self.assertEqual(
            [call.doi for call in source.calls],
            ["10.5555/success", "10.5555/failure"],
        )
        self.assertEqual(
            [item.document.abstract for item in result.items],
            [
                characterized["cleaning"]["output"],
                "provider failure",
                "provider missing",
            ],
        )
        self.assertEqual(result.warnings, ["abstract_enrichment_failed:10.5555/failure"])
        self.assertEqual(len(observer.checkpoints), 1)
        self.assertEqual(observer.checkpoints[0].step_key, "enrich_results.batch")
        self.assertEqual(observer.checkpoints[0].state["completed_ids"], ["success", "failure"])
        degraded = [event for event in observer.events if event.event_type == "enrichment.degraded"]
        self.assertEqual(degraded[0].payload["code"], "abstract_enrichment_failed")
        self.assertNotIn("private upstream failure body", json.dumps(degraded[0].payload))
        started = next(event.payload for event in observer.events if event.event_type == "enrichment.started")
        self.assertEqual(started["request_count"], 2)
        self.assertEqual(started["concurrency"], 2)
        progress = next(event.payload for event in observer.events if event.event_type == "enrichment.progress")
        self.assertEqual(progress["current"], 2)
        self.assertEqual(progress["total"], 2)
        self.assertEqual(progress["concurrency"], 2)
        completed = next(event.payload for event in observer.events if event.event_type == "enrichment.completed")
        self.assertEqual(completed["request_count"], 2)
        self.assertEqual(completed["enriched_count"], 1)

    async def test_resume_skips_committed_dois_and_retains_enriched_values(self) -> None:
        source = FixtureAbstractPort()
        first_observer = RecordingObserver()
        original = [
            RankedPaper(document=record("success", "10.5555/success", "provider success"), score=9),
            RankedPaper(document=record("failure", "10.5555/failure", "provider failure"), score=8),
        ]
        first = await AbstractEnrichmentPipeline(source, first_observer).run(
            AbstractEnrichmentRequest(items=original, batch_size=1, concurrency=1)
        )
        resume = first.resume
        resumed_source = FixtureAbstractPort()
        resumed = await AbstractEnrichmentPipeline(resumed_source, RecordingObserver()).run(
            AbstractEnrichmentRequest(items=original, batch_size=1, concurrency=1, resume=resume)
        )

        self.assertEqual(resumed_source.calls, [])
        self.assertEqual(
            [item.document.abstract for item in resumed.items],
            ["Updated & verified abstract with sufficient detail.", "provider failure"],
        )
        self.assertEqual(resumed.warnings, first.warnings)

    async def test_crossref_port_keeps_exact_request_cleaning_length_and_cache_contract(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls = []

            async def request(self, method, url, *, params=None, json=None, headers=None, timeout=None):
                del params, json
                self.calls.append({"method": method, "url": url, "headers": headers, "timeout": timeout})
                request = httpx.Request(method, url, headers=headers)
                if url.endswith("/10.5555/success"):
                    return httpx.Response(
                        200,
                        json={"message": {"abstract": "<jats:p>Updated &amp; verified abstract with sufficient detail.</jats:p>"}},
                        request=request,
                    )
                if url.endswith("/10.5555/short"):
                    return httpx.Response(200, json={"message": {"abstract": "Too short."}}, request=request)
                return httpx.Response(503, json={"message": "private upstream failure"}, request=request)

        client = Client()
        source = CrossrefSource(transport=AsyncHttpTransport(client=client, sleep=lambda _: asyncio.sleep(0)))
        success = await source.fetch_abstract(AbstractFetchRequest(doi="10.5555/success"))
        cached_success = await source.fetch_abstract(AbstractFetchRequest(doi="10.5555/success"))
        short = await source.fetch_abstract(AbstractFetchRequest(doi="10.5555/short"))
        cached_short = await source.fetch_abstract(AbstractFetchRequest(doi="10.5555/short"))
        with self.assertRaisesRegex(Exception, "HTTP 503"):
            await source.fetch_abstract(AbstractFetchRequest(doi="10.5555/failure"))
        with self.assertRaisesRegex(Exception, "cached Crossref"):
            await source.fetch_abstract(AbstractFetchRequest(doi="10.5555/failure"))

        self.assertEqual(success, cached_success)
        self.assertEqual(success.abstract, "Updated & verified abstract with sufficient detail.")
        self.assertTrue(success.found)
        self.assertEqual(short, cached_short)
        self.assertFalse(short.found)
        self.assertEqual(
            [(call["url"], call["timeout"]) for call in client.calls],
            [
                ("https://api.crossref.org/works/10.5555/success", 10),
                ("https://api.crossref.org/works/10.5555/short", 10),
                ("https://api.crossref.org/works/10.5555/failure", 10),
            ],
        )


def _paper_from_expected(item: dict) -> RankedPaper:
    document = PaperRecord(
        uid=item["uid"],
        title=item["title"],
        types=item["document_types"],
        source_types=item["document_types"],
        source=PaperSource(source_title=item["source"], publish_year=item["publish_year"]),
        names=PaperNames(
            authors=[{"display_name": name} for name in item["authors"]]
        ),
        links=PaperLinks.model_validate(item["links"]),
        citations=[PaperCitation(db="OpenAlex", count=item["citation_count"])],
        identifiers=PaperIdentifiers(doi=item["doi"], openalex=item["uid"]),
        keywords=PaperKeywords(author_keywords=item["keywords"].split("; ")),
        abstract=item["abstract"],
        provider=item["provider"],
    )
    return RankedPaper(
        document=document,
        score=item["score"],
        reasoning=item["reasoning"],
        provenance={
            "source_rank": item["source_rank"],
            "retrieval_score": item["retrieval_score"],
            "retrieval_lanes": item["retrieval_lanes"],
            "origins": ["retrieval"],
        },
    )


class M2FinalAssemblyContractTest(unittest.TestCase):
    def test_m0_ranked_user_fields_and_export_artifacts_are_exact(self) -> None:
        expected = json.loads((M0 / "final_result.json").read_text(encoding="utf-8"))
        expected_export = json.loads((M0 / "export.json").read_text(encoding="utf-8"))
        request = ResearchAssemblyRequest(
            question=expected["question"],
            source=expected["source"],
            search_plan=SearchPlan.model_validate(expected["search_plan"]),
            final_query=expected["final_query"],
            total=expected["total"],
            iterations=expected["iterations"],
            history=expected["history"],
            query_view_selection=expected["query_view_selection"],
            query_portfolio=expected["query_portfolio"],
            query_iteration_memory=expected_export["query_iteration_memory"],
            citation_map=expected["citation_map"],
            ranking_steps=expected["ranking_steps"],
            search_state=expected["search_state"],
            items=[_paper_from_expected(item) for item in expected["ranked"]],
        )

        result = FinalResultAssembler().assemble(request)

        self.assertEqual(
            result.public_payload(),
            expected,
        )
        artifacts = {artifact.filename: artifact for artifact in result.artifacts}
        self.assertEqual(
            set(artifacts),
            {"final_result.json", "export.json", "export.csv", "candidate_pool.jsonl", "citation_map.json"},
        )
        self.assertEqual(artifacts["export.csv"].content, (M0 / "export.csv").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(artifacts["export.json"].content), json.loads((M0 / "export.json").read_text(encoding="utf-8")))
        self.assertEqual(artifacts["candidate_pool.jsonl"].content, (M0 / "candidate_pool.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(artifacts["citation_map.json"].content), expected["citation_map"])


class FixtureWorkflowLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses

    async def chat_json(self, messages, *, temperature=0.0, max_tokens=4096) -> str:
        del messages, temperature, max_tokens
        if not self.responses:
            raise AssertionError("workflow LLM fixture was exhausted")
        return self.responses.pop(0)


class FixtureWorkflowSource:
    name = "openalex"
    capabilities = SourceCapabilities(source=name, lanes=("relevance",), supports_abstracts=True)

    def __init__(self, records: list[PaperRecord]) -> None:
        self.records = records

    async def search(self, request) -> SourceSearchResult:
        return SourceSearchResult(
            metadata=SourceSearchMetadata(total=len(self.records), page=request.page, limit=request.limit),
            hits=self.records if request.page == 1 else [],
        )


class ExistingAbstractPort:
    async def fetch_abstract(self, request: AbstractFetchRequest) -> AbstractFetchResult:
        return AbstractFetchResult(doi=request.doi, abstract=f"Enriched abstract for {request.doi}.", found=True)


class RecordingEmbedding:
    def __init__(self) -> None:
        self.calls = 0

    async def embedding_scores(self, question: str, documents: list[PaperRecord]) -> list[float]:
        del question
        self.calls += 1
        return [0.5 for _ in documents]


class RecordingReranker:
    def __init__(self) -> None:
        self.calls = 0

    async def rerank(self, question: str, documents: list[PaperRecord]) -> RetrievalRerankResult:
        del question
        self.calls += 1
        return RetrievalRerankResult(
            items=[RetrievalRerankItem(document=document, score=1.0) for document in documents]
        )


class M2ResearchWorkflowContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_single_workflow_passes_external_retrieval_ports_to_retrieval_stage(self) -> None:
        source_payload = json.loads((M0 / "source_responses.json").read_text(encoding="utf-8"))
        mapper = OpenAlexSource(transport=AsyncHttpTransport())
        records = [mapper._to_record(item) for item in source_payload["relevance"]]
        llm = FixtureWorkflowLLM(
            [
                (ROOT / "tests" / "fixtures" / "llm" / "intent_search_plan.json").read_text(encoding="utf-8"),
                (M0 / "llm_query.json").read_text(encoding="utf-8"),
                (M0 / "llm_ranking_scores.json").read_text(encoding="utf-8"),
                (M0 / "llm_ranking_reasons.json").read_text(encoding="utf-8"),
            ]
        )
        embedding = RecordingEmbedding()
        reranker = RecordingReranker()
        workflow = ResearchWorkflow(
            llm=llm,
            source=FixtureWorkflowSource(records),
            observer=RecordingObserver(),
            embedding=embedding,
            reranker=reranker,
        )

        await workflow.run(
            ResearchWorkflowRequest(
                question="How do transparent AI decision systems affect accountability in public agencies?",
                query_budget=QueryLoopBudget(
                    target_min=1,
                    target_max=5,
                    retrieval_pool_min=1,
                    retrieval_pool_max=3000,
                    max_iterations=5,
                    query_portfolio_enabled=False,
                ),
                citation_enabled=False,
                fetch_abstracts=False,
            )
        )

        self.assertEqual(embedding.calls, 1)
        self.assertEqual(reranker.calls, 1)

    async def test_single_workflow_composes_every_core_stage_and_checkpoints_final_artifacts(self) -> None:
        source_payload = json.loads((M0 / "source_responses.json").read_text(encoding="utf-8"))
        mapper = OpenAlexSource(transport=AsyncHttpTransport())
        records = [mapper._to_record(item) for item in source_payload["relevance"]]
        llm = FixtureWorkflowLLM(
            [
                (ROOT / "tests" / "fixtures" / "llm" / "intent_search_plan.json").read_text(encoding="utf-8"),
                (M0 / "llm_query.json").read_text(encoding="utf-8"),
                (M0 / "llm_ranking_scores.json").read_text(encoding="utf-8"),
                (M0 / "llm_ranking_reasons.json").read_text(encoding="utf-8"),
            ]
        )
        observer = RecordingObserver()
        workflow = ResearchWorkflow(
            llm=llm,
            source=FixtureWorkflowSource(records),
            observer=observer,
            abstracts=ExistingAbstractPort(),
        )

        result = await workflow.run(
            ResearchWorkflowRequest(
                question="How do transparent AI decision systems affect accountability in public agencies?",
                query_budget=QueryLoopBudget(
                    target_min=1,
                    target_max=5,
                    retrieval_pool_min=1,
                    retrieval_pool_max=3000,
                    max_iterations=5,
                    query_portfolio_enabled=False,
                ),
                citation_enabled=True,
            )
        )

        self.assertEqual([item.uid for item in result.ranked], [record.uid for record in records])
        self.assertTrue(all(item.abstract.startswith("Enriched abstract for ") for item in result.ranked))
        self.assertEqual(result.warnings, [])
        stages = [event.stage for event in observer.events]
        for stage in ("workflow", "query", "retrieval", "citation", "ranking", "enrichment"):
            self.assertIn(stage, stages)
        self.assertEqual(observer.checkpoints[-1].step_key, "assemble_final_result")
        self.assertEqual(
            {item["filename"] for item in observer.checkpoints[-1].state["artifacts"]},
            {"final_result.json", "export.json", "export.csv", "candidate_pool.jsonl", "citation_map.json"},
        )
        self.assertEqual(observer.events[-1].event_type, "workflow.completed")


if __name__ == "__main__":
    unittest.main()
