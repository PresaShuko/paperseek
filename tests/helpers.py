
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]

CONFIG_ENV_KEYS = (
    "DATA_SOURCE",
    "WOS_API_KEY",
    "OPENALEX_API_KEY",
    "OPENALEX_EMAIL",
    "CROSSREF_EMAIL",
    "SEMANTIC_SCHOLAR_API_KEY",
    "PUBMED_API_KEY",
    "PUBMED_EMAIL",
    "PUBMED_TOOL",
    "SERPER_API_KEY",
    "SERPER_API_KEYS",
    "LLM_API_KEY",
    "LLM_PROVIDER",
    "LLM_API_TYPE",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "SEARCH_BUDGET",
    "MAX_ITERATIONS",
    "CITATION_SEED_COUNT",
    "CITATION_PER_SEED",
    "CITATION_MAX_RECORDS",
    "CITATION_DEPTH",
    "RETRIEVAL_POOL_MAX",
    "RETRIEVAL_POOL_MIN",
    "RETRIEVAL_LANE_LIMIT",
    "QUERY_PORTFOLIO_MAX",
    "QUERY_PORTFOLIO_LIMIT",
    "RANKING_CANDIDATE_LIMIT",
    "SEARCH_LOOP_BACKEND",
    "PAPERSEEK_PYDANTICAI_QUERY_RETRY",
    "DISCIPLINE_FIELDS",
)


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def read_json(relative_path: str):
    return json.loads(read_text(relative_path))


def assert_contains_all(testcase, text: str, expected: tuple[str, ...] | list[str]) -> None:
    for item in expected:
        with testcase.subTest(item=item):
            testcase.assertIn(item, text)


def fake_harness_search_result(question: str = "graph neural networks", source: str = "openalex") -> dict:
    return {
        "question": question,
        "search_intent": "Find core literature about graph neural networks.",
        "source": source,
        "final_query": "graph neural networks",
        "db": source.upper(),
        "field": "",
        "total": 1,
        "iterations": 1,
        "history": [{"iteration": 1, "total": 1, "action": "accept"}],
        "query_iteration_memory": [
            {"iteration": 1, "query": "graph neural networks", "total": 1, "hit_count": 1}
        ],
        "search_loop": {"backend_requested": "auto", "backend_used": "native"},
        "search_state": {
            "question": question,
            "source": source,
            "candidate_queue": {
                "keys": ["uid:w1"],
                "ledger": {
                    "uid:w1": {
                        "candidate_id": "uid:w1",
                        "title": "Graph Neural Network Robustness",
                        "lifecycle": [
                            {"stage": "ranking_gate", "action": "selected_for_llm", "origin": "local_fused_rank"},
                            {"stage": "results", "action": "final_output", "origin": "ranked_output"},
                        ],
                    }
                },
                "ledger_summary": {
                    "total_candidates": 1,
                    "serialized_candidates": 1,
                    "omitted_candidates": 0,
                    "lifecycle_candidate_counts": {"selected_for_llm": 1, "final_output": 1},
                    "citation_candidate_count": 0,
                },
                "origin_counts": {"retrieval": 1},
                "duplicate_count": 0,
                "events": [],
            },
            "ranking_recovery_decisions": [{"action": "retry_same_tier"}],
            "citation_recovery_decisions": [{"action": "skip_citation_expansion"}],
        },
        "citation_map": {},
        "ranking_steps": [{"id": "llm_ranking", "status": "complete"}],
        "ranked": [],
    }


@contextmanager
def temporary_env(values: dict[str, str] | None = None, *, clear: tuple[str, ...] | list[str] = ()):
    keys = set(clear)
    if values:
        keys.update(values)
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in clear:
            os.environ.pop(key, None)
        if values:
            os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value


def run_cli(*args: str, env: dict[str, str] | None = None, cwd=None) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    merged_env["PYTHONIOENCODING"] = "utf-8"
    python_path = [str(ROOT)]
    if merged_env.get("PYTHONPATH"):
        python_path.append(merged_env["PYTHONPATH"])
    merged_env["PYTHONPATH"] = os.pathsep.join(python_path)
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "paperseek.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=merged_env,
        cwd=cwd,
    )
