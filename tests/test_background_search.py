import time

from paperseek.application import SearchRunSession, submit_background_search
from paperseek.config import AgentConfig
from paperseek.history import HistoryStore
from paperseek.run_executor import InProcessRunExecutor
from paperseek_core.execution import SearchCancelled
from tests.helpers import fake_harness_search_result


class CompletingAgent:
    def search(
        self,
        question,
        verbose=False,
        event_handler=None,
        cancel_check=None,
        checkpoint_handler=None,
        resume_checkpoint=None,
    ):
        event_handler({"type": "stage", "stage": "query", "status": "complete"})
        checkpoint_handler({"sequence": 1, "stage": "query", "question": question})
        return fake_harness_search_result(question, "crossref")


class CancellableAgent:
    def search(
        self,
        question,
        verbose=False,
        event_handler=None,
        cancel_check=None,
        checkpoint_handler=None,
        resume_checkpoint=None,
    ):
        checkpoint_handler({"sequence": 1, "stage": "query", "question": question})
        for _ in range(200):
            if cancel_check():
                raise SearchCancelled("stopped")
            time.sleep(0.005)
        raise AssertionError("cancellation was not observed")


def _wait_for_status(store, run_id, expected, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = store.get_run(run_id)
        if detail and detail["status"] == expected:
            return detail
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {expected}")


def _session_factory(store, config, question):
    return lambda owner_id: SearchRunSession(
        store,
        config,
        question,
        "crossref",
        owner_id=owner_id,
        heartbeat_interval_seconds=0.02,
    )


def test_background_search_persists_events_and_terminal_state(tmp_path):
    store = HistoryStore(db_path=tmp_path / "runs.db", enabled=True)
    executor = InProcessRunExecutor()
    config = AgentConfig(data_source="crossref", llm_api_key="test-key")

    run_id = submit_background_search(
        executor,
        _session_factory(store, config, "open innovation"),
        lambda _persist: CompletingAgent(),
        run_event={"operation": "create", "source_run_id": ""},
    )

    detail = _wait_for_status(store, run_id, "success")
    assert not executor.is_active(run_id)
    assert detail["attempt_count"] == 1
    run_event = next(event for event in detail["events"] if event["type"] == "run")
    assert run_event["payload"]["operation"] == "create"
    assert any(event["stage"] == "query" for event in detail["events"])
    assert detail["total"] == 1


def test_background_search_cancellation_is_persisted(tmp_path):
    store = HistoryStore(db_path=tmp_path / "runs.db", enabled=True)
    executor = InProcessRunExecutor()
    config = AgentConfig(data_source="crossref", llm_api_key="test-key")

    run_id = submit_background_search(
        executor,
        _session_factory(store, config, "cancel search"),
        lambda _persist: CancellableAgent(),
    )
    assert executor.cancel(run_id)

    detail = _wait_for_status(store, run_id, "cancelled")
    assert not executor.is_active(run_id)
    assert detail["error_message"] == "stopped"
    assert detail["checkpoint"] is not None
