from __future__ import annotations

from typing import Optional


def reconstruct_abstract(inverted_index: Optional[dict[str, list[int]]]) -> str:
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int):
                positions[index] = word
    return " ".join(positions[index] for index in sorted(positions))


def normalize_doi(value: str) -> str:
    value = str(value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.lower().startswith(prefix):
            return value[len(prefix) :].strip()
    return value
