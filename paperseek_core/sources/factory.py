"""Construct the configured scholarly source adapter."""

from __future__ import annotations

from typing import Any, Callable, Optional

from paperseek_core.sources.providers import (
    ArxivProvider,
    CrossrefProvider,
    GoogleScholarSerperProvider,
    OpenAlexProvider,
    PaperHubProvider,
    PubMedProvider,
    SemanticScholarProvider,
    WosProvider,
)


def create_source_provider(
    config: Any,
    data_source: str,
    *,
    log: Optional[Callable[[str], None]] = None,
):
    source = str(data_source or "").strip().lower()
    if source == "openalex":
        return OpenAlexProvider(
            api_key=getattr(config, "openalex_api_key", ""),
            email=getattr(config, "openalex_email", ""),
        )
    if source == "crossref":
        return CrossrefProvider(email=getattr(config, "crossref_email", ""))
    if source == "arxiv":
        return ArxivProvider()
    if source == "semanticscholar":
        return SemanticScholarProvider(api_key=getattr(config, "semantic_scholar_api_key", ""))
    if source == "pubmed":
        return PubMedProvider(
            api_key=getattr(config, "pubmed_api_key", ""),
            email=getattr(config, "pubmed_email", ""),
            tool=getattr(config, "pubmed_tool", "paperseek"),
        )
    if source == "googlescholar":
        return GoogleScholarSerperProvider(api_key=getattr(config, "serper_api_key", ""))
    if source == "paperhub":
        return PaperHubProvider()
    if source == "wos":
        return WosProvider(
            api_key=getattr(config, "wos_api_key", ""),
            db=getattr(config, "wos_db", "WOS"),
            log=log,
        )
    raise ValueError(f"Unsupported data source: {data_source!r}")
