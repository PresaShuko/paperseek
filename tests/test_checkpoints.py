import json

import pytest

from paperseek.history import HistoryStore
from paperseek_core.checkpoints import (
    CheckpointError,
    paper_record_from_checkpoint,
    paper_record_to_checkpoint,
    scrub_checkpoint_value,
)
from paperseek_core.harness import (
    ActionFrontierState,
    CandidateEvidence,
    CandidateQueueState,
    CrawlerState,
    FrontierAction,
    FrontierBudget,
    SearchCheckpoint,
    SearchRunState,
)
from paperseek_core.sources.providers import (
    PaperAuthor,
    PaperCitation,
    PaperIdentifiers,
    PaperNames,
    PaperRecord,
    PaperSource,
)


def test_paper_record_checkpoint_round_trip_keeps_downstream_metadata():
    record = PaperRecord(
        uid="W123",
        title="Durable literature search",
        source=PaperSource(source_title="Test Journal", publish_year=2026),
        names=PaperNames(authors=[PaperAuthor(display_name="A. Researcher")]),
        citations=[PaperCitation(db="OpenAlex", count=42)],
        identifiers=PaperIdentifiers(doi="10.1000/example", openalex="W123"),
        abstract="A" * 9000,
        provider="openalex",
        raw={
            "request_url": "https://example.test/?api_key=secret-value",
            "large": "x" * 5000,
            "referenced_works": ["https://openalex.org/W456"],
        },
    )

    payload = paper_record_to_checkpoint(record)
    restored = paper_record_from_checkpoint(payload)

    assert payload["raw"] == {"referenced_works": ["https://openalex.org/W456"]}
    assert len(payload["abstract"]) == 8000
    assert restored.uid == record.uid
    assert restored.source.publish_year == 2026
    assert restored.names.authors[0].display_name == "A. Researcher"
    assert restored.citations[0].count == 42
    assert restored.identifiers.doi == "10.1000/example"
    assert restored.raw == {"referenced_works": ["https://openalex.org/W456"]}


def test_checkpoint_scrubbing_removes_secret_fields_and_values():
    payload = scrub_checkpoint_value(
        {
            "llm_api_key": "sk-super-secret-value",
            "nested": {
                "authorization": "Bearer abcdefghijklmnop",
                "url": "https://example.test/search?token=abcdefghi&query=paper",
            },
        }
    )
    serialized = json.dumps(payload)

    assert "super-secret" not in serialized
    assert "abcdefghijklmnop" not in serialized
    assert "abcdefghi" not in serialized
    assert payload["llm_api_key"] == "[redacted]"


def test_checkpoint_schema_rejects_missing_required_stage():
    with pytest.raises(Exception):
        SearchCheckpoint.model_validate({"question": "q", "source": "openalex"})


def test_checkpoint_record_requires_stable_uid():
    with pytest.raises(CheckpointError, match="missing uid"):
        paper_record_from_checkpoint({"title": "No identifier"})


def test_closed_loop_state_round_trip_preserves_selector_frontier_and_budget():
    state = SearchRunState(
        question="causal interventions",
        source="openalex",
        candidate_queue=CandidateQueueState(
            keys=["W1"],
            ledger={
                "W1": CandidateEvidence(
                    candidate_id="W1",
                    title="Causal Bandits",
                    selector_label="uncertain",
                    selector_relevance_score=0.65,
                    selector_concept_coverage={"causal bandits": 1.0},
                    selector_missing_concepts=["intervention selection"],
                    selector_recommended_actions=["expand_forward"],
                    selector_input_hash="selector-cache-key",
                )
            },
        ),
        action_frontier=ActionFrontierState(
            actions=[
                FrontierAction(
                    action_id="expand-W1",
                    action_type="expand_forward",
                    candidate_id="W1",
                    status="pending",
                )
            ],
            budget=FrontierBudget(
                max_source_requests=3,
                max_reader_requests=4,
                max_citation_requests=5,
                source_requests=2,
                reader_requests=1,
                citation_requests=3,
            ),
            elapsed_seconds=42.5,
        ),
        crawler_state=CrawlerState(
            concept_gaps={"intervention selection": 2},
            concept_coverage={"causal bandits": 1.0, "intervention selection": 0.3},
            selector_counts={"uncertain": 1},
        ),
    )

    restored = SearchRunState.model_validate_json(state.model_dump_json())

    evidence = restored.candidate_queue.ledger["W1"]
    assert evidence.selector_input_hash == "selector-cache-key"
    assert evidence.selector_missing_concepts == ["intervention selection"]
    assert restored.action_frontier.actions[0].status == "pending"
    assert restored.action_frontier.budget.citation_requests == 3
    assert restored.action_frontier.elapsed_seconds == 42.5
    assert restored.crawler_state.concept_coverage["causal bandits"] == 1.0


def test_history_store_persists_latest_checkpoint_and_redacts_secrets(tmp_path):
    store = HistoryStore(tmp_path / "history.db", enabled=True)
    run_id = store.create_run("durable search", {"llm_api_key": "sk-param-secret"})
    store.save_checkpoint(
        run_id,
        {
            "sequence": 1,
            "stage": "search_plan",
            "question": "durable search",
            "source": "openalex",
            "metadata": {"authorization": "Bearer checkpoint-secret"},
        },
    )
    store.save_checkpoint(
        run_id,
        {
            "sequence": 2,
            "stage": "candidate_merge",
            "question": "durable search",
            "source": "openalex",
        },
    )

    latest = store.latest_checkpoint(run_id)
    detail = store.get_run(run_id)

    assert latest["sequence"] == 2
    assert latest["stage"] == "candidate_merge"
    assert detail["resumable"] is True
    assert detail["checkpoint_count"] == 2
    assert detail["checkpoint"]["payload"]["stage"] == "candidate_merge"
    raw_db = (tmp_path / "history.db").read_bytes()
    assert b"param-secret" not in raw_db
    assert b"checkpoint-secret" not in raw_db


def test_successful_run_clears_temporary_checkpoints(tmp_path):
    store = HistoryStore(tmp_path / "history.db", enabled=True)
    run_id = store.create_run("durable search", {})
    store.save_checkpoint(
        run_id,
        {"sequence": 1, "stage": "pre_rank", "question": "durable search", "source": "openalex"},
    )
    store.complete_run(
        run_id,
        {
            "question": "durable search",
            "source": "openalex",
            "final_query": "query",
            "db": "OPENALEX",
            "field": "",
            "total": 0,
            "iterations": 1,
            "ranked": [],
        },
    )

    assert store.latest_checkpoint(run_id) is None
    assert store.get_run(run_id)["resumable"] is False
