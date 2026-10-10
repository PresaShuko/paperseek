from __future__ import annotations

import re
from collections import deque
from threading import Lock


def split_api_keys(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for item in re.split(r"[\s,;]+", str(value or ""))
            if item.strip()
        )
    )


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


class RequestKeys:
    """Per-request rotation; transient failures never reject a credential."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self._keys = deque(keys)
        self.current = ""

    def next_key(self) -> str:
        self.current = self._keys[0]
        self._keys.rotate(-1)
        return self.current

    def reject_current(self) -> bool:
        self._keys.remove(self.current)
        return bool(self._keys)


__all__ = ["ApiKeyPool", "RequestKeys", "split_api_keys"]
