import socket
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

import uvicorn

from paperseek.search_agent import SearchCancelled
from paperseek.web_app import app
from tests.helpers import fake_harness_search_result, temporary_env

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
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


class BrowserResumeTest(unittest.TestCase):
    def test_stopped_run_can_resume_from_history_checkpoint(self):
        if sync_playwright is None:
            self.skipTest("playwright is not installed")
        chrome = _chrome_executable()
        if not chrome:
            self.skipTest("Chrome executable not found")

        cancel_seen = Event()
        resume_seen = Event()

        class ResumableAgent:
            def __init__(self, config, llm):
                self.config = config

            def search(
                self,
                question,
                verbose=False,
                event_handler=None,
                cancel_check=None,
                checkpoint_handler=None,
                resume_checkpoint=None,
            ):
                if resume_checkpoint:
                    resume_seen.set()
                    return fake_harness_search_result(question, self.config.data_source)
                checkpoint_handler(
                    {
                        "schema_version": 1,
                        "sequence": 1,
                        "stage": "query_execution",
                        "question": question,
                        "source": self.config.data_source,
                        "current_query": "durable search",
                        "total": 2,
                        "iteration": 1,
                        "history": [],
                        "records": [],
                        "metadata": {"phase": "query_complete"},
                    }
                )
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if cancel_check and cancel_check():
                        cancel_seen.set()
                        raise SearchCancelled("Search cancelled by user.")
                    time.sleep(0.02)
                raise AssertionError("browser Stop did not cancel the checkpoint fixture")

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
                    "paperseek.web_app.PaperSeekAgent", ResumableAgent
                ):
                    thread.start()
                    deadline = time.monotonic() + 10
                    while not server.started and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(server.started)
                    try:
                        with sync_playwright() as playwright:
                            browser = playwright.chromium.launch(executable_path=chrome, headless=True)
                            page = browser.new_page()
                            try:
                                page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                                page.fill("#question", "durable search")
                                page.select_option("#dataSource", "arxiv")
                                page.evaluate(
                                    """() => {
                                      document.getElementById('llmProvider').value = 'ollama';
                                      document.getElementById('llmApiType').value = 'openai_chat';
                                      document.getElementById('llmModel').value = 'qwen3:8b';
                                      document.getElementById('llmBaseUrl').value = 'http://127.0.0.1:11434/v1';
                                    }"""
                                )
                                page.click("#searchButton")
                                page.wait_for_function(
                                    "() => document.getElementById('logOutput').textContent.includes('Local history run:')",
                                    timeout=10000,
                                )
                                page.click("#stopButton")
                                deadline = time.monotonic() + 10
                                while not cancel_seen.is_set() and time.monotonic() < deadline:
                                    time.sleep(0.02)
                                self.assertTrue(cancel_seen.is_set())

                                page.click('[data-view="history"]')
                                page.wait_for_selector(".history-run-button", timeout=10000)
                                page.click(".history-run-button")
                                page.wait_for_selector('[data-history-action="resume"]', timeout=10000)
                                page.click('[data-history-action="resume"]')
                                page.wait_for_function(
                                    "() => document.getElementById('logOutput').textContent.includes('Run completed successfully.')",
                                    timeout=7000,
                                )
                                self.assertTrue(resume_seen.is_set())
                            finally:
                                browser.close()
                    finally:
                        server.should_exit = True
                        thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
