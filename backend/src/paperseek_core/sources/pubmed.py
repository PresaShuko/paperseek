from __future__ import annotations

import re
from typing import Any
import xml.etree.ElementTree as ET

from paperseek_core.models import PaperAuthor, PaperIdentifiers, PaperKeywords, PaperLinks, PaperNames, PaperRecord, PaperSource
from paperseek_core.sources.contracts import SourceCapabilities, SourceError, SourceSearchMetadata, SourceSearchRequest, SourceSearchResult
from paperseek_core.sources.http import AsyncHttpTransport
from paperseek_core.sources.normalization import normalize_doi


class PubMedSource:
    name = "pubmed"
    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    SEARCH_URL = f"{BASE_URL}/esearch.fcgi"
    SUMMARY_URL = f"{BASE_URL}/esummary.fcgi"
    FETCH_URL = f"{BASE_URL}/efetch.fcgi"

    def __init__(
        self,
        *,
        transport: AsyncHttpTransport,
        api_key: str = "",
        email: str = "",
        tool: str = "paperseek",
    ) -> None:
        self.transport = transport
        self.api_key = str(api_key or "").strip()
        self.email = str(email or "").strip()
        self.tool = str(tool or "paperseek").strip()
        self.capabilities = SourceCapabilities(
            source=self.name,
            lanes=("relevance", "recent"),
            metadata_fields=("title", "names", "source", "identifiers", "abstract"),
            supports_abstracts=True,
            api_key="optional",
            max_page_size=100,
            max_lane_limit=500,
            backoff_policy="3 attempts for transport, 429, and transient 5xx responses",
        )
        self.last_response_info: dict[str, Any] = {}

    async def search(self, request: SourceSearchRequest) -> SourceSearchResult:
        query = request.query.strip()
        if not query:
            raise SourceError(self.name, "PubMed search query is empty.")
        page_size = max(1, min(int(request.limit or 10), 100))
        search_payload = await self._get_json(
            self.SEARCH_URL,
            {
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": page_size,
                "retstart": max(0, (int(request.page or 1) - 1) * page_size),
                "sort": "pub+date" if request.lane == "recent" else "relevance",
            },
            query,
        )
        search_result = search_payload.get("esearchresult") or {}
        ids = [str(value) for value in search_result.get("idlist") or [] if value]
        total = int(search_result.get("count") or 0)
        metadata = SourceSearchMetadata(total=total, page=max(1, request.page), limit=page_size)
        if not ids:
            return SourceSearchResult(metadata=metadata, hits=[])
        summaries = (await self._get_json(
            self.SUMMARY_URL,
            {"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            query,
        )).get("result") or {}
        abstracts = await self._fetch_abstracts(ids, query)
        hits = [self._to_record(pmid, summaries[pmid], abstracts.get(pmid, "")) for pmid in ids if isinstance(summaries.get(pmid), dict)]
        return SourceSearchResult(metadata=metadata, hits=hits)

    async def _get_json(self, url: str, params: dict[str, Any], query: str) -> dict[str, Any]:
        response, self.last_response_info = await self.transport.request(
            self.name,
            "GET",
            url,
            params={**params, **self._common_params()},
            headers={"Accept": "application/json", "User-Agent": self._user_agent()},
            timeout=45,
            query=query,
        )
        if response.status_code >= 400:
            raise SourceError(self.name, f"PubMed returned HTTP {response.status_code}.", status=response.status_code, body=response.text[:1000], query=query)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(self.name, "PubMed returned a non-JSON response.", body=response.text[:1000], query=query) from exc

    async def _fetch_abstracts(self, ids: list[str], query: str) -> dict[str, str]:
        try:
            response, self.last_response_info = await self.transport.request(
                self.name,
                "GET",
                self.FETCH_URL,
                params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml", **self._common_params()},
                headers={"Accept": "application/xml", "User-Agent": self._user_agent()},
                timeout=45,
                query=query,
            )
        except SourceError:
            return {}
        if response.status_code >= 400:
            return {}
        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            return {}
        abstracts: dict[str, str] = {}
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID") or ""
            parts = []
            for node in article.findall(".//Abstract/AbstractText"):
                text = "".join(node.itertext()).strip()
                if text:
                    parts.append(f"{node.attrib.get('Label')}: {text}" if node.attrib.get("Label") else text)
            if pmid and parts:
                abstracts[pmid] = re.sub(r"\s+", " ", " ".join(parts)).strip()
        return abstracts

    def _common_params(self) -> dict[str, str]:
        params = {"tool": self.tool}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _user_agent(self) -> str:
        return f"paperseek/1.0 (mailto:{self.email})" if self.email else "paperseek/1.0"

    @staticmethod
    def _to_record(pmid: str, item: dict[str, Any], abstract: str) -> PaperRecord:
        doi = ""
        for article_id in item.get("articleids") or []:
            if isinstance(article_id, dict) and str(article_id.get("idtype") or "").lower() == "doi":
                doi = normalize_doi(article_id.get("value") or "")
                break
        authors = [PaperAuthor(display_name=str(author.get("name") or "")) for author in item.get("authors") or [] if isinstance(author, dict) and author.get("name")]
        date = item.get("pubdate") or item.get("epubdate") or ""
        match = re.search(r"\b(19|20)\d{2}\b", date)
        pub_types = [str(value) for value in item.get("pubtype") or [] if value]
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
        return PaperRecord(
            uid=f"PMID:{pmid}",
            title=item.get("title") or pmid,
            types=pub_types,
            source_types=pub_types,
            source=PaperSource(source_title=item.get("fulljournalname") or item.get("source") or "PubMed", publish_year=int(match.group(0)) if match else None),
            names=PaperNames(authors=authors),
            links=PaperLinks(record=url, landing_page=url),
            identifiers=PaperIdentifiers(doi=doi, pmid=pmid),
            keywords=PaperKeywords(author_keywords=[]),
            abstract=abstract,
            provider="pubmed",
            raw=item,
        )
