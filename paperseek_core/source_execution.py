"""Execution boundary for source-provider requests."""

import inspect
from collections.abc import Callable
from typing import Any

from paperseek_core.disciplines import discipline_source_note, openalex_field_ids
from paperseek_core.sources.contracts import ProviderError, ProviderSearchResult


class SourceRequestExecutor:
    """Invoke source adapters without leaking provider details into the agent."""

    def __init__(
        self,
        config: Any,
        data_source: str,
        discipline_fields: tuple[str, ...],
        run_cancellable: Callable[[Callable[[], Any]], Any],
    ) -> None:
        self.config = config
        self.data_source = data_source
        self.discipline_fields = discipline_fields
        self.run_cancellable = run_cancellable

    def search_lane(
        self,
        query: str,
        lane: str,
        limit: int,
        *,
        page: int = 1,
        provider: Any,
        documents_api: Any = None,
    ) -> ProviderSearchResult:
        return self.run_cancellable(
            lambda: self._search_lane_blocking(
                query,
                lane,
                limit,
                page=page,
                provider=provider,
                documents_api=documents_api,
            )
        )

    def _search_lane_blocking(
        self,
        query: str,
        lane: str,
        limit: int,
        *,
        page: int,
        provider: Any,
        documents_api: Any,
    ) -> ProviderSearchResult:
        if provider is None:
            raise ProviderError(
                self.data_source,
                "No source provider is configured.",
                query=query,
            )
        if self.data_source == "wos" and documents_api is not provider.documents_api:
            provider.documents_api = documents_api

        parameters = {
            "query": query,
            "limit": limit,
            "page": page,
            "lane": lane,
        }
        if self.data_source == "openalex":
            parameters["field_ids"] = openalex_field_ids(self.discipline_fields)
        return self.call_provider_search(provider, **parameters)

    @staticmethod
    def call_provider_search(provider: Any, **parameters: Any) -> ProviderSearchResult:
        search = provider.search
        signature = inspect.signature(search)
        if any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ):
            return search(**parameters)
        supported = {
            name: value
            for name, value in parameters.items()
            if name in signature.parameters
        }
        return search(**supported)

    def source_label(self) -> str:
        labels = {
            "wos": "WoS Starter",
            "openalex": "OpenAlex",
            "crossref": "Crossref",
            "arxiv": "arXiv",
            "semanticscholar": "Semantic Scholar",
            "pubmed": "PubMed",
            "googlescholar": "Google Scholar",
            "paperhub": "Computer science top conferences",
        }
        return labels[self.data_source]

    def request_label(self, query: str) -> str:
        discipline_note = discipline_source_note(
            self.discipline_fields,
            self.data_source,
        )
        suffix = f" ({discipline_note})" if discipline_note else ""
        if self.data_source == "wos":
            return f"GET /documents db={self.config.wos_db} q={query}{suffix}"
        if self.data_source == "openalex":
            return f"GET /works search={query}{suffix}"
        if self.data_source == "crossref":
            return f"GET /works query.bibliographic={query}{suffix}"
        if self.data_source == "arxiv":
            return f"GET /api/query search_query={query}{suffix}"
        if self.data_source == "semanticscholar":
            return f"GET /graph/v1/paper/search query={query}{suffix}"
        if self.data_source == "pubmed":
            return f"GET /entrez/eutils/esearch.fcgi term={query}{suffix}"
        if self.data_source == "googlescholar":
            return f"POST /scholar q={query}{suffix}"
        return f"GET paper-hub shards query={query}{suffix}"

    def response_log(
        self,
        result: ProviderSearchResult,
        *,
        provider: Any,
    ) -> str:
        total = result.metadata.total if result.metadata else 0
        count = len(result.hits or [])
        info = getattr(provider, "last_response_info", {}) or {}
        method = info.get("method", "GET")
        url = str(info.get("url", "")).split("?")[0] or self.source_label()
        status = info.get("status", "unknown")
        elapsed = info.get("elapsed_ms")
        elapsed_text = f" in {elapsed}ms" if elapsed is not None else ""
        attempts = info.get("attempts")
        attempts_text = f"; attempts={attempts}" if attempts else ""
        return (
            f"{self.source_label()} {method} {url} -> HTTP {status} OK"
            f"{elapsed_text}{attempts_text}; total={total}; returned={count}."
        )
