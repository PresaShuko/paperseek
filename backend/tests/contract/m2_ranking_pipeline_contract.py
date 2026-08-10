from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import unittest

from paperseek_core.models import PaperRecord
from paperseek_core.ports import LLMPort
from paperseek_core.ranking import (
    EmptyRankingBatchError,
    RankingBatchScheduler,
    RankingOutputCodec,
    RankingPipeline,
    RankingRequest,
    RankingScorer,
    SYSTEM_RESULT_RANKING,
)


ROOT = Path(__file__).resolve().parents[3]
M0_FIXTURES = ROOT / "tests" / "fixtures"
QUESTION = "How do transparent AI decision systems affect accountability in public agencies?"
RANKING_PROMPT_SHA256 = "BBD312897894056E8A3BF7C4BA3BA76E7333F169CDB615E67EF4C52CEC03C7FA"


def read_fixture(path: str) -> str:
    return (M0_FIXTURES / path).read_text(encoding="utf-8")


def documents() -> list[PaperRecord]:
    return [
        PaperRecord(
            uid="fixture:accountability",
            title="Accountable Automated Decisions in Public Agencies",
            abstract="A controlled study of accountability mechanisms for automated public decisions.",
            provider="arxiv",
        ),
        PaperRecord(
            uid="fixture:audit",
            title="Auditing Public-Sector Algorithms",
            abstract="A governance framework for auditing algorithms used by public institutions.",
            provider="arxiv",
        ),
        PaperRecord(
            uid="fixture:transparency",
            title="Transparency Practices for Decision Support",
            abstract="A general survey of transparency practices for decision-support systems.",
            provider="arxiv",
        ),
    ]


class FixtureLLM:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat_json(self, messages, *, temperature=0.0, max_tokens=4096) -> str:
        if not self.responses:
            raise AssertionError("fixture response sequence was exhausted")
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.responses.pop(0)


class RecordingObserver:
    def __init__(self) -> None:
        self.events = []
        self.checkpoints = []

    def on_event(self, event) -> None:
        self.events.append(event)

    def on_checkpoint(self, checkpoint) -> None:
        self.checkpoints.append(checkpoint)


class GeneratedBatchLLM:
    def __init__(self) -> None:
        self.score_calls = 0
        self.reason_calls = 0

    async def chat_json(self, messages, *, temperature=0.0, max_tokens=4096) -> str:
        prompt = messages[-1]["content"]
        if "integer-indexed papers" in messages[0]["content"]:
            self.score_calls += 1
            entries = []
            for block in prompt.split("\n\n"):
                index_match = re.search(r"^(\d+)\.$", block, re.MULTILINE)
                title_match = re.search(r"^\s*Title: Batch Paper (\d+)$", block, re.MULTILINE)
                if index_match and title_match:
                    entries.append([int(index_match.group(1)), int(title_match.group(1))])
            await asyncio.sleep(0)
            return json.dumps({"scores": entries})
        self.reason_calls += 1
        indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", prompt, re.MULTILINE)]
        return json.dumps({"reasons": [[index, f"reason-{index}"] for index in indexes]})


class FailingLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_json(self, messages, *, temperature=0.0, max_tokens=4096) -> str:
        del messages, temperature, max_tokens
        self.calls += 1
        raise RuntimeError("LLM API error (429): too many requests")


class RateLimitOnceLLM(GeneratedBatchLLM):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    async def chat_json(self, messages, *, temperature=0.0, max_tokens=4096) -> str:
        prompt = messages[-1]["content"]
        if "integer-indexed papers" in messages[0]["content"] and "Title: Batch Paper 1" in prompt:
            self.score_calls += 1
            if not self.failed:
                self.failed = True
                raise RuntimeError("LLM API error (429): too many requests")
        else:
            return await super().chat_json(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        entries = []
        for block in prompt.split("\n\n"):
            index_match = re.search(r"^(\d+)\.$", block, re.MULTILINE)
            title_match = re.search(r"^\s*Title: Batch Paper (\d+)$", block, re.MULTILINE)
            if index_match and title_match:
                entries.append([int(index_match.group(1)), int(title_match.group(1))])
        return json.dumps({"scores": entries})


class M2RankingPipelineContractTest(unittest.TestCase):
    def test_m0_prompt_codec_scores_and_reasons_are_exact(self) -> None:
        self.assertEqual(
            hashlib.sha256(SYSTEM_RESULT_RANKING.encode("utf-8")).hexdigest().upper(),
            RANKING_PROMPT_SHA256,
        )
        codec = RankingOutputCodec()
        records = documents()
        scores = codec.parse_scores(read_fixture("llm/ranking_scores.json"), records)
        reasons = codec.parse_reasons(
            read_fixture("llm/ranking_reasons.json"),
            [record.uid for record in records],
        )

        self.assertEqual(
            scores,
            [
                {"uid": "fixture:accountability", "score": 9.0, "reasoning": ""},
                {"uid": "fixture:audit", "score": 6.0, "reasoning": ""},
                {"uid": "fixture:transparency", "score": 3.0, "reasoning": ""},
            ],
        )
        self.assertEqual(
            reasons,
            {
                "fixture:accountability": "Directly addresses accountable AI use in public agencies.",
                "fixture:audit": "Provides relevant governance mechanisms but less direct outcome evidence.",
                "fixture:transparency": "Offers adjacent transparency context with weaker accountability focus.",
            },
        )

    def test_scorer_preserves_structured_calls_and_limited_repair(self) -> None:
        llm = FixtureLLM(
            read_fixture("llm/ranking_scores.json"),
            read_fixture("llm/ranking_reasons.json"),
        )
        scorer = RankingScorer(llm)

        scores = asyncio.run(scorer.score_batch(QUESTION, documents(), "{}"))
        scores = asyncio.run(scorer.attach_reasons(QUESTION, documents(), scores, "{}"))

        self.assertIsInstance(llm, LLMPort)
        self.assertEqual([entry["score"] for entry in scores], [9.0, 6.0, 3.0])
        self.assertEqual(
            [entry["reasoning"] for entry in scores],
            [
                "Directly addresses accountable AI use in public agencies.",
                "Provides relevant governance mechanisms but less direct outcome evidence.",
                "Offers adjacent transparency context with weaker accountability focus.",
            ],
        )
        self.assertEqual([call["max_tokens"] for call in llm.calls], [4096, 2048])
        self.assertTrue(all(call["temperature"] == 0.0 for call in llm.calls))

        invalid = read_fixture("llm/query_invalid.txt")
        failing = FixtureLLM(invalid, invalid)
        with self.assertRaisesRegex(EmptyRankingBatchError, "omitted 3/3 candidate"):
            asyncio.run(RankingScorer(failing).score_batch(QUESTION, documents(), "{}"))
        self.assertEqual(len(failing.calls), 2)

    def test_invalid_reason_output_keeps_scores_without_inventing_reasons(self) -> None:
        llm = FixtureLLM(read_fixture("llm/query_invalid.txt"))
        scores = [
            {"uid": record.uid, "score": score, "reasoning": "stale"}
            for record, score in zip(documents(), (9.0, 6.0, 3.0))
        ]

        output = asyncio.run(RankingScorer(llm).attach_reasons(QUESTION, documents(), scores, "{}"))

        self.assertTrue(all(item["reasoning"] == "" for item in output))
        self.assertEqual(len(llm.calls), 1)

    def test_pipeline_makes_missing_reasons_visible_without_inventing_text(self) -> None:
        llm = FixtureLLM(
            read_fixture("llm/ranking_scores.json"),
            read_fixture("llm/query_invalid.txt"),
        )
        observer = RecordingObserver()

        result = asyncio.run(
            RankingPipeline(llm, observer).run(
                RankingRequest(question=QUESTION, documents=documents())
            )
        )

        self.assertEqual([item.score for item in result.items], [9.0, 6.0, 3.0])
        self.assertTrue(all(item.reasoning == "" for item in result.items))
        self.assertEqual(result.warnings, ["ranking_reasons_missing"])
        degraded = [event for event in observer.events if event.event_type == "ranking.degraded"]
        self.assertEqual(degraded[-1].payload["code"], "ranking_reasons_missing")
        self.assertEqual(degraded[-1].payload["missing_reason_count"], 3)

    def test_pipeline_sorts_and_preserves_provenance_with_batch_checkpoints(self) -> None:
        records = [
            PaperRecord(uid=f"W{index}", title=f"Batch Paper {index}", provider="fixture")
            for index in range(1, 5)
        ]
        llm = GeneratedBatchLLM()
        observer = RecordingObserver()
        request = RankingRequest(
            question="batch ranking",
            documents=records,
            batch_size=2,
            concurrency=4,
            provenance_by_identity={
                record.uid: {"origins": ["retrieval"], "retrieval_score": index / 10}
                for index, record in enumerate(records, 1)
            },
        )

        result = asyncio.run(RankingPipeline(llm, observer).run(request))

        self.assertEqual([item.document.uid for item in result.items], ["W4", "W3", "W2", "W1"])
        self.assertEqual([item.score for item in result.items], [4.0, 3.0, 2.0, 1.0])
        self.assertEqual(result.items[0].provenance["retrieval_score"], 0.4)
        self.assertEqual(llm.score_calls, 2)
        self.assertEqual(llm.reason_calls, 1)
        self.assertEqual(len(observer.checkpoints), 2)
        self.assertEqual(len(result.completed_batch_ids), 2)
        self.assertEqual(observer.events[0].event_type, "ranking.started")
        self.assertEqual(observer.events[-1].event_type, "ranking.completed")
        self.assertEqual(result.warnings, [])

    def test_rate_limit_retries_failed_batch_at_lower_concurrency(self) -> None:
        records = [
            PaperRecord(uid=f"W{index}", title=f"Batch Paper {index}", provider="fixture")
            for index in range(1, 5)
        ]
        llm = RateLimitOnceLLM()
        observer = RecordingObserver()

        result = asyncio.run(
            RankingPipeline(llm, observer).run(
                RankingRequest(
                    question="batch ranking",
                    documents=records,
                    batch_size=2,
                    concurrency=8,
                )
            )
        )

        self.assertTrue(llm.failed)
        self.assertEqual(llm.score_calls, 3)
        self.assertEqual([item.document.uid for item in result.items], ["W4", "W3", "W2", "W1"])
        self.assertEqual(result.warnings, [])
        failed = [event for event in observer.events if event.event_type == "ranking.batch_failed"]
        self.assertEqual(len(failed), 1)
        self.assertTrue(failed[0].payload["rate_limited"])
        self.assertEqual(failed[0].payload["concurrency"], 8)
        self.assertEqual(len(observer.checkpoints), 2)

    def test_completed_batch_resumes_without_rescoring_and_checkpoints_only_new_work(self) -> None:
        records = [
            PaperRecord(uid=f"W{index}", title=f"Batch Paper {index}", provider="fixture")
            for index in range(1, 5)
        ]
        first_batch_id = RankingBatchScheduler.batch_id("llm_reranking", records[:2])
        llm = GeneratedBatchLLM()
        observer = RecordingObserver()

        result = asyncio.run(
            RankingPipeline(llm, observer).run(
                RankingRequest(
                    question="batch ranking",
                    documents=records,
                    batch_size=2,
                    concurrency=4,
                    resume_scores=[
                        {"uid": "W1", "score": 1, "reasoning": ""},
                        {"uid": "W2", "score": 2, "reasoning": ""},
                    ],
                    completed_batch_ids=[first_batch_id],
                )
            )
        )

        self.assertEqual(llm.score_calls, 1)
        self.assertEqual(llm.reason_calls, 1)
        self.assertEqual([item.document.uid for item in result.items], ["W4", "W3", "W2", "W1"])
        self.assertEqual(len(result.completed_batch_ids), 2)
        self.assertEqual(len(observer.checkpoints), 1)
        self.assertNotEqual(observer.checkpoints[0].idempotency_key, first_batch_id)

    def test_pipeline_matches_golden_search_ranking_and_candidate_provenance(self) -> None:
        golden = json.loads(read_fixture("golden_search/final_result.json"))
        expected = golden["ranked"]
        records = [
            PaperRecord(
                uid=item["uid"],
                title=item["title"],
                abstract=item["abstract"],
                provider=item["provider"],
            )
            for item in expected
        ]
        candidate_rows = [
            json.loads(line)
            for line in read_fixture("golden_search/candidate_pool.jsonl").splitlines()
            if line and json.loads(line).get("record_type") == "candidate"
        ]
        provenance = {
            row["openalex"]: {
                "candidate_id": row["candidate_id"],
                "origins": row["origins"],
                "retrieval_score": row["retrieval_score"],
                "lifecycle": row["lifecycle"],
            }
            for row in candidate_rows
        }
        llm = FixtureLLM(
            read_fixture("golden_search/llm_ranking_scores.json"),
            read_fixture("golden_search/llm_ranking_reasons.json"),
        )
        observer = RecordingObserver()

        result = asyncio.run(
            RankingPipeline(llm, observer).run(
                RankingRequest(
                    question=QUESTION,
                    documents=records,
                    provenance_by_identity=provenance,
                )
            )
        )

        self.assertEqual([item.document.uid for item in result.items], [item["uid"] for item in expected])
        self.assertEqual([item.score for item in result.items], [item["score"] for item in expected])
        self.assertEqual([item.reasoning for item in result.items], [item["reasoning"] for item in expected])
        self.assertEqual(
            [item.provenance["candidate_id"] for item in result.items],
            [
                "doi:10.5555/fixture.1001",
                "doi:10.5555/fixture.1003",
                "doi:10.5555/fixture.1002",
                "doi:10.5555/fixture.1004",
                "doi:10.5555/fixture.1005",
            ],
        )
        self.assertTrue(all(item.provenance["lifecycle"] for item in result.items))
        self.assertEqual(len(observer.checkpoints), 1)

    def test_failure_is_visible_and_falls_back_to_local_order(self) -> None:
        llm = FailingLLM()
        observer = RecordingObserver()

        result = asyncio.run(
            RankingPipeline(llm, observer).run(
                RankingRequest(question=QUESTION, documents=documents(), batch_size=256, concurrency=4)
            )
        )

        self.assertEqual([item.document.uid for item in result.items], [record.uid for record in documents()])
        self.assertTrue(all(item.score == 0 for item in result.items))
        self.assertEqual(result.warnings, ["ranking_failed_local_order_retained"])
        self.assertIn("ranking.degraded", [event.event_type for event in observer.events])
        self.assertEqual(observer.checkpoints, [])
        self.assertEqual(llm.calls, 1)

    def test_empty_input_is_deterministic_and_does_not_call_llm(self) -> None:
        llm = FailingLLM()
        observer = RecordingObserver()

        result = asyncio.run(
            RankingPipeline(llm, observer).run(RankingRequest(question=QUESTION, documents=[]))
        )

        self.assertEqual(result.items, [])
        self.assertEqual(result.scores, [])
        self.assertEqual(result.completed_batch_ids, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(llm.calls, 0)
        self.assertEqual(observer.events, [])

    def test_scheduler_and_codec_keep_existing_defaults_and_matching(self) -> None:
        scheduler = RankingBatchScheduler(batch_size_value="invalid", concurrency_value="invalid")
        self.assertEqual(scheduler.batch_size(300), 256)
        self.assertEqual(scheduler.concurrency_schedule(), [16, 8, 4])
        self.assertEqual(RankingBatchScheduler(concurrency_value=1).concurrency_schedule(), [4])

        codec = RankingOutputCodec()
        records = documents()[:2]
        parsed = codec.parse_scores(
            '```json\n{"scores":[[1,9],[1,3],[2,"NaN"],[3,8],[2,6]]}\n```',
            records,
        )
        matched, missing = codec.match_scores(
            records,
            [
                {"uid": "FIXTURE:ACCOUNTABILITY", "score": 9, "reasoning": "exact"},
                {"uid": "audit", "score": 7, "reasoning": "partial"},
            ],
        )
        self.assertEqual([entry["score"] for entry in parsed], [9.0, 6.0])
        self.assertEqual([entry["uid"] for entry in matched], [record.uid for record in records])
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
