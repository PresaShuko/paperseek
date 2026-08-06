import pytest

from paperseek.run_executor import InProcessRunExecutor


def test_active_run_can_be_cancelled_and_unregisters_on_close():
    executor = InProcessRunExecutor()
    run = executor.create()
    run.bind("run_1")

    assert run.owner_id.startswith("worker_")
    assert executor.is_active("run_1")

    assert executor.cancel("run_1") is True
    assert run.is_cancelled() is True

    run.close()
    assert not executor.is_active("run_1")
    assert executor.cancel("run_1") is False


def test_closed_run_rejects_late_events():
    executor = InProcessRunExecutor()
    run = executor.create()
    run.close()

    assert run.emit({"type": "result"}) is False


def test_event_iterator_delivers_events_until_close():
    executor = InProcessRunExecutor()
    run = executor.create()
    run.emit({"type": "log", "message": "started"})
    run.close()

    assert list(run.iter_events(heartbeat_seconds=0.01, heartbeat_factory=lambda: {"type": "heartbeat"})) == [
        {"type": "log", "message": "started"}
    ]


def test_unbuffered_run_does_not_expose_a_stream_queue():
    executor = InProcessRunExecutor()
    run = executor.create(buffer_events=False)
    run.bind("run_background")
    assert run.emit({"type": "log"})

    with pytest.raises(RuntimeError, match="does not buffer"):
        next(run.iter_events(heartbeat_seconds=0.01, heartbeat_factory=dict))

    run.close()
