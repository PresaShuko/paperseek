from __future__ import annotations

import time
from typing import Any, Callable, Optional

import requests

from paperseek_core.client import ApiClient, ApiException, Configuration, DocumentsApi
from paperseek_core.retrieval import ProviderRetrievalCapabilities, RetrievalLane
import paperseek_core.sources.providers as _shared


PaperAuthor = _shared.PaperAuthor
PaperCitation = _shared.PaperCitation
PaperIdentifiers = _shared.PaperIdentifiers
PaperKeywords = _shared.PaperKeywords
PaperLinks = _shared.PaperLinks
PaperNames = _shared.PaperNames
PaperRecord = _shared.PaperRecord
PaperSource = _shared.PaperSource
ProviderSearchResult = _shared.ProviderSearchResult
SearchMetadata = _shared.SearchMetadata


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
        return ""
    if isinstance(value, dict):
        for key in ("value", "name", "displayName", "display_name", "title"):
            text = _first_text(value.get(key))
            if text:
                return text
        return ""
    return str(value or "").strip()


def _author(item: Any) -> PaperAuthor:
    if isinstance(item, dict):
        return PaperAuthor(
            display_name=_first_text(item.get("displayName") or item.get("display_name") or item.get("name")),
            wos_standard=_first_text(item.get("wosStandard") or item.get("wos_standard")),
            researcher_id=_first_text(item.get("researcherId") or item.get("researcher_id")),
        )
    return PaperAuthor(display_name=_first_text(item))


def record_from_json(item: dict[str, Any]) -> PaperRecord:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    names = item.get("names") if isinstance(item.get("names"), dict) else {}
    identifiers = item.get("identifiers") if isinstance(item.get("identifiers"), dict) else {}
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    keywords = item.get("keywords") if isinstance(item.get("keywords"), dict) else {}
    citations = []
    for citation in _as_list(item.get("citations")):
        if isinstance(citation, dict):
            citations.append(
                PaperCitation(
                    db=_first_text(citation.get("db")),
                    count=_to_int(citation.get("count")) or 0,
                )
            )

    return PaperRecord(
        uid=_first_text(item.get("uid") or item.get("id") or identifiers.get("wosuid") or item.get("title")),
        title=_first_text(item.get("title")),
        types=[_first_text(value) for value in _as_list(item.get("types")) if _first_text(value)],
        source_types=[
            _first_text(value)
            for value in _as_list(item.get("sourceTypes"))
            if _first_text(value)
        ],
        source=PaperSource(
            source_title=_first_text(source.get("sourceTitle") or source.get("source_title")),
            publish_year=_to_int(source.get("publishYear") or source.get("publish_year")),
            publish_month=_first_text(source.get("publishMonth") or source.get("publish_month")),
            volume=_first_text(source.get("volume")),
            issue=_first_text(source.get("issue")),
        ),
        names=PaperNames(authors=[_author(author) for author in _as_list(names.get("authors"))]),
        links=PaperLinks(
            record=_first_text(links.get("record")),
            citing_articles=_first_text(links.get("citingArticles") or links.get("citing_articles")),
            references=_first_text(links.get("references")),
            related=_first_text(links.get("related")),
            landing_page=_first_text(
                links.get("record") or links.get("landingPage") or links.get("landing_page")
            ),
        ),
        citations=citations,
        identifiers=PaperIdentifiers(
            doi=_first_text(identifiers.get("doi")),
            issn=_first_text(identifiers.get("issn")),
            eissn=_first_text(identifiers.get("eissn")),
            isbn=_first_text(identifiers.get("isbn")),
            eisbn=_first_text(identifiers.get("eisbn")),
            pmid=_first_text(identifiers.get("pmid")),
        ),
        keywords=PaperKeywords(
            author_keywords=[
                _first_text(value)
                for value in _as_list(
                    keywords.get("authorKeywords") or keywords.get("author_keywords")
                )
                if _first_text(value)
            ]
        ),
        provider="wos",
        raw=item,
    )


def result_from_json(payload: dict[str, Any], limit: int) -> ProviderSearchResult:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    hits = payload.get("hits") if isinstance(payload.get("hits"), list) else []
    return ProviderSearchResult(
        metadata=SearchMetadata(
            total=_to_int(metadata.get("total")) or 0,
            page=_to_int(metadata.get("page")) or 1,
            limit=_to_int(metadata.get("limit")) or limit,
        ),
        hits=[record_from_json(item) for item in hits if isinstance(item, dict)],
    )


class WosProvider:
    BASE_URL = "https://api.clarivate.com/apis/wos-starter/v1/documents"

    def __init__(
        self,
        api_key: str,
        db: str = "WOS",
        *,
        log: Optional[Callable[[str], None]] = None,
    ):
        self.api_key = (api_key or "").strip()
        self.db = (db or "WOS").strip() or "WOS"
        self.log = log or (lambda _message: None)
        configuration = Configuration(api_key={"ClarivateApiKeyAuth": self.api_key})
        self.documents_api = DocumentsApi(ApiClient(configuration=configuration))

    def retrieval_capabilities(self) -> ProviderRetrievalCapabilities:
        return ProviderRetrievalCapabilities(
            source="wos",
            lanes=(RetrievalLane.RELEVANCE, RetrievalLane.IMPACT, RetrievalLane.RECENT),
            max_lane_limit=100,
        )

    def search(
        self,
        query: str,
        limit: int = 50,
        page: int = 1,
        lane: str = RetrievalLane.RELEVANCE,
    ) -> ProviderSearchResult:
        del page
        sort_field = self.sort_field_for_lane(lane)
        try:
            return self.documents_api.documents_get(
                q=query,
                db=self.db,
                limit=limit,
                sort_field=sort_field,
            )
        except ApiException as exc:
            if exc.status != 429:
                raise
            self.log("WoS Starter rate limit reached; waiting briefly before one retry.")
            time.sleep(2.0)
            return self.documents_api.documents_get(
                q=query,
                db=self.db,
                limit=limit,
                sort_field=sort_field,
            )
        except Exception as exc:
            self.log(
                "WoS client parsing failed; retrying with the fallback JSON parser: "
                f"{exc.__class__.__name__}."
            )
            return self.raw_search(query, limit=limit, sort_field=sort_field)

    @staticmethod
    def sort_field_for_lane(lane: str) -> str:
        if lane == RetrievalLane.IMPACT:
            return "TC+D"
        if lane == RetrievalLane.RECENT:
            return "PY+D"
        return "RS+D"

    def raw_search(
        self,
        query: str,
        *,
        limit: int,
        sort_field: str = "RS+D",
    ) -> ProviderSearchResult:
        response = requests.get(
            self.BASE_URL,
            params={"q": query, "db": self.db, "limit": limit, "sortField": sort_field},
            headers={"Accept": "application/json", "X-ApiKey": self.api_key},
            timeout=45,
        )
        if response.status_code == 429:
            self.log("WoS Starter raw request rate limited; waiting briefly before one retry.")
            time.sleep(2.0)
            response = requests.get(
                self.BASE_URL,
                params={"q": query, "db": self.db, "limit": limit, "sortField": sort_field},
                headers={"Accept": "application/json", "X-ApiKey": self.api_key},
                timeout=45,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ApiException(
                status=response.status_code,
                reason=response.reason,
                body=response.text,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiException(
                status=response.status_code,
                reason="Invalid JSON response",
                body=response.text,
            ) from exc
        return result_from_json(payload, limit)

