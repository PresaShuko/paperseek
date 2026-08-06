from typing import Dict, List, Optional


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    if not inverted_index:
        return ""

    positions: Dict[int, str] = {}
    for word, indexes in inverted_index.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int):
                positions[index] = word

    return " ".join(positions[index] for index in sorted(positions))


def normalize_doi(value: str) -> str:
    value = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.lower().startswith(prefix):
            return value[len(prefix) :].strip()
    return value
