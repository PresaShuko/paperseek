import math
import unittest
from unittest.mock import patch

from paperseek_core.harness.native_loop import NativeQueryLoopRunner
from paperseek_core.harness.schemas import SearchRunState
from paperseek_core.sources.providers import CitationSeedPlan, OpenAlexProvider, PaperIdentifiers, PaperRecord


def record(work_id: str, references=None) -> PaperRecord:
    uid = f"https://openalex.org/{work_id}"
    return PaperRecord(
        uid=uid,
        title=work_id,
        identifiers=PaperIdentifiers(openalex=uid),
        provider="openalex",
        raw={"referenced_works": list(references or [])},
    )


class CitationFrontierTest(unittest.TestCase):
    def test_direction_budgets_prevent_backward_links_from_exhausting_pool(self):
        provider = OpenAlexProvider()
        backward_urls = [f"https://openalex.org/Wback{index}" for index in range(10)]
        seed = record("Wseed", backward_urls)
        forward = [record(f"Wforward{index}") for index in range(10)]

        with patch.object(
            provider,
            "_fetch_works",
            side_effect=lambda urls, **_: [record(url.rsplit("/", 1)[-1]) for url in urls],
        ), patch.object(
            provider,
            "_fetch_forward_citations",
            return_value=forward,
        ):
            result = provider.citation_neighbors_with_graph(
                [seed],
                per_seed=10,
                max_records=10,
                seed_plans=[CitationSeedPlan(record=seed, directions=("backward", "forward"), depth=1)],
                depth=1,
            )

        frontier = result["frontier"]
        self.assertEqual(len(result["records"]), 10)
        self.assertEqual(frontier["direction_stats"]["backward"]["budget"], math.ceil(10 * 0.7))
        self.assertEqual(frontier["direction_stats"]["backward"]["added"], 7)
        self.assertEqual(frontier["direction_stats"]["forward"]["added"], 3)
        self.assertEqual(frontier["stop_reason"], "max_records")

    def test_frontier_stops_after_repeated_empty_seed_plans(self):
        provider = OpenAlexProvider()
        seeds = [record(f"Wseed{index}") for index in range(10)]
        plans = [CitationSeedPlan(record=seed, role="recent", directions=("forward",), depth=1) for seed in seeds]

        with patch.object(provider, "_fetch_forward_citations", return_value=[]):
            result = provider.citation_neighbors_with_graph(
                seeds,
                per_seed=4,
                max_records=40,
                seed_plans=plans,
                depth=1,
            )

        frontier = result["frontier"]
        self.assertEqual(result["records"], [])
        self.assertEqual(frontier["stop_reason"], "low_yield")
        self.assertEqual(frontier["processed_items"], 6)
        self.assertEqual(frontier["skipped_items"], 4)
        self.assertEqual(frontier["request_count"], 6)

    def test_typed_loop_observation_preserves_frontier_audit(self):
        state = SearchRunState(question="graph retrieval", source="openalex")
        updated, observation = NativeQueryLoopRunner().observe_citation_traversal(
            state,
            status="complete",
            seed_count=10,
            depth=2,
            per_seed=4,
            max_records=40,
            added_candidates=12,
            candidate_pool=112,
            frontier={
                "planned_items": 10,
                "processed_items": 6,
                "skipped_items": 4,
                "request_count": 6,
                "request_budget": 40,
                "stop_reason": "low_yield",
                "direction_stats": {
                    "forward": {"budget": 28, "requests": 6, "fetched": 12, "added": 12}
                },
            },
        )

        self.assertEqual(observation.frontier.stop_reason, "low_yield")
        self.assertEqual(observation.frontier.direction_stats["forward"].added, 12)
        self.assertEqual(updated.citation_traversal_observations[-1], observation)


if __name__ == "__main__":
    unittest.main()
