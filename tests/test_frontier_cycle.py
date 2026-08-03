import unittest
from unittest.mock import patch

from paperseek_core.crawler import CrawlerController
from paperseek_core.frontier import FrontierScheduler
from paperseek_core.harness import SearchLoopController
from paperseek_core.harness.schemas import FrontierOutcome
from paperseek_core.planning import SearchPlan


class Interrupted(Exception):
    pass


def controller_with_action():
    controller = CrawlerController(
        SearchPlan(intent="test", core_concepts=["test"]),
        "openalex",
        FrontierScheduler(),
    )
    controller.scheduler.enqueue(
        [controller.scheduler.make_action("search", query="test", expected_gain=1.0)]
    )
    return controller


class FrontierCycleTest(unittest.TestCase):
    def test_native_cycle_schedules_executes_selects_and_completes(self):
        controller = controller_with_action()
        calls = []

        result = SearchLoopController("native").run_frontier_cycle(
            controller,
            lambda action: calls.append(("execute", action.action_id)) or {"records": [1]},
            lambda action, execution: calls.append(("select", len(execution["records"])))
            or FrontierOutcome(
                action_id=action.action_id,
                status="done",
                added_unique=1,
                newly_relevant_count=1,
            ),
        )

        self.assertTrue(result.scheduled)
        self.assertEqual(result.outcome.status, "done")
        self.assertEqual([name for name, _ in calls], ["execute", "select"])
        self.assertEqual(controller.scheduler.state.actions[0].status, "done")
        self.assertEqual(controller.state.completed_actions, 1)

    def test_native_cycle_releases_action_when_cancelled(self):
        controller = controller_with_action()

        with self.assertRaises(Interrupted):
            SearchLoopController("native").run_frontier_cycle(
                controller,
                lambda action: (_ for _ in ()).throw(Interrupted("stop")),
                lambda action, execution: FrontierOutcome(action_id=action.action_id, status="done"),
                passthrough_exceptions=(Interrupted,),
            )

        self.assertEqual(controller.scheduler.state.actions[0].status, "pending")
        self.assertEqual(controller.scheduler.state.outcomes, [])

    def test_langgraph_cycle_matches_native_lifecycle(self):
        controller = controller_with_action()
        loop = SearchLoopController("langgraph")
        if loop.summary()["backend_used"] != "langgraph":
            self.skipTest("LangGraph backend is unavailable")

        result = loop.run_frontier_cycle(
            controller,
            lambda action: {"records": [1, 2]},
            lambda action, execution: FrontierOutcome(
                action_id=action.action_id,
                status="done",
                candidates_seen=len(execution["records"]),
                newly_relevant_count=1,
            ),
        )

        self.assertTrue(result.scheduled)
        self.assertEqual(result.backend_used, "langgraph")
        self.assertEqual(result.outcome.candidates_seen, 2)
        self.assertEqual(controller.scheduler.state.actions[0].status, "done")
        self.assertIn("frontier_cycle", loop.runner._graphs)

    def test_langgraph_compile_failure_falls_back_before_side_effect(self):
        controller = controller_with_action()
        loop = SearchLoopController("langgraph")
        if loop.summary()["backend_used"] != "langgraph":
            self.skipTest("LangGraph backend is unavailable")
        calls = []

        with patch.object(loop.runner, "_build_frontier_cycle_graph", side_effect=RuntimeError("compile")):
            result = loop.run_frontier_cycle(
                controller,
                lambda action: calls.append(action.action_id) or {},
                lambda action, execution: FrontierOutcome(action_id=action.action_id, status="done"),
            )

        self.assertEqual(result.backend_used, "native_fallback")
        self.assertEqual(len(calls), 1)
        self.assertEqual(controller.scheduler.state.actions[0].status, "done")


if __name__ == "__main__":
    unittest.main()
