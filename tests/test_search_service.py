import unittest

from paperseek.application import SearchRunSession
from paperseek.config import AgentConfig
from tests.helpers import fake_harness_search_result


class FakeRunStore:
    def __init__(self):
        self.params = None
        self.checkpoints = []
        self.completed = None
        self.failed = None
        self.claimed = None
        self.completed_claimed = None
        self.failed_claimed = None
        self.cancelled = None
        self.cancelled_claimed = None
        self.claimed_events = []
        self.claimed_checkpoints = []
        self.resume = None
        self.existing = None

    def create_run(self, question, params=None):
        self.params = params
        return "run_test"

    def record_event(self, run_id, event):
        pass

    def record_claimed_event(self, run_id, owner_id, event):
        self.claimed_events.append((run_id, owner_id, event))
        return True

    def save_checkpoint(self, run_id, checkpoint):
        self.checkpoints.append((run_id, checkpoint))

    def save_claimed_checkpoint(self, run_id, owner_id, checkpoint):
        self.claimed_checkpoints.append((run_id, owner_id, checkpoint))
        return True

    def latest_checkpoint(self, run_id):
        return self.resume

    def get_run(self, run_id):
        return self.existing

    def claim_run(self, run_id, owner_id, lease_seconds=60):
        self.claimed = (run_id, owner_id, lease_seconds)
        return True

    def renew_run_lease(self, run_id, owner_id, lease_seconds=60):
        return True

    def release_run(self, run_id, owner_id):
        return True

    def cancel_run(self, run_id, message=""):
        self.cancelled = (run_id, message)
        return True

    def cancel_claimed_run(self, run_id, owner_id, message=""):
        self.cancelled_claimed = (run_id, owner_id, message)
        return True

    def complete_run(self, run_id, payload):
        self.completed = (run_id, payload)

    def fail_run(self, run_id, error_message, payload=None):
        self.failed = (run_id, error_message, payload)

    def complete_claimed_run(self, run_id, owner_id, payload):
        self.completed_claimed = (run_id, owner_id, payload)
        return True

    def fail_claimed_run(self, run_id, owner_id, error_message, payload=None):
        self.failed_claimed = (run_id, owner_id, error_message, payload)
        return True


class FakeAgent:
    def __init__(self, source="openalex"):
        self.source = source
        self.resume_checkpoint = None

    def search(
        self,
        question,
        verbose=False,
        event_handler=None,
        cancel_check=None,
        checkpoint_handler=None,
        resume_checkpoint=None,
    ):
        self.resume_checkpoint = resume_checkpoint
        if event_handler is not None:
            event_handler({"type": "stage", "stage": "query", "status": "complete"})
        checkpoint_handler({"sequence": 1, "stage": "query", "question": question})
        return fake_harness_search_result(question, self.source)

    def partial_result_payload(self, question):
        payload = fake_harness_search_result(question, self.source)
        payload["total"] = 17
        return payload


class SearchRunSessionTest(unittest.TestCase):
    def test_session_owns_run_checkpoint_result_and_failure_lifecycle(self):
        store = FakeRunStore()
        store.resume = {"payload": {"sequence": 2, "stage": "retrieval"}}
        config = AgentConfig(data_source="openalex")
        session = SearchRunSession(
            store,
            config,
            "open innovation",
            "openalex",
            resume_run_id="run_previous",
        )

        self.assertEqual(session.start(), "run_test")
        self.assertEqual(store.params["resume_from_run_id"], "run_previous")

        agent = FakeAgent()
        result = session.invoke(agent)
        self.assertEqual(agent.resume_checkpoint["stage"], "retrieval")
        self.assertEqual(store.checkpoints[0][0], "run_test")

        response = session.response(result)
        self.assertEqual(response["run_id"], "run_test")
        session.complete(response)
        self.assertEqual(store.completed, ("run_test", response))

        session.fail("ranking failed")
        self.assertEqual(store.failed[0:2], ("run_test", "ranking failed"))
        self.assertEqual(store.failed[2]["total"], 17)

    def test_missing_resume_checkpoint_is_rejected(self):
        store = FakeRunStore()
        session = SearchRunSession(
            store,
            AgentConfig(data_source="openalex"),
            "open innovation",
            "openalex",
            resume_run_id="missing",
        )
        session.start()

        with self.assertRaisesRegex(ValueError, "no recoverable checkpoint"):
            session.invoke(FakeAgent())

    def test_run_metadata_is_allowlisted_before_persistence(self):
        store = FakeRunStore()
        session = SearchRunSession(
            store,
            AgentConfig(data_source="openalex"),
            "open innovation",
            "openalex",
            run_metadata={
                "interface": "api_v1",
                "operation": "retry",
                "source_run_id": "run_source",
                "credential_resume_mode": "request_or_environment",
                "api_key": "must-not-be-persisted",
            },
        )

        session.start()

        self.assertEqual(
            store.params["run_submission"],
            {
                "interface": "api_v1",
                "operation": "retry",
                "source_run_id": "run_source",
                "credential_resume_mode": "request_or_environment",
            },
        )
        self.assertNotIn("api_key", store.params["run_submission"])

    def test_claimed_session_uses_owner_checked_terminal_write(self):
        store = FakeRunStore()
        session = SearchRunSession(
            store,
            AgentConfig(data_source="openalex"),
            "open innovation",
            "openalex",
            owner_id="worker-a",
            heartbeat_interval_seconds=0.01,
        )

        session.start()
        result = session.invoke(FakeAgent(), event_handler=session.record_event)
        response = session.response(result)
        session.complete(response)
        claimed_event_count = len(store.claimed_events)
        session.record_event({"type": "log", "message": "client-only completion"})

        self.assertEqual(store.claimed, ("run_test", "worker-a", 60))
        self.assertEqual(store.claimed_events[0][0:2], ("run_test", "worker-a"))
        self.assertEqual(store.claimed_checkpoints[0][0:2], ("run_test", "worker-a"))
        self.assertEqual(store.completed_claimed[0:2], ("run_test", "worker-a"))
        self.assertIsNone(store.completed)
        self.assertEqual(len(store.claimed_events), claimed_event_count)
        self.assertTrue(session.terminal_committed)

    def test_existing_run_is_claimed_and_resumed_without_creating_a_duplicate(self):
        store = FakeRunStore()
        store.existing = {
            "id": "run_existing",
            "question": "stored question",
            "status": "error",
        }
        store.resume = {"payload": {"sequence": 3, "stage": "retrieval"}}
        session = SearchRunSession(
            store,
            AgentConfig(data_source="openalex"),
            "ignored question",
            "openalex",
            existing_run_id="run_existing",
            owner_id="worker-recovery",
        )

        self.assertEqual(session.start(), "run_existing")
        self.assertIsNone(store.params)
        agent = FakeAgent()
        result = session.invoke(agent)

        self.assertEqual(session.question, "stored question")
        self.assertEqual(agent.resume_checkpoint["sequence"], 3)
        self.assertEqual(store.claimed[0:2], ("run_existing", "worker-recovery"))
        session.complete(session.response(result))
        self.assertEqual(store.completed_claimed[0], "run_existing")

    def test_existing_terminal_run_cannot_be_resumed_in_place(self):
        store = FakeRunStore()
        store.existing = {
            "id": "run_done",
            "question": "done",
            "status": "success",
        }
        session = SearchRunSession(
            store,
            AgentConfig(data_source="openalex"),
            "done",
            "openalex",
            existing_run_id="run_done",
            owner_id="worker-recovery",
        )

        with self.assertRaisesRegex(ValueError, "cannot be resumed"):
            session.start()

    def test_claimed_session_persists_cancellation_as_a_terminal_state(self):
        store = FakeRunStore()
        session = SearchRunSession(
            store,
            AgentConfig(data_source="openalex"),
            "cancel me",
            "openalex",
            owner_id="worker-a",
        )
        session.start()

        self.assertTrue(session.cancel("stopped"))
        self.assertEqual(
            store.cancelled_claimed,
            ("run_test", "worker-a", "stopped"),
        )
        self.assertTrue(session.terminal_committed)


if __name__ == "__main__":
    unittest.main()
