from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import httpx

from paperseek_app.execution import CancellationScope
from paperseek_app.services import RunSubmissionService
from paperseek_community.cli import _parser
from paperseek_community.composition import CommunityExecutionResolver
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_community.submission import (
    RetrievalRouteInput,
    RunSubmission,
    prepare_run_submission,
)
from paperseek_core.models import (
    CandidateMetadataEnrichmentRequest,
    PaperCitation,
    PaperIdentifiers,
    PaperRecord,
    PaperSource,
    RetrievalRequest,
)
from paperseek_core.ports import CandidateMetadataPort
from paperseek_core.retrieval import RetrievalPipeline
from paperseek_core.sources.contracts import (
    SourceCapabilities,
    SourceSearchMetadata,
    SourceSearchRequest,
    SourceSearchResult,
)
from paperseek_core.sources.crossref import CrossrefSource


def _settings() -> CommunityDeploymentSettings:
    return CommunityDeploymentSettings(
        llm_api_type="openai_chat",
        llm_base_url="https://llm.test/v1",
        llm_model="controlled-model",
        llm_api_key="controlled-key",
        openalex_api_key="",
        semantic_scholar_api_key="",
        pubmed_api_key="",
        wos_api_key="",
        google_scholar_api_key="",
        contact_email="paperseek-test@example.invalid",
    )


def _record(
    index: int,
    *,
    doi: str | None = None,
    year: int | None = None,
    citations: list[PaperCitation] | None = None,
) -> PaperRecord:
    return PaperRecord(
        uid=f"record-{index}",
        title=f"Controlled metadata candidate {index}",
        source=PaperSource(source_title="Controlled Journal", publish_year=year),
        citations=list(citations or []),
        identifiers=PaperIdentifiers(doi=doi or ""),
        provider="openalex",
        raw={"provider_marker": index},
    )


class RecordingTransport:
    def __init__(self, outcomes: dict[str, object] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.requests: list[dict[str, object]] = []

    async def request(self, source, method, url, **kwargs):
        self.requests.append(
            {
                "source": source,
                "method": method,
                "url": url,
                **kwargs,
            }
        )
        doi = str(url).split("/works/", 1)[-1]
        outcome = self.outcomes.get(doi)
        request = httpx.Request(method, url)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, tuple):
            status, body = outcome
            if isinstance(body, bytes):
                return httpx.Response(status, content=body, request=request), {}
            return httpx.Response(status, json=body, request=request), {}
        payload = outcome or {
            "message": {
                "is-referenced-by-count": 12,
                "published-print": {"date-parts": [[2022, 1, 1]]},
                "published-online": {"date-parts": [[2023, 4, 2]]},
            }
        }
        return httpx.Response(200, json=payload, request=request), {}


class FixtureSource:
    name = "openalex"
    capabilities = SourceCapabilities(
        source=name,
        lanes=("relevance",),
        metadata_fields=("title", "source", "citations", "identifiers"),
        max_page_size=200,
        max_lane_limit=200,
    )

    def __init__(self, records: list[PaperRecord]) -> None:
        self.records = records

    async def search(self, request: SourceSearchRequest) -> SourceSearchResult:
        return SourceSearchResult(
            metadata=SourceSearchMetadata(
                total=len(self.records),
                page=request.page,
                limit=request.limit,
            ),
            hits=list(self.records),
        )


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []
        self.checkpoints = []

    def on_event(self, event) -> None:
        self.events.append(event)

    def on_checkpoint(self, checkpoint) -> None:
        self.checkpoints.append(checkpoint)


class ExplodingMetadataPort:
    async def enrich_candidate_metadata(self, request):
        raise AssertionError("disabled metadata enrichment must make zero requests")


class M4CrossrefMetadataEnrichmentContract(unittest.IsolatedAsyncioTestCase):
    def test_submission_snapshot_and_cli_keep_the_feature_explicit_and_default_off(self) -> None:
        default = prepare_run_submission(
            RunSubmission(question="default metadata setting", source="openalex"),
            _settings(),
        )
        enabled = prepare_run_submission(
            RunSubmission(
                question="default metadata setting",
                source="openalex",
                retrieval=RetrievalRouteInput(crossref_metadata_enrichment=True),
            ),
            _settings(),
        )

        self.assertIs(default.config_snapshot["retrieval"]["crossref_metadata_enrichment"], False)
        self.assertIs(enabled.config_snapshot["retrieval"]["crossref_metadata_enrichment"], True)
        self.assertNotEqual(default.request_digest, enabled.request_digest)
        parsed = _parser().parse_args(
            ["search", "controlled question", "--retrieval-crossref-enrichment"]
        )
        self.assertIs(parsed.retrieval_crossref_enrichment, True)

    async def test_product_resolver_reuses_the_crossref_adapter_for_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "paperseek.db"
            migrate_database(database)
            uow = SQLiteRunUnitOfWork(database)
            credentials = EncryptedRunCredentialStore(database)
            service = RunSubmissionService(uow)
            prepared = prepare_run_submission(
                RunSubmission(
                    question="resolver metadata wiring",
                    source="openalex",
                    retrieval=RetrievalRouteInput(crossref_metadata_enrichment=True),
                ),
                _settings(),
            )
            run = service.submit_run(
                subject="metadata-contract",
                idempotency_key=str(uuid4()),
                request_digest=prepared.request_digest,
                question=prepared.question,
                source=prepared.source,
                config_snapshot=prepared.config_snapshot,
            )
            execution = CommunityExecutionResolver(_settings(), credentials)(
                run,
                CancellationScope(),
            )
            try:
                self.assertIsInstance(execution.candidate_metadata, CandidateMetadataPort)
                self.assertIs(execution.candidate_metadata, execution.abstracts)
                self.assertIs(execution.request.crossref_metadata_enrichment, True)
            finally:
                if execution.close is not None:
                    await execution.close()
                uow.close()

    async def test_disabled_pipeline_makes_zero_metadata_requests(self) -> None:
        original = _record(1, doi="10.5555/off")
        result = await RetrievalPipeline(
            FixtureSource([original]),
            RecordingObserver(),
            candidate_metadata=ExplodingMetadataPort(),
        ).run(
            RetrievalRequest(
                question="controlled question",
                query="controlled query",
                lane_limit=10,
                ranking_candidate_limit=10,
                pool_max=10,
                crossref_metadata_enrichment=False,
            )
        )

        self.assertEqual(result.documents, [original])
        self.assertEqual(result.warnings, [])

    async def test_crossref_adapter_fills_only_missing_fields_and_caps_the_batch_at_100(self) -> None:
        existing_citation = PaperCitation(db="OpenAlex", count=7)
        records = [_record(index, doi=f"10.5555/item-{index}") for index in range(1, 102)]
        records[1] = _record(
            2,
            doi="10.5555/item-2",
            year=2019,
            citations=[existing_citation],
        )
        original_first = records[0]
        transport = RecordingTransport()
        source = CrossrefSource(transport=transport, email="paperseek-test@example.invalid")

        outcome = await source.enrich_candidate_metadata(
            CandidateMetadataEnrichmentRequest(documents=records)
        )

        self.assertEqual(outcome.attempted_count, 100)
        self.assertEqual(outcome.enriched_count, 100)
        self.assertEqual(outcome.failed_count, 0)
        self.assertEqual(len(transport.requests), 100)
        self.assertEqual(outcome.documents[0].citations, [PaperCitation(db="Crossref", count=12)])
        self.assertEqual(outcome.documents[0].source.publish_year, 2022)
        self.assertEqual(outcome.documents[0].raw, original_first.raw)
        self.assertEqual(outcome.documents[0].provider, original_first.provider)
        self.assertEqual(original_first.citations, [])
        self.assertIsNone(original_first.source.publish_year)
        self.assertEqual(outcome.documents[1].citations, [existing_citation])
        self.assertEqual(outcome.documents[1].source.publish_year, 2019)
        self.assertEqual(outcome.documents[100], records[100])
        first_request = transport.requests[0]
        self.assertEqual(first_request["url"], "https://api.crossref.org/works/10.5555/item-1")
        self.assertEqual(first_request["timeout"], 20)
        self.assertEqual(first_request["attempts"], 1)
        self.assertEqual(
            first_request["headers"],
            {
                "Accept": "application/json",
                "User-Agent": "paperseek/1.0 (mailto:paperseek-test@example.invalid)",
            },
        )

    async def test_no_doi_and_all_crossref_failure_kinds_degrade_without_private_details(self) -> None:
        transport = RecordingTransport(
            {
                "10.5555/not-found": (404, {"private": "not-found-body"}),
                "10.5555/server": (500, {"private": "server-body"}),
                "10.5555/invalid": (200, b"{"),
                "10.5555/transport": httpx.ConnectError("private transport detail"),
            }
        )
        records = [
            _record(0),
            _record(1, doi="10.5555/not-found"),
            _record(2, doi="10.5555/server"),
            _record(3, doi="10.5555/invalid"),
            _record(4, doi="10.5555/transport"),
        ]

        outcome = await CrossrefSource(transport=transport).enrich_candidate_metadata(
            CandidateMetadataEnrichmentRequest(documents=records)
        )

        self.assertEqual(outcome.documents, records)
        self.assertEqual(outcome.attempted_count, 4)
        self.assertEqual(len(transport.requests), 4)
        self.assertEqual(outcome.failed_count, 4)
        self.assertEqual(outcome.warnings, ["retrieval_crossref_metadata_partial"])
        self.assertNotIn("private", repr(outcome))

    async def test_cancelled_crossref_metadata_request_propagates(self) -> None:
        transport = RecordingTransport(
            {"10.5555/cancel": asyncio.CancelledError()}
        )
        with self.assertRaises(asyncio.CancelledError):
            await CrossrefSource(transport=transport).enrich_candidate_metadata(
                CandidateMetadataEnrichmentRequest(
                    documents=[_record(1, doi="10.5555/cancel")]
                )
            )

    async def test_pipeline_applies_metadata_before_reranking_and_reports_degradation(self) -> None:
        success_observer = RecordingObserver()
        success = await RetrievalPipeline(
            FixtureSource([_record(1, doi="10.5555/success")]),
            success_observer,
            candidate_metadata=CrossrefSource(transport=RecordingTransport()),
        ).run(
            RetrievalRequest(
                question="controlled question",
                query="controlled query",
                lane_limit=10,
                ranking_candidate_limit=10,
                pool_max=10,
                crossref_metadata_enrichment=True,
            )
        )
        failure_observer = RecordingObserver()
        failure = await RetrievalPipeline(
            FixtureSource([_record(2, doi="10.5555/fail")]),
            failure_observer,
            candidate_metadata=CrossrefSource(
                transport=RecordingTransport(
                    {"10.5555/fail": (500, {"private": "server-body"})}
                )
            ),
        ).run(
            RetrievalRequest(
                question="controlled question",
                query="controlled query",
                lane_limit=10,
                ranking_candidate_limit=10,
                pool_max=10,
                crossref_metadata_enrichment=True,
            )
        )

        self.assertEqual(success.documents[0].citations[0].count, 12)
        self.assertEqual(success.documents[0].source.publish_year, 2022)
        self.assertEqual(success.warnings, [])
        self.assertIn(
            "retrieval.metadata_enrichment_completed",
            [event.event_type for event in success_observer.events],
        )
        self.assertEqual(failure.documents[0].citations, [])
        self.assertEqual(failure.warnings, ["retrieval_crossref_metadata_partial"])
        self.assertIn(
            "retrieval.metadata_enrichment_degraded",
            [event.event_type for event in failure_observer.events],
        )


if __name__ == "__main__":
    unittest.main()
