import unittest

from paperseek_core.planning import ConceptGroup, QueryView, SearchPlan
from paperseek_core.query_view_selector import select_query_views, selected_query_views


def _view(view_id: str, view_type: str, *terms: str) -> QueryView:
    return QueryView(
        view_id=view_id,
        view_type=view_type,
        purpose=view_id,
        concept_groups=[ConceptGroup(label=view_id, terms=list(terms))],
    )


class QueryViewSelectorTest(unittest.TestCase):
    def test_high_overlap_is_audited_without_overriding_plan_order(self):
        plan = SearchPlan(
            intent="Image retrieval methods",
            query_views=[
                _view("direct", "direct_terminology", "image retrieval", "content based image retrieval"),
                _view("successor", "successor_paradigm", "cross modal retrieval", "image text retrieval"),
                _view("mechanism", "mechanism_method", "visual representation learning", "image embedding"),
            ],
        )

        selections = select_query_views(plan, "openalex", '"image retrieval" AND methods', 2)
        selected = selected_query_views(selections)

        self.assertEqual([item.view.view_id for item in selected], ["direct", "successor"])
        direct = next(item for item in selections if item.view.view_id == "direct")
        self.assertTrue(direct.selected)
        self.assertIn("high_primary_overlap_observed", direct.reason_codes)

    def test_low_overlap_direct_view_keeps_search_plan_priority(self):
        plan = SearchPlan(
            intent="Robust representation learning",
            query_views=[
                _view("direct", "direct_terminology", "conditional Gaussian distribution"),
                _view("mechanism", "mechanism_method", "variational inference"),
                _view("successor", "successor_paradigm", "distributional robustness"),
            ],
        )

        selected = selected_query_views(
            select_query_views(plan, "openalex", '"adversarial robustness" AND feature', 2)
        )

        self.assertEqual([item.view.view_id for item in selected], ["direct", "mechanism"])

    def test_exact_duplicate_and_compile_error_do_not_consume_budget(self):
        plan = SearchPlan(
            intent="Image retrieval",
            query_views=[
                _view("duplicate", "direct_terminology", "image retrieval"),
                _view("invalid", "mechanism_method", "*"),
                _view("successor", "successor_paradigm", "cross modal retrieval"),
                _view("mechanism", "mechanism_method", "visual embedding"),
            ],
        )

        selections = select_query_views(plan, "openalex", '"image retrieval"', 2)
        selected = selected_query_views(selections)

        self.assertEqual([item.view.view_id for item in selected], ["successor", "mechanism"])
        duplicate = next(item for item in selections if item.view.view_id == "duplicate")
        invalid = next(item for item in selections if item.view.view_id == "invalid")
        self.assertIn("exact_primary_duplicate", duplicate.reason_codes)
        self.assertTrue(invalid.compile_error)

    def test_duplicate_supplementary_views_do_not_repeat_source_requests(self):
        plan = SearchPlan(
            intent="AI governance accountability",
            query_views=[
                _view("first", "relation_variant", "AI governance", "accountability"),
                _view("duplicate", "domain_variant", "AI governance", "accountability"),
                _view("mechanism", "mechanism_method", "algorithmic oversight", "public accountability"),
            ],
        )

        selections = select_query_views(plan, "openalex", '"responsible AI"', 3)
        selected = selected_query_views(selections)

        self.assertEqual([item.view.view_id for item in selected], ["first", "mechanism"])
        duplicate = next(item for item in selections if item.view.view_id == "duplicate")
        self.assertIn("exact_selected_view_duplicate", duplicate.reason_codes)
        self.assertFalse(duplicate.selected)


if __name__ == "__main__":
    unittest.main()
