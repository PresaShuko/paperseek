import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from tests.helpers import CONFIG_ENV_KEYS, fake_harness_search_result, temporary_env


class CliTest(unittest.TestCase):
    def test_benchmark_trace_streams_events_without_polluting_json_output(self):
        from paperseek import cli

        class FakeAgent:
            def __init__(self, config, llm):
                self.config = config

            def search(self, question, verbose=False, event_handler=None):
                event_handler({"type": "stage", "stage": "query", "status": "processing"})
                return fake_harness_search_result(question, self.config.data_source)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with temporary_env(
            {
                "PAPERSEEK_HISTORY_ENABLED": "false",
                "PAPERSEEK_BENCHMARK_TRACE": "true",
            },
            clear=CONFIG_ENV_KEYS + ("PAPERSEEK_HISTORY_ENABLED", "PAPERSEEK_BENCHMARK_TRACE"),
        ):
            with patch("paperseek.cli.load_env_file"), patch("paperseek.cli.load_user_config_into_env", return_value=[]):
                with patch("paperseek.cli.create_llm_client", return_value=object()), patch(
                    "paperseek.cli.PaperSeekAgent", FakeAgent
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        cli.main(
                            [
                                "search",
                                "graph neural networks",
                                "--source",
                                "arxiv",
                                "--llm-provider",
                                "ollama",
                                "--llm-api-type",
                                "openai_chat",
                                "--llm-model",
                                "qwen3:8b",
                                "--llm-base-url",
                                "http://127.0.0.1:11434/v1",
                                "--min",
                                "0",
                                "--max",
                                "5",
                                "--iterations",
                                "1",
                                "--output",
                                "json",
                            ]
                        )

        json.loads(stdout.getvalue())
        self.assertIn('PAPERSEEK_BENCHMARK_EVENT {"type":"stage"', stderr.getvalue())
        self.assertIn('"benchmark_elapsed_ms":', stderr.getvalue())

    def test_query_portfolio_help_matches_default_request_budget(self):
        from paperseek import cli

        help_text = cli._search_parser("paperseek search").format_help()

        self.assertIn("Maximum actual source requests from SearchPlan views", help_text)
        self.assertIn("fast default: 2", help_text)

    def test_search_budget_cli_preset_is_applied_before_granular_overrides(self):
        from paperseek import cli
        from paperseek.config import AgentConfig

        parser = cli._search_parser("paperseek search")
        args = parser.parse_args(
            [
                "image retrieval",
                "--search-budget",
                "high",
                "--ranking-candidate-limit",
                "600",
            ]
        )
        config = cli._apply_search_args(AgentConfig(), args)

        self.assertEqual(config.search_budget, "high")
        self.assertEqual(config.retrieval_pool_max, 7000)
        self.assertEqual(config.ranking_candidate_limit, 600)

    def test_query_portfolio_cli_settings_are_applied(self):
        from paperseek import cli
        from paperseek.config import AgentConfig

        parser = cli._search_parser("paperseek search")
        args = parser.parse_args(
            [
                "image retrieval",
                "--no-query-portfolio",
                "--query-portfolio-max",
                "3",
                "--query-portfolio-limit",
                "40",
            ]
        )
        config = cli._apply_search_args(AgentConfig(), args)

        self.assertFalse(config.query_portfolio_enabled)
        self.assertEqual(config.query_portfolio_max, 3)
        self.assertEqual(config.query_portfolio_limit, 40)

    def test_search_json_preserves_harness_payload(self):
        from paperseek import cli

        class FakeAgent:
            def __init__(self, config, llm):
                self.config = config
                self.llm = llm

            def search(self, question, verbose=False):
                return fake_harness_search_result(question, self.config.data_source)

        stdout = io.StringIO()
        with temporary_env(
            {"PAPERSEEK_HISTORY_ENABLED": "false"},
            clear=CONFIG_ENV_KEYS + ("PAPERSEEK_HISTORY_ENABLED",),
        ):
            with patch("paperseek.cli.load_env_file"), patch("paperseek.cli.load_user_config_into_env", return_value=[]):
                with patch("paperseek.cli.create_llm_client", return_value=object()), patch(
                    "paperseek.cli.PaperSeekAgent", FakeAgent
                ):
                    with redirect_stdout(stdout):
                        cli.main(
                            [
                                "search",
                                "graph neural networks",
                                "--source",
                                "arxiv",
                                "--llm-provider",
                                "ollama",
                                "--llm-api-type",
                                "openai_chat",
                                "--llm-model",
                                "qwen3:8b",
                                "--llm-base-url",
                                "http://127.0.0.1:11434/v1",
                                "--min",
                                "0",
                                "--max",
                                "5",
                                "--iterations",
                                "1",
                                "--output",
                                "json",
                            ]
                        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["source"], "arxiv")
        self.assertIn("search_plan", payload)
        self.assertIn("query_portfolio", payload)
        self.assertEqual(payload["query_iteration_memory"][0]["hit_count"], 1)
        self.assertEqual(payload["search_loop"]["backend_used"], "native")
        self.assertEqual(payload["search_state"]["candidate_queue"]["keys"], ["uid:w1"])
        self.assertEqual(payload["ranking_steps"][0]["id"], "llm_ranking")
        self.assertEqual(payload["final_query"], "graph neural networks")


if __name__ == "__main__":
    unittest.main()
