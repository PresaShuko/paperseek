"""Canonical document identity used across retrieval, citation, and ranking."""

from __future__ import annotations

import re
from typing import Any

from paperseek_core.models import PaperRecord


def _normalize_identifier(value: Any) -> str:
    text = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return re.sub(r"\s+", "", text)


def _normalize_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def document_key(document: PaperRecord) -> str:
    identifiers = document.identifiers
    for name in ("doi", "openalex", "arxiv", "semanticscholar", "pmid"):
        normalized = _normalize_identifier(
            getattr(identifiers, name, "") if identifiers else ""
        )
        if normalized:
            return f"{name}:{normalized}"
    uid = _normalize_identifier(document.uid)
    if uid:
        return f"uid:{uid}"
    title = _normalize_title(document.title)
    return f"title:{title}" if title else ""


def document_alias_keys(document: PaperRecord) -> tuple[str, ...]:
    aliases = []
    primary = document_key(document)
    if primary:
        aliases.append(primary)
    title = _normalize_title(document.title)
    if title:
        aliases.append(f"title:{title}")
    return tuple(dict.fromkeys(aliases))


def document_identity(document: PaperRecord) -> str:
    return str(document.uid or document_key(document) or "").strip()


__all__ = ["document_alias_keys", "document_identity", "document_key"]
