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

class ArxivProvider:
    BASE_URL = "http://export.arxiv.org/api/query"
    ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    _lock = threading.Lock()
    _last_request_at = 0.0

    def __init__(self):
        self.last_response_info: Dict[str, Any] = {}

    def retrieval_capabilities(self) -> ProviderRetrievalCapabilities:
        return ProviderRetrievalCapabilities(
            source="arxiv",
            lanes=(RetrievalLane.RELEVANCE, RetrievalLane.RECENT),
            max_lane_limit=200,
        )

    def search(self, query: str, limit: int = 50, page: int = 1, lane: str = RetrievalLane.RELEVANCE) -> ProviderSearchResult:
        query = (query or "").strip()
        if not query:
            raise ProviderError("arxiv", "arXiv search query is empty.")

        page_size = max(1, min(int(limit or 10), 100))
        params = {
            "search_query": self._search_query(query),
            "start": max(0, (int(page or 1) - 1) * page_size),
            "max_results": page_size,
            "sortBy": "submittedDate" if lane == RetrievalLane.RECENT else "relevance",
            "sortOrder": "descending",
        }
        headers = {"Accept": "application/atom+xml", "User-Agent": "paperseek/1.0"}
        try:
            self._throttle()
            response, info = get_with_retries("arxiv", self.BASE_URL, params=params, headers=headers, timeout=45, query=query, attempts=3)
            self.last_response_info = info
        except ProviderError as exc:
            self.last_response_info = {"method": "GET", "url": self.BASE_URL, "status": "request_error", "elapsed_ms": None}
            raise exc

        if response.status_code >= 400:
            raise ProviderError("arxiv", f"arXiv returned HTTP {response.status_code}.", status=response.status_code, body=response.text[:1000], query=query)

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise ProviderError("arxiv", "arXiv returned invalid Atom XML.", body=response.text[:1000], query=query) from exc

        total_text = root.findtext("opensearch:totalResults", default="", namespaces={"opensearch": "http://a9.com/-/spec/opensearch/1.1/"})
        try:
            total = int((total_text or "0").strip())
        except ValueError:
            total = 0
        entries = root.findall("atom:entry", self.ATOM_NS)
        return ProviderSearchResult(
            metadata=SearchMetadata(total=total, page=max(1, int(page or 1)), limit=page_size),
            hits=[self._to_record(entry) for entry in entries],
        )

    @staticmethod
    def _search_query(query: str) -> str:
        if re.search(r"\b(?:all|ti|au|abs|cat|id|jr):", query, flags=re.I):
            return query
        cleaned = re.sub(r"\s+", " ", query).strip()
        if not cleaned:
            return "all:*"
        if re.search(r"\b(AND|OR|ANDNOT)\b", cleaned, flags=re.I):
            return cleaned
        return f'all:"{ArxivProvider._quote_phrase(cleaned)}"'

    @staticmethod
    def _quote_phrase(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @classmethod
    def _throttle(cls) -> None:
        with cls._lock:
            elapsed = time.monotonic() - cls._last_request_at
            if elapsed < 3.1:
                time.sleep(3.1 - elapsed)
            cls._last_request_at = time.monotonic()

    def _to_record(self, entry: ET.Element) -> PaperRecord:
        arxiv_url = self._text(entry, "atom:id")
        arxiv_id = arxiv_url.rstrip("/").split("/")[-1]
        title = self._clean(self._text(entry, "atom:title"))
        abstract = self._clean(self._text(entry, "atom:summary"))
        year = self._year(self._text(entry, "atom:published") or self._text(entry, "atom:updated"))
        authors = [
            PaperAuthor(display_name=self._clean(author.findtext("atom:name", default="", namespaces=self.ATOM_NS)))
            for author in entry.findall("atom:author", self.ATOM_NS)
        ]
        authors = [author for author in authors if author.display_name]
        pdf = ""
        landing_page = arxiv_url
        for link in entry.findall("atom:link", self.ATOM_NS):
            href = link.attrib.get("href") or ""
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf = href
            elif link.attrib.get("rel") == "alternate":
                landing_page = href
        doi = normalize_doi(self._text(entry, "arxiv:doi"))
        categories = []
        primary = entry.find("arxiv:primary_category", self.ATOM_NS)
        if primary is not None and primary.attrib.get("term"):
            categories.append(primary.attrib["term"])
        for category in entry.findall("atom:category", self.ATOM_NS):
            term = category.attrib.get("term")
            if term and term not in categories:
                categories.append(term)
        return PaperRecord(
            uid=f"arxiv:{arxiv_id}" if arxiv_id else arxiv_url or title,
            title=title,
            types=["preprint"],
            source_types=["preprint"],
            source=PaperSource(source_title="arXiv", publish_year=year),
            names=PaperNames(authors=authors),
            links=PaperLinks(record=landing_page, landing_page=landing_page, pdf=pdf),
            identifiers=PaperIdentifiers(doi=doi, arxiv=arxiv_id),
            keywords=PaperKeywords(author_keywords=categories),
            abstract=abstract,
            provider="arxiv",
            raw={"id": arxiv_id, "categories": categories, "url": arxiv_url},
        )

    def _text(self, entry: ET.Element, path: str) -> str:
        return entry.findtext(path, default="", namespaces=self.ATOM_NS)

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", unescape(text or "")).strip()

    @staticmethod
    def _year(value: str) -> Optional[int]:
        match = re.match(r"^(\d{4})", value or "")
        return int(match.group(1)) if match else None
