from __future__ import annotations

from html import unescape
from typing import Any, Dict, List, Optional
import re
import requests
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
from paperseek_core.sources.http import redact_request_text, retry_delay, split_api_keys

class GoogleScholarSerperProvider:
    BASE_URL = "https://google.serper.dev/scholar"

    def __init__(self, api_key: str = ""):
        self.api_keys = split_api_keys(api_key)
        self.last_response_info: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._index = 0

    def retrieval_capabilities(self) -> ProviderRetrievalCapabilities:
        return ProviderRetrievalCapabilities(
            source="googlescholar",
            lanes=(RetrievalLane.RELEVANCE,),
            max_lane_limit=100,
        )

    def search(self, query: str, limit: int = 50, page: int = 1, lane: str = RetrievalLane.RELEVANCE) -> ProviderSearchResult:
        query = (query or "").strip()
        if not query:
            raise ProviderError("googlescholar", "Google Scholar search query is empty.")
        if not self.api_keys:
            raise ProviderError("googlescholar", "SERPER_API_KEY or SERPER_API_KEYS is required for Google Scholar searches.", query=query)

        requested_limit = max(1, min(int(limit or 10), 100))
        page_size = 10
        page_number = max(1, int(page or 1))
        records: List[PaperRecord] = []
        total = 0
        last_info: Dict[str, Any] = {}
        seen = set()
        pages_scanned = 0
        empty_pages = 0
        max_pages = self._max_pages_to_scan(requested_limit, page_size)
        while pages_scanned < max_pages:
            payload = {
                "q": query,
                "page": page_number,
            }
            response, info = self._post_with_key_rotation(payload, query=query)
            last_info = info
            pages_scanned += 1
            if response.status_code >= 400:
                raise ProviderError(
                    "googlescholar",
                    f"Google Scholar via Serper returned HTTP {response.status_code}.",
                    status=response.status_code,
                    body=response.text[:1000],
                    query=query,
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderError("googlescholar", "Google Scholar via Serper returned a non-JSON response.", body=response.text[:1000], query=query) from exc
            if not isinstance(data, dict):
                raise ProviderError("googlescholar", "Google Scholar via Serper returned an unexpected JSON structure.", body=response.text[:1000], query=query)

            items = [item for item in data.get("organic") or [] if isinstance(item, dict)]
            if items:
                empty_pages = 0
                total = max(total, self._total(data, items, page_number, page_size))
                for item in items:
                    key = self._record_key(item)
                    if key and key in seen:
                        continue
                    if key:
                        seen.add(key)
                    if len(records) < requested_limit:
                        records.append(self._to_record(item))
                if len(records) >= requested_limit or len(items) < page_size:
                    break
            else:
                empty_pages += 1
                if empty_pages >= self._empty_page_stop_threshold(records):
                    break
            page_number += 1
        if last_info:
            last_info = dict(last_info)
            last_info["pages_scanned"] = pages_scanned
            last_info["returned_before_truncate"] = len(records)
            last_info["estimated_total"] = total or len(records)
        self.last_response_info = last_info
        if not total:
            total = len(records)
        elif records:
            total = max(total, len(records))
        return ProviderSearchResult(
            metadata=SearchMetadata(total=total, page=max(1, int(page or 1)), limit=requested_limit),
            hits=records[:requested_limit],
        )

    @staticmethod
    def _max_pages_to_scan(requested_limit: int, page_size: int) -> int:
        pages_needed = max(1, (requested_limit + page_size - 1) // page_size)
        return min(50, max(10, pages_needed * 3))

    @staticmethod
    def _empty_page_stop_threshold(records: List[PaperRecord]) -> int:
        return 3 if records else 5

    @staticmethod
    def _record_key(item: Dict[str, Any]) -> str:
        for key in ("id", "resultId", "link", "title"):
            value = str(item.get(key) or "").strip().lower()
            if value:
                return value
        return ""

    def _post_with_key_rotation(self, payload: Dict[str, Any], query: str):
        last_response: Optional[requests.Response] = None
        last_exc: Optional[requests.RequestException] = None
        started = time.perf_counter()
        attempts = max(1, min(max(3, len(self.api_keys)), len(self.api_keys) * 3))
        for attempt in range(1, attempts + 1):
            api_key = self._next_api_key()
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "paperseek/1.0",
                "X-API-KEY": api_key,
            }
            try:
                response = requests.post(self.BASE_URL, json=payload, headers=headers, timeout=45)
                info = {
                    "method": "POST",
                    "url": self.BASE_URL,
                    "status": response.status_code,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "attempts": attempt,
                }
                last_response = response
                if response.status_code in {401, 403, 408, 409, 425, 429, 500, 502, 503, 504} and attempt < attempts:
                    time.sleep(retry_delay(response, attempt, "googlescholar"))
                    continue
                return response, info
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < attempts:
                    time.sleep(0.7 * attempt)
        if last_response is not None:
            return last_response, {
                "method": "POST",
                "url": self.BASE_URL,
                "status": last_response.status_code,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "attempts": attempts,
            }
        detail = redact_request_text(last_exc)
        raise ProviderError("googlescholar", f"Google Scholar via Serper request failed after {attempts} attempts: {detail}", query=query) from last_exc

    def _next_api_key(self) -> str:
        if not self.api_keys:
            return ""
        with self._lock:
            index = self._index
            self._index += 1
        return self.api_keys[index % len(self.api_keys)]

    @staticmethod
    def _total(data: Dict[str, Any], records: List[Any], page: int, page_size: int) -> int:
        for path in (
            ("searchInformation", "totalResults"),
            ("searchInformation", "total_results"),
            ("searchParameters", "totalResults"),
        ):
            value: Any = data
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            try:
                if value not in (None, ""):
                    return int(str(value).replace(",", ""))
            except (TypeError, ValueError):
                pass
        return max(len(records), ((page - 1) * page_size) + len(records))

    def _to_record(self, item: Dict[str, Any]) -> PaperRecord:
        scholar_id = str(item.get("id") or item.get("resultId") or "")
        title = self._clean_text(item.get("title") or scholar_id or item.get("link") or "")
        link = item.get("link") or ""
        pdf = item.get("pdfUrl") or ""
        publication_info = item.get("publicationInfo") or {}
        year = self._year(item.get("year")) or self._year(self._publication_summary(publication_info))
        authors = self._authors(publication_info)
        source_title = self._source_title(publication_info)
        cited_by = item.get("citedBy") or {}
        cited_total = 0
        citing_link = ""
        if isinstance(cited_by, dict):
            try:
                cited_total = int(cited_by.get("total") or cited_by.get("cites") or cited_by.get("count") or cited_by.get("value") or 0)
            except (TypeError, ValueError):
                cited_total = 0
            citing_link = cited_by.get("link") or ""
        elif cited_by not in (None, ""):
            try:
                cited_total = int(cited_by)
            except (TypeError, ValueError):
                cited_total = 0
        snippet = self._clean_snippet(item.get("snippet") or "")
        return PaperRecord(
            uid=f"googlescholar:{scholar_id}" if scholar_id else link or title,
            title=title,
            types=["scholarly result"],
            source_types=["scholarly result"],
            source=PaperSource(source_title=source_title or "Google Scholar", publish_year=year),
            names=PaperNames(authors=authors),
            links=PaperLinks(record=link, landing_page=link, pdf=pdf, citing_articles=citing_link),
            citations=[PaperCitation(db="Google Scholar", count=cited_total)] if cited_total else [],
            identifiers=PaperIdentifiers(),
            keywords=PaperKeywords(author_keywords=[]),
            abstract=snippet,
            provider="googlescholar",
            raw=item,
        )

    @staticmethod
    def _authors(publication_info: Any) -> List[PaperAuthor]:
        if not isinstance(publication_info, dict):
            return GoogleScholarSerperProvider._authors_from_summary(publication_info)
        authors_list = publication_info.get("authors")
        authors = []
        if isinstance(authors_list, list):
            for author in authors_list:
                if isinstance(author, dict):
                    name = GoogleScholarSerperProvider._clean_author_name(author.get("name") or author.get("title") or "")
                else:
                    name = GoogleScholarSerperProvider._clean_author_name(author)
                if name:
                    authors.append(PaperAuthor(display_name=name))
        if authors:
            return authors
        return GoogleScholarSerperProvider._authors_from_summary(publication_info)

    @staticmethod
    def _authors_from_summary(publication_info: Any) -> List[PaperAuthor]:
        parts = GoogleScholarSerperProvider._summary_parts(publication_info)
        if len(parts) < 2:
            return []
        author_text = parts[0]
        if GoogleScholarSerperProvider._year(author_text):
            return []
        authors = []
        for part in re.split(r"\s*,\s*|;\s*", author_text):
            name = GoogleScholarSerperProvider._clean_author_name(part)
            if name:
                authors.append(PaperAuthor(display_name=name))
        return authors

    @staticmethod
    def _source_title(publication_info: Any) -> str:
        if isinstance(publication_info, dict):
            for key in ("journal", "venue"):
                value = GoogleScholarSerperProvider._clean_source_name(publication_info.get(key))
                if value:
                    return value
        parts = GoogleScholarSerperProvider._summary_parts(publication_info)
        for part in parts[1:]:
            value = GoogleScholarSerperProvider._clean_source_name(part)
            if value:
                return value
        return "Google Scholar"

    @staticmethod
    def _publication_summary(publication_info: Any) -> str:
        if isinstance(publication_info, dict):
            return GoogleScholarSerperProvider._clean_text(publication_info.get("summary") or "")
        return GoogleScholarSerperProvider._clean_text(publication_info)

    @staticmethod
    def _summary_parts(publication_info: Any) -> List[str]:
        summary = GoogleScholarSerperProvider._publication_summary(publication_info)
        return [part for part in (GoogleScholarSerperProvider._clean_text(item) for item in re.split(r"\s+-\s+", summary)) if part]

    @staticmethod
    def _clean_author_name(value: Any) -> str:
        text = GoogleScholarSerperProvider._clean_text(value)
        text = re.sub(r"\bet\s+al\.?$", "", text, flags=re.IGNORECASE).strip()
        text = text.replace("...", "").strip(" ,;.-")
        if not text or GoogleScholarSerperProvider._year(text):
            return ""
        if re.search(r"://|www\.|\.com\b|\.org\b|\.net\b|\.edu\b", text, flags=re.IGNORECASE):
            return ""
        return text

    @staticmethod
    def _clean_source_name(value: Any) -> str:
        text = GoogleScholarSerperProvider._clean_text(value)
        text = re.sub(r"\b(19|20)\d{2}\b", "", text)
        text = re.sub(r"\bAvailable at\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\bSSRN\s+\d+\b", "SSRN", text, flags=re.IGNORECASE)
        text = re.sub(r"\bet\s+al\.?\b", "", text, flags=re.IGNORECASE)
        text = text.replace("...", " ")
        text = re.sub(r"\s+", " ", text).strip(" ,;:-")
        return text

    @staticmethod
    def _clean_snippet(value: Any) -> str:
        text = GoogleScholarSerperProvider._clean_text(value)
        text = re.sub(r"^(?:\.\.\.|…)\s*,?\s*", "", text)
        text = re.sub(r"\s*(?:\.\.\.|…)$", "", text)
        return text.strip()

    @staticmethod
    def _clean_text(value: Any) -> str:
        text = unescape(str(value or ""))
        text = text.replace("\u00a0", " ")
        text = GoogleScholarSerperProvider._repair_mojibake(text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _repair_mojibake(text: str) -> str:
        replacements = {
            "â€¦": "...",
            "â€“": "–",
            "â€”": "—",
            "â€œ": "“",
            "â€�": "”",
            "â€˜": "‘",
            "â€™": "’",
            "鈥�": "...",
            "鈥?": "...",
            "\u0431\u043d": "...",
        }
        for bad, good in replacements.items():
            text = text.replace(bad, good)

        def replace_pair(match: re.Match) -> str:
            token = match.group(0)
            try:
                repaired = token.encode("gbk").decode("utf-8")
            except UnicodeError:
                return token
            return repaired if "\ufffd" not in repaired else token

        return re.sub(r"鈥[\u4e00-\u9fff]", replace_pair, text)

    @staticmethod
    def _year(value: Any) -> Optional[int]:
        current_year = time.gmtime().tm_year + 2
        try:
            if value not in (None, ""):
                year = int(value)
                if 1500 <= year <= current_year:
                    return year
        except (TypeError, ValueError):
            pass
        for match in re.finditer(r"\b(19|20)\d{2}\b", str(value or "")):
            year = int(match.group(0))
            if year <= current_year:
                return year
        return None
