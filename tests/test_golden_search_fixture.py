import json
import unittest

from tests.golden_search_fixture import FIXTURE_ROOT, build_search_artifacts
from tests.helpers import read_json, read_text


class GoldenSearchFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = build_search_artifacts()
        cls.second = build_search_artifacts()

    def test_current_search_entry_is_offline_and_stable_across_two_runs(self):
        self.assertEqual(self.first["final_result_text"], self.second["final_result_text"])
        self.assertEqual(self.first["candidate_pool_text"], self.second["candidate_pool_text"])
        self.assertEqual(self.first["citation_map_text"], self.second["citation_map_text"])
        self.assertEqual(self.first["json_export_text"], self.second["json_export_text"])
        self.assertEqual(len(self.first["llm_calls"]), 4)
        lanes = {call["lane"] for call in self.first["provider_calls"]}
        self.assertEqual(lanes, {"relevance", "impact", "recent"})

    def test_final_result_matches_golden(self):
        self.assertEqual(
            self.first["final_result"],
            read_json(str(FIXTURE_ROOT / "final_result.json")),
        )

    def test_candidate_pool_and_citation_provenance_match_goldens(self):
        self.assertEqual(
            self.first["candidate_pool_text"],
            read_text(str(FIXTURE_ROOT / "candidate_pool.jsonl")),
        )
        self.assertEqual(
            self.first["citation_map_text"],
            read_text(str(FIXTURE_ROOT / "citation_map.json")),
        )

    def test_current_cli_json_formatter_matches_golden(self):
        self.assertEqual(
            json.loads(self.first["json_export_text"]),
            read_json(str(FIXTURE_ROOT / "export.json")),
        )

if __name__ == "__main__":
    unittest.main()
