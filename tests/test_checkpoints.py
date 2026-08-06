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
    SearchCheckpoint,
)
from paperseek_core.domain.models import (
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
