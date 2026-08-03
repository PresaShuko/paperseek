import unittest

from paperseek_core.frontier import FrontierScheduler
from paperseek_core.harness.schemas import ActionFrontierState, FrontierBudget, FrontierOutcome, SearchRunState


class FrontierSchedulerTest(unittest.TestCase):
    def test_shared_tool_budget_caps_mixed_action_types(self):
        scheduler = FrontierScheduler(
            ActionFrontierState(
                budget=FrontierBudget(
                    max_source_requests=5,
                    max_reader_requests=5,
                    max_citation_requests=5,
                    max_tool_requests=2,
                )
            )
        )
        actions = [
            scheduler.make_action("search", source="openalex", query="first"),
            scheduler.make_action("read", source="openalex", candidate_id="W1"),
            scheduler.make_action("expand_forward", source="openalex", candidate_id="W1"),
        ]
        scheduler.enqueue(actions)

        for _ in range(2):
            action = scheduler.schedule(1)[0]
            scheduler.complete(FrontierOutcome(action_id=action.action_id, status="done"))

        self.assertEqual(scheduler.state.budget.tool_requests, 2)
        self.assertEqual(scheduler.schedule(1), [])
        self.assertEqual(scheduler.state.stop_reason, "tool_request_budget_exhausted")

    def test_new_supported_action_reopens_phase_specific_stop(self):
        scheduler = FrontierScheduler()
        scheduler.state = scheduler.state.model_copy(update={"stop_reason": "source_request_budget_exhausted"})

        accepted = scheduler.enqueue(
            [scheduler.make_action("read", candidate_id="W1", expected_gain=0.8)]
        )

        self.assertEqual(len(accepted), 1)
        self.assertEqual(scheduler.state.stop_reason, "")
        self.assertEqual(scheduler.schedule(1)[0].action_type, "read")
    def test_schedules_expected_gain_per_cost_not_insertion_order(self):
        scheduler = FrontierScheduler()
        low = scheduler.make_action("search", query="low", expected_gain=1.0, estimated_cost=1.0)
        high = scheduler.make_action(
            "search",
            query="high",
            expected_gain=2.0,
            concept_gap_coverage=1.0,
            estimated_cost=0.5,
        )
        scheduler.enqueue([low, high])

        selected = scheduler.schedule(limit=1)

        self.assertEqual(selected[0].action_id, high.action_id)
        self.assertGreater(selected[0].priority, low.priority)

    def test_duplicate_action_does_not_enter_frontier_twice(self):
        scheduler = FrontierScheduler()
        first = scheduler.make_action("search", source="openalex", query="causal bandits")
        duplicate = scheduler.make_action("search", source="OPENALEX", query="  causal   bandits  ")

        accepted = scheduler.enqueue([first, duplicate])

        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(scheduler.state.actions), 1)

    def test_completion_consumes_action_specific_budget(self):
        budget = FrontierBudget(max_source_requests=2, max_reader_requests=2, max_citation_requests=2)
        scheduler = FrontierScheduler(ActionFrontierState(budget=budget))
        actions = [
            scheduler.make_action("search", query="q"),
            scheduler.make_action("read", candidate_id="p1"),
            scheduler.make_action("expand_forward", candidate_id="p1"),
        ]
        scheduler.enqueue(actions)

        for _ in range(3):
            action = scheduler.schedule(1)[0]
            scheduler.complete(
                FrontierOutcome(action_id=action.action_id, status="done", added_unique=2, include_count=2)
            )

        current = scheduler.state.budget
        self.assertEqual(current.source_requests, 1)
        self.assertEqual(current.reader_requests, 1)
        self.assertEqual(current.citation_requests, 1)
        self.assertEqual(current.candidate_count, 6)

    def test_source_budget_blocks_additional_search_actions(self):
        budget = FrontierBudget(max_source_requests=1, max_reader_requests=0, max_citation_requests=0)
        scheduler = FrontierScheduler(ActionFrontierState(budget=budget))
        scheduler.enqueue(
            [
                scheduler.make_action("search", query="q1", expected_gain=2),
                scheduler.make_action("search", query="q2", expected_gain=1),
            ]
        )
        first = scheduler.schedule(1)[0]
        scheduler.complete(FrontierOutcome(action_id=first.action_id, status="done", include_count=2))

        self.assertEqual(scheduler.schedule(1), [])
        self.assertEqual(scheduler.state.stop_reason, "source_request_budget_exhausted")

    def test_two_low_yield_rounds_stop_only_when_no_concept_gap_remains(self):
        scheduler = FrontierScheduler(low_yield_threshold=1, low_yield_round_limit=2)
        scheduler.enqueue(
            [
                scheduler.make_action("search", query="q1", expected_gain=3),
                scheduler.make_action("search", query="q2", expected_gain=2),
                scheduler.make_action("search", query="q3", expected_gain=1),
            ]
        )
        for _ in range(2):
            action = scheduler.schedule(1)[0]
            scheduler.complete(FrontierOutcome(action_id=action.action_id, status="done", include_count=0, uncertain_count=1))

        self.assertFalse(scheduler.should_stop(["missing intervention concept"]))
        self.assertTrue(scheduler.should_stop([]))
        self.assertEqual(scheduler.state.stop_reason, "marginal_gain_exhausted")

    def test_useful_action_resets_low_yield_counter(self):
        scheduler = FrontierScheduler(low_yield_threshold=1, low_yield_round_limit=2)
        scheduler.enqueue(
            [
                scheduler.make_action("search", query="q1", expected_gain=3),
                scheduler.make_action("search", query="q2", expected_gain=2),
            ]
        )
        first = scheduler.schedule(1)[0]
        scheduler.complete(FrontierOutcome(action_id=first.action_id, status="done", include_count=0))
        second = scheduler.schedule(1)[0]
        scheduler.complete(FrontierOutcome(action_id=second.action_id, status="done", include_count=2))

        self.assertEqual(scheduler.state.low_yield_rounds, 0)

    def test_concept_gap_reduction_counts_as_action_utility(self):
        scheduler = FrontierScheduler(low_yield_threshold=1, low_yield_round_limit=2)
        scheduler.enqueue(
            [
                scheduler.make_action("search", query="q1", expected_gain=2),
                scheduler.make_action("search", query="q2", expected_gain=1),
            ]
        )
        first = scheduler.schedule(1)[0]
        scheduler.complete(
            FrontierOutcome(action_id=first.action_id, status="done", newly_relevant_count=0)
        )
        self.assertEqual(scheduler.state.low_yield_rounds, 1)

        second = scheduler.schedule(1)[0]
        scheduler.complete(
            FrontierOutcome(
                action_id=second.action_id,
                status="done",
                newly_relevant_count=0,
                concept_gap_reduction=2,
            )
        )

        self.assertEqual(scheduler.state.low_yield_rounds, 0)

    def test_snapshot_persists_elapsed_budget_across_scheduler_rebuild(self):
        scheduler = FrontierScheduler(ActionFrontierState(elapsed_seconds=17.0))

        snapshot = scheduler.snapshot()
        restored = FrontierScheduler(ActionFrontierState.model_validate(snapshot.model_dump()))

        self.assertGreaterEqual(snapshot.elapsed_seconds, 17.0)
        self.assertGreaterEqual(restored.snapshot().elapsed_seconds, snapshot.elapsed_seconds)

    def test_failed_action_records_penalty_and_audit_reason(self):
        scheduler = FrontierScheduler()
        action = scheduler.make_action("enrich", candidate_id="p1", expected_gain=2)
        scheduler.enqueue([action])
        running = scheduler.schedule(1)[0]

        completed = scheduler.complete(
            FrontierOutcome(action_id=running.action_id, status="failed", error="timeout")
        )

        self.assertEqual(completed.status, "failed")
        self.assertEqual(completed.failure_penalty, 1.0)
        self.assertIn("action_failed", completed.reason_codes)
        self.assertEqual(scheduler.state.outcomes[0].error, "timeout")

    def test_release_returns_interrupted_running_action_to_pending_without_cost(self):
        scheduler = FrontierScheduler()
        action = scheduler.make_action("search", query="q")
        scheduler.enqueue([action])
        running = scheduler.schedule(1)[0]

        released = scheduler.release(running.action_id)

        self.assertEqual(released.status, "pending")
        self.assertIn("action_interrupted", released.reason_codes)
        self.assertEqual(scheduler.state.budget.source_requests, 0)
        self.assertEqual(scheduler.state.outcomes, [])
        self.assertEqual(scheduler.schedule(1)[0].action_id, running.action_id)

    def test_frontier_is_part_of_search_run_state(self):
        scheduler = FrontierScheduler()
        scheduler.enqueue([scheduler.make_action("search", source="arxiv", query="graph robustness")])
        state = SearchRunState(question="q", source="arxiv").with_action_frontier(scheduler.snapshot())

        payload = state.model_dump(mode="json")

        self.assertEqual(payload["action_frontier"]["actions"][0]["action_type"], "search")


if __name__ == "__main__":
    unittest.main()
