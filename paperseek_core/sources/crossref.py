from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import math
import re
import requests
import threading
import time
import xml.etree.ElementTree as ET

from paperseek_core.retrieval import ProviderRetrievalCapabilities, RetrievalLane
import paperseek_core.sources.providers as _shared

PaperAuthor = _shared.PaperAuthor
PaperNames = _shared.PaperNames
PaperSource = _shared.PaperSource
PaperLinks = _shared.PaperLinks
PaperCitation = _shared.PaperCitation
PaperIdentifiers = _shared.PaperIdentifiers
PaperKeywords = _shared.PaperKeywords
PaperRecord = _shared.PaperRecord
CitationSeedPlan = _shared.CitationSeedPlan
SearchMetadata = _shared.SearchMetadata
ProviderSearchResult = _shared.ProviderSearchResult
ProviderError = _shared.ProviderError
reconstruct_abstract = _shared.reconstruct_abstract
normalize_doi = _shared.normalize_doi


def get_with_retries(*args, **kwargs):
    return _shared.get_with_retries(*args, **kwargs)


def _split_api_keys(value: str) -> List[str]:
    return _shared._split_api_keys(value)


def _retry_delay(response: requests.Response, attempt: int, source: str = "") -> float:
    return _shared._retry_delay(response, attempt, source)

class CrossrefProvider:
    BASE_URL = "https://api.crossref.org/works"

    def __init__(self, email: str = ""):
        self.email = (email or "").strip()
        self.last_response_info: Dict[str, Any] = {}

    def retrieval_capabilities(self) -> ProviderRetrievalCapabilities:
        return ProviderRetrievalCapabilities(
            source="crossref",
            lanes=(RetrievalLane.RELEVANCE, RetrievalLane.IMPACT, RetrievalLane.RECENT),
            lane_concurrency=2,
        )

    def search(self, query: str, limit: int = 50, page: int = 1, lane: str = RetrievalLane.RELEVANCE) -> ProviderSearchResult:
        query = (query or "").strip()
        if not query:
            raise ProviderError("crossref", "Crossref search query is empty.")

        page_size = max(1, min(int(limit or 10), 100))
        params = {
            "query.bibliographic": query,
            "rows": page_size,
            "offset": max(0, (int(page or 1) - 1) * page_size),
            "order": "desc",
            "select": ",".join([
                "DOI",
                "title",
                "author",
                "published-print",
                "published-online",
                "issued",
                "container-title",
                "type",
                "is-referenced-by-count",
                "URL",
                "abstract",
                "ISSN",
                "ISBN",
            ]),
        }
        if lane == RetrievalLane.IMPACT:
            params["sort"] = "is-referenced-by-count"
        elif lane == RetrievalLane.RECENT:
            params["sort"] = "published"
        if self.email:
            params["mailto"] = self.email

        headers = {
            "Accept": "application/json",
            "User-Agent": self._user_agent(),
        }

        try:
            response, info = get_with_retries("crossref", self.BASE_URL, params=params, headers=headers, timeout=45, query=query)
            self.last_response_info = info
        except ProviderError as exc:
            self.last_response_info = {"method": "GET", "url": self.BASE_URL, "status": "request_error", "elapsed_ms": None}
            raise exc


        if response.status_code >= 400:
            raise ProviderError(
                "crossref",
                f"Crossref returned HTTP {response.status_code}.",
                status=response.status_code,
                body=response.text[:1000],
                query=query,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("crossref", "Crossref returned a non-JSON response.", body=response.text[:1000], query=query) from exc

        message = payload.get("message") or {}
        items = message.get("items") or []
        records = [self._to_record(item) for item in items if isinstance(item, dict)]

        return ProviderSearchResult(
            metadata=SearchMetadata(
                total=int(message.get("total-results") or 0),
                page=max(1, int(page or 1)),
                limit=page_size,
            ),
            hits=records,
        )

    def _user_agent(self) -> str:
        if self.email:
            return f"paperseek/1.0 (mailto:{self.email})"
        return "paperseek/1.0"

    def _to_record(self, item: Dict[str, Any]) -> PaperRecord:
        doi = normalize_doi(item.get("DOI") or "")
        title = self._first(item.get("title")) or doi
        authors = []
        for author in item.get("author") or []:
            parts = [author.get("given") or "", author.get("family") or ""]
            name = " ".join(p for p in parts if p).strip()
            if not name:
                name = author.get("name") or ""
            if name:
                authors.append(PaperAuthor(display_name=name, wos_standard=name))

        source_title = self._first(item.get("container-title"))
        year = self._extract_year(item)
        work_type = item.get("type") or ""
        abstract = self._clean_xml(item.get("abstract") or "")
        url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")

        issn = self._first(item.get("ISSN"))
        isbn = self._first(item.get("ISBN"))
        cited_by_count = int(item.get("is-referenced-by-count") or 0)

        return PaperRecord(
            uid=f"DOI:{doi}" if doi else url or title,
            title=title,
            types=[work_type] if work_type else [],
            source_types=[work_type] if work_type else [],
            source=PaperSource(source_title=source_title, publish_year=year),
            names=PaperNames(authors=authors),
            links=PaperLinks(record=url, landing_page=url),
            citations=[PaperCitation(db="Crossref", count=cited_by_count)] if cited_by_count else [],
            identifiers=PaperIdentifiers(doi=doi, issn=issn, isbn=isbn),
            keywords=PaperKeywords(author_keywords=[]),
            abstract=abstract,
            provider="crossref",
            raw=item,
        )

    @staticmethod
    def _first(value: Any) -> str:
        if isinstance(value, list) and value:
            return str(value[0] or "")
        if value:
            return str(value)
        return ""

    @staticmethod
    def _extract_year(item: Dict[str, Any]) -> Optional[int]:
        for key in ("published-print", "published-online", "issued"):
            date_parts = ((item.get(key) or {}).get("date-parts") or [])
            if date_parts and date_parts[0]:
                try:
                    return int(date_parts[0][0])
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _clean_xml(text: str) -> str:
        if not text:
            return ""
        import re

        text = re.sub(r"<[^>]+>", "", text)
        text = (
            text.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        return re.sub(r"\s+", " ", text).strip()
