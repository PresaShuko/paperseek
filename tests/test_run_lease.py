import time

import pytest

from paperseek.application.run_lease import RunLease, RunOwnershipLost


class LeaseStore:
    def __init__(self, *, renew_result=True):
        self.renew_result = renew_result
        self.claims = []
        self.renewals = []
        self.releases = []

    def claim_run(self, run_id, owner_id, lease_seconds=60):
        self.claims.append((run_id, owner_id, lease_seconds))
        return True

    def renew_run_lease(self, run_id, owner_id, lease_seconds=60):
        self.renewals.append((run_id, owner_id, lease_seconds))
        return self.renew_result

    def release_run(self, run_id, owner_id):
        self.releases.append((run_id, owner_id))
        return True


def test_lease_heartbeat_renews_and_stops_cleanly():
    store = LeaseStore()
    lease = RunLease(
        store,
        "run-1",
        "worker-a",
        lease_seconds=5,
        heartbeat_interval_seconds=0.01,
    )

    assert lease.claim()
    lease.start_heartbeat()
    deadline = time.monotonic() + 1
    while not store.renewals and time.monotonic() < deadline:
        time.sleep(0.005)
    lease.stop_heartbeat()

    assert store.renewals
    assert not lease.lost


def test_failed_heartbeat_marks_ownership_lost_and_prevents_release():
    store = LeaseStore(renew_result=False)
    lease = RunLease(
        store,
        "run-1",
        "worker-a",
        lease_seconds=5,
        heartbeat_interval_seconds=0.01,
    )

    assert lease.claim()
    lease.start_heartbeat()
    deadline = time.monotonic() + 1
    while not lease.lost and time.monotonic() < deadline:
        time.sleep(0.005)

    assert lease.lost
    with pytest.raises(RunOwnershipLost):
        lease.ensure_owned()
    assert not lease.release()
    assert store.releases == []
