import json
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import SimpleNamespace

from paperseek_core.agent import PaperSeekAgent
from paperseek_core.execution import SearchCancelled, run_cancellable
from paperseek_core.llm import OpenAIChatClient
from paperseek_core.sources.providers import PaperRecord, ProviderSearchResult, SearchMetadata


class _SlowChatHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        time.sleep(2)
        payload = json.dumps({"choices": [{"message": {"content": "late response"}}]}).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        return


class ExecutionLifecycleTest(unittest.TestCase):
    @staticmethod
    def _agent(llm=None):
        config = SimpleNamespace(
            data_source="openalex",
            discipline_fields=(),
            expand_citations=False,
            openalex_api_key="",
            openalex_email="",
            ranking_batch_size=256,
            ranking_concurrency=4,
            target_min=5,
            target_max=50,
            search_loop_backend="native",
        )
        return PaperSeekAgent(config, llm or SimpleNamespace())

    def test_slow_http_call_stops_waiting_promptly(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowChatHandler)
        server.daemon_threads = True
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        cancelled = Event()
        timer = Thread(target=lambda: (time.sleep(0.2), cancelled.set()), daemon=True)
        timer.start()
        client = OpenAIChatClient(
            "test-key",
            model="test-model",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            timeout_seconds=5,
        )

        started = time.monotonic()
        try:
            with self.assertRaises(SearchCancelled):
                run_cancellable(
                    lambda: client.chat([{"role": "user", "content": "test"}]),
                    cancelled.is_set,
                    poll_interval=0.02,
                )
        finally:
            server.shutdown()
            server.server_close()

        self.assertLess(time.monotonic() - started, 1.0)

    def test_cancelled_run_does_not_write_checkpoint(self):
        agent = self._agent()
        writes = []
        agent.cancel_check = lambda: True
        agent.checkpoint_handler = writes.append

        with self.assertRaises(SearchCancelled):
            agent._save_checkpoint("query_execution")

        self.assertEqual(writes, [])

    def test_blocking_source_request_stops_waiting_promptly(self):
        cancelled = Event()

        class SlowProvider:
            def search(self, **kwargs):
                time.sleep(2)
                return ProviderSearchResult(SearchMetadata(total=1), [])

        agent = self._agent()
        agent.provider = SlowProvider()
        agent.cancel_check = cancelled.is_set
        Thread(target=lambda: (time.sleep(0.2), cancelled.set()), daemon=True).start()

        started = time.monotonic()
        with self.assertRaises(SearchCancelled):
            agent._provider_search("slow query")

        self.assertLess(time.monotonic() - started, 1.0)

    def test_blocking_ranking_request_stops_waiting_promptly(self):
        cancelled = Event()

        class SlowRankingLLM:
            def chat_json(self, messages, temperature=0.0, max_tokens=4096):
                time.sleep(2)
                return '{"scores":[[1,8]]}'

        agent = self._agent(SlowRankingLLM())
        agent.cancel_check = cancelled.is_set
        Thread(target=lambda: (time.sleep(0.2), cancelled.set()), daemon=True).start()

        started = time.monotonic()
        with self.assertRaises(SearchCancelled):
            agent._rank_results("test", [PaperRecord(uid="p1", title="Test paper")])

        self.assertLess(time.monotonic() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
