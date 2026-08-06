import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from paperseek.history import HistoryStore
from paperseek.web_app import _RUN_EXECUTOR, app
from tests.helpers import temporary_env
from tests.helpers import fake_harness_search_result


class FakeSearchAgent:
    def __init__(self, config, llm):
        self.config = config
        self.llm = llm

    def search(
        self,
        question,
        verbose=False,
        event_handler=None,
        cancel_check=None,
        checkpoint_handler=None,
        resume_checkpoint=None,
    ):
        event_handler({"type": "stage", "stage": "query", "status": "complete"})
        checkpoint_handler({"sequence": 1, "stage": "query", "question": question})
        return fake_harness_search_result(question, self.config.data_source)


def wait_for_terminal(client, run_id, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}")
        if response.status_code == 200 and response.json()["status"] in {
            "success",
            "error",
            "cancelled",
        }:
            return response.json()
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not finish")


class RunApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_run_detail_event_replay_and_results_use_persisted_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "runs.db")
            with temporary_env(
                {"PAPERSEEK_HISTORY_ENABLED": "true", "PAPERSEEK_HISTORY_DB": db_path}
            ):
                store = HistoryStore()
                run_id = store.create_run("open innovation", {"data_source": "openalex"})
                store.record_event(run_id, {"type": "log", "message": "first"})
                store.record_event(run_id, {"type": "stage", "stage": "ranking", "status": "complete"})
                store.complete_run(
                    run_id,
                    {
                        "source": "openalex",
                        "final_query": "open innovation",
                        "total": 1,
                        "iterations": 1,
                        "ranked": [{"rank": 1, "uid": "W1", "title": "Open Innovation"}],
                    },
                )

                detail = self.client.get(f"/api/v1/runs/{run_id}")
                events = self.client.get(f"/api/v1/runs/{run_id}/events")
                after_first = self.client.get(
                    f"/api/v1/runs/{run_id}/events",
                    params={"after_id": events.json()["events"][0]["id"]},
                )
                results = self.client.get(f"/api/v1/runs/{run_id}/results")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], "success")
        self.assertEqual(len(events.json()["events"]), 2)
        self.assertEqual(len(after_first.json()["events"]), 1)
        self.assertEqual(results.json()["results"][0]["uid"], "W1")

    def test_run_cancel_targets_active_in_process_run(self):
        run = _RUN_EXECUTOR.create()
        run.bind("run_active_v1")
        try:
            response = self.client.post("/api/v1/runs/run_active_v1/cancel")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(run.is_cancelled())
        finally:
            run.close()

        missing = self.client.post("/api/v1/runs/run_missing/cancel")
        self.assertEqual(missing.status_code, 404)

    def test_run_cancel_persists_for_an_orphaned_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "runs.db")
            with temporary_env(
                {"PAPERSEEK_HISTORY_ENABLED": "true", "PAPERSEEK_HISTORY_DB": db_path}
            ):
                store = HistoryStore()
                run_id = store.create_run("orphaned search")
                response = self.client.post(f"/api/v1/runs/{run_id}/cancel")
                detail = self.client.get(f"/api/v1/runs/{run_id}")
                repeated = self.client.post(f"/api/v1/runs/{run_id}/cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(detail.json()["status"], "cancelled")
        self.assertEqual(repeated.status_code, 404)

    def test_api_v1_create_resume_and_retry_use_persisted_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "runs.db")
            payload = {
                "question": "open innovation",
                "data_source": "crossref",
                "llm_provider": "deepseek",
                "llm_api_key": "test-key",
                "expand_citations": False,
            }
            with temporary_env(
                {"PAPERSEEK_HISTORY_ENABLED": "true", "PAPERSEEK_HISTORY_DB": db_path}
            ), patch("paperseek.web_app.create_llm_client", return_value=object()), patch(
                "paperseek.web_app.PaperSeekAgent", FakeSearchAgent
            ):
                created = self.client.post("/api/v1/runs", json=payload)
                self.assertEqual(created.status_code, 202)
                created_id = created.json()["run_id"]
                self.assertEqual(wait_for_terminal(self.client, created_id)["status"], "success")

                store = HistoryStore()
                resume_id = store.create_run(
                    "open innovation",
                    {"data_source": "crossref"},
                )
                store.save_checkpoint(
                    resume_id,
                    {"sequence": 2, "stage": "retrieval", "question": "open innovation"},
                )
                store.fail_run(resume_id, "process stopped")
                resumed = self.client.post(f"/api/v1/runs/{resume_id}/resume", json=payload)
                self.assertEqual(resumed.status_code, 202)
                self.assertEqual(resumed.json()["run_id"], resume_id)
                self.assertEqual(wait_for_terminal(self.client, resume_id)["status"], "success")

                retried = self.client.post(f"/api/v1/runs/{created_id}/retry", json=payload)
                self.assertEqual(retried.status_code, 202)
                retry_id = retried.json()["run_id"]
                self.assertNotEqual(retry_id, created_id)
                self.assertEqual(retried.json()["source_run_id"], created_id)
                self.assertEqual(wait_for_terminal(self.client, retry_id)["status"], "success")

    def test_api_v1_rejects_retry_for_an_active_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "runs.db")
            payload = {
                "question": "open innovation",
                "data_source": "crossref",
                "llm_provider": "deepseek",
                "llm_api_key": "test-key",
                "expand_citations": False,
            }
            with temporary_env(
                {"PAPERSEEK_HISTORY_ENABLED": "true", "PAPERSEEK_HISTORY_DB": db_path}
            ):
                run_id = HistoryStore().create_run("open innovation")
                response = self.client.post(f"/api/v1/runs/{run_id}/retry", json=payload)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Run is still active.")

    def test_api_v1_rejects_resume_while_another_worker_holds_the_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "runs.db")
            payload = {
                "question": "open innovation",
                "data_source": "crossref",
                "llm_provider": "deepseek",
                "llm_api_key": "test-key",
                "expand_citations": False,
            }
            with temporary_env(
                {"PAPERSEEK_HISTORY_ENABLED": "true", "PAPERSEEK_HISTORY_DB": db_path}
            ):
                store = HistoryStore()
                run_id = store.create_run("open innovation", {"data_source": "crossref"})
                store.save_checkpoint(run_id, {"sequence": 1, "stage": "query"})
                self.assertTrue(store.claim_run(run_id, "worker-a", lease_seconds=60))
                response = self.client.post(f"/api/v1/runs/{run_id}/resume", json=payload)

        self.assertEqual(response.status_code, 409)
        self.assertIn("could not be claimed", response.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
