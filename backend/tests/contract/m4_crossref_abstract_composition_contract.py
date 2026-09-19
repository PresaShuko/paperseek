from __future__ import annotations

import asyncio
from datetime import timedelta
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from paperseek_app.execution import CancellationScope
from paperseek_app.models import RunStatus
from paperseek_app.services import (
    RunExecutionService,
    RunQueryService,
    RunSubmissionService,
)
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.composition import CommunityExecutionResolver
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_app.submission import RunSubmission, prepare_run_submission
from paperseek_app.worker import RunExecutor
from paperseek_core.enrichment import AbstractEnrichmentPipeline
from paperseek_core.models import AbstractEnrichmentRequest, CheckpointDraft, RankedPaper
from paperseek_core.ports import AbstractPort
from paperseek_core.sources.contracts import SourceSearchRequest
from paperseek_core.sources.crossref import CrossrefSource
from paperseek_core.sources.openalex import OpenAlexSource


LONG_ABSTRACT = "A sufficiently detailed Crossref abstract restored through the product composition."
RESUMED_ABSTRACT = "A previously committed abstract restored from the enrichment checkpoint."
ROOT = Path(__file__).resolve().parents[3]


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []
        self.checkpoints = []

    def on_event(self, event) -> None:
        self.events.append(event)

    def on_checkpoint(self, checkpoint) -> None:
        self.checkpoints.append(checkpoint)


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


def _llm_payloads(record_count: int) -> list[str]:
    return [
        (ROOT / "tests" / "fixtures" / "llm" / "intent_search_plan.json").read_text(
            encoding="utf-8"
        ),
        (ROOT / "tests" / "fixtures" / "llm" / "query_generated.json").read_text(
            encoding="utf-8"
        ),
        json.dumps({"scores": [[index, 9] for index in range(1, record_count + 1)]}),
        json.dumps(
            {
                "reasons": [
                    [index, "Matches the controlled product-composition fixture."]
                    for index in range(1, record_count + 1)
                ]
            }
        ),
    ]


class ControlledProductHTTP:
    def __init__(
        self,
        *,
        crossref_outcome: str = "success",
        with_doi: bool = True,
        record_count: int = 5,
    ) -> None:
        self.crossref_outcome = crossref_outcome
        self.with_doi = with_doi
        self.record_count = record_count
        self.llm_payloads = _llm_payloads(record_count)
        self.requests: list[httpx.Request] = []
        self.crossref_entered = asyncio.Event()

    @contextmanager
    def install(self):
        controlled = self
        real_client = httpx.AsyncClient

        class ControlledAsyncClient(real_client):
            def __init__(self, *args, **kwargs) -> None:
                kwargs["transport"] = httpx.MockTransport(controlled.handle)
                super().__init__(*args, **kwargs)

        with patch(
            "paperseek_community.composition.httpx.AsyncClient",
            ControlledAsyncClient,
        ):
            yield

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "llm.test":
            if not self.llm_payloads:
                raise AssertionError("The controlled LLM response queue was exhausted.")
            content = self.llm_payloads.pop(0)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": content}}]},
                request=request,
            )
        if request.url.host == "api.openalex.org":
            page = int(request.url.params.get("page", "1"))
            records = self._openalex_records() if page == 1 else []
            return httpx.Response(
                200,
                json={
                    "meta": {
                        "count": self.record_count,
                        "page": page,
                        "per_page": self.record_count,
                    },
                    "results": records,
                },
                request=request,
            )
        if request.url.host == "api.crossref.org":
            return await self._crossref_response(request)
        raise AssertionError(f"Unexpected controlled product request: {request.url}")

    def _openalex_records(self) -> list[dict]:
        records = []
        for index in range(1, self.record_count + 1):
            doi = f"https://doi.org/10.5555/product-{index}" if self.with_doi else None
            records.append(
                {
                    "id": f"https://openalex.org/W{index}",
                    "doi": doi,
                    "title": (
                        "Transparent AI decision systems and accountability in public agencies "
                        f"{index}"
                    ),
                    "publication_year": 2025,
                    "publication_date": "2025-01-01",
                    "type": "article",
                    "authorships": [{"author": {"display_name": "A. Researcher"}}],
                    "primary_location": {
                        "source": {"display_name": "Controlled Journal"},
                        "landing_page_url": f"https://example.invalid/W{index}",
                        "pdf_url": None,
                    },
                    "cited_by_count": index,
                    "abstract_inverted_index": None,
                    "keywords": [{"display_name": "controlled evidence"}],
                    "ids": {},
                    "primary_topic": {"field": {"id": "https://openalex.org/fields/17"}},
                    "referenced_works": [],
                    "product_marker": f"raw-{index}",
                }
            )
        return records

    async def _crossref_response(self, request: httpx.Request) -> httpx.Response:
        self.crossref_entered.set()
        outcome = self.crossref_outcome
        if outcome == "cancel_late":
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                return httpx.Response(
                    200,
                    json={"message": {"abstract": LONG_ABSTRACT}},
                    request=request,
                )
        if outcome == "success":
            return httpx.Response(
                200,
                json={"message": {"abstract": f"<jats:p>{LONG_ABSTRACT}</jats:p>"}},
                request=request,
            )
        if outcome == "short":
            return httpx.Response(200, json={"message": {"abstract": "Too short."}}, request=request)
        if outcome == "empty":
            return httpx.Response(200, json={"message": {"abstract": ""}}, request=request)
        if outcome == "invalid_json":
            return httpx.Response(200, content=b"{", request=request)
        if outcome in {"404", "500"}:
            return httpx.Response(int(outcome), json={"message": "private body"}, request=request)
        if outcome == "transport_error":
            raise httpx.ConnectError("private transport detail", request=request)
        raise AssertionError(f"Unsupported Crossref outcome: {outcome}")

    @property
    def selected_requests(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.host == "api.openalex.org"]

    @property
    def abstract_requests(self) -> list[httpx.Request]:
        return [
            request
            for request in self.requests
            if request.url.host == "api.crossref.org" and "/works/" in request.url.path
        ]


class M4CrossrefAbstractCompositionContract(unittest.IsolatedAsyncioTestCase):
    def _create_services(self, root: Path):
        database = root / "paperseek.db"
        migrate_database(database)
        uow = SQLiteRunUnitOfWork(database)
        store = FileArtifactStore(root)
        submission_service = RunSubmissionService(uow)
        execution_service = RunExecutionService(uow, store)
        query_service = RunQueryService(uow, store)
        credentials = EncryptedRunCredentialStore(database)
        return database, uow, submission_service, execution_service, query_service, credentials

    def _submit(
        self, service: RunSubmissionService, *, source: str = "openalex",
        fetch_abstracts: bool | None = True,
    ):
        prepared = prepare_run_submission(
            RunSubmission(
                question="controlled Community abstract composition",
                source=source,
                search_budget="fast",
                citation_enabled=False,
                **({"fetch_abstracts": fetch_abstracts} if fetch_abstracts is not None else {}),
            ),
            _settings(),
        )
        return service.submit_run(
            subject="community-abstract-contract",
            idempotency_key=str(uuid4()),
            request_digest=prepared.request_digest,
            question=prepared.question,
            source=prepared.source,
            config_snapshot=prepared.config_snapshot,
        )

    async def _execute_product_run(
        self,
        *,
        crossref_outcome: str,
        with_doi: bool = True,
        fetch_abstracts: bool | None = True,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database, uow, submission, execution, query, credentials = self._create_services(root)
            run = self._submit(submission, fetch_abstracts=fetch_abstracts)
            controlled = ControlledProductHTTP(
                crossref_outcome=crossref_outcome,
                with_doi=with_doi,
            )
            resolver = CommunityExecutionResolver(_settings(), credentials)
            executor = RunExecutor(
                execution,
                resolver,
                owner_id="abstract-contract",
                cancellation_poll_seconds=0.01,
            )
            try:
                with controlled.install():
                    detail = await executor.run_once()
                results = query.get_result_page(run.id, page_size=20).results
                artifacts = query.list_artifacts(run.id)
            finally:
                uow.close()
            return detail, results, artifacts, controlled, database

    async def test_non_crossref_source_gets_independent_crossref_port_on_same_transport(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _database, uow, submission, _execution, _query, credentials = self._create_services(root)
            run = self._submit(submission)
            controlled = ControlledProductHTTP(record_count=1)
            resolver = CommunityExecutionResolver(_settings(), credentials)
            try:
                with controlled.install():
                    execution = resolver(run, CancellationScope())
                self.assertIsInstance(execution.source, OpenAlexSource)
                self.assertIsInstance(execution.abstracts, CrossrefSource)
                self.assertIsInstance(execution.abstracts, AbstractPort)
                self.assertIs(execution.source.transport, execution.abstracts.transport)
                selected = await execution.source.search(
                    SourceSearchRequest(query="controlled evidence", lane="relevance", limit=1)
                )
                original = selected.hits[0]
                enriched = await AbstractEnrichmentPipeline(
                    execution.abstracts,
                    RecordingObserver(),
                ).run(
                    AbstractEnrichmentRequest(
                        items=[RankedPaper(document=original, score=1)],
                        batch_size=1,
                        concurrency=1,
                    )
                )
                self.assertEqual(len(controlled.selected_requests), 1)
                self.assertEqual(len(controlled.abstract_requests), 1)
                self.assertEqual(enriched.items[0].document.abstract, LONG_ABSTRACT)
                self.assertEqual(enriched.items[0].document.raw, original.raw)
                self.assertEqual(original.abstract, "")
            finally:
                if "execution" in locals() and execution.close is not None:
                    await execution.close()
                uow.close()

    async def test_crossref_selected_source_reuses_the_same_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _database, uow, submission, _execution, _query, credentials = self._create_services(root)
            run = self._submit(submission, source="crossref")
            controlled = ControlledProductHTTP()
            try:
                with controlled.install():
                    execution = CommunityExecutionResolver(_settings(), credentials)(
                        run,
                        CancellationScope(),
                    )
                self.assertIsInstance(execution.source, CrossrefSource)
                self.assertIs(execution.abstracts, execution.source)
            finally:
                if "execution" in locals() and execution.close is not None:
                    await execution.close()
                uow.close()

    async def test_default_product_run_does_not_request_external_abstracts(self) -> None:
        for option in (None, False):
            with self.subTest(fetch_abstracts=option):
                detail, results, _artifacts, controlled, _database = await self._execute_product_run(
                    crossref_outcome="success", fetch_abstracts=option,
                )
                self.assertEqual(detail.status, RunStatus.COMPLETED)
                self.assertEqual(len(results), 5)
                self.assertTrue(all(item.record.doi for item in results))
                self.assertTrue(all(item.record.abstract == "" for item in results))
                self.assertEqual(controlled.abstract_requests, [])

    async def test_product_run_enriches_doi_and_preserves_provider_record(self) -> None:
        detail, results, _artifacts, controlled, _database = await self._execute_product_run(
            crossref_outcome="success"
        )

        self.assertEqual(detail.status, RunStatus.COMPLETED)
        self.assertEqual(len(results), 5)
        self.assertEqual(len(controlled.selected_requests) > 0, True)
        self.assertEqual(len(controlled.abstract_requests), 5)
        self.assertTrue(all(item.record.abstract == LONG_ABSTRACT for item in results))
        self.assertTrue(all(item.record.provider == "openalex" for item in results))
        self.assertEqual(
            {item.record.uid for item in results},
            {f"https://openalex.org/W{index}" for index in range(1, 6)},
        )

    async def test_product_run_without_doi_makes_no_crossref_request(self) -> None:
        detail, results, _artifacts, controlled, _database = await self._execute_product_run(
            crossref_outcome="success",
            with_doi=False,
        )

        self.assertEqual(detail.status, RunStatus.COMPLETED)
        self.assertEqual(len(results), 5)
        self.assertEqual(controlled.abstract_requests, [])
        self.assertTrue(all(item.record.abstract == "" for item in results))

    async def test_short_empty_and_crossref_failures_are_warnings_not_failed_runs(self) -> None:
        for outcome, warning_prefix, metadata_status in (
            ("short", "abstract_enrichment_unavailable:", "unavailable"),
            ("empty", "abstract_enrichment_unavailable:", "unavailable"),
            ("404", "abstract_enrichment_failed:", "degraded"),
            ("500", "abstract_enrichment_failed:", "degraded"),
            ("invalid_json", "abstract_enrichment_failed:", "degraded"),
            ("transport_error", "abstract_enrichment_failed:", "degraded"),
        ):
            with self.subTest(outcome=outcome):
                detail, results, _artifacts, controlled, _database = await self._execute_product_run(
                    crossref_outcome=outcome
                )
                self.assertEqual(detail.status, RunStatus.COMPLETED_WITH_WARNINGS)
                self.assertEqual(len(controlled.abstract_requests), 5)
                self.assertTrue(all(warning.startswith(warning_prefix) for warning in detail.warnings))
                self.assertTrue(all(item.metadata_status == metadata_status for item in results))
                self.assertTrue(all(item.record.abstract == "" for item in results))
                self.assertNotIn("private", json.dumps(detail.warnings))

    async def test_cancellation_during_crossref_request_blocks_late_results_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _database, uow, submission, execution_service, query, credentials = self._create_services(root)
            run = self._submit(submission)
            controlled = ControlledProductHTTP(crossref_outcome="cancel_late")
            executor = RunExecutor(
                execution_service,
                CommunityExecutionResolver(_settings(), credentials),
                owner_id="abstract-cancel-contract",
                cancellation_poll_seconds=0.01,
            )
            try:
                with controlled.install():
                    task = asyncio.create_task(executor.run_once())
                    await asyncio.wait_for(controlled.crossref_entered.wait(), timeout=5)
                    before = {artifact.id for artifact in query.list_artifacts(run.id)}
                    submission.request_cancel(run.id)
                    detail = await asyncio.wait_for(task, timeout=5)
                after = {artifact.id for artifact in query.list_artifacts(run.id)}
                results = query.get_result_page(run.id, page_size=20).results
            finally:
                uow.close()

        self.assertEqual(detail.status, RunStatus.CANCELLED)
        self.assertEqual(results, [])
        self.assertEqual(after, before)
        self.assertGreaterEqual(len(controlled.abstract_requests), 1)

    async def test_enrichment_checkpoint_resume_skips_completed_doi(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _database, uow, submission, execution_service, query, credentials = self._create_services(root)
            run = self._submit(submission)
            lease = uow.claim_run(run.id, "abstract-resume-contract", timedelta(seconds=60))
            execution_service.append_checkpoint(
                lease,
                [],
                CheckpointDraft(
                    step_key="enrich_results.batch",
                    idempotency_key="controlled-enrichment-resume",
                    workflow_version=run.versions.workflow_version,
                    state={
                        "completed_ids": ["https://openalex.org/W1"],
                        "abstract_by_uid": {"https://openalex.org/W1": RESUMED_ABSTRACT},
                        "warnings": [],
                        "resume_from_stage": "enrich_results",
                        "step_workflow_version": "m2.enrichment.v1",
                    },
                ),
            )
            controlled = ControlledProductHTTP(crossref_outcome="success")
            scope = CancellationScope()
            execution = None
            try:
                with controlled.install():
                    execution = CommunityExecutionResolver(_settings(), credentials)(
                        query.get_run(run.id),
                        scope,
                    )
                detail = await execution_service.execute_claimed_workflow(
                    lease,
                    llm=execution.llm,
                    source=execution.source,
                    request=execution.request,
                    abstracts=execution.abstracts,
                    cancellation=scope,
                )
                results = query.get_result_page(run.id, page_size=20).results
            finally:
                if execution is not None and execution.close is not None:
                    await execution.close()
                uow.close()

        requested_paths = [request.url.path for request in controlled.abstract_requests]
        by_id = {item.record.uid: item.record for item in results}
        self.assertEqual(detail.status, RunStatus.COMPLETED)
        self.assertNotIn("/works/10.5555/product-1", requested_paths)
        self.assertEqual(len(requested_paths), 4)
        self.assertEqual(by_id["https://openalex.org/W1"].abstract, RESUMED_ABSTRACT)
        self.assertEqual(by_id["https://openalex.org/W2"].abstract, LONG_ABSTRACT)


if __name__ == "__main__":
    unittest.main()
