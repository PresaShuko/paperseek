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

class PubMedProvider:
    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, api_key: str = "", email: str = "", tool: str = "paperseek"):
        self.api_key = (api_key or "").strip()
        self.email = (email or "").strip()
        self.tool = (tool or "paperseek").strip()
        self.last_response_info: Dict[str, Any] = {}

    def retrieval_capabilities(self) -> ProviderRetrievalCapabilities:
        return ProviderRetrievalCapabilities(
            source="pubmed",
            lanes=(RetrievalLane.RELEVANCE, RetrievalLane.RECENT),
            max_lane_limit=500,
        )

    def search(self, query: str, limit: int = 50, page: int = 1, lane: str = RetrievalLane.RELEVANCE) -> ProviderSearchResult:
        query = (query or "").strip()
        if not query:
            raise ProviderError("pubmed", "PubMed search query is empty.")

        page_size = max(1, min(int(limit or 10), 100))
        retstart = max(0, (int(page or 1) - 1) * page_size)
        search_payload = self._get_json(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": page_size,
                "retstart": retstart,
                "sort": "pub+date" if lane == RetrievalLane.RECENT else "relevance",
            },
            query,
        )
        result = search_payload.get("esearchresult") or {}
        ids = [str(value) for value in result.get("idlist") or [] if value]
        total = int(result.get("count") or 0)
        if not ids:
            return ProviderSearchResult(metadata=SearchMetadata(total=total, page=max(1, int(page or 1)), limit=page_size), hits=[])

        summary_payload = self._get_json(
            "esummary.fcgi",
            {"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            query,
        )
        summaries = (summary_payload.get("result") or {})
        abstracts = self._fetch_abstracts(ids, query)
        records = []
        for pmid in ids:
            item = summaries.get(pmid)
            if isinstance(item, dict):
                records.append(self._to_record(pmid, item, abstracts.get(pmid, "")))
        return ProviderSearchResult(metadata=SearchMetadata(total=total, page=max(1, int(page or 1)), limit=page_size), hits=records)

    def _get_json(self, endpoint: str, params: Dict[str, Any], query: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/{endpoint}"
        params = {**params, **self._common_params()}
        headers = {"Accept": "application/json", "User-Agent": self._user_agent()}
        try:
            response, info = get_with_retries("pubmed", url, params=params, headers=headers, timeout=45, query=query)
            self.last_response_info = info
        except ProviderError as exc:
            self.last_response_info = {"method": "GET", "url": url, "status": "request_error", "elapsed_ms": None}
            raise exc
        if response.status_code >= 400:
            raise ProviderError("pubmed", f"PubMed returned HTTP {response.status_code}.", status=response.status_code, body=response.text[:1000], query=query)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("pubmed", "PubMed returned a non-JSON response.", body=response.text[:1000], query=query) from exc

    def _fetch_abstracts(self, pmids: List[str], query: str) -> Dict[str, str]:
        if not pmids:
            return {}
        url = f"{self.BASE_URL}/efetch.fcgi"
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            **self._common_params(),
        }
        headers = {"Accept": "application/xml", "User-Agent": self._user_agent()}
        try:
            response, info = get_with_retries("pubmed", url, params=params, headers=headers, timeout=45, query=query)
            self.last_response_info = info
        except ProviderError:
            return {}
        if response.status_code >= 400:
            return {}
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            return {}
        abstracts: Dict[str, str] = {}
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID") or ""
            parts = []
            for node in article.findall(".//Abstract/AbstractText"):
                label = node.attrib.get("Label")
                text = "".join(node.itertext()).strip()
                if text:
                    parts.append(f"{label}: {text}" if label else text)
            if pmid and parts:
                abstracts[pmid] = re.sub(r"\s+", " ", " ".join(parts)).strip()
        return abstracts

    def _common_params(self) -> Dict[str, str]:
        params = {"tool": self.tool}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _user_agent(self) -> str:
        if self.email:
            return f"paperseek/1.0 (mailto:{self.email})"
        return "paperseek/1.0"

    def _to_record(self, pmid: str, item: Dict[str, Any], abstract: str) -> PaperRecord:
        article_ids = item.get("articleids") or []
        doi = ""
        for article_id in article_ids:
            if isinstance(article_id, dict) and str(article_id.get("idtype") or "").lower() == "doi":
                doi = normalize_doi(article_id.get("value") or "")
                break
        authors = []
        for author in item.get("authors") or []:
            if isinstance(author, dict) and author.get("name"):
                authors.append(PaperAuthor(display_name=str(author.get("name") or "")))
        year = self._extract_year(item.get("pubdate") or item.get("epubdate") or "")
        pub_types = [str(value) for value in (item.get("pubtype") or []) if value]
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
        return PaperRecord(
            uid=f"PMID:{pmid}",
            title=item.get("title") or pmid,
            types=pub_types,
            source_types=pub_types,
            source=PaperSource(source_title=item.get("fulljournalname") or item.get("source") or "PubMed", publish_year=year),
            names=PaperNames(authors=authors),
            links=PaperLinks(record=url, landing_page=url),
            identifiers=PaperIdentifiers(doi=doi, pmid=pmid),
            keywords=PaperKeywords(author_keywords=[]),
            abstract=abstract,
            provider="pubmed",
            raw=item,
        )

    @staticmethod
    def _extract_year(value: str) -> Optional[int]:
        match = re.search(r"\b(19|20)\d{2}\b", value or "")
        return int(match.group(0)) if match else None

