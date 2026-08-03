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
from tests.helpers import temporary_env

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


class BrowserStopTest(unittest.TestCase):
    def test_stop_button_sends_backend_cancel_request(self):
        if sync_playwright is None:
            self.skipTest("playwright is not installed")
        chrome = _chrome_executable()
        if not chrome:
            self.skipTest("Chrome executable not found")

        cancel_seen = Event()

        class BlockingAgent:
            def __init__(self, config, llm):
                self.config = config
                self.llm = llm

            def search(self, question, verbose=False, event_handler=None, cancel_check=None):
                if event_handler:
                    event_handler({"type": "log", "message": "browser fake search started"})
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if cancel_check and cancel_check():
                        cancel_seen.set()
                        raise SearchCancelled("Search cancelled by user.")
                    time.sleep(0.02)
                raise AssertionError("browser Stop did not reach backend cancellation")

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
                    deadline = time.monotonic() + 10
                    while not server.started and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(server.started)

                    cancel_urls = []
                    try:
                        with sync_playwright() as playwright:
                            browser = playwright.chromium.launch(executable_path=chrome, headless=True)
                            page = browser.new_page()
                            page.on(
                                "request",
                                lambda request: cancel_urls.append(request.url)
                                if "/api/search/" in request.url and request.url.endswith("/cancel")
                                else None,
                            )
                            try:
                                page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                                page.fill("#question", "graph neural networks")
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
                                page.wait_for_function(
                                    "() => document.getElementById('stateLabel').textContent.includes('Stopped')",
                                    timeout=10000,
                                )
                            finally:
                                browser.close()

                        deadline = time.monotonic() + 10
                        while not cancel_seen.is_set() and time.monotonic() < deadline:
                            time.sleep(0.02)
                    finally:
                        server.should_exit = True
                        thread.join(timeout=5)

        self.assertTrue(cancel_urls)
        self.assertTrue(cancel_seen.is_set())


if __name__ == "__main__":
    unittest.main()
