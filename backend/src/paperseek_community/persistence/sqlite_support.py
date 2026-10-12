from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from paperseek_app.models import RunStatus


TERMINAL_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.COMPLETED_WITH_WARNINGS.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
}
MAX_RECOVERY_RECLAIMS = 3
MAX_ATTEMPTS = 1 + MAX_RECOVERY_RECLAIMS
MAX_CLEANUP_ATTEMPTS = 3


def system_clock() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Run clock values must be timezone-aware.")
    return value.astimezone(timezone.utc)


def timestamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="microseconds")


def parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_load(value: str) -> Any:
    return json.loads(value)


__all__ = [
    "MAX_ATTEMPTS",
    "MAX_CLEANUP_ATTEMPTS",
    "MAX_RECOVERY_RECLAIMS",
    "TERMINAL_STATUSES",
    "json_dump",
    "json_load",
    "parse_datetime",
    "system_clock",
    "timestamp",
    "utc",
]
