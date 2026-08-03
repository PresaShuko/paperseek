import os
import unittest
from pathlib import Path

from paperseek.config import AgentConfig
from paperseek.diagnostics import smoke_source
from paperseek.env_loader import load_env_file
from paperseek_core.planning import ConceptGroup, QueryView
from paperseek_core.query_compiler import compile_query_view


def _live_smoke_enabled() -> bool:
    return os.environ.get("PAPERSEEK_LIVE_SMOKE", "").strip().lower() in {"1", "true", "yes", "on"}


def _live_strict_enabled() -> bool:
    return os.environ.get("PAPERSEEK_LIVE_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}


def _is_external_rate_limited(result: dict) -> bool:
    status = str(result.get("status", "")).lower()
    text = f"{result.get('message', '')} {result.get('body', '')}".lower()
    return status == "429" or "rate limit" in text or "insufficient budget" in text or "quota" in text


def _load_local_env_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    load_env_file(repo_root / ".env")
    load_env_file(repo_root.parent / ".env")


class LiveSourceSmokeTest(unittest.TestCase):
    def setUp(self):
        if not _live_smoke_enabled():
            self.skipTest("set PAPERSEEK_LIVE_SMOKE=true to run live source smoke tests")
        _load_local_env_files()

    def _config(self, source: str) -> AgentConfig:
        config = AgentConfig.from_env()
        config.data_source = source
        return config

    def _smoke_result(self, source: str, query: str = "graph neural networks") -> dict:
        result = smoke_source(self._config(source), query=query, limit=1)
        return result

    def _assert_smoke_result_passes(self, source: str, result: dict) -> None:
        self.assertTrue(result.get("ok"), f"{source} smoke failed: {result}")
        self.assertGreaterEqual(result.get("returned", 0), 0)
        self.assertIn("elapsed_ms", result)

    def test_openalex_arxiv_crossref_and_paperhub_live_smoke(self):
        checked = 0
        skipped = []
        for source in ("openalex", "arxiv", "crossref", "paperhub"):
            with self.subTest(source=source):
                result = self._smoke_result(source)
                if not result.get("ok") and _is_external_rate_limited(result) and not _live_strict_enabled():
                    skipped.append(source)
                    continue
                self._assert_smoke_result_passes(source, result)
                checked += 1
        if checked == 0:
            self.skipTest(f"all live source smokes were rate-limited or quota-limited: {', '.join(skipped)}")

    def test_optional_keyed_sources_live_smoke(self):
        keyed_sources = (
            ("googlescholar", "SERPER_API_KEY"),
            ("semanticscholar", "SEMANTIC_SCHOLAR_API_KEY"),
            ("pubmed", "PUBMED_API_KEY"),
            ("wos", "WOS_API_KEY"),
        )
        configured = [(source, env_key) for source, env_key in keyed_sources if os.environ.get(env_key, "").strip()]
        if not configured:
            self.skipTest("no keyed source API keys are configured")
        checked = 0
        skipped = []
        for source, env_key in configured:
            with self.subTest(source=source):
                result = self._smoke_result(source)
                if not result.get("ok") and _is_external_rate_limited(result) and not _live_strict_enabled():
                    skipped.append(source)
                    continue
                self._assert_smoke_result_passes(source, result)
                checked += 1
        if checked == 0:
            self.skipTest(f"all configured keyed source smokes were rate-limited or quota-limited: {', '.join(skipped)}")

    def test_compiled_query_view_returns_results_for_available_sources(self):
        view = QueryView(
            view_id="graph_neural_networks",
            purpose="Find graph neural network research",
            concept_groups=[
                ConceptGroup(
                    label="method",
                    terms=["graph neural networks", "graph convolutional networks"],
                )
            ],
        )
        sources = ["openalex", "arxiv", "crossref", "paperhub"]
        keyed = {
            "googlescholar": "SERPER_API_KEY",
            "semanticscholar": "SEMANTIC_SCHOLAR_API_KEY",
            "pubmed": "PUBMED_API_KEY",
        }
        sources.extend(source for source, key in keyed.items() if os.environ.get(key, "").strip())
        checked = 0
        skipped = []
        for source in sources:
            with self.subTest(source=source):
                query = compile_query_view(source, view).query
                result = self._smoke_result(source, query=query)
                if not result.get("ok") and _is_external_rate_limited(result) and not _live_strict_enabled():
                    skipped.append(source)
                    continue
                self._assert_smoke_result_passes(source, result)
                self.assertGreater(result.get("returned", 0), 0, f"{source} compiled query returned no records: {query}")
                checked += 1
        if checked == 0:
            self.skipTest(f"all compiled-query smokes were rate-limited or quota-limited: {', '.join(skipped)}")


if __name__ == "__main__":
    unittest.main()
