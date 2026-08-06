import sqlite3

from paperseek.history import HistoryStore, _row_value


def _store(tmp_path):
    return HistoryStore(db_path=tmp_path / "paperseek.db", enabled=True)


def _expire_lease(store: HistoryStore, run_id: str) -> None:
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE search_runs SET lease_expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", run_id),
        )


def test_legacy_sqlite_rows_can_omit_lease_columns():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT 'run_legacy' AS id").fetchone()
        assert _row_value(row, "claimed_by", "") == ""
        assert _row_value(row, "attempt_count", 0) == 0
    finally:
        connection.close()


def test_run_claim_is_exclusive_idempotent_and_recoverable(tmp_path):
    store = _store(tmp_path)
    run_id = store.create_run("durable literature search")

    assert store.claim_run(run_id, "worker-a", lease_seconds=60)
    first = store.get_run(run_id)
    assert first["claimed_by"] == "worker-a"
    assert first["attempt_count"] == 1

    assert store.claim_run(run_id, "worker-a", lease_seconds=60)
    assert store.get_run(run_id)["attempt_count"] == 1
    assert not store.claim_run(run_id, "worker-b", lease_seconds=60)
    assert not store.renew_run_lease(run_id, "worker-b", lease_seconds=60)
    assert store.renew_run_lease(run_id, "worker-a", lease_seconds=60)

    _expire_lease(store, run_id)
    assert not store.renew_run_lease(run_id, "worker-a", lease_seconds=60)
    assert store.claim_run(run_id, "worker-b", lease_seconds=60)
    recovered = store.get_run(run_id)
    assert recovered["claimed_by"] == "worker-b"
    assert recovered["attempt_count"] == 2


def test_run_release_requires_owner_and_allows_a_new_attempt(tmp_path):
    store = _store(tmp_path)
    run_id = store.create_run("release a search")
    assert store.claim_run(run_id, "worker-a")

    assert not store.release_run(run_id, "worker-b")
    assert store.release_run(run_id, "worker-a")
    released = store.get_run(run_id)
    assert released["claimed_by"] == ""
    assert released["lease_expires_at"] == ""

    assert store.claim_run(run_id, "worker-b")
    assert store.get_run(run_id)["attempt_count"] == 2


def test_terminal_updates_clear_the_run_lease(tmp_path):
    store = _store(tmp_path)
    completed_id = store.create_run("completed search")
    failed_id = store.create_run("failed search")
    assert store.claim_run(completed_id, "worker-a")
    assert store.claim_run(failed_id, "worker-a")

    assert not store.complete_claimed_run(completed_id, "worker-b", {"ranked": []})
    assert not store.fail_claimed_run(failed_id, "worker-b", "stale failure")
    assert store.complete_claimed_run(completed_id, "worker-a", {"ranked": []})
    assert store.fail_claimed_run(failed_id, "worker-a", "upstream failed")

    completed = store.get_run(completed_id)
    failed = store.get_run(failed_id)
    assert completed["status"] == "success"
    assert completed["claimed_by"] == ""
    assert completed["lease_expires_at"] == ""
    assert not store.claim_run(completed_id, "worker-b")
    assert failed["status"] == "error"
    assert failed["claimed_by"] == ""
    assert failed["lease_expires_at"] == ""


def test_expired_owner_cannot_publish_a_late_result(tmp_path):
    store = _store(tmp_path)
    run_id = store.create_run("late result")
    assert store.claim_run(run_id, "worker-a")
    _expire_lease(store, run_id)

    assert not store.complete_claimed_run(
        run_id,
        "worker-a",
        {"ranked": [{"uid": "stale", "title": "Stale result"}]},
    )
    assert store.get_run(run_id)["status"] == "running"
    assert store.get_run(run_id)["ranked"] == []

    assert store.claim_run(run_id, "worker-b")
    assert store.complete_claimed_run(
        run_id,
        "worker-b",
        {"ranked": [{"uid": "fresh", "title": "Fresh result"}]},
    )
    detail = store.get_run(run_id)
    assert detail["status"] == "success"
    assert detail["ranked"][0]["title"] == "Fresh result"


def test_events_and_checkpoints_require_the_current_unexpired_owner(tmp_path):
    store = _store(tmp_path)
    run_id = store.create_run("owned activity")
    assert store.claim_run(run_id, "worker-a")

    assert not store.record_claimed_event(run_id, "worker-b", {"type": "log"})
    assert not store.save_claimed_checkpoint(
        run_id,
        "worker-b",
        {"sequence": 1, "stage": "query", "query": "stale"},
    )
    assert store.record_claimed_event(
        run_id,
        "worker-a",
        {"type": "log", "message": "owned"},
    )
    assert store.save_claimed_checkpoint(
        run_id,
        "worker-a",
        {"sequence": 1, "stage": "query", "query": "owned"},
    )

    detail = store.get_run(run_id)
    assert [event["message"] for event in detail["events"]] == ["owned"]
    assert detail["checkpoint"]["payload"]["query"] == "owned"

    _expire_lease(store, run_id)
    assert not store.record_claimed_event(run_id, "worker-a", {"type": "log"})
    assert not store.save_claimed_checkpoint(
        run_id,
        "worker-a",
        {"sequence": 2, "stage": "ranking"},
    )


def test_claiming_a_failed_run_resets_its_active_status(tmp_path):
    store = _store(tmp_path)
    run_id = store.create_run("recover failed run")
    store.fail_run(run_id, "process stopped")
    assert store.get_run(run_id)["status"] == "error"

    assert store.claim_run(run_id, "worker-recovery")
    detail = store.get_run(run_id)
    assert detail["status"] == "running"
    assert detail["error_message"] == ""
    assert detail["finished_at"] == ""


def test_persisted_cancellation_invalidates_the_current_worker(tmp_path):
    store = _store(tmp_path)
    run_id = store.create_run("cancel durable run")
    assert store.claim_run(run_id, "worker-a")

    assert store.cancel_run(run_id, "stopped by user")
    detail = store.get_run(run_id)
    assert detail["status"] == "cancelled"
    assert detail["claimed_by"] == ""
    assert detail["error_message"] == "stopped by user"
    assert not store.record_claimed_event(run_id, "worker-a", {"type": "late"})
    assert not store.complete_claimed_run(run_id, "worker-a", {"ranked": []})
