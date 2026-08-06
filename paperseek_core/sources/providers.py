
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import math
import re
import requests
import threading
import time
import xml.etree.ElementTree as ET

from paperseek_core.retrieval import ProviderRetrievalCapabilities, RetrievalLane
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


@dataclass
class CitationSeedPlan:
    record: PaperRecord
    role: str = "relevance"
    directions: Tuple[str, ...] = ("backward", "forward")
    depth: int = 1


@dataclass
class SearchMetadata:
    total: int = 0
    page: int = 1
    limit: int = 10


@dataclass
class ProviderSearchResult:
    metadata: SearchMetadata
    hits: List[PaperRecord]


class ProviderError(Exception):
    def __init__(self, source: str, message: str, status: Optional[int] = None, body: str = "", query: str = ""):
        super().__init__(message)
        self.source = source
        self.status = status
        self.body = body
        self.query = query


def _redact_request_text(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    return re.sub(r"([?&](?:api_key|apikey|key|token|access_token)=)[^&\s)]+", r"\1<redacted>", text, flags=re.I)


def reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    if not inverted_index:
        return ""

    positions: Dict[int, str] = {}
    for word, indexes in inverted_index.items():
        if not isinstance(indexes, list):
            continue
        for idx in indexes:
            if isinstance(idx, int):
                positions[idx] = word

    if not positions:
        return ""

    return " ".join(positions[i] for i in sorted(positions))


def normalize_doi(value: str) -> str:
    value = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.lower().startswith(prefix):
            return value[len(prefix):].strip()
    return value


def get_with_retries(
    source: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    query: str = "",
    attempts: int = 3,
):
    last_exc: Optional[requests.RequestException] = None
    started = time.perf_counter()
    for attempt in range(1, max(1, attempts) + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            info = {
                "method": "GET",
                "url": _redact_request_text(response.url),
                "status": response.status_code,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "attempts": attempt,
            }
            if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                time.sleep(_retry_delay(response, attempt, source))
                continue
            return response, info
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(0.7 * attempt)

    info = {
        "method": "GET",
        "url": url,
        "status": "request_error",
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "attempts": attempts,
    }
    detail = _redact_request_text(last_exc)
    raise ProviderError(source, f"{source.title()} request failed after {attempts} attempts: {detail}", query=query) from last_exc


def _split_api_keys(value: str) -> List[str]:
    return list(dict.fromkeys(item.strip() for item in re.split(r"[\s,;]+", value or "") if item.strip()))


def _retry_delay(response: requests.Response, attempt: int, source: str = "") -> float:
    retry_after = response.headers.get("Retry-After", "")
    try:
        return max(0.7 * attempt, min(float(retry_after), 15.0))
    except (TypeError, ValueError):
        if response.status_code == 429 and (source or "").lower() == "arxiv":
            return min(5.0 * attempt, 20.0)
        if response.status_code == 429 and (source or "").lower() == "semanticscholar":
            return min(2.0 * attempt, 8.0)
        return 0.7 * attempt
from paperseek_core.sources.openalex import OpenAlexProvider
from paperseek_core.sources.crossref import CrossrefProvider
from paperseek_core.sources.google_scholar import GoogleScholarSerperProvider
from paperseek_core.sources.arxiv import ArxivProvider
from paperseek_core.sources.semantic_scholar import SemanticScholarProvider
from paperseek_core.sources.pubmed import PubMedProvider
from paperseek_core.sources.paperhub import PaperHubProvider, PaperHubQuery
from paperseek_core.sources.wos import WosProvider

__all__ = [
    "PaperAuthor",
    "PaperNames",
    "PaperSource",
    "PaperLinks",
    "PaperCitation",
    "PaperIdentifiers",
    "PaperKeywords",
    "PaperRecord",
    "CitationSeedPlan",
    "SearchMetadata",
    "ProviderSearchResult",
    "ProviderError",
    "reconstruct_abstract",
    "normalize_doi",
    "get_with_retries",
    "OpenAlexProvider",
    "CrossrefProvider",
    "GoogleScholarSerperProvider",
    "ArxivProvider",
    "SemanticScholarProvider",
    "PubMedProvider",
    "PaperHubQuery",
    "PaperHubProvider",
    "WosProvider",
]
