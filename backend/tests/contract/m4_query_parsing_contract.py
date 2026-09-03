from __future__ import annotations

import json
import unittest

from paperseek_core import query_loop

try:
    from paperseek_core import query_parsing
except ImportError:
    query_parsing = None


QUESTION = "Compare transparent AI systems without robotics."


class QueryParsingContract(unittest.TestCase):
    def test_parsing_has_one_module_owner(self) -> None:
        self.assertIsNotNone(query_parsing)
        self.assertNotIn("parse_search_plan", query_loop.__dict__)

    def test_search_plan_accepts_fences_embedded_braces_and_filters_machine_fields(self) -> None:
        payload = {
            "intent": "Transparent {AI} comparison",
            "question_type": "unknown-machine-value",
            "unknown_plan_field": "discarded",
            "query_views": [
                {
                    "name": "Direct View",
                    "purpose": 'Compare "audit {evidence}"',
                    "concept_groups": [
                        {
                            "label": "Transparency",
                            "terms": ["transparent AI"],
                            "required": True,
                            "unknown_group_field": "discarded",
                        }
                    ],
                    "exclusions": ["robotics", "healthcare"],
                    "unknown_view_field": "discarded",
                },
                "discard this non-object",
            ],
        }
        encoded = json.dumps(payload)
        raw = f"preface\n{encoded}\ntrailing prose"
        fenced = f"```json\n{encoded}\n```"

        plan = query_parsing.parse_search_plan(raw, QUESTION)
        fenced_plan = query_parsing.parse_search_plan(fenced, QUESTION)

        self.assertIsNotNone(plan)
        self.assertIsNotNone(fenced_plan)
        assert plan is not None
        assert fenced_plan is not None
        self.assertEqual(fenced_plan, plan)
        self.assertEqual(plan.intent, "Transparent {AI} comparison")
        self.assertEqual(plan.question_type, "comparison")
        self.assertEqual(len(plan.query_views), 1)
        self.assertEqual(plan.query_views[0].view_id, "direct_view")
        self.assertEqual(plan.query_views[0].exclusions, ["robotics"])
        self.assertEqual(plan.query_views[0].concept_groups[0].terms, ["transparent AI"])

    def test_invalid_search_plan_shapes_remain_none(self) -> None:
        for raw in ("", "[]", "prefix {not-json} suffix", 'prefix {"intent": "open"'):
            with self.subTest(raw=raw):
                self.assertIsNone(query_parsing.parse_search_plan(raw, QUESTION))

    def test_query_proposal_aliases_nested_values_and_rationale_order_are_stable(self) -> None:
        raw = (
            "model note before "
            + json.dumps(
                {
                    "search_query": {"query": 'all:"audit {evidence}"'},
                    "rationale": ["first", "second"],
                    "adjustment": "tighten scope",
                }
            )
            + " model note after"
        )

        self.assertEqual(
            query_parsing.parse_query_proposal(raw),
            ('all:"audit {evidence}"', "first; second\ntighten scope"),
        )
        for invalid in ("", "[]", "```json\n{broken}\n```"):
            with self.subTest(invalid=invalid):
                self.assertEqual(query_parsing.parse_query_proposal(invalid), ("", ""))


if __name__ == "__main__":
    unittest.main()
