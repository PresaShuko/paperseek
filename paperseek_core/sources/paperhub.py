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

@dataclass
class PaperHubQuery:
    groups: List[List[str]] = field(default_factory=list)
    excludes: List[str] = field(default_factory=list)
    conference: Optional[str] = None
    year: Optional[int] = None
    after: Optional[int] = None
    before: Optional[int] = None


class PaperHubProvider:
    MANIFEST_URL = "https://raw.githubusercontent.com/Yupu-Wang/paper-hub/main/data/manifest.json"
    RAW_BASE_URL = "https://raw.githubusercontent.com/Yupu-Wang/paper-hub/main/data"
    CACHE_TTL_SECONDS = 3600
    MAX_DOWNLOAD_WORKERS = 8
    _lock = threading.Lock()
    _paper_cache: Optional[List[Dict[str, Any]]] = None
    _paper_cache_loaded_at = 0.0
    _paper_cache_manifest_version = ""

    @classmethod
    def reset_cache(cls) -> None:
        with cls._lock:
            cls._paper_cache = None
            cls._paper_cache_loaded_at = 0.0
            cls._paper_cache_manifest_version = ""

    def __init__(self):
        self.last_response_info: Dict[str, Any] = {}

    def retrieval_capabilities(self) -> ProviderRetrievalCapabilities:
        return ProviderRetrievalCapabilities(
            source="paperhub",
            lanes=(RetrievalLane.RELEVANCE, RetrievalLane.RECENT, RetrievalLane.LOCAL_QUALITY),
            max_lane_limit=1000,
        )

    def search(self, query: str, limit: int = 50, page: int = 1, lane: str = RetrievalLane.RELEVANCE) -> ProviderSearchResult:
        query = (query or "").strip()
        if not query:
            raise ProviderError("paperhub", "Paper Hub search query is empty.")
        papers = self._load_papers(query)
        scored = []
        parsed_query = self._parse_query(query)
        for paper in papers:
            score = self._match_score(paper, parsed_query)
            if score is not None:
                scored.append((score, paper))
        if lane == RetrievalLane.RECENT:
            scored.sort(key=lambda item: (int(item[1].get("year") or 0), item[0], item[1].get("conference") or ""), reverse=True)
        elif lane == RetrievalLane.LOCAL_QUALITY:
            scored.sort(key=lambda item: (item[0], self._conference_weight(item[1]), int(item[1].get("year") or 0)), reverse=True)
        else:
            scored.sort(key=lambda item: (item[0], int(item[1].get("year") or 0), item[1].get("conference") or ""), reverse=True)
        page_size = max(1, min(int(limit or 10), 100))
        offset = max(0, (int(page or 1) - 1) * page_size)
        selected = [paper for _, paper in scored[offset:offset + page_size]]
        return ProviderSearchResult(
            metadata=SearchMetadata(total=len(scored), page=max(1, int(page or 1)), limit=page_size),
            hits=[self._to_record(paper) for paper in selected],
        )

    def _load_papers(self, query: str) -> List[Dict[str, Any]]:
        now = time.monotonic()
        if (
            PaperHubProvider._paper_cache is not None
            and now - PaperHubProvider._paper_cache_loaded_at < self.CACHE_TTL_SECONDS
        ):
            return PaperHubProvider._paper_cache
        with PaperHubProvider._lock:
            now = time.monotonic()
            if (
                PaperHubProvider._paper_cache is not None
                and now - PaperHubProvider._paper_cache_loaded_at < self.CACHE_TTL_SECONDS
            ):
                return PaperHubProvider._paper_cache

            stale_cache = PaperHubProvider._paper_cache
            try:
                response, info = get_with_retries(
                    "paperhub",
                    self.MANIFEST_URL,
                    headers={"Accept": "application/json"},
                    timeout=45,
                    query=query,
                )
                if response.status_code >= 400:
                    raise ProviderError(
                        "paperhub",
                        f"Paper Hub manifest returned HTTP {response.status_code}.",
                        status=response.status_code,
                        body=response.text[:1000],
                        query=query,
                    )
                try:
                    manifest = response.json()
                except ValueError as exc:
                    raise ProviderError(
                        "paperhub",
                        "Paper Hub manifest returned non-JSON content.",
                        body=response.text[:1000],
                        query=query,
                    ) from exc

                shards = self._manifest_shards(manifest, query)
                manifest_version = self._manifest_version(manifest, shards)
                if stale_cache is not None and manifest_version == PaperHubProvider._paper_cache_manifest_version:
                    PaperHubProvider._paper_cache_loaded_at = now
                    self.last_response_info = {
                        **info,
                        "manifest_version": manifest_version,
                        "shards": len(shards),
                        "papers": len(stale_cache),
                        "cache_revalidated": True,
                    }
                    return stale_cache

                workers = min(self.MAX_DOWNLOAD_WORKERS, len(shards))
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="paperhub") as executor:
                    futures = [executor.submit(self._download_shard, shard, query) for shard in shards]
                    chunks = [future.result() for future in futures]

                papers = [paper for chunk in chunks for paper in chunk]
                expected_total = sum(int(shard.get("count") or 0) for shard in shards)
                if expected_total and len(papers) != expected_total:
                    raise ProviderError(
                        "paperhub",
                        f"Paper Hub snapshot count mismatch: expected {expected_total}, received {len(papers)}.",
                        query=query,
                    )
            except Exception as exc:
                if stale_cache is not None:
                    self.last_response_info = {
                        "method": "GET",
                        "url": self.MANIFEST_URL,
                        "status": "stale_cache",
                        "papers": len(stale_cache),
                        "refresh_error": str(exc),
                    }
                    PaperHubProvider._paper_cache_loaded_at = now
                    return stale_cache
                if isinstance(exc, ProviderError):
                    raise
                raise ProviderError("paperhub", f"Paper Hub snapshot loading failed: {exc}", query=query) from exc

            PaperHubProvider._paper_cache = papers
            PaperHubProvider._paper_cache_loaded_at = now
            PaperHubProvider._paper_cache_manifest_version = manifest_version
            self.last_response_info = {
                **info,
                "manifest_version": manifest_version,
                "shards": len(shards),
                "papers": len(papers),
                "download_workers": workers,
            }
            return papers

    @staticmethod
    def _manifest_shards(manifest: Any, query: str) -> List[Dict[str, Any]]:
        if not isinstance(manifest, dict) or not isinstance(manifest.get("shards"), list):
            raise ProviderError("paperhub", "Paper Hub manifest did not contain a shard list.", query=query)
        shards: List[Dict[str, Any]] = []
        for shard in manifest["shards"]:
            if not isinstance(shard, dict):
                raise ProviderError("paperhub", "Paper Hub manifest contained an invalid shard entry.", query=query)
            file_name = str(shard.get("file") or "").strip().replace("\\", "/")
            if not file_name or file_name.startswith("/") or ".." in file_name.split("/"):
                raise ProviderError("paperhub", "Paper Hub manifest contained an unsafe shard path.", query=query)
            shards.append({**shard, "file": file_name})
        if not shards:
            raise ProviderError("paperhub", "Paper Hub manifest did not list any data shards.", query=query)
        return shards

    @staticmethod
    def _manifest_version(manifest: Dict[str, Any], shards: Sequence[Dict[str, Any]]) -> str:
        built_at = str(manifest.get("built_at") or "").strip()
        shard_signature = "|".join(str(shard.get("file") or "") for shard in shards)
        return f"{built_at}|{shard_signature}"

    def _download_shard(self, shard: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        file_name = str(shard["file"])
        url = f"{self.RAW_BASE_URL}/{file_name}"
        response, _ = get_with_retries(
            "paperhub",
            url,
            headers={"Accept": "application/json"},
            timeout=90,
            query=query,
        )
        if response.status_code >= 400:
            raise ProviderError(
                "paperhub",
                f"Paper Hub shard {file_name} returned HTTP {response.status_code}.",
                status=response.status_code,
                body=response.text[:1000],
                query=query,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                "paperhub",
                f"Paper Hub shard {file_name} returned non-JSON content.",
                body=response.text[:1000],
                query=query,
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("papers"), list):
            raise ProviderError("paperhub", f"Paper Hub shard {file_name} did not contain a paper list.", query=query)
        papers = [paper for paper in payload["papers"] if isinstance(paper, dict)]
        expected_count = int(shard.get("count") or 0)
        if expected_count and len(papers) != expected_count:
            raise ProviderError(
                "paperhub",
                f"Paper Hub shard {file_name} count mismatch: expected {expected_count}, received {len(papers)}.",
                query=query,
            )
        return papers

    @classmethod
    def _parse_query(cls, query: str) -> PaperHubQuery:
        parsed = PaperHubQuery()
        append_to_previous_group = False
        token_pattern = re.compile(r'(-?)"([^"]+)"|(\S+)')
        stop = {"and", "the", "with", "for", "from", "paper", "papers", "study", "research"}
        for match in token_pattern.finditer(query or ""):
            quoted = bool(match.group(2))
            value = match.group(2) if quoted else match.group(3)
            excluded = bool(match.group(1))
            value = cls._normalize_query_token(value)
            if not value:
                continue
            if value.upper() == "OR":
                append_to_previous_group = True
                continue
            if not quoted and value.startswith("-"):
                excluded = True
                value = cls._normalize_query_token(value[1:])
            if value.startswith("+"):
                value = cls._normalize_query_token(value[1:])
            if not value:
                continue

            field_match = re.match(r"^(conference|conf|venue|year|after|before):(.+)$", value, flags=re.I)
            if field_match and not excluded:
                field_name = field_match.group(1).lower()
                field_value = cls._normalize_query_token(field_match.group(2)).strip('"')
                if field_name in {"conference", "conf", "venue"}:
                    parsed.conference = field_value.upper()
                else:
                    year_match = re.search(r"(19|20)\d{2}", field_value)
                    if year_match:
                        setattr(parsed, field_name, int(year_match.group(0)))
                append_to_previous_group = False
                continue

            term = value.lower()
            if not quoted and term in stop:
                append_to_previous_group = False
                continue
            if excluded:
                parsed.excludes.append(term)
                append_to_previous_group = False
            elif append_to_previous_group and parsed.groups:
                parsed.groups[-1].append(term)
                append_to_previous_group = False
            else:
                parsed.groups.append([term])
        return parsed

    @staticmethod
    def _normalize_query_token(value: str) -> str:
        return re.sub(r"^[()]+|[()]+$", "", str(value or "").strip()).strip()

    def _match_score(self, paper: Dict[str, Any], query: PaperHubQuery) -> Optional[int]:
        if not self._metadata_matches(paper, query):
            return None
        text = self._paper_text(paper)
        if any(term and term in text for term in query.excludes):
            return None
        score = 0
        for group in query.groups:
            best = 0
            for term in group:
                if term and term in text:
                    best = max(best, self._score_term(paper, term))
            if best <= 0:
                return None
            score += best
        return max(score, 1)

    @staticmethod
    def _metadata_matches(paper: Dict[str, Any], query: PaperHubQuery) -> bool:
        conference = str(paper.get("conference") or "").upper()
        if query.conference and conference != query.conference:
            return False
        try:
            year = int(paper.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        if query.year and year != query.year:
            return False
        if query.after and year <= query.after:
            return False
        if query.before and year >= query.before:
            return False
        return True

    @staticmethod
    def _paper_text(paper: Dict[str, Any]) -> str:
        return " ".join(
            [
                str(paper.get("title") or ""),
                str(paper.get("abstract") or ""),
                " ".join(str(value) for value in (paper.get("keywords") or [])),
                " ".join(str(value) for value in (paper.get("authors") or [])),
                str(paper.get("conference") or ""),
                str(paper.get("year") or ""),
                str(paper.get("presentation") or ""),
            ]
        ).lower()

    @staticmethod
    def _score_term(paper: Dict[str, Any], term: str) -> int:
        title = str(paper.get("title") or "").lower()
        abstract = str(paper.get("abstract") or "").lower()
        keywords = " ".join(str(value) for value in (paper.get("keywords") or [])).lower()
        authors = " ".join(str(value) for value in (paper.get("authors") or [])).lower()
        venue = f"{paper.get('conference') or ''} {paper.get('year') or ''} {paper.get('presentation') or ''}".lower()
        score = 0
        if term in title:
            score += 8
        if term in keywords:
            score += 5
        if term in abstract:
            score += 3
        if term in authors:
            score += 2
        if term in venue:
            score += 4
        return score

    @staticmethod
    def _conference_weight(paper: Dict[str, Any]) -> int:
        conference = str(paper.get("conference") or "").upper()
        order = {"NEURIPS": 6, "ICML": 5, "ICLR": 5, "AAAI": 4, "NDSS": 4}
        return order.get(conference, 1)

    def _to_record(self, paper: Dict[str, Any]) -> PaperRecord:
        paper_id = str(paper.get("id") or paper.get("url") or paper.get("title") or "")
        conference = str(paper.get("conference") or "")
        year = paper.get("year")
        presentation = str(paper.get("presentation") or "")
        keywords = [str(value) for value in (paper.get("keywords") or []) if value]
        if conference and conference not in keywords:
            keywords.append(conference)
        if presentation and presentation not in keywords:
            keywords.append(presentation)
        authors = [PaperAuthor(display_name=str(name)) for name in (paper.get("authors") or []) if name]
        url = str(paper.get("url") or "")
        return PaperRecord(
            uid=paper_id or url,
            title=str(paper.get("title") or paper_id),
            types=["conference-paper"],
            source_types=[presentation] if presentation else ["conference-paper"],
            source=PaperSource(source_title=conference, publish_year=year),
            names=PaperNames(authors=authors),
            links=PaperLinks(record=url, landing_page=url),
            identifiers=PaperIdentifiers(),
            keywords=PaperKeywords(author_keywords=keywords),
            abstract=str(paper.get("abstract") or ""),
            provider="paperhub",
            raw=paper,
        )
