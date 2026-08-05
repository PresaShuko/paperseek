import json
import re
from threading import Event

import pytest

from paperseek.config import AgentConfig
from paperseek_core.agent import PaperSeekAgent, SearchCancelled
from paperseek_core.harness import QueryLoopDecision, SearchCheckpoint, SearchRunState
from paperseek_core.planning import ConceptGroup, QueryView, SearchPlan
from paperseek_core.retrieval import document_key
from paperseek_core.sources.providers import PaperRecord, ProviderSearchResult, SearchMetadata


class RankingLLM:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, temperature=0.3):
        text = messages[-1]["content"]
        reason_indexes = [int(value) for value in re.findall(r"^(\d+)\. Score:", text, re.MULTILINE)]
        if reason_indexes:
            return json.dumps({"reasons": [[index, "relevant"] for index in reason_indexes]})
        self.calls += 1
        indexes = [int(value) for value in re.findall(r"^(\d+)\.$", text, re.MULTILINE)]
        return json.dumps({"scores": [[index, 8] for index in indexes]})

    def fork(self):
        return self


class CheckpointAgent(PaperSeekAgent):
    def __init__(self, config, llm):
        super().__init__(config, llm)
        self.retrieve_calls = 0

    def _analyze_intent(self, question):
        self.search_plan = SearchPlan(
            intent=question,
            core_concepts=["durable search"],
            query_views=[
                QueryView(
                    view_id="direct",
                    view_type="direct_terminology",
                    concept_groups=[ConceptGroup(label="topic", terms=["durable search"])],
                )
            ],
        )
        return "intent: durable literature search"

    def _generate_query(self, question):
        return '"durable search"'

    def _harness_source_search(self, query):
        records = [PaperRecord(uid="W1", title="First"), PaperRecord(uid="W2", title="Second")]
        return ProviderSearchResult(SearchMetadata(total=2, page=1, limit=2), records), None

    def _query_loop_decision(self, query, hits, total, iteration, configured_iterations, adaptive_max_iterations, history):
        self._set_search_state_query(query)
        return QueryLoopDecision(action="accept", message="accepted", terminal=True, reason="fixture")

    def _retrieve_candidates(self, question, query, primary_hits):
        self.retrieve_calls += 1
        return list(primary_hits)


def checkpoint_config() -> AgentConfig:
    config = AgentConfig(
        data_source="crossref",
        llm_provider="custom",
        llm_api_type="openai_chat",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_base_url="https://example.test/v1",
        target_min=1,
        target_max=10,
        max_iterations=2,
        expand_citations=False,
        query_portfolio_enabled=False,
        ranking_batch_size=1,
        ranking_concurrency=4,
    )
    return config


def test_candidate_merge_checkpoint_resume_skips_retrieval():
    cancel = Event()
    snapshots = []
    first_llm = RankingLLM()
    first_agent = CheckpointAgent(checkpoint_config(), first_llm)

    def save(checkpoint):
        snapshots.append(checkpoint)
        if checkpoint["stage"] == "candidate_merge":
            cancel.set()

    with pytest.raises(SearchCancelled):
        first_agent.search(
            "durable search",
            cancel_check=cancel.is_set,
            checkpoint_handler=save,
        )

    candidate_checkpoint = next(item for item in reversed(snapshots) if item["stage"] == "candidate_merge")
    resumed_agent = CheckpointAgent(checkpoint_config(), RankingLLM())
    result = resumed_agent.search("durable search", resume_checkpoint=candidate_checkpoint)

    assert resumed_agent.retrieve_calls == 0
    assert [entry["document"].uid for entry in result["ranked"]] == ["W1", "W2"]


def test_ranking_batch_checkpoint_resume_only_scores_unfinished_batches():
    cancel = Event()
    snapshots = []
    first_llm = RankingLLM()
    first_agent = CheckpointAgent(checkpoint_config(), first_llm)

    def save(checkpoint):
        snapshots.append(checkpoint)
        if checkpoint["stage"] == "ranking_batch":
            cancel.set()

    with pytest.raises(SearchCancelled):
        first_agent.search(
            "durable search",
            cancel_check=cancel.is_set,
            checkpoint_handler=save,
        )

    ranking_checkpoint = next(item for item in reversed(snapshots) if item["stage"] == "ranking_batch")
    assert len(ranking_checkpoint["completed_batch_ids"]) == 1

    resumed_llm = RankingLLM()
    resumed_agent = CheckpointAgent(checkpoint_config(), resumed_llm)
    result = resumed_agent.search("durable search", resume_checkpoint=ranking_checkpoint)

    assert resumed_agent.retrieve_calls == 0
    assert resumed_llm.calls == 1
    assert {entry["document"].uid for entry in result["ranked"]} == {"W1", "W2"}


def test_resume_rejects_question_or_source_mismatch():
    checkpoint = {
        "stage": "search_plan",
        "question": "original",
        "source": "crossref",
    }
    agent = CheckpointAgent(checkpoint_config(), RankingLLM())
    with pytest.raises(ValueError, match="question does not match"):
        agent.search("different", resume_checkpoint=checkpoint)


def test_query_iteration_memory_survives_checkpoint_round_trip():
    snapshots = []
    agent = CheckpointAgent(checkpoint_config(), RankingLLM())
    agent.run_question = "durable search"
    agent.search_run_state = SearchRunState(
        question="durable search",
        source="crossref",
        current_query='"durable search"',
    )
    agent.checkpoint_handler = snapshots.append
    agent._record_query_iteration(
        1,
        '"durable search"',
        20,
        [PaperRecord(uid="W1", title="Remembered iteration result")],
    )

    agent._save_checkpoint("query_execution", metadata={"phase": "next_query"})

    checkpoint = SearchCheckpoint.model_validate(snapshots[-1])
    restored = CheckpointAgent(checkpoint_config(), RankingLLM())
    restored._restore_checkpoint_state(checkpoint)
    assert restored._query_iteration_memory_payload() == [
        {
            "iteration": 1,
            "query": '"durable search"',
            "total": 20,
            "candidate_count": 1,
        }
    ]
    assert restored.query_iteration_results[0]["records"][0].uid == "W1"


def test_prior_query_iterations_join_fusion_without_repeating_final_query():
    agent = PaperSeekAgent(checkpoint_config(), RankingLLM())
    prior = PaperRecord(uid="W-prior", title="Prior query evidence")
    final = PaperRecord(uid="W-final", title="Final query evidence")
    agent._record_query_iteration(1, "broad query", 100, [prior])
    agent._record_query_iteration(2, "final query", 1, [final])
    agent._collect_retrieval_lane = lambda query, lane, limit: [final]

    documents = agent._retrieve_candidates("prior evidence", "final query", [final])

    assert {document.uid for document in documents} == {"W-prior", "W-final"}
    prior_metadata = agent.retrieval_metadata_by_key[document_key(prior)]
    assert "query_iteration:1" in prior_metadata["retrieval_lanes"]
    assert "query_iteration:2" not in {
        lane
        for metadata in agent.retrieval_metadata_by_key.values()
        for lane in metadata["retrieval_lanes"]
    }
