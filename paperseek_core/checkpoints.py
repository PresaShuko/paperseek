import re
from dataclasses import asdict
from typing import Any, Iterable

from paperseek_core.domain.models import (
    PaperAuthor,
    PaperCitation,
    PaperIdentifiers,
    PaperKeywords,
    PaperLinks,
    PaperNames,
    PaperRecord,
    PaperSource,
)


CHECKPOINT_SCHEMA_VERSION = 1
_SECRET_PARTS = ("api_key", "apikey", "authorization", "access_token", "auth_token", "password", "secret")
_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+/=]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9._\-]{8,}\b", re.IGNORECASE),
    re.compile(r"\b(?:ghp|github_pat|hf|ms)-[A-Za-z0-9._\-]{12,}\b", re.IGNORECASE),
    re.compile(r"([?&](?:api_key|apikey|key|token|access_token)=)[^&\s]+", re.IGNORECASE),
)


class CheckpointError(ValueError):
    """Raised when a saved checkpoint cannot be safely restored."""


def scrub_checkpoint_value(value: Any) -> Any:
    """Return a JSON-safe copy with credential-shaped fields removed."""
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            normalized = str(key or "").casefold().replace("-", "_")
            if any(part in normalized for part in _SECRET_PARTS) or normalized.endswith("_key"):
                output[str(key)] = "[redacted]"
            else:
                output[str(key)] = scrub_checkpoint_value(item)
        return output
    if isinstance(value, (list, tuple)):
        return [scrub_checkpoint_value(item) for item in value]
    if isinstance(value, str):
        output = value
        for pattern in _SECRET_PATTERNS:
            output = pattern.sub(lambda match: f"{match.group(1)}[redacted]" if match.lastindex else "[redacted]", output)
        return output
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def paper_record_to_checkpoint(record: PaperRecord) -> dict[str, Any]:
    payload = asdict(record)
    # Provider payloads are large and may contain request diagnostics. Keep
    # only OpenAlex fields needed to resume backward citation traversal and
    # discipline validation; all other downstream fields are represented by
    # the normalized dataclass attributes above.
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    payload["raw"] = {
        key: raw[key]
        for key in ("referenced_works", "primary_topic", "topics")
        if key in raw
    }
    payload["abstract"] = str(payload.get("abstract") or "")[:8000]
    return scrub_checkpoint_value(payload)


def paper_records_to_checkpoint(records: Iterable[PaperRecord]) -> list[dict[str, Any]]:
    return [paper_record_to_checkpoint(record) for record in records or [] if isinstance(record, PaperRecord)]


def paper_record_from_checkpoint(payload: dict[str, Any]) -> PaperRecord:
    if not isinstance(payload, dict):
        raise CheckpointError("checkpoint paper record is not an object")
    uid = str(payload.get("uid") or "").strip()
    if not uid:
        raise CheckpointError("checkpoint paper record is missing uid")

    source = payload.get("source") if isinstance(payload.get("source"), dict) else None
    names = payload.get("names") if isinstance(payload.get("names"), dict) else None
    links = payload.get("links") if isinstance(payload.get("links"), dict) else None
    identifiers = payload.get("identifiers") if isinstance(payload.get("identifiers"), dict) else None
    keywords = payload.get("keywords") if isinstance(payload.get("keywords"), dict) else None

    return PaperRecord(
        uid=uid,
        title=str(payload.get("title") or ""),
        types=[str(value) for value in payload.get("types") or []],
        source_types=[str(value) for value in payload.get("source_types") or []],
        source=PaperSource(**source) if source else None,
        names=PaperNames(
            authors=[PaperAuthor(**author) for author in names.get("authors") or [] if isinstance(author, dict)]
        ) if names else None,
        links=PaperLinks(**links) if links else None,
        citations=[PaperCitation(**citation) for citation in payload.get("citations") or [] if isinstance(citation, dict)],
        identifiers=PaperIdentifiers(**identifiers) if identifiers else None,
        keywords=PaperKeywords(**keywords) if keywords else None,
        abstract=str(payload.get("abstract") or ""),
        provider=str(payload.get("provider") or ""),
        raw=scrub_checkpoint_value(payload.get("raw") or {}),
    )


def paper_records_from_checkpoint(records: Iterable[dict[str, Any]]) -> list[PaperRecord]:
    return [paper_record_from_checkpoint(record) for record in records or []]
