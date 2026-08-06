import unittest

from paperseek_core.ranking import RankingBatchScheduler, RankingOutputCodec


class _Document:
    def __init__(self, uid: str = ""):
        self.uid = uid


class RankingBatchSchedulerTest(unittest.TestCase):
    def test_batch_size_uses_configured_limit_and_candidate_count(self):
        scheduler = RankingBatchScheduler(batch_size_value=64)

        self.assertEqual(scheduler.batch_size(256), 64)
        self.assertEqual(scheduler.batch_size(12), 12)

    def test_invalid_values_fall_back_to_existing_defaults(self):
        scheduler = RankingBatchScheduler(batch_size_value="invalid", concurrency_value="invalid")

        self.assertEqual(scheduler.batch_size(300), 256)
        self.assertEqual(scheduler.concurrency(), 16)

    def test_concurrency_schedule_never_drops_below_four(self):
        self.assertEqual(
            RankingBatchScheduler(concurrency_value=32).concurrency_schedule(),
            [32, 16, 8, 4],
        )
        self.assertEqual(
            RankingBatchScheduler(concurrency_value=12).concurrency_schedule(),
            [12, 8, 4],
        )
        self.assertEqual(
            RankingBatchScheduler(concurrency_value=1).concurrency_schedule(),
            [4],
        )

    def test_batch_id_is_stable_and_sensitive_to_document_order(self):
        documents = [_Document("A"), _Document("B")]
        identity = lambda document: f"fallback:{id(document)}"

        first = RankingBatchScheduler.batch_id("ranking", documents, identity)
        second = RankingBatchScheduler.batch_id("ranking", documents, identity)
        reversed_id = RankingBatchScheduler.batch_id("ranking", list(reversed(documents)), identity)

        self.assertEqual(first, second)
        self.assertNotEqual(first, reversed_id)


class RankingOutputCodecTest(unittest.TestCase):
    def setUp(self):
        self.codec = RankingOutputCodec(lambda document: document.uid)
        self.documents = [_Document("paper:A"), _Document("paper:B")]

    def test_parses_fenced_compact_scores_and_rejects_invalid_pairs(self):
        raw = '```json\n{"scores":[[1,9],[1,3],[2,"NaN"],[3,8],[2,6]]}\n```'

        self.assertEqual(
            self.codec.parse_scores(raw, self.documents),
            [
                {"uid": "paper:A", "score": 9.0, "reasoning": ""},
                {"uid": "paper:B", "score": 6.0, "reasoning": ""},
            ],
        )

    def test_parses_reasons_and_normalizes_whitespace(self):
        raw = '{"reasons":[[2,"  useful\\nreason  "],[0,"ignored"],[1,""]]}'

        self.assertEqual(self.codec.parse_reasons(raw, ["paper:A", "paper:B"]), {"paper:B": "useful reason"})

    def test_matches_exact_and_unique_partial_identities(self):
        scores = [
            {"uid": "PAPER:A", "score": 9, "reasoning": "exact"},
            {"uid": "B", "score": 7, "reasoning": "partial"},
        ]

        matched, missing = self.codec.match_scores(self.documents, scores)

        self.assertEqual([entry["uid"] for entry in matched], ["paper:A", "paper:B"])
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
