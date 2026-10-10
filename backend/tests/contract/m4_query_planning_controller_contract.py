from __future__ import annotations

import json
from pathlib import Path
import unittest

from paperseek_core import query_loop
from paperseek_core.models import QueryLoopSnapshot
from paperseek_core.query_parsing import parse_search_plan

try:
    from paperseek_core import query_planning
except ImportError:
    query_planning = None


ROOT = Path(__file__).resolve().parents[3]
QUESTION = "How do transparent AI decision systems affect accountability in public agencies?"


class QueryPlanningControllerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = parse_search_plan(
            (ROOT / "tests" / "fixtures" / "llm" / "intent_search_plan.json").read_text(
                encoding="utf-8"
            ),
            QUESTION,
        )
        assert cls.plan is not None
        cls.golden = json.loads(
            (ROOT / "tests" / "fixtures" / "golden_search" / "final_result.json").read_text(
                encoding="utf-8"
            )
        )

    def test_planning_and_controller_have_one_module_owner(self) -> None:
        self.assertIsNotNone(query_planning)
        self.assertIs(query_loop.QueryPlanner, query_planning.QueryPlanner)
        self.assertIs(query_loop.QueryLoopController, query_planning.QueryLoopController)
        self.assertNotIn("fallback_search_plan", query_loop.__dict__)

    def test_view_selection_order_scores_and_reason_codes_remain_exact(self) -> None:
        selections = query_planning.select_query_views(
            self.plan,
            "openalex",
            self.golden["final_query"],
            3,
        )
        actual = [
            {
                "source": item.source,
                "view_id": item.view.view_id,
                "view_type": item.view.view_type,
                "selected": item.selected,
                "score": round(item.score, 6),
                "lexical_overlap": round(item.lexical_overlap, 6),
                "max_pairwise_overlap": round(item.max_pairwise_overlap, 6),
                "reason_codes": item.reason_codes,
                "compile_error": item.compile_error,
            }
            for item in selections
        ]
        self.assertEqual(actual, self.golden["query_view_selection"])

    def test_controller_messages_and_stalled_narrowing_semantics_remain_exact(self) -> None:
        controller = query_planning.QueryLoopController()
        base = dict(
            configured_iterations=5,
            adaptive_max_iterations=15,
            target_min=5,
            target_max=50,
            retrieval_pool_min=5,
            retrieval_pool_max=3000,
            query="AI governance accountability",
        )

        accepted = controller.decide(QueryLoopSnapshot(iteration=1, total=25, **base))
        self.assertEqual(
            accepted.model_dump(mode="json"),
            {
                "action": "accept",
                "terminal": True,
                "message": "Accepted 25 records within the target range.",
                "adjustment": "",
                "reason": "The source count is inside the user-facing target range.",
                "stop_reason": "",
            },
        )

        broadened = controller.decide(QueryLoopSnapshot(iteration=1, total=0, **base))
        self.assertEqual(broadened.action, "broaden")
        self.assertFalse(broadened.terminal)
        self.assertEqual(broadened.adjustment, "too few or zero records")

        stalled = controller.decide(
            QueryLoopSnapshot(
                iteration=5,
                total=31_500,
                history=[
                    {"total": 33_000, "action": "narrow"},
                    {"total": 32_000, "action": "narrow"},
                ],
                **base,
            )
        )
        self.assertEqual(stalled.action, "accept_high")
        self.assertTrue(stalled.terminal)
        self.assertIn("successive narrowing rounds", stalled.message)
        self.assertEqual(stalled.adjustment, "above LLM pre-ranking safety pool 3000")


if __name__ == "__main__":
    unittest.main()
