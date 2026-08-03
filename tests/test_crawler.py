import unittest

from paperseek_core.crawler import CrawlerController
from paperseek_core.frontier import FrontierScheduler
from paperseek_core.harness.schemas import FrontierBudget, FrontierOutcome, SelectorBatch, SelectorDecision
from paperseek_core.planning import ConceptGroup, QueryView, SearchPlan
from paperseek_core.query_view_selector import QueryViewSelection


def _plan():
    return SearchPlan(
        intent="Find causal bandit methods for selecting interventions",
        question_type="method_application",
        core_concepts=["causal bandits", "intervention selection"],
        query_views=[
            QueryView(
                view_id="direct",
                view_type="direct_terminology",
                purpose="direct terminology",
                concept_groups=[
                    ConceptGroup(label="causal bandits", terms=["causal bandits"]),
                ],
            ),
            QueryView(
                view_id="interventions",
                view_type="mechanism_method",
                purpose="intervention mechanism",
                concept_groups=[
                    ConceptGroup(label="intervention selection", terms=["good interventions"]),
                ],
            ),
        ],
    )


def _selections():
    plan = _plan()
    return [
        QueryViewSelection(
            view=plan.query_views[0],
            original_index=0,
            score=1.0,
            lexical_overlap=0.4,
            selected=True,
            compiled_query="causal bandits",
            reason_codes=["search_plan_expected_gain_order"],
        ),
        QueryViewSelection(
            view=plan.query_views[1],
            original_index=1,
            score=0.9,
            lexical_overlap=0.1,
            selected=True,
            compiled_query="intervention selection causal inference",
            reason_codes=["complementary_view"],
        ),
    ]


class CrawlerControllerTest(unittest.TestCase):
    def test_seeds_query_views_as_frontier_actions(self):
        controller = CrawlerController(_plan(), "openalex", FrontierScheduler())

        actions = controller.seed_query_views(_selections())

        self.assertEqual(len(actions), 2)
        self.assertEqual({action.action_type for action in actions}, {"search"})
        self.assertEqual(controller.state.planned_actions, 2)
        self.assertEqual(controller.query_view_id(actions[0]), "direct")

    def test_selector_feedback_adds_only_non_excluded_follow_up_actions(self):
        controller = CrawlerController(_plan(), "openalex", FrontierScheduler())
        batch = SelectorBatch(
            decisions=[
                SelectorDecision(
                    candidate_id="p1",
                    label="include",
                    relevance_score=0.9,
                    missing_concepts=["intervention selection"],
                    evidence=["match"],
                    recommended_actions=["expand_backward", "expand_forward"],
                ),
                SelectorDecision(
                    candidate_id="p2",
                    label="uncertain",
                    relevance_score=0.5,
                    missing_concepts=["causal mechanism"],
                    recommended_actions=["enrich"],
                ),
                SelectorDecision(
                    candidate_id="p3",
                    label="exclude",
                    relevance_score=0.0,
                    evidence=["wrong scope"],
                    recommended_actions=["read"],
                ),
            ]
        )

        actions = controller.observe_selector(batch)

        self.assertEqual(len(actions), 3)
        self.assertEqual(
            {action.action_type for action in actions},
            {"expand_backward", "expand_forward", "enrich"},
        )
        self.assertEqual(controller.state.selector_counts, {"include": 1, "uncertain": 1, "exclude": 1})
        self.assertEqual(controller.concept_gaps(), ["causal mechanism", "intervention selection"])

    def test_selector_gaps_reprioritize_pending_query(self):
        controller = CrawlerController(_plan(), "openalex", FrontierScheduler())
        controller.seed_query_views(_selections())
        controller.observe_selector(
            SelectorBatch(
                decisions=[
                    SelectorDecision(
                        candidate_id="p1",
                        label="uncertain",
                        relevance_score=0.5,
                        missing_concepts=["intervention selection"],
                        recommended_actions=["none"],
                    )
                ]
            )
        )

        selected = controller.next_actions(1)

        self.assertEqual(controller.query_view_id(selected[0]), "interventions")
        self.assertIn("selector_gap_reprioritized", selected[0].reason_codes)

    def test_corpus_concept_coverage_resolves_gap_and_excluded_paper_adds_no_gap(self):
        controller = CrawlerController(_plan(), "openalex", FrontierScheduler())
        controller.observe_selector(
            SelectorBatch(
                decisions=[
                    SelectorDecision(
                        candidate_id="p1",
                        label="uncertain",
                        relevance_score=0.5,
                        concept_coverage={"intervention selection": 0.2},
                        missing_concepts=["intervention selection"],
                    ),
                    SelectorDecision(
                        candidate_id="off-topic",
                        label="exclude",
                        relevance_score=0.0,
                        missing_concepts=["causal bandits"],
                    ),
                ]
            ),
            allow_follow_up_actions=False,
        )
        self.assertEqual(controller.concept_gaps(), ["intervention selection"])
        self.assertNotIn("causal bandits", controller.state.concept_gaps)

        controller.observe_selector(
            SelectorBatch(
                decisions=[
                    SelectorDecision(
                        candidate_id="p2",
                        label="include",
                        relevance_score=0.9,
                        concept_coverage={"intervention selection": 0.9},
                    )
                ]
            ),
            allow_follow_up_actions=False,
        )

        self.assertEqual(controller.concept_gaps(), [])
        self.assertEqual(controller.state.concept_coverage["intervention selection"], 0.9)

    def test_query_only_feedback_does_not_enqueue_reader_actions(self):
        controller = CrawlerController(_plan(), "openalex", FrontierScheduler())
        controller.seed_query_views(_selections()[:1])
        batch = SelectorBatch(
            decisions=[
                SelectorDecision(
                    candidate_id="p1",
                    label="uncertain",
                    relevance_score=0.7,
                    missing_concepts=["accountability"],
                    recommended_actions=["read", "expand_backward"],
                )
            ]
        )

        accepted = controller.observe_selector(batch, allow_follow_up_actions=False)

        self.assertEqual(accepted, [])
        self.assertEqual(
            {action.action_type for action in controller.scheduler.state.actions},
            {"search"},
        )
        self.assertEqual(controller.state.concept_gaps, {"accountability": 1})

    def test_unsupported_and_over_depth_actions_are_not_enqueued(self):
        controller = CrawlerController(
            _plan(),
            "openalex",
            FrontierScheduler(),
            supported_actions={"read", "expand_backward"},
            max_citation_depth=1,
        )
        batch = SelectorBatch(
            decisions=[
                SelectorDecision(
                    candidate_id="p1",
                    label="include",
                    relevance_score=0.9,
                    recommended_actions=["read", "enrich", "expand_backward", "expand_forward"],
                )
            ]
        )

        actions = controller.observe_selector(batch, candidate_depths={"p1": 1})

        self.assertEqual([action.action_type for action in actions], ["read"])

    def test_role_aware_citation_seeding_uses_expected_directions(self):
        controller = CrawlerController(
            _plan(),
            "openalex",
            FrontierScheduler(),
            supported_actions={"expand_backward", "expand_forward"},
            max_citation_depth=2,
        )
        batch = SelectorBatch(
            decisions=[
                SelectorDecision(candidate_id="relevant", label="include", relevance_score=0.9),
                SelectorDecision(candidate_id="impact", label="include", relevance_score=0.8),
                SelectorDecision(candidate_id="recent", label="uncertain", relevance_score=0.6),
                SelectorDecision(candidate_id="excluded", label="exclude", relevance_score=0.1),
            ]
        )

        actions = controller.seed_citation_actions(
            batch,
            roles_by_candidate={
                "relevant": ["relevance"],
                "impact": ["impact"],
                "recent": ["recent"],
                "excluded": ["relevance"],
            },
            candidate_depths={"recent": 2},
            max_actions=8,
        )

        self.assertEqual(
            {(action.candidate_id, action.action_type) for action in actions},
            {
                ("relevant", "expand_backward"),
                ("relevant", "expand_forward"),
                ("impact", "expand_backward"),
            },
        )

    def test_action_outcome_updates_frontier_and_crawler_state(self):
        controller = CrawlerController(_plan(), "openalex", FrontierScheduler())
        controller.seed_query_views(_selections()[:1])
        action = controller.next_actions(1)[0]

        completed = controller.complete_action(
            FrontierOutcome(
                action_id=action.action_id,
                status="done",
                candidates_seen=100,
                added_unique=80,
                include_count=12,
                uncertain_count=8,
            )
        )

        self.assertEqual(completed.status, "done")
        self.assertEqual(controller.state.completed_actions, 1)
        self.assertEqual(controller.scheduler.state.budget.source_requests, 1)
        self.assertEqual(controller.scheduler.state.budget.candidate_count, 80)

    def test_request_budget_is_enforced_by_controller(self):
        scheduler = FrontierScheduler()
        scheduler.state = scheduler.state.model_copy(
            update={"budget": FrontierBudget(max_source_requests=1, max_reader_requests=0, max_citation_requests=0)}
        )
        controller = CrawlerController(_plan(), "openalex", scheduler)
        controller.seed_query_views(_selections())
        first = controller.next_actions(1)[0]
        controller.complete_action(FrontierOutcome(action_id=first.action_id, status="done", include_count=5))

        self.assertEqual(controller.next_actions(1), [])
        self.assertEqual(controller.state.stop_reason, "source_request_budget_exhausted")


if __name__ == "__main__":
    unittest.main()
