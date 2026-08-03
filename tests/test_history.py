import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from paperseek.config import AgentConfig
from paperseek.history import HistoryStore, result_payload_from_search_result, safe_search_params_from_config
from paperseek.web_app import app
from tests.helpers import temporary_env


class HistoryStoreTest(unittest.TestCase):
    def test_result_payload_preserves_search_loop_state_for_api_surfaces(self):
        payload = result_payload_from_search_result(
            {
                "question": "open innovation",
                "source": "openalex",
                "final_query": '"open innovation"',
                "db": "OPENALEX",
                "field": "",
                "total": 1,
                "iterations": 1,
                "history": [{"iteration": 1, "total": 1}],
                "search_loop": {"backend_used": "langgraph"},
                "search_state": {"recovery_decisions": [{"action": "repair_query"}]},
                "ranking_steps": [{"id": "llm_ranking"}],
                "citation_map": {},
                "ranked": [],
            },
            "openalex",
        )

        self.assertEqual(payload["search_loop"]["backend_used"], "langgraph")
        self.assertEqual(payload["search_state"]["recovery_decisions"][0]["action"], "repair_query")
        self.assertEqual(payload["ranking_steps"][0]["id"], "llm_ranking")

    def test_store_saves_run_events_and_results_without_raw_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paperseek.db"
            store = HistoryStore(db_path=db_path, enabled=True)
            config = AgentConfig(
                data_source="openalex",
                openalex_api_key="oa-secret",
                llm_api_key="llm-secret",
                llm_provider="openai",
                llm_api_type="openai_responses",
                llm_model="gpt-5.4-mini",
                llm_base_url="https://api.openai.com/v1",
                discipline_fields=("17", "14"),
            )
            run_id = store.create_run("open innovation", safe_search_params_from_config(config))
            store.record_event(run_id, {"type": "log", "message": "Started", "api_key": "event-secret"})
            store.complete_run(
                run_id,
                {
                    "question": "open innovation",
                    "source": "openalex",
                    "final_query": '"open innovation"',
                    "db": "OPENALEX",
                    "field": "",
                    "total": 1,
                    "iterations": 1,
                    "history": [{"iteration": 1, "query": '"open innovation"', "total": 1}],
                    "search_loop": {"backend_requested": "auto", "backend_used": "langgraph"},
                    "search_state": {
                        "question": "open innovation",
                        "source": "openalex",
                        "current_query": '"open innovation"',
                        "recovery_decisions": [{"action": "repair_query", "message": "Recovered with sk-secret-value"}],
                    },
                    "citation_map": {"enabled": True, "nodes": [], "edges": []},
                    "ranking_steps": [{"id": "llm_ranking", "status": "complete", "api_key": "ranking-secret"}],
                    "ranked": [
                        {
                            "rank": 1,
                            "uid": "W1",
                            "provider": "openalex",
                            "title": "Open Innovation",
                            "authors": ["Ada Lovelace"],
                            "publish_year": 2025,
                            "source": "Research Policy",
                            "doi": "10.1234/example",
                            "links": {"record": "https://example.org/record"},
                            "keywords": "open innovation; platforms",
                            "citations": "42",
                            "score": 9.1,
                            "reasoning": "Relevant",
                        }
                    ],
                },
            )

            runs = store.list_runs()
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["result_count"], 1)

            detail = store.get_run(run_id)
            self.assertIsNotNone(detail)
            self.assertEqual(detail["status"], "success")
            self.assertEqual(detail["history"][0]["total"], 1)
            self.assertEqual(detail["search_loop"]["backend_used"], "langgraph")
            self.assertEqual(detail["search_state"]["recovery_decisions"][0]["action"], "repair_query")
            self.assertEqual(detail["ranking_steps"][0]["id"], "llm_ranking")
            self.assertEqual(detail["ranked"][0]["title"], "Open Innovation")
            self.assertEqual(detail["ranked"][0]["keywords"], "open innovation; platforms")
            self.assertTrue(detail["params"]["has_llm_api_key"])
            self.assertEqual(detail["params"]["discipline_fields"], ["17", "14"])
            self.assertEqual(detail["params"]["search_budget"], "fast")
            self.assertFalse(detail["params"]["llm_thinking_enabled"])
            serialized = json.dumps(detail, ensure_ascii=False)
            self.assertNotIn("llm-secret", serialized)
            self.assertNotIn("oa-secret", serialized)
            self.assertNotIn("event-secret", serialized)
            self.assertNotIn("sk-secret-value", serialized)
            self.assertNotIn("ranking-secret", serialized)

            self.assertTrue(store.delete_run(run_id))
            self.assertEqual(store.list_runs(), [])

    def test_fail_run_can_persist_partial_harness_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(db_path=Path(tmp) / "paperseek.db", enabled=True)
            run_id = store.create_run("open innovation", {"data_source": "openalex"})

            store.fail_run(
                run_id,
                "upstream timeout",
                payload={
                    "question": "open innovation",
                    "source": "openalex",
                    "final_query": '"open innovation"',
                    "db": "OPENALEX",
                    "field": "",
                    "total": 1200,
                    "iterations": 3,
                    "history": [{"iteration": 3, "total": 1200, "action": "narrow"}],
                    "search_loop": {"backend_used": "langgraph"},
                    "search_state": {
                        "current_query": '"open innovation"',
                        "recovery_decisions": [{"action": "repair_query"}],
                    },
                    "citation_map": {"status": "partial"},
                    "ranking_steps": [{"id": "llm_ranking", "status": "processing"}],
                },
            )

            detail = store.get_run(run_id)

            self.assertIsNotNone(detail)
            self.assertEqual(detail["status"], "error")
            self.assertEqual(detail["error_message"], "upstream timeout")
            self.assertEqual(detail["total"], 1200)
            self.assertEqual(detail["iterations"], 3)
            self.assertEqual(detail["history"][0]["action"], "narrow")
            self.assertEqual(detail["search_loop"]["backend_used"], "langgraph")
            self.assertEqual(detail["search_state"]["recovery_decisions"][0]["action"], "repair_query")
            self.assertEqual(detail["citation_map"]["status"], "partial")
            self.assertEqual(detail["ranking_steps"][0]["status"], "processing")

    def test_store_defaults_to_shanghai_timezone_for_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(db_path=Path(tmp) / "paperseek.db", enabled=True)
            run_id = store.create_run("open innovation", {"data_source": "openalex"})

            detail = store.get_run(run_id)

            self.assertIsNotNone(detail)
            self.assertIn("+08:00", detail["created_at"])

    def test_store_uses_client_timezone_offset_when_zone_name_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(
                db_path=Path(tmp) / "paperseek.db",
                enabled=True,
                timezone_name="Unsupported/Zone",
                utc_offset_minutes=-300,
            )
            run_id = store.create_run("open innovation", {"data_source": "openalex"})

            detail = store.get_run(run_id)

            self.assertIsNotNone(detail)
            self.assertIn("-05:00", detail["created_at"])

    def test_ensure_column_validates_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(db_path=Path(tmp) / "paperseek.db", enabled=True)
            with store._connection() as conn:
                # Valid input
                store._ensure_column(conn, "search_runs", "test_column", "TEXT")
                # Invalid table
                with self.assertRaises(ValueError):
                    store._ensure_column(conn, "search_runs; DROP TABLE search_runs;", "test_column", "TEXT")
                # Invalid column
                with self.assertRaises(ValueError):
                    store._ensure_column(conn, "search_runs", "test_column; DROP TABLE search_runs;", "TEXT")
                # Invalid definition
                with self.assertRaises(ValueError):
                    store._ensure_column(conn, "search_runs", "test_column2", "TEXT; DROP TABLE search_runs;")


class HistoryApiTest(unittest.TestCase):
    def test_history_endpoint_reads_configured_local_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            with temporary_env({
                "PAPERSEEK_HISTORY_DB": str(Path(tmp) / "paperseek.db"),
                "PAPERSEEK_HISTORY_ENABLED": "true",
            }):
                store = HistoryStore()
                run_id = store.create_run("responsible AI", {"data_source": "openalex"})
                store.fail_run(run_id, "Missing LLM key")

                client = TestClient(app)
                response = client.get("/api/history")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["history"][0]["id"], run_id)
                self.assertEqual(payload["history"][0]["status"], "error")

                detail = client.get(f"/api/history/{run_id}").json()
                self.assertEqual(detail["error_message"], "Missing LLM key")

    def test_clear_history_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with temporary_env({
                "PAPERSEEK_HISTORY_DB": str(Path(tmp) / "paperseek.db"),
                "PAPERSEEK_HISTORY_ENABLED": "true",
            }):
                store = HistoryStore()
                run_id = store.create_run("platform governance", {"data_source": "openalex"})
                self.assertTrue(run_id)

                client = TestClient(app)
                response = client.delete("/api/history")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(len(store.list_runs()), 1)

                confirmed = client.delete("/api/history?confirm=true")
                self.assertEqual(confirmed.status_code, 200)
                self.assertEqual(confirmed.json()["deleted"], 1)
                self.assertEqual(store.list_runs(), [])


if __name__ == "__main__":
    unittest.main()
