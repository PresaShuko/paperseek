
import re
from typing import Any

from paperseek_core.harness.schemas import ErrorObservation


RETRYABLE_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 512}


def classify_error(exc: Exception, *, stage: str, source: str = "", query: str = "") -> ErrorObservation:
    status = _status_code(exc)
    message = _redact_error_text(_error_text(exc))
    error_type = exc.__class__.__name__
    retryable = bool(status in RETRYABLE_STATUSES or (status is not None and status >= 500) or _looks_repairable_query_error(status, message))
    return ErrorObservation(
        stage=stage,
        source=source,
        query=query or str(getattr(exc, "query", "") or ""),
        error_type=error_type,
        status=status,
        message=message,
        retryable=retryable,
    )


def _looks_repairable_query_error(status: int | None, message: str) -> bool:
    if status not in (400, 422):
        return False
    lowered = (message or "").lower()
    markers = (
        "invalid query",
        "invalid query parameters",
        "syntax",
        "wildcard",
        "parse",
        "unbalanced",
        "unsupported",
        "malformed",
        "bad query",
    )
    return any(marker in lowered for marker in markers)


def _status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _error_text(exc: Exception) -> str:
    parts = [str(exc)]
    for attr in ("body", "data", "reason"):
        value: Any = getattr(exc, attr, None)
        if value:
            parts.append(str(value))
    return " ".join(part for part in parts if part)


def _redact_error_text(text: str, max_chars: int = 700) -> str:
    value = str(text or "")
    value = re.sub(r"(?i)(x-api[_-]?key|api[_-]?key|authorization)\s*[:=]\s*([^\n\r,;}]+)", r"\1: [redacted]", value)
    value = re.sub(r"(?i)bearer\s+([A-Za-z0-9._\-+/=]{8,})", "Bearer [redacted]", value)
    if len(value) > max_chars:
        value = value[:max_chars].rstrip() + "..."
    return value
