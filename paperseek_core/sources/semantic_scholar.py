from __future__ import annotations

from typing import Any, Dict
import threading
import time

from paperseek_core.domain.models import (
    PaperAuthor,
    PaperCitation,
    PaperIdentifiers,
    PaperKeywords,
    PaperLinks,
    PaperNames,
    PaperRecord,
    PaperSource,
)
from paperseek_core.retrieval import ProviderRetrievalCapabilities, RetrievalLane
from paperseek_core.sources.contracts import ProviderError, ProviderSearchResult, SearchMetadata
from paperseek_core.sources.http import get_with_retries
from paperseek_core.sources.normalization import normalize_doi

class SemanticScholarProvider:
    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
    BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
    _lock = threading.Lock()
    _last_request_at = 0.0
    _minimum_request_interval = 1.2
    FULL_FIELDS = (
        "paperId",
        "corpusId",
        "title",
        "abstract",
        "year",
        "publicationDate",
        "venue",
        "publicationVenue",
        "publicationTypes",
        "authors",
        "url",
        "externalIds",
        "citationCount",
        "fieldsOfStudy",
        "openAccessPdf",
    )
    FALLBACK_FIELDS = (
        "paperId",
        "corpusId",
        "title",
        "year",
        "publicationDate",
        "venue",
        "authors",
        "url",
        "externalIds",
        "citationCount",
    )

    def __init__(self, api_key: str = ""):
        self.api_key = (api_key or "").strip()
        self.last_response_info: Dict[str, Any] = {}

    def retrieval_capabilities(self) -> ProviderRetrievalCapabilities:
        return ProviderRetrievalCapabilities(
            source="semanticscholar",
            lanes=(RetrievalLane.RELEVANCE, RetrievalLane.IMPACT, RetrievalLane.RECENT),
        )

    def search(self, query: str, limit: int = 50, page: int = 1, lane: str = RetrievalLane.RELEVANCE) -> ProviderSearchResult:
        query = (query or "").strip()
        if not query:
            raise ProviderError("semanticscholar", "Semantic Scholar search query is empty.")

        if lane in (RetrievalLane.IMPACT, RetrievalLane.RECENT):
            return self._bulk_search(query, limit=limit, lane=lane)

        page_size = max(1, min(int(limit or 10), 100))
        params = {
            "query": query,
            "limit": page_size,
            "offset": max(0, (int(page or 1) - 1) * page_size),
            "fields": ",".join(self.FULL_FIELDS),
        }
        headers = {"Accept": "application/json", "User-Agent": "paperseek/1.0"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            self._throttle()
            response, info = get_with_retries("semanticscholar", self.BASE_URL, params=params, headers=headers, timeout=45, query=query)
            self.last_response_info = info
        except ProviderError as exc:
            self.last_response_info = {"method": "GET", "url": self.BASE_URL, "status": "request_error", "elapsed_ms": None}
            raise exc
        if response.status_code >= 500:
            fallback_params = dict(params)
            fallback_params["fields"] = ",".join(self.FALLBACK_FIELDS)
            self._throttle()
            response, fallback_info = get_with_retries(
                "semanticscholar",
                self.BASE_URL,
                params=fallback_params,
                headers=headers,
                timeout=45,
                query=query,
            )
            fallback_info["fallback"] = "basic_fields"
            self.last_response_info = fallback_info

        if response.status_code >= 400:
            raise ProviderError(
                "semanticscholar",
                f"Semantic Scholar returned HTTP {response.status_code}.",
                status=response.status_code,
                body=response.text[:1000],
                query=query,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("semanticscholar", "Semantic Scholar returned a non-JSON response.", body=response.text[:1000], query=query) from exc
        papers = payload.get("data") or []
        records = [self._to_record(item) for item in papers if isinstance(item, dict)]
        return ProviderSearchResult(
            metadata=SearchMetadata(total=int(payload.get("total") or len(records)), page=max(1, int(page or 1)), limit=page_size),
            hits=records,
        )

    def _bulk_search(self, query: str, limit: int = 50, lane: str = RetrievalLane.IMPACT) -> ProviderSearchResult:
        page_size = max(1, min(int(limit or 10), 1000))
        params = {
            "query": query,
            "limit": page_size,
            "fields": ",".join(self.FULL_FIELDS),
            "sort": "publicationDate:desc" if lane == RetrievalLane.RECENT else "citationCount:desc",
        }
        headers = {"Accept": "application/json", "User-Agent": "paperseek/1.0"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            self._throttle()
            response, info = get_with_retries("semanticscholar", self.BULK_URL, params=params, headers=headers, timeout=45, query=query)
            self.last_response_info = info
        except ProviderError as exc:
            self.last_response_info = {"method": "GET", "url": self.BULK_URL, "status": "request_error", "elapsed_ms": None}
            raise exc
        if response.status_code >= 500:
            fallback_params = dict(params)
            fallback_params["fields"] = ",".join(self.FALLBACK_FIELDS)
            self._throttle()
            response, fallback_info = get_with_retries(
                "semanticscholar",
                self.BULK_URL,
                params=fallback_params,
                headers=headers,
                timeout=45,
                query=query,
            )
            fallback_info["fallback"] = "basic_fields"
            self.last_response_info = fallback_info
        if response.status_code >= 400:
            raise ProviderError(
                "semanticscholar",
                f"Semantic Scholar returned HTTP {response.status_code}.",
                status=response.status_code,
                body=response.text[:1000],
                query=query,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("semanticscholar", "Semantic Scholar returned a non-JSON response.", body=response.text[:1000], query=query) from exc
        papers = payload.get("data") or []
        records = [self._to_record(item) for item in papers if isinstance(item, dict)]
        total = int(payload.get("total") or len(records))
        return ProviderSearchResult(metadata=SearchMetadata(total=total, page=1, limit=page_size), hits=records)

    @classmethod
    def _throttle(cls) -> None:
        with cls._lock:
            elapsed = time.monotonic() - cls._last_request_at
            if elapsed < cls._minimum_request_interval:
                time.sleep(cls._minimum_request_interval - elapsed)
            cls._last_request_at = time.monotonic()

    def _to_record(self, item: Dict[str, Any]) -> PaperRecord:
        external = item.get("externalIds") or {}
        paper_id = str(item.get("paperId") or "")
        corpus_id = str(item.get("corpusId") or "")
        title = item.get("title") or paper_id or corpus_id
        authors = [
            PaperAuthor(display_name=str(author.get("name") or ""))
            for author in item.get("authors") or []
            if isinstance(author, dict) and author.get("name")
        ]
        venue_obj = item.get("publicationVenue") or {}
        venue = venue_obj.get("name") if isinstance(venue_obj, dict) else ""
        source_title = venue or item.get("venue") or ""
        pdf = ""
        open_pdf = item.get("openAccessPdf") or {}
        if isinstance(open_pdf, dict):
            pdf = open_pdf.get("url") or ""
        doi = normalize_doi(external.get("DOI") or external.get("DOIUrl") or "")
        pmid = str(external.get("PubMed") or "")
        arxiv_id = str(external.get("ArXiv") or "")
        citations = int(item.get("citationCount") or 0)
        fields = [str(value) for value in (item.get("fieldsOfStudy") or []) if value]
        publication_types = [str(value) for value in (item.get("publicationTypes") or []) if value]
        return PaperRecord(
            uid=paper_id or f"CorpusId:{corpus_id}" or title,
            title=title,
            types=publication_types,
            source_types=publication_types,
            source=PaperSource(source_title=source_title, publish_year=item.get("year")),
            names=PaperNames(authors=authors),
            links=PaperLinks(record=item.get("url") or "", landing_page=item.get("url") or "", pdf=pdf),
            citations=[PaperCitation(db="Semantic Scholar", count=citations)] if citations else [],
            identifiers=PaperIdentifiers(doi=doi, pmid=pmid, arxiv=arxiv_id, semanticscholar=paper_id),
            keywords=PaperKeywords(author_keywords=fields),
            abstract=item.get("abstract") or "",
            provider="semanticscholar",
            raw=item,
        )
