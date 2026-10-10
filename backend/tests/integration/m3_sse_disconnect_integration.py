from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

import httpx
import uvicorn

from paperseek_app.models import RunStatus
from paperseek_app.services import (
    RunExecutionService,
    RunQueryService,
    RunSubmissionService,
)
from paperseek_community.api import create_app
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database


class M3SseDisconnectIntegrationTest(unittest.TestCase):
    def test_real_sse_disconnect_does_not_cancel_and_reconnect_replays_from_last_event_id(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with nullcontext(temporary.name) as temp:
            data_dir = Path(temp)
            database = data_dir / "paperseek.db"
            migrate_database(database)
            uow = SQLiteRunUnitOfWork(database)
            self.addCleanup(uow.close)
            store = FileArtifactStore(data_dir)
            submission_service = RunSubmissionService(uow)
            execution_service = RunExecutionService(uow, store)
            query_service = RunQueryService(uow, store)
            run = submission_service.create_run("SSE disconnect contract", "openalex")

            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            server = uvicorn.Server(
                uvicorn.Config(
                    create_app(database),
                    host="127.0.0.1",
                    port=port,
                    log_level="error",
                    lifespan="on",
                )
            )
            thread = threading.Thread(
                target=server.run,
                kwargs={"sockets": [listener]},
                daemon=True,
            )
            thread.start()
            self.addCleanup(self._stop_server, server, thread, listener)
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(server.started)

            base_url = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base_url, timeout=5, trust_env=False) as client:
                with client.stream("GET", f"/api/v1/runs/{run.id}/events") as response:
                    first = self._first_event(response)
                self.assertEqual(first["sequence"], 1)
                self.assertEqual(query_service.get_run(run.id).status, RunStatus.QUEUED)

                lease = uow.claim_run(run.id, "sse-worker", timedelta(seconds=60))
                with client.stream(
                    "GET",
                    f"/api/v1/runs/{run.id}/events",
                    headers={"Last-Event-ID": "1"},
                ) as response:
                    replayed = self._first_event(response)
                self.assertEqual(replayed["sequence"], 2)
                self.assertEqual(replayed["event_type"], "run.claimed")
                self.assertEqual(query_service.get_run(run.id).status, RunStatus.RUNNING)

            submission_service.request_cancel(run.id)
            self.assertEqual(execution_service.complete_cancel(lease).status, RunStatus.CANCELLED)

    @staticmethod
    def _first_event(response: httpx.Response) -> dict:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("data: "):
                return json.loads(line[6:])
        raise AssertionError("The SSE stream closed before emitting an event.")

    @staticmethod
    def _stop_server(
        server: uvicorn.Server,
        thread: threading.Thread,
        listener: socket.socket,
    ) -> None:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        if thread.is_alive():
            raise AssertionError("The SSE integration server did not stop.")


if __name__ == "__main__":
    unittest.main()
