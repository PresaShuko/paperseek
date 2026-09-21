"""Contracts for full-set result filtering/sorting/summary and history search.

The results endpoint must filter, sort and summarize over the run's complete
committed result set; pagination is only a transport concern. History search
must cover the full history, not just the loaded first page.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from paperseek_app.errors import InvalidCursor, InvalidResultQuery
from paperseek_app.models import (
    ArtifactRole,
    ArtifactVisibility,
    ArtifactWrite,
    PendingEvent,
)
from paperseek_app.services import (
    RunExecutionService,
    RunQueryService,
    RunSubmissionService,
)
from paperseek_community.api import create_app
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_core.models import CheckpointDraft, FinalPaperResult, ResearchResult


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += timedelta(seconds=seconds)


def _record(rank: int, **overrides) -> FinalPaperResult:
    values = {
        "rank": rank,
        "title": f"Paper {rank}",
        "uid": f"paper-{rank}",
        "source": "Journal",
        "provider": "openalex",
        "authors_text": f"Author {rank}",
        "keywords_text": "",
        "abstract": "",
        "doi": "",
        "pdf_url": "",
        "citation_count": 0,
    }
    values.update(overrides)
    return FinalPaperResult(**values)


class M4ResultQueryContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name)
        self.database = self.data_dir / "paperseek.db"
        self.clock = MutableClock()
        migrate_database(self.database)
        self.store = FileArtifactStore(self.data_dir)
        self.uow = SQLiteRunUnitOfWork(self.database, clock=self.clock)
        self.addCleanup(self.uow.close)
        self.submission_service = RunSubmissionService(self.uow)
        self.execution_service = RunExecutionService(self.uow, self.store)
        self.query_service = RunQueryService(self.uow, self.store)

    def _complete(self, records: list[FinalPaperResult], *, question: str | None = None):
        run = self.submission_service.create_run(
            question or f"Question {self.clock.value.isoformat()}", "openalex"
        )
        lease = self.uow.claim_run(run.id, "contract-worker", timedelta(seconds=60))
        self.execution_service.append_checkpoint(
            lease,
            [PendingEvent(event_type="workflow.progress", stage="workflow", payload={})],
            CheckpointDraft(
                step_key="assemble_final_result",
                idempotency_key="final-before-complete",
                state={"final": True, "step_workflow_version": "m2.research-workflow.v1"},
                workflow_version="m2.research-workflow.v1",
                schema_version=1,
            ),
        )
        payload = {"ranked": [record.model_dump(mode="json") for record in records]}
        artifacts = [
            self.store.put(
                ArtifactWrite(
                    run_id=run.id,
                    kind="final_result",
                    role=ArtifactRole.COMPLETION_REQUIRED,
                    visibility=ArtifactVisibility.USER,
                    filename="final_result.json",
                    media_type="application/json",
                    schema_version=1,
                    content=(json.dumps(payload) + "\n").encode(),
                )
            ),
            self.store.put(
                ArtifactWrite(
                    run_id=run.id,
                    kind="export_json",
                    role=ArtifactRole.COMPLETION_REQUIRED,
                    visibility=ArtifactVisibility.USER,
                    filename="export.json",
                    media_type="application/json",
                    schema_version=1,
                    content=(json.dumps(payload, sort_keys=True) + "\n").encode(),
                )
            ),
        ]
        result = ResearchResult(
            question=run.question,
            search_intent="contract",
            search_plan={"intent": "contract"},
            source="openalex",
            final_query="contract",
            db="OPENALEX",
            ranked=records,
        )
        completed = self.uow.complete_run(lease, [], result, artifacts)
        self.clock.advance()
        return completed

    def _seed_results(self):
        records = [
            _record(1, title="Alpha study", score=9, abstract="has abstract", doi="10.1/a", citation_count=30, publish_year=2020),
            _record(2, title="Beta study", score=8, doi="10.1/b", citation_count=10, publish_year=2022),
            _record(3, title="Gamma study", score=None, abstract="has abstract", citation_count=99, publish_year=2019),
            _record(4, title="Delta study", score=7.5, pdf_url="https://pdf.example/d", citation_count=5, publish_year=2024),
            _record(5, title="Epsilon study", score=0, doi="10.1/e", citation_count=1, publish_year=2021),
            _record(6, title="Transformer survey", score=None, keywords_text="transformer; attention", citation_count=50, publish_year=2023),
        ]
        return self._complete(records, question="Result query seed")

    def test_summary_counts_cover_the_complete_set(self) -> None:
        run = self._seed_results()
        page = self.query_service.get_result_page(run.id, page_size=2)
        self.assertEqual(page.total_count, 6)
        self.assertEqual(page.matched_count, 6)
        self.assertEqual(page.scored_count, 4)
        self.assertEqual(page.max_score, 9)
        self.assertEqual([item.rank for item in page.results], [1, 2])
        self.assertIsNotNone(page.next_cursor)

    def test_text_search_matches_beyond_the_first_page(self) -> None:
        run = self._seed_results()
        page = self.query_service.get_result_page(run.id, page_size=2, query="transformer")
        self.assertEqual(page.matched_count, 1)
        self.assertEqual([item.record.title for item in page.results], ["Transformer survey"])
        self.assertIsNone(page.next_cursor)

    def test_min_score_excludes_unscored_but_keeps_legal_zero(self) -> None:
        run = self._seed_results()
        page = self.query_service.get_result_page(run.id, min_score=0)
        self.assertEqual([item.record.title for item in page.results],
                         ["Alpha study", "Beta study", "Delta study", "Epsilon study"])
        page = self.query_service.get_result_page(run.id, min_score=8)
        self.assertEqual([item.record.title for item in page.results], ["Alpha study", "Beta study"])

    def test_metadata_filters(self) -> None:
        run = self._seed_results()
        self.assertEqual(
            [item.record.title for item in self.query_service.get_result_page(run.id, metadata="abstract").results],
            ["Alpha study", "Gamma study"],
        )
        self.assertEqual(
            [item.record.title for item in self.query_service.get_result_page(run.id, metadata="doi").results],
            ["Alpha study", "Beta study", "Epsilon study"],
        )
        self.assertEqual(
            [item.record.title for item in self.query_service.get_result_page(run.id, metadata="pdf").results],
            ["Delta study"],
        )

    def test_sort_orders_with_unscored_last_and_stable_ties(self) -> None:
        run = self._seed_results()
        by_score = self.query_service.get_result_page(run.id, sort="score")
        self.assertEqual(
            [(item.record.title, item.record.score) for item in by_score.results],
            [
                ("Alpha study", 9),
                ("Beta study", 8),
                ("Delta study", 7.5),
                ("Epsilon study", 0),
                ("Gamma study", None),
                ("Transformer survey", None),
            ],
        )
        by_citations = self.query_service.get_result_page(run.id, sort="citations")
        self.assertEqual([item.record.title for item in by_citations.results][:2],
                         ["Gamma study", "Transformer survey"])
        by_year = self.query_service.get_result_page(run.id, sort="year")
        self.assertEqual([item.record.title for item in by_year.results][:2],
                         ["Delta study", "Transformer survey"])

    def test_cursor_roundtrip_and_filter_mismatch_rejection(self) -> None:
        run = self._seed_results()
        first = self.query_service.get_result_page(run.id, page_size=2, sort="score")
        second = self.query_service.get_result_page(run.id, cursor=first.next_cursor, page_size=2, sort="score")
        self.assertEqual([item.record.title for item in second.results], ["Delta study", "Epsilon study"])
        with self.assertRaises(InvalidCursor):
            self.query_service.get_result_page(run.id, cursor=first.next_cursor, page_size=2, sort="citations")

    def test_invalid_query_parameters_are_rejected(self) -> None:
        run = self._seed_results()
        with self.assertRaises(InvalidResultQuery):
            self.query_service.get_result_page(run.id, sort="unknown")
        with self.assertRaises(InvalidResultQuery):
            self.query_service.get_result_page(run.id, metadata="unknown")
        with self.assertRaises(InvalidResultQuery):
            self.query_service.get_result_page(run.id, min_score=11)

    def test_api_exposes_filters_summary_and_validation(self) -> None:
        run = self._seed_results()
        client = TestClient(create_app(self.database))
        response = client.get(f"/api/v1/runs/{run.id}/results", params={"min_score": 8})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["matched_count"], 2)
        self.assertEqual(payload["total_count"], 6)
        self.assertEqual(payload["scored_count"], 4)
        self.assertEqual(payload["max_score"], 9)
        bad = client.get(f"/api/v1/runs/{run.id}/results", params={"sort": "unknown"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["error"]["code"], "invalid_result_query")

    def test_history_search_covers_all_pages(self) -> None:
        for index in range(5):
            self._complete([_record(1)], question=f"Common topic run {index}")
        self._complete([_record(1)], question="Needle in the history haystack")
        page = self.query_service.get_history_page(page_size=2, query="needle")
        self.assertEqual(page.matched_count, 1)
        self.assertEqual([item.question for item in page.items], ["Needle in the history haystack"])
        common = self.query_service.get_history_page(page_size=2, query="common")
        self.assertEqual(common.matched_count, 5)
        self.assertIsNotNone(common.next_cursor)
        rest = self.query_service.get_history_page(cursor=common.next_cursor, page_size=2, query="common")
        self.assertEqual(len(rest.items), 2)
        with self.assertRaises(InvalidCursor):
            self.query_service.get_history_page(cursor=common.next_cursor, page_size=2, query="other")
        unfiltered = self.query_service.get_history_page(page_size=10)
        self.assertEqual(len(unfiltered.items), 6)
        self.assertEqual(unfiltered.matched_count, 0)

    def test_history_api_search(self) -> None:
        self._complete([_record(1)], question="Visible through the API")
        client = TestClient(create_app(self.database))
        response = client.get("/api/v1/history", params={"query": "visible"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["matched_count"], 1)
        self.assertEqual(payload["items"][0]["question"], "Visible through the API")

    def test_high_score_count_uses_full_set_threshold(self) -> None:
        run = self._seed_results()
        page = self.query_service.get_result_page(run.id, page_size=1)
        self.assertEqual(page.high_score_count, 3)
        client = TestClient(create_app(self.database))
        payload = client.get(f"/api/v1/runs/{run.id}/results").json()
        self.assertEqual(payload["high_score_count"], 3)

    def test_selected_export_csv_and_json_use_full_records(self) -> None:
        run = self._seed_results()
        csv_content = self.query_service.get_selected_export(run.id, "csv", ["paper-1", "paper-5"])
        text = csv_content.content.decode("utf-8")
        self.assertIn("Alpha study", text)
        self.assertIn("Epsilon study", text)
        self.assertNotIn("Beta study", text)
        self.assertEqual(csv_content.filename, "export-selected.csv")
        json_content = self.query_service.get_selected_export(run.id, "json", ["paper-6"])
        payload = json.loads(json_content.content.decode("utf-8"))
        self.assertEqual([item["title"] for item in payload["ranked"]], ["Transformer survey"])
        self.assertIsNone(payload["ranked"][0]["score"])

    def test_selected_export_rejects_empty_or_foreign_selection(self) -> None:
        run = self._seed_results()
        with self.assertRaises(InvalidResultQuery):
            self.query_service.get_selected_export(run.id, "csv", [])
        with self.assertRaises(InvalidResultQuery):
            self.query_service.get_selected_export(run.id, "csv", ["not-in-this-run"])
        with self.assertRaises(InvalidResultQuery):
            self.query_service.get_selected_export(run.id, "xml", ["paper-1"])
        client = TestClient(create_app(self.database))
        response = client.post(
            f"/api/v1/runs/{run.id}/export-selected",
            json={"format": "csv", "uids": ["paper-1"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("attachment", response.headers["content-disposition"])
        bad = client.post(
            f"/api/v1/runs/{run.id}/export-selected",
            json={"format": "csv", "uids": []},
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["error"]["code"], "invalid_result_query")


if __name__ == "__main__":
    unittest.main()
