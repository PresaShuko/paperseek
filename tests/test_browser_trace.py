import socket
import tempfile
import time
import unittest
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import patch

import uvicorn

from paperseek.web_app import app
from tests.helpers import fake_harness_search_result, temporary_env

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - exercised when optional browser deps are absent.
    sync_playwright = None


CHROME_CANDIDATES = (
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
)


def _chrome_executable() -> str:
    for path in CHROME_CANDIDATES:
        if path.is_file():
            return str(path)
    return ""


class BrowserTraceTest(unittest.TestCase):
    def test_final_result_shows_loop_and_recovery_audits(self):
        if sync_playwright is None:
            self.skipTest("playwright is not installed")
        chrome = _chrome_executable()
        if not chrome:
            self.skipTest("Chrome executable not found")

        class TraceAgent:
            def __init__(self, config, llm):
                self.config = config
                self.llm = llm

            def search(self, question, verbose=False, event_handler=None, cancel_check=None):
                payload = fake_harness_search_result(question, self.config.data_source)
                payload["search_plan"] = {
                    "intent": "Find robust graph neural network literature.",
                    "question_type": "broad_landscape",
                    "core_concepts": ["graph neural networks", "robustness"],
                    "likely_synonyms": ["GNN", "graph model stability"],
                    "adjacent_concepts": ["adversarial robustness"],
                    "boundaries": ["exclude social networks"],
                    "ambiguities": ["robustness can refer to attacks or distribution shift"],
                    "adjustment_strategy": "Use title feedback to keep graph learning in scope.",
                    "query_views": [
                        {
                            "view_id": "direct_terminology",
                            "view_type": "direct_terminology",
                            "purpose": "Direct robustness terminology",
                        }
                    ],
                }
                payload["query_portfolio"] = [
                    {
                        "view_id": "direct_terminology",
                        "status": "completed",
                        "query": '"graph neural network robustness"',
                        "total": 11,
                        "hit_count": 6,
                        "added_unique": 4,
                    }
                ]
                payload["history"] = [
                    {
                        "iteration": 1,
                        "query": "graph neural networks",
                        "total": 25,
                        "action": "narrow",
                        "message": "Top titles were off-intent; generated a redirected query.",
                        "rationale": "Title feedback requested a narrower graph neural network query.",
                        "next_query": "graph neural networks robustness",
                    },
                    {
                        "iteration": 2,
                        "query": "graph neural networks robustness",
                        "total": 7,
                        "action": "accept",
                        "message": "Accepted 7 records within the target range.",
                    },
                    {
                        "iteration": 2,
                        "query": '"graph neural network robustness"',
                        "total": 11,
                        "action": "portfolio",
                        "status": "completed",
                        "view_id": "direct_terminology",
                        "message": "Query view returned 6 and added 4 unique candidates.",
                    },
                ]
                payload["search_state"]["observations"] = [
                    {"iteration": 1, "query": "graph neural networks", "total": 25, "hit_count": 3},
                    {"iteration": 2, "query": "graph neural networks robustness", "total": 7, "hit_count": 1},
                ]
                payload["search_state"]["decisions"] = [
                    {"action": "narrow", "message": "Title feedback requested a redirected query."},
                    {"action": "accept", "message": "Accepted the revised query."},
                ]
                payload["search_state"]["candidate_queue"]["origin_counts"] = {"retrieval": 1, "citation_expansion": 1}
                payload["search_state"]["candidate_queue"]["duplicate_count"] = 1
                payload["ranking_steps"] = [
                    {
                        "id": "llm_ranking",
                        "title": "LLM reranking",
                        "status": "complete",
                        "current": 1,
                        "total": 1,
                        "detail": "Completed batch 1/1 at concurrency=4.",
                        "concurrency": 4,
                        "candidate_count": 1,
                    }
                ]
                payload["citation_map"] = {
                    "enabled": True,
                    "supported": True,
                    "status": "complete",
                    "initial_candidates": 1,
                    "seed_count": 1,
                    "added_candidates": 1,
                    "candidate_pool": 2,
                    "nodes": [
                        {
                            "id": "https://example.test/gnn",
                            "title": "Graph Neural Network Robustness",
                            "year": 2025,
                            "source": "Fake Journal",
                            "citations": 3,
                            "score": 9,
                            "rank": 1,
                            "roles": ["seed", "result"],
                        },
                        {
                            "id": "https://example.test/reference",
                            "title": "Foundational Graph Robustness",
                            "year": 2022,
                            "source": "Reference Journal",
                            "citations": 20,
                            "roles": ["backward"],
                        },
                    ],
                    "edges": [
                        {
                            "source": "https://example.test/gnn",
                            "target": "https://example.test/reference",
                            "seed": "https://example.test/gnn",
                            "direction": "backward",
                        }
                    ],
                    "frontier": {
                        "planned_items": 1,
                        "processed_items": 1,
                        "request_count": 1,
                        "request_budget": 2,
                        "stop_reason": "completed",
                        "direction_stats": {
                            "backward": {"added": 1},
                            "forward": {"added": 0},
                        },
                    },
                }
                payload["ranked"] = [
                    {
                        "document": SimpleNamespace(
                            uid="arxiv:2501.00001",
                            title="Graph Neural Network Robustness",
                            abstract="A paper about graph neural network robustness.",
                            provider=self.config.data_source,
                            source=SimpleNamespace(
                                publish_year=2025,
                                source_title="Fake Journal",
                                types=["article"],
                                volume=None,
                                issue=None,
                                pages=None,
                            ),
                            identifiers=SimpleNamespace(doi="10.1000/gnn", openalex=""),
                            names=SimpleNamespace(
                                authors=[SimpleNamespace(display_name="A. Researcher", wos_standard="")]
                            ),
                            citations=[SimpleNamespace(count=3)],
                            keywords=SimpleNamespace(author_keywords=["graph neural networks", "robustness"]),
                            links={"record": "https://example.test/gnn", "pdf": "https://example.test/gnn.pdf"},
                        ),
                        "score": 9,
                        "reasoning": "Relevant to the requested topic.",
                        "abstract": "A paper about graph neural network robustness.",
                    }
                ]
                if event_handler:
                    event_handler({
                        "type": "stage",
                        "stage": "query",
                        "status": "complete",
                        "data": {
                            "intent": payload["search_intent"],
                            "search_plan": payload["search_plan"],
                            "source": self.config.data_source,
                            "query": payload["final_query"],
                        },
                    })
                    event_handler({
                        "type": "stage",
                        "stage": "search",
                        "status": "complete",
                        "data": {
                            "history": payload["history"],
                            "query_portfolio": payload["query_portfolio"],
                            "final_query": payload["final_query"],
                            "total": payload["total"],
                        },
                    })
                    event_handler({
                        "type": "stage",
                        "stage": "ranking",
                        "status": "processing",
                        "data": {"ranking_steps": payload["ranking_steps"]},
                    })
                return payload

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
                    "paperseek.web_app.PaperSeekAgent", TraceAgent
                ):
                    thread.start()
                    deadline = time.monotonic() + 10
                    while not server.started and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(server.started)

                    try:
                        with sync_playwright() as playwright:
                            browser = playwright.chromium.launch(executable_path=chrome, headless=True)
                            page = browser.new_page(viewport={"width": 1366, "height": 900})
                            try:
                                page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                                page.fill("#question", "graph neural networks")
                                page.select_option("#dataSource", "arxiv")
                                page.evaluate(
                                    """() => {
                                      localStorage.setItem('paperseek-language', 'en');
                                      document.getElementById('llmProvider').value = 'ollama';
                                      document.getElementById('llmApiType').value = 'openai_chat';
                                      document.getElementById('llmModel').value = 'qwen3:8b';
                                      document.getElementById('llmBaseUrl').value = 'http://127.0.0.1:11434/v1';
                                    }"""
                                )
                                page.click("#searchButton")
                                page.wait_for_selector('[data-switch-view="results"]', timeout=15000)
                                active_view_after_completion = page.locator("body").get_attribute("data-view")
                                stage_expansion_after_completion = {
                                    key: page.locator(f'[data-stage-toggle="{key}"]').get_attribute("aria-expanded")
                                    for key in ("query", "search", "ranking", "results")
                                }
                                log_expansion_after_completion = page.locator("#logToggle").get_attribute("aria-expanded")

                                page.click('[data-stage-toggle="query"]')
                                page.wait_for_selector(".intent-audit")
                                page.click('[data-section-toggle="intent-analysis"]')
                                query_text = page.locator("#workflow-stage-query").inner_text()

                                page.evaluate(
                                    """() => applyStageEvent({
                                      type: 'stage',
                                      stage: 'ranking',
                                      status: 'processing',
                                      data: {
                                        ranking_steps: [{
                                          id: 'llm_ranking',
                                          title: 'LLM reranking',
                                          status: 'processing',
                                          current: 17,
                                          total: 32,
                                          concurrency: 16,
                                          candidate_count: 256,
                                          detail: 'Scoring candidate batches.'
                                        }]
                                      }
                                    })"""
                                )
                                manual_query_expansion_after_event = page.locator('[data-stage-toggle="query"]').get_attribute("aria-expanded")
                                ranking_expansion_during_event = page.locator('[data-stage-toggle="ranking"]').get_attribute("aria-expanded")
                                live_step_label = page.locator("#stepLabel").inner_text()
                                page.evaluate(
                                    """() => {
                                      applyStageEvent({
                                        type: 'stage',
                                        stage: 'ranking',
                                        status: 'complete',
                                        data: {ranking_steps: [{id: 'llm_ranking', title: 'LLM reranking', status: 'complete', current: 32, total: 32, concurrency: 16, candidate_count: 256}]}
                                      });
                                      showFinalStage();
                                      renderWorkflow();
                                    }"""
                                )

                                page.click('[data-stage-toggle="search"]')
                                page.click('[data-section-toggle="query-portfolio"]')
                                page.click('[data-section-toggle="search-audit"]')
                                search_text = page.locator("#workflow-stage-search").inner_text()

                                page.click('[data-stage-toggle="ranking"]')
                                page.click('[data-section-toggle="ranking-audit"]')
                                ranking_text = page.locator("#workflow-stage-ranking").inner_text()

                                page.click('[data-view="citations"]')
                                page.wait_for_selector(".citation-node", timeout=10000)
                                citation_circle = page.locator(".citation-node").last.locator(".citation-hit-target")
                                citation_circle.click()
                                citation_text = page.locator(".citation-view").inner_text()

                                page.click('[data-language="zh"]')
                                page.wait_for_function("document.documentElement.lang === 'zh-CN'", timeout=3000)
                                chinese_citation_text = page.locator(".citation-view").inner_text()

                                page.click('[data-view="results"]')
                                page.wait_for_selector("#exportCsvButton", timeout=3000)
                                csv_path = Path(tmp) / "results.csv"
                                with page.expect_download(timeout=3000) as csv_download:
                                    page.click("#exportCsvButton")
                                csv_download.value.save_as(csv_path)
                                csv_text = csv_path.read_text(encoding="utf-8-sig")

                                page.click('[data-view="search"]')
                                log_path = Path(tmp) / "system-log.txt"
                                with page.expect_download(timeout=3000) as log_download:
                                    page.click("#exportLogButton")
                                log_download.value.save_as(log_path)
                                log_text = log_path.read_text(encoding="utf-8-sig")

                                page.click('[data-view="history"]')
                                page.wait_for_selector(".history-run-button", timeout=10000)
                                page.locator(".history-run-button").first.click()
                                page.wait_for_function(
                                    "document.querySelector('.history-detail-panel')?.innerText.includes('graph neural networks')",
                                    timeout=10000,
                                )
                                history_text = page.locator(".history-detail-panel").inner_text()

                                page.click('[data-view="search"]')
                                page.evaluate("() => showRunError('Synthetic upstream failure')")
                                error_stage_expansion = page.locator('[data-stage-toggle="results"]').get_attribute("aria-expanded")
                                error_log_expansion = page.locator("#logToggle").get_attribute("aria-expanded")
                                error_badge_visible = page.locator("#logErrorBadge").is_visible()
                            finally:
                                browser.close()
                    finally:
                        server.should_exit = True
                        thread.join(timeout=5)

        self.assertEqual(active_view_after_completion, "search")
        self.assertEqual(
            stage_expansion_after_completion,
            {"query": "false", "search": "false", "ranking": "false", "results": "true"},
        )
        self.assertEqual(log_expansion_after_completion, "false")
        self.assertIn("graph neural networks", query_text)
        self.assertIn("GNN", query_text)
        self.assertEqual(manual_query_expansion_after_event, "true")
        self.assertEqual(ranking_expansion_during_event, "true")
        self.assertIn("3/4", live_step_label)
        self.assertIn("17/32", live_step_label)
        self.assertIn("Technical audit", search_text)
        self.assertIn("LOOP BACKEND", search_text)
        self.assertIn("Loop decisions", search_text)
        self.assertIn("Candidate queue", search_text)
        self.assertIn("Query portfolio", search_text)
        self.assertIn("6 returned", search_text)
        self.assertIn("4 unique added", search_text)
        self.assertIn("Recovery and candidate audit", ranking_text)
        self.assertIn("LEDGER CANDIDATES", ranking_text)
        self.assertIn("SELECTED FOR LLM", ranking_text)
        self.assertIn("FINAL OUTPUT", ranking_text)
        self.assertIn("Ledger details retained: 1/1", ranking_text)
        self.assertIn("Foundational Graph Robustness", citation_text)
        self.assertIn("2 NODES", citation_text)
        self.assertIn("1 EDGES", citation_text)
        self.assertIn("FRONTIER ITEMS", citation_text)
        self.assertIn("引用扩展", chinese_citation_text)
        self.assertIn("前沿任务", chinese_citation_text)
        self.assertIn("title,authors,publish_year", csv_text)
        self.assertIn("Graph Neural Network Robustness", csv_text)
        self.assertIn("Run completed successfully", log_text)
        self.assertIn("graph neural networks", history_text)
        self.assertIn("Graph Neural Network Robustness", history_text)
        self.assertEqual(error_stage_expansion, "true")
        self.assertEqual(error_log_expansion, "true")
        self.assertTrue(error_badge_visible)


if __name__ == "__main__":
    unittest.main()
