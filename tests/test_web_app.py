import json
import socket
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

from fastapi.testclient import TestClient
import requests
import uvicorn

from paperseek.search_agent import SearchCancelled
from paperseek.history import HistoryStore
from paperseek.llm_client import LLMError
from paperseek.web_app import app
from paperseek.web_app import SearchRequest, _RUN_EXECUTOR, _config_from_payload
from tests.helpers import CONFIG_ENV_KEYS, fake_harness_search_result, temporary_env


SOURCE_IDS = ["openalex", "arxiv", "semanticscholar", "pubmed", "googlescholar", "paperhub", "crossref", "wos"]


class WebAppTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_sources_endpoint_returns_ordered_source_capabilities(self):
        response = self.client.get("/api/sources")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["sources"]], SOURCE_IDS)
        self.assertTrue(payload["sources"][0]["default"])
        self.assertEqual(payload["sources"][-1]["status"], "temporarily_unavailable")
        self.assertIn("discipline_fields", payload["sources"][0]["supported_parameters"])

    def test_disciplines_endpoint_returns_openalex_fields(self):
        response = self.client.get("/api/disciplines")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["disciplines"]), 26)
        self.assertEqual(payload["disciplines"][6]["id"], "17")
        self.assertEqual(payload["disciplines"][6]["label"], "Computer Science")
        self.assertEqual(payload["sources"]["openalex"]["mode"], "native")
        self.assertEqual(payload["sources"]["wos"]["label"], "Web of Science Category")
        self.assertEqual(payload["sources"]["googlescholar"]["mode"], "text")
        self.assertEqual(payload["sources"]["paperhub"]["mode"], "text")
        self.assertEqual(payload["sources"]["paperhub"]["options"], [])

    def test_diagnostics_accepts_ollama_without_api_key(self):
        response = self.client.post(
            "/api/diagnostics",
            json={
                "data_source": "openalex",
                "llm_provider": "ollama",
                "llm_api_type": "openai_chat",
                "llm_model": "qwen3:8b",
                "llm_base_url": "http://127.0.0.1:11434/v1",
                "target_min": 5,
                "target_max": 50,
                "max_iterations": 5,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["status"], ("pass", "warning"))
        self.assertNotEqual(payload["status"], "fail")

    def test_search_validation_reports_missing_question(self):
        response = self.client.post(
            "/api/search",
            json={
                "question": "",
                "data_source": "openalex",
                "llm_provider": "ollama",
                "llm_api_type": "openai_chat",
                "target_min": 5,
                "target_max": 50,
                "max_iterations": 5,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Research Question is required", response.json()["detail"])

    def test_search_rejects_invalid_target_range_before_llm_setup(self):
        response = self.client.post(
            "/api/search",
            json={
                "question": "open innovation",
                "data_source": "openalex",
                "llm_provider": "ollama",
                "llm_api_type": "openai_chat",
                "target_min": 20,
                "target_max": 5,
                "max_iterations": 5,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Target minimum cannot exceed", response.json()["detail"])

    def test_search_accepts_new_source_payload(self):
        class FakeAgent:
            def __init__(self, config, llm):
                self.config = config
                self.llm = llm

            def search(self, question, verbose=False, event_handler=None):
                return fake_harness_search_result(question, self.config.data_source)

        with patch("paperseek.web_app.create_llm_client", return_value=object()), patch(
            "paperseek.web_app.PaperSeekAgent", FakeAgent
        ):
            response = self.client.post(
                "/api/search",
                json={
                    "question": "graph neural networks",
                    "data_source": "arxiv",
                    "llm_provider": "ollama",
                    "llm_api_type": "openai_chat",
                    "llm_model": "qwen3:8b",
                    "llm_base_url": "http://127.0.0.1:11434/v1",
                    "target_min": 0,
                    "target_max": 5,
                    "max_iterations": 1,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "arxiv")
        self.assertEqual(payload["search_state"]["candidate_queue"]["origin_counts"]["retrieval"], 1)
        self.assertEqual(payload["ranking_steps"][0]["id"], "llm_ranking")

    def test_stream_search_result_preserves_harness_payload(self):
        cancel_checks = []

        class FakeAgent:
            def __init__(self, config, llm):
                self.config = config
                self.llm = llm

            def search(self, question, verbose=False, event_handler=None, cancel_check=None):
                cancel_checks.append(cancel_check)
                if event_handler:
                    event_handler({"type": "log", "message": "fake progress"})
                return fake_harness_search_result(question, self.config.data_source)

        with temporary_env({"PAPERSEEK_HISTORY_ENABLED": "false"}, clear=("PAPERSEEK_HISTORY_ENABLED",)):
            with patch("paperseek.web_app.create_llm_client", return_value=object()), patch(
                "paperseek.web_app.PaperSeekAgent", FakeAgent
            ):
                response = self.client.post(
                    "/api/search/stream",
                    json={
                        "question": "graph neural networks",
                        "data_source": "arxiv",
                        "llm_provider": "ollama",
                        "llm_api_type": "openai_chat",
                        "llm_model": "qwen3:8b",
                        "llm_base_url": "http://127.0.0.1:11434/v1",
                        "target_min": 0,
                        "target_max": 5,
                        "max_iterations": 1,
                    },
                )

        self.assertEqual(response.status_code, 200)
        events = [
            json.loads(line)
            for line in response.text.splitlines()
            if line.strip() and line.strip().startswith("{")
        ]
        result_events = [event for event in events if event.get("type") == "result"]
        self.assertEqual(len(result_events), 1)
        payload = result_events[0]["data"]
        self.assertEqual(payload["search_state"]["candidate_queue"]["keys"], ["uid:w1"])
        self.assertEqual(payload["ranking_steps"][0]["status"], "complete")
        self.assertTrue(callable(cancel_checks[0]))

    def test_stream_failure_saves_partial_harness_payload(self):
        class FailingAgent:
            def __init__(self, config, llm):
                self.config = config
                self.llm = llm

            def search(self, question, verbose=False, event_handler=None, cancel_check=None):
                if event_handler:
                    event_handler({"type": "log", "message": "fake failure after state update"})
                raise LLMError("ranking timeout")

            def partial_result_payload(self, question=""):
                payload = fake_harness_search_result(question, self.config.data_source)
                payload["total"] = 1200
                payload["iterations"] = 3
                payload["history"] = [{"iteration": 3, "total": 1200, "action": "narrow"}]
                payload["ranking_steps"] = [{"id": "llm_ranking", "status": "processing"}]
                payload["ranked"] = []
                return payload

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "paperseek.db")
            with temporary_env(
                {"PAPERSEEK_HISTORY_ENABLED": "true", "PAPERSEEK_HISTORY_DB": db_path},
                clear=("PAPERSEEK_HISTORY_ENABLED", "PAPERSEEK_HISTORY_DB"),
            ):
                with patch("paperseek.web_app.create_llm_client", return_value=object()), patch(
                    "paperseek.web_app.PaperSeekAgent", FailingAgent
                ):
                    response = self.client.post(
                        "/api/search/stream",
                        json={
                            "question": "graph neural networks",
                            "data_source": "arxiv",
                            "llm_provider": "ollama",
                            "llm_api_type": "openai_chat",
                            "llm_model": "qwen3:8b",
                            "llm_base_url": "http://127.0.0.1:11434/v1",
                            "target_min": 0,
                            "target_max": 5,
                            "max_iterations": 1,
                        },
                    )

                events = [
                    json.loads(line)
                    for line in response.text.splitlines()
                    if line.strip() and line.strip().startswith("{")
                ]
                run_id = next(event["run_id"] for event in events if event.get("type") == "run")
                detail = HistoryStore(db_path=db_path, enabled=True).get_run(run_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["status"], "error")
        self.assertEqual(detail["error_message"], "ranking timeout")
        self.assertEqual(detail["history"][0]["action"], "narrow")
        self.assertEqual(detail["search_state"]["candidate_queue"]["keys"], ["uid:w1"])
        self.assertEqual(detail["ranking_steps"][0]["status"], "processing")

    def test_cancel_endpoint_sets_active_run_event(self):
        run = _RUN_EXECUTOR.create()
        run.bind("run_cancel_test")
        try:
            response = self.client.post("/api/search/run_cancel_test/cancel")
        finally:
            run.close()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(run.is_cancelled())

    def test_cancel_endpoint_rejects_inactive_run(self):
        response = self.client.post("/api/search/run_not_active/cancel")
        self.assertEqual(response.status_code, 404)

    def test_stream_cancel_endpoint_interrupts_active_search(self):
        cancel_seen = Event()

        class BlockingAgent:
            def __init__(self, config, llm):
                self.config = config
                self.llm = llm

            def search(self, question, verbose=False, event_handler=None, cancel_check=None):
                if event_handler:
                    event_handler({"type": "log", "message": "blocking fake search started"})
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if cancel_check and cancel_check():
                        cancel_seen.set()
                        raise SearchCancelled("Search cancelled by user.")
                    time.sleep(0.01)
                raise AssertionError("stream search was not cancelled")

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = Thread(target=server.run, daemon=True)
        with tempfile.TemporaryDirectory() as tmp:
            with temporary_env(
                {
                    "PAPERSEEK_HISTORY_ENABLED": "true",
                    "PAPERSEEK_HISTORY_DB": str(Path(tmp) / "paperseek.db"),
                },
                clear=("PAPERSEEK_HISTORY_ENABLED", "PAPERSEEK_HISTORY_DB"),
            ):
                with patch("paperseek.web_app.create_llm_client", return_value=object()), patch(
                    "paperseek.web_app.PaperSeekAgent", BlockingAgent
                ):
                    thread.start()
                    deadline = time.monotonic() + 5
                    while not server.started and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(server.started)
                    events = []
                    run_id = ""
                    try:
                        with requests.post(
                            f"http://127.0.0.1:{port}/api/search/stream",
                            json={
                                "question": "graph neural networks",
                                "data_source": "arxiv",
                                "llm_provider": "ollama",
                                "llm_api_type": "openai_chat",
                                "llm_model": "qwen3:8b",
                                "llm_base_url": "http://127.0.0.1:11434/v1",
                                "target_min": 0,
                                "target_max": 5,
                                "max_iterations": 1,
                            },
                            stream=True,
                            timeout=(3, 10),
                        ) as response:
                            self.assertEqual(response.status_code, 200)
                            for raw_line in response.iter_lines(chunk_size=1, decode_unicode=True):
                                if not raw_line:
                                    continue
                                event = json.loads(raw_line)
                                events.append(event)
                                if event.get("type") == "run":
                                    run_id = event["run_id"]
                                    cancel_response = requests.post(
                                        f"http://127.0.0.1:{port}/api/search/{run_id}/cancel",
                                        timeout=3,
                                    )
                                    self.assertEqual(cancel_response.status_code, 200)
                                if event.get("type") == "cancelled":
                                    break
                    finally:
                        server.should_exit = True
                        thread.join(timeout=5)

        self.assertTrue(cancel_seen.is_set())
        self.assertTrue(run_id)
        self.assertEqual(events[-1]["type"], "cancelled")
        self.assertIn("cancelled", events[-1]["message"].lower())

    def test_config_from_payload_preserves_environment_credentials_when_form_keys_are_blank(self):
        with temporary_env({
            "DATA_SOURCE": "openalex",
            "OPENALEX_API_KEY": "oa-env-test",
            "LLM_PROVIDER": "deepseek",
            "LLM_API_TYPE": "openai_chat",
            "LLM_MODEL": "deepseek-test",
            "LLM_BASE_URL": "https://api.deepseek.com",
            "LLM_API_KEY": "sk-env-test",
        }, clear=CONFIG_ENV_KEYS):
            payload = SearchRequest(
                question="open innovation",
                data_source="openalex",
                openalex_api_key="",
                llm_api_key="",
                llm_provider="",
                llm_api_type="",
                llm_model=None,
                llm_base_url=None,
                discipline_fields=["Computer Science", "14"],
            )
            config = _config_from_payload(payload)
            self.assertEqual(config.openalex_api_key, "oa-env-test")
            self.assertEqual(config.llm_api_key, "sk-env-test")
            self.assertEqual(config.llm_provider, "deepseek")
            self.assertEqual(config.llm_model, "deepseek-test")
            self.assertEqual(config.discipline_fields, ("17", "14"))

    def test_default_search_budget_is_fast(self):
        payload = SearchRequest(question="open innovation")
        config = _config_from_payload(payload)

        self.assertEqual(payload.search_budget, "fast")
        self.assertEqual(config.search_budget, "fast")
        self.assertEqual(payload.retrieval_lane_limit, 500)
        self.assertEqual(config.retrieval_lane_limit, 500)
        self.assertEqual(config.retrieval_pool_max, 3000)
        self.assertEqual(config.ranking_candidate_limit, 256)
        self.assertEqual(config.citation_seed_count, 3)
        self.assertEqual(config.citation_max_records, 40)
        self.assertTrue(config.llm_thinking_enabled)

    def test_fast_search_budget_uses_minimum_request_limits(self):
        config = _config_from_payload(SearchRequest(question="open innovation", search_budget="fast"))

        self.assertEqual(config.max_iterations, 5)
        self.assertEqual(config.query_portfolio_max, 3)
        self.assertEqual(config.retrieval_lane_limit, 500)
        self.assertEqual(config.retrieval_pool_max, 3000)
        self.assertEqual(config.ranking_candidate_limit, 256)
        self.assertEqual(config.citation_seed_count, 3)
        self.assertEqual(config.citation_max_records, 40)
        self.assertTrue(config.llm_thinking_enabled)

    def test_matching_web_budget_preserves_granular_environment_overrides(self):
        with temporary_env(
            {
                "SEARCH_BUDGET": "high",
                "RANKING_CANDIDATE_LIMIT": "333",
                "RETRIEVAL_POOL_MAX": "6000",
            },
            clear=CONFIG_ENV_KEYS,
        ):
            config = _config_from_payload(
                SearchRequest(question="open innovation", search_budget="high")
            )

        self.assertEqual(config.search_budget, "high")
        self.assertEqual(config.ranking_candidate_limit, 333)
        self.assertEqual(config.retrieval_pool_max, 6000)

    def test_config_from_payload_applies_query_portfolio_budget(self):
        payload = SearchRequest(
            question="image retrieval",
            data_source="openalex",
            query_portfolio_enabled=False,
            query_portfolio_max=1,
            query_portfolio_limit=40,
        )
        config = _config_from_payload(payload)
        self.assertFalse(config.query_portfolio_enabled)
        self.assertEqual(config.query_portfolio_max, 1)
        self.assertEqual(config.query_portfolio_limit, 40)

    def test_config_from_payload_uses_text_hint_for_sources_without_native_filter(self):
        payload = SearchRequest(
            question="graph neural networks",
            data_source="paperhub",
            llm_provider="ollama",
            llm_api_type="openai_chat",
            discipline_fields=["Computer Science", "17"],
            search_field="human-computer interaction",
        )
        config = _config_from_payload(payload)
        self.assertEqual(config.data_source, "paperhub")
        self.assertEqual(config.discipline_fields, ())
        self.assertEqual(config.search_field, "human-computer interaction")

    def test_config_defaults_reports_configured_secrets_without_exposing_values(self):
        with temporary_env({
            "DATA_SOURCE": "openalex",
            "OPENALEX_API_KEY": "oa-env-test",
            "LLM_PROVIDER": "deepseek",
            "LLM_API_TYPE": "openai_chat",
            "LLM_MODEL": "deepseek-test",
            "LLM_BASE_URL": "https://api.deepseek.com",
            "LLM_API_KEY": "sk-env-test",
        }, clear=CONFIG_ENV_KEYS):
            response = self.client.get("/api/config/defaults")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["llm_provider"], "deepseek")
            self.assertEqual(payload["search_budget"], "fast")
            self.assertTrue(payload["query_portfolio_enabled"])
            self.assertEqual(payload["query_portfolio_max"], 3)
            self.assertEqual(payload["query_portfolio_limit"], 100)
            self.assertTrue(payload["has_llm_api_key"])
            self.assertTrue(payload["has_openalex_api_key"])
            self.assertNotIn("sk-env-test", response.text)
            self.assertNotIn("oa-env-test", response.text)


if __name__ == "__main__":
    unittest.main()
