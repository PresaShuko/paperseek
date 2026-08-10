import hashlib
import json
import os
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from paperseek.config import AgentConfig
from paperseek_core import prompts
from paperseek_core.budgets import (
    DEFAULT_SEARCH_BUDGET,
    SEARCH_BUDGET_NAMES,
    SEARCH_BUDGET_PRESETS,
)
from paperseek_core.config import SearchConfig
from paperseek_core.harness import SearchLoopController, SearchRunState


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "baseline" / "frozen_search_semantics.json"


class FrozenSearchSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_all_active_system_prompts_match_frozen_hashes(self):
        actual = {
            name: hashlib.sha256(value.encode("utf-8")).hexdigest().upper()
            for name, value in vars(prompts).items()
            if name.startswith("SYSTEM_") and isinstance(value, str)
        }

        self.assertEqual(actual, self.fixture["prompt_sha256"])

    def test_all_search_budget_values_match_frozen_contract(self):
        expected = self.fixture["search_budget"]
        actual_presets = {
            name: asdict(SEARCH_BUDGET_PRESETS[name])
            for name in SEARCH_BUDGET_NAMES
        }

        self.assertEqual(DEFAULT_SEARCH_BUDGET, expected["default"])
        self.assertEqual(list(SEARCH_BUDGET_NAMES), expected["names"])
        self.assertEqual(actual_presets, expected["presets"])

    def test_default_candidate_controls_match_frozen_contract(self):
        with patch.dict(os.environ, {}, clear=True):
            agent = AgentConfig.from_env()
        core = SearchConfig()
        fields = tuple(self.fixture["default_controls"]["agent"])

        self.assertEqual(
            {name: getattr(agent, name) for name in fields},
            self.fixture["default_controls"]["agent"],
        )
        core_fields = tuple(self.fixture["default_controls"]["core"])
        self.assertEqual(
            {name: getattr(core, name) for name in core_fields},
            self.fixture["default_controls"]["core"],
        )

    def test_citation_role_quotas_match_frozen_contract(self):
        controller = SearchLoopController()
        state = SearchRunState(
            question="M0 characterization",
            source="openalex",
            current_query="M0 characterization",
        )

        for case in self.fixture["citation_planning_cases"]:
            with self.subTest(case=case):
                _, decision = controller.plan_citation_expansion(
                    state,
                    configured_seed_count=case["configured_seed_count"],
                    configured_depth=case["configured_depth"],
                )
                actual = {
                    name: getattr(decision, name)
                    for name in case["expected"]
                }
                self.assertEqual(actual, case["expected"])


if __name__ == "__main__":
    unittest.main()
