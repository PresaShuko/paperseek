import os
import unittest
from pathlib import Path

from paperseek.config import AgentConfig
from paperseek.env_loader import load_env_file
from paperseek.llm_client import create_llm_client
from paperseek.search_agent import PaperSeekAgent


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _load_local_env_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    load_env_file(repo_root / ".env")
    load_env_file(repo_root.parent / ".env")


def _external_failure_text(exc: Exception) -> str:
    return str(exc or "").lower()


def _is_external_service_failure(exc: Exception) -> bool:
    text = _external_failure_text(exc)
    return any(
        marker in text
        for marker in (
            "401",
            "403",
            "408",
            "429",
            "500",
            "502",
            "503",
            "504",
            "quota",
            "rate limit",
            "rate_limit",
            "network error",
            "timed out",
            "timeout",
            "temporarily",
        )
    )


def _source_list() -> list[str]:
    raw = os.environ.get("PAPERSEEK_LIVE_FULL_SOURCES", "openalex,paperhub")
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return values or ["openalex"]


def _question_for_source(source: str) -> str:
    questions = {
        "paperhub": "GUI agents adversarial attacks",
        "arxiv": "graph neural network robustness",
        "crossref": "AI governance accountability",
        "openalex": "AI governance accountability",
    }
    return questions.get(source, "AI governance accountability")


def _apply_live_llm(config: AgentConfig) -> bool:
    explicit_key = os.environ.get("LLM_API_KEY", "").strip()
    if explicit_key:
        return True

    nvidia_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if nvidia_key:
        config.llm_provider = "nvidia"
        config.llm_api_type = "openai_chat"
        config.llm_model = "z-ai/glm-5.2"
        config.llm_base_url = "https://integrate.api.nvidia.com/v1"
        config.llm_api_key = nvidia_key
        return True

    cstcloud_key = os.environ.get("CSTCLOUD_API_KEY", "").strip()
    if cstcloud_key:
        config.llm_provider = "cstcloud"
        config.llm_api_type = "openai_chat"
        config.llm_model = "deepseek-v4-flash"
        config.llm_base_url = "https://uni-api.cstcloud.cn/v1"
        config.llm_api_key = cstcloud_key
        return True

    kimi_key = os.environ.get("KIMI_CODE_API_KEY", "").strip()
    if kimi_key:
        config.llm_provider = "moonshot"
        config.llm_api_type = "openai_chat"
        config.llm_model = "kimi-for-coding"
        config.llm_base_url = "https://api.kimi.com/coding/v1"
        config.llm_api_key = kimi_key
        return True

    return False


class LiveFullSearchTest(unittest.TestCase):
    def setUp(self):
        if not _truthy_env("PAPERSEEK_LIVE_FULL_SEARCH"):
            self.skipTest("set PAPERSEEK_LIVE_FULL_SEARCH=true to run live end-to-end search tests")
        _load_local_env_files()

    def _config(self, source: str) -> AgentConfig:
        config = AgentConfig.from_env()
        if not _apply_live_llm(config):
            self.skipTest("no supported live LLM key found")
        config.data_source = source
        config.search_loop_backend = os.environ.get("PAPERSEEK_LIVE_FULL_BACKEND", "auto").strip().lower() or "auto"
        config.target_min = 1
        config.target_max = 10
        config.max_iterations = int(os.environ.get("PAPERSEEK_LIVE_FULL_MAX_ITERATIONS", "1"))
        config.adaptive_max_iterations = config.max_iterations
        config.retrieval_pool_min = 1
        config.retrieval_pool_max = 80
        config.retrieval_lane_limit = 30
        config.ranking_candidate_limit = 8
        config.ranking_batch_size = 8
        config.ranking_concurrency = 4
        config.expand_citations = False
        config.fetch_abstracts = False
        config.retrieval_embedding_provider = "local"
        config.retrieval_reranker_provider = ""
        config.retrieval_crossref_enrichment = False
        config.llm_max_tokens = 1600
        config.llm_timeout_seconds = 45
        config.ranking_llm_timeout_seconds = 30
        return config

    def test_configured_sources_full_search(self):
        checked = 0
        skipped = []
        for source in _source_list():
            with self.subTest(source=source):
                config = self._config(source)
                try:
                    config.validate()
                    agent = PaperSeekAgent(config, create_llm_client(config))
                    result = agent.search(_question_for_source(source))
                except Exception as exc:
                    if _is_external_service_failure(exc) and not _truthy_env("PAPERSEEK_LIVE_STRICT"):
                        skipped.append(f"{source}: {exc}")
                        continue
                    raise

                self.assertEqual(result["source"], source)
                self.assertTrue(result.get("final_query"), result)
                self.assertGreaterEqual(len(result.get("history") or []), 1)
                self.assertIn("search_loop", result)
                self.assertIn(result["search_loop"].get("backend_used"), {"native", "langgraph"})
                self.assertIn("search_state", result)
                self.assertGreaterEqual(len(result["search_state"].get("observations") or []), 1)
                self.assertIn("ranked", result)
                checked += 1

        if checked == 0:
            self.skipTest(f"all live full-search checks were skipped by external service failures: {'; '.join(skipped)}")


if __name__ == "__main__":
    unittest.main()
