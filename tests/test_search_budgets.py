import os
import unittest
from unittest.mock import patch

from paperseek.config import AgentConfig
from paperseek_core.budgets import (
    SEARCH_BUDGET_NAMES,
    SEARCH_BUDGET_PRESETS,
    apply_search_budget,
    normalize_search_budget,
)
from paperseek_core.config import SearchConfig


class SearchBudgetTest(unittest.TestCase):
    def test_fast_uses_the_smallest_request_budget(self):
        fast = SEARCH_BUDGET_PRESETS["fast"]

        self.assertEqual(fast.max_iterations, 5)
        self.assertEqual(fast.query_portfolio_max, 3)
        self.assertEqual(fast.query_portfolio_limit, 100)
        self.assertEqual(fast.retrieval_lane_limit, 500)
        self.assertEqual(fast.retrieval_pool_max, 3000)
        self.assertEqual(fast.ranking_candidate_limit, 256)
        self.assertEqual(fast.citation_seed_count, 3)
        self.assertEqual(fast.citation_per_seed, 4)
        self.assertEqual(fast.citation_max_records, 40)
        self.assertEqual(fast.citation_depth, 2)

    def test_presets_widen_the_search_budget_monotonically(self):
        ordered = [SEARCH_BUDGET_PRESETS[name] for name in SEARCH_BUDGET_NAMES]
        strictly_increasing = (
            "max_iterations",
            "retrieval_pool_max",
            "ranking_candidate_limit",
            "citation_seed_count",
            "citation_per_seed",
            "citation_max_records",
            "candidate_selector_max_llm_calls",
            "crawler_max_reader_requests",
            "crawler_max_citation_requests",
            "crawler_max_wall_seconds",
        )
        for field_name in strictly_increasing:
            values = [getattr(item, field_name) for item in ordered]
            with self.subTest(field=field_name):
                self.assertEqual(values, sorted(values))
                self.assertEqual(len(values), len(set(values)))

        lane_limits = [item.retrieval_lane_limit for item in ordered]
        self.assertEqual(lane_limits, sorted(lane_limits))
        self.assertEqual(lane_limits[-1], 1000)

        portfolio_limits = [item.query_portfolio_max for item in ordered]
        self.assertEqual(portfolio_limits, sorted(portfolio_limits))
        self.assertTrue(all(value >= 3 for value in portfolio_limits))

    def test_apply_search_budget_updates_all_controlled_fields(self):
        config = AgentConfig(llm_thinking_enabled=False)
        apply_search_budget(config, "high")
        high = SEARCH_BUDGET_PRESETS["high"]

        self.assertEqual(config.search_budget, "high")
        for field_name, expected in high.values().items():
            with self.subTest(field=field_name):
                self.assertEqual(getattr(config, field_name), expected)
        self.assertFalse(config.llm_thinking_enabled)

    def test_agent_and_core_defaults_use_fast(self):
        with patch.dict(os.environ, {}, clear=True):
            agent = AgentConfig.from_env()
        core = SearchConfig()
        fast = SEARCH_BUDGET_PRESETS["fast"]

        self.assertEqual(agent.search_budget, "fast")
        self.assertEqual(core.search_budget, "fast")
        self.assertTrue(agent.llm_thinking_enabled)
        self.assertTrue(core.llm_thinking_enabled)
        self.assertEqual(agent.ranking_batch_size, 8)
        self.assertEqual(agent.retrieval_pool_max, fast.retrieval_pool_max)
        self.assertEqual(core.ranking_candidate_limit, fast.ranking_candidate_limit)

    def test_granular_environment_values_override_the_environment_preset(self):
        with patch.dict(
            os.environ,
            {
                "SEARCH_BUDGET": "high",
                "MAX_ITERATIONS": "4",
                "RANKING_CANDIDATE_LIMIT": "123",
            },
            clear=True,
        ):
            config = AgentConfig.from_env()

        self.assertEqual(config.search_budget, "high")
        self.assertEqual(config.max_iterations, 4)
        self.assertEqual(config.ranking_candidate_limit, 123)
        self.assertEqual(config.retrieval_pool_max, SEARCH_BUDGET_PRESETS["high"].retrieval_pool_max)

    def test_invalid_budget_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "fast, medium, high, max"):
            normalize_search_budget("unlimited")


if __name__ == "__main__":
    unittest.main()
