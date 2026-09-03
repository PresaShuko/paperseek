from __future__ import annotations

import re
from threading import Lock


def split_api_keys(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for item in re.split(r"[\s,;]+", str(value or ""))
            if item.strip()
        )
    )


def retryable_key_status(status_code: int) -> bool:
    return status_code in {401, 429} or status_code >= 500


class ApiKeyPool:
    def __init__(self, value: str) -> None:
        self.keys = split_api_keys(value)
        self._next_index = 0
        self._lock = Lock()

    @property
    def available(self) -> bool:
        return bool(self.keys)

    def attempts(self, max_attempts: int = 3) -> tuple[str, ...]:
        if not self.keys:
            return ("",)
        count = min(max(1, int(max_attempts)), len(self.keys))
        with self._lock:
            start = self._next_index
            self._next_index = (self._next_index + 1) % len(self.keys)
        return tuple(self.keys[(start + offset) % len(self.keys)] for offset in range(count))


__all__ = ["ApiKeyPool", "retryable_key_status", "split_api_keys"]
