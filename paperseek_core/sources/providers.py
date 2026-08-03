
from concurrent.futures import ThreadPoolExecutor
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


@dataclass
class PaperAuthor:
    display_name: str = ""
    wos_standard: str = ""
    researcher_id: str = ""


@dataclass
class PaperNames:
    authors: List[PaperAuthor] = field(default_factory=list)


@dataclass
class PaperSource:
    source_title: str = ""
    publish_year: Optional[int] = None
    publish_month: str = ""
    volume: str = ""
    issue: str = ""
    pages: Any = None


@dataclass
class PaperLinks:
    record: str = ""
    citing_articles: str = ""
    references: str = ""
    related: str = ""
    landing_page: str = ""
    pdf: str = ""


@dataclass
class PaperCitation:
    db: str = ""
    count: int = 0


@dataclass
class PaperIdentifiers:
    doi: str = ""
    issn: str = ""
    eissn: str = ""
    isbn: str = ""
    eisbn: str = ""
    pmid: str = ""
    openalex: str = ""
    arxiv: str = ""
    semanticscholar: str = ""


@dataclass
class PaperKeywords:
    author_keywords: List[str] = field(default_factory=list)


@dataclass
class PaperRecord:
    uid: str
    title: str = ""
    types: List[str] = field(default_factory=list)
    source_types: List[str] = field(default_factory=list)
    source: Optional[PaperSource] = None
    names: Optional[PaperNames] = None
    links: Optional[PaperLinks] = None
    citations: List[PaperCitation] = field(default_factory=list)
    identifiers: Optional[PaperIdentifiers] = None
    keywords: Optional[PaperKeywords] = None
    abstract: str = ""
    provider: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


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


class OpenAlexProvider:
    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, api_key: str = "", email: str = ""):
        self.api_key = (api_key or "").strip()
        self.email = (email or "").strip()
        self.last_response_info: Dict[str, Any] = {}

    def retrieval_capabilities(self) -> ProviderRetrievalCapabilities:
        lanes = [RetrievalLane.RELEVANCE]
        if self.api_key:
            lanes.append(RetrievalLane.SEMANTIC)
        lanes.extend((RetrievalLane.IMPACT, RetrievalLane.RECENT))
        return ProviderRetrievalCapabilities(
            source="openalex",
            lanes=tuple(lanes),
            lane_concurrency=2,
        )

    def search(
        self,
        query: str,
        limit: int = 50,
        page: int = 1,
        field_ids: Optional[Sequence[str]] = None,
        lane: str = RetrievalLane.RELEVANCE,
    ) -> ProviderSearchResult:
        query = (query or "").strip()
        if not query:
            raise ProviderError("openalex", "OpenAlex search query is empty.")
        if lane == RetrievalLane.SEMANTIC and not self.api_key:
            raise ProviderError("openalex", "OpenAlex semantic search requires an API key.", query=query)

        page_limit = 50 if lane == RetrievalLane.SEMANTIC else 100
        page_size = max(1, min(int(limit or 10), page_limit))
        params = {
            "per-page": page_size,
            "page": max(1, int(page or 1)),
            "select": ",".join([
                "id",
                "doi",
                "title",
                "display_name",
                "publication_year",
                "publication_date",
                "type",
                "type_crossref",
                "authorships",
                "primary_location",
                "cited_by_count",
                "abstract_inverted_index",
                "open_access",
                "keywords",
                "concepts",
                "ids",
                "primary_topic",
                "referenced_works",
            ]),
        }
        if lane == RetrievalLane.SEMANTIC:
            params["search.semantic"] = query
        else:
            params["search"] = query
        normalized_field_ids = self._normalize_field_ids(field_ids)
        if normalized_field_ids:
            params["filter"] = self._field_filter_clause(normalized_field_ids)
        if lane == RetrievalLane.IMPACT:
            params["sort"] = "cited_by_count:desc"
        elif lane == RetrievalLane.RECENT:
            params["sort"] = "publication_date:desc"
        elif lane == RetrievalLane.RELEVANCE:
            params["sort"] = "relevance_score:desc"
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["mailto"] = self.email

        headers = {
            "Accept": "application/json",
            "User-Agent": self._user_agent(),
        }

        try:
            response, info = get_with_retries("openalex", self.BASE_URL, params=params, headers=headers, timeout=45, query=query)
            self.last_response_info = info
        except ProviderError as exc:
            self.last_response_info = {"method": "GET", "url": self.BASE_URL, "status": "request_error", "elapsed_ms": None}
            raise exc


        if response.status_code >= 400:
            raise ProviderError(
                "openalex",
                f"OpenAlex returned HTTP {response.status_code}.",
                status=response.status_code,
                body=response.text[:1000],
                query=query,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("openalex", "OpenAlex returned a non-JSON response.", body=response.text[:1000], query=query) from exc

        meta = payload.get("meta") or {}
        works = payload.get("results") or []
        records = [self._to_record(work) for work in works if isinstance(work, dict)]

        return ProviderSearchResult(
            metadata=SearchMetadata(
                total=int(meta.get("count") or 0),
                page=int(meta.get("page") or page),
                limit=int(meta.get("per_page") or page_size),
            ),
            hits=records,
        )

    def citation_neighbors(
        self,
        seeds: List[PaperRecord],
        per_seed: int = 4,
        max_records: int = 40,
        field_ids: Optional[Sequence[str]] = None,
    ) -> List[PaperRecord]:
        return self.citation_neighbors_with_graph(seeds, per_seed=per_seed, max_records=max_records, field_ids=field_ids)["records"]

    def citation_neighbors_with_graph(
        self,
        seeds: List[PaperRecord],
        per_seed: int = 4,
        max_records: int = 40,
        field_ids: Optional[Sequence[str]] = None,
        seed_plans: Optional[Sequence[Any]] = None,
        depth: int = 1,
        cancel_check: Optional[Callable[[], None]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        request_attempts: int = 3,
        request_timeout: int = 30,
    ) -> Dict[str, Any]:
        """Fetch forward and backward citation neighbors for seed OpenAlex works."""
        per_seed = max(1, min(int(per_seed or 4), 10))
        max_records = max(1, min(int(max_records or 40), 500))
        depth = max(1, min(int(depth or 1), 3))
        request_attempts = max(1, min(int(request_attempts or 3), 3))
        request_timeout = max(5, min(int(request_timeout or 30), 30))
        normalized_field_ids = self._normalize_field_ids(field_ids)
        output: List[PaperRecord] = []
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, str]] = []
        seen = set()
        expanded = set()
        direction_budget = max(1, int(math.ceil(max_records * 0.7)))
        request_budget = max(1, max_records)
        direction_stats = {
            direction: {"budget": direction_budget, "requests": 0, "fetched": 0, "added": 0, "duplicates": 0, "filtered": 0}
            for direction in ("backward", "forward")
        }
        depth_stats: Dict[str, Dict[str, int]] = {}
        processed_plans = 0
        consecutive_empty_plans = 0
        stop_reason = ""

        def request_count() -> int:
            return sum(stats["requests"] for stats in direction_stats.values())

        def check_cancelled() -> None:
            if cancel_check:
                cancel_check()

        def emit_progress(**payload: Any) -> None:
            if progress_callback:
                progress_callback(payload)

        def add_node(record: PaperRecord, role: str, seed_uid: str = ""):
            node_id = record.uid or (record.identifiers.openalex if record.identifiers else "") or record.title
            if not node_id:
                return
            source = record.source
            citations = sum((c.count or 0) for c in (record.citations or []))
            existing = nodes.get(node_id)
            if existing:
                if role not in existing["roles"]:
                    existing["roles"].append(role)
                if seed_uid and seed_uid not in existing["seed_uids"]:
                    existing["seed_uids"].append(seed_uid)
                return
            nodes[node_id] = {
                "id": node_id,
                "title": record.title or "(no title)",
                "year": source.publish_year if source else None,
                "source": source.source_title if source else "",
                "citations": citations,
                "roles": [role],
                "seed_uids": [seed_uid] if seed_uid else [],
            }

        def add_record(record: Optional[PaperRecord]) -> bool:
            if not record:
                return False
            key = (record.uid or "").lower()
            doi = ((record.identifiers.doi if record.identifiers else "") or "").lower()
            dedupe = key or doi
            if not dedupe or dedupe in seen:
                return False
            seen.add(dedupe)
            output.append(record)
            return True

        def normalize_seed_plans() -> List[CitationSeedPlan]:
            plans: List[CitationSeedPlan] = []
            raw_plans = seed_plans or [
                {"record": seed, "role": "relevance", "directions": ("backward", "forward"), "depth": depth}
                for seed in (seeds or [])
            ]
            for item in raw_plans:
                if isinstance(item, CitationSeedPlan):
                    plan = item
                elif isinstance(item, dict):
                    record = item.get("record") or item.get("seed")
                    if not isinstance(record, PaperRecord):
                        continue
                    directions = tuple(
                        direction
                        for direction in (item.get("directions") or ("backward", "forward"))
                        if direction in ("backward", "forward")
                    )
                    plan = CitationSeedPlan(
                        record=record,
                        role=str(item.get("role") or "relevance"),
                        directions=directions or ("backward", "forward"),
                        depth=max(1, min(int(item.get("depth") or depth), 3)),
                    )
                elif isinstance(item, PaperRecord):
                    plan = CitationSeedPlan(record=item, depth=depth)
                else:
                    continue
                plans.append(plan)
            return plans

        def append_neighbor(
            *,
            seed_uid: str,
            parent_uid: str,
            record: Optional[PaperRecord],
            direction: str,
            layer: int,
            next_frontier: List[PaperRecord],
            frontier_seen: set,
        ) -> bool:
            if not record:
                return False
            if not self._record_matches_field_ids(record, normalized_field_ids):
                direction_stats[direction]["filtered"] += 1
                layer_stats = depth_stats.setdefault(
                    str(layer),
                    {"expanded_items": 0, "fetched": 0, "added": 0, "duplicates": 0, "filtered": 0},
                )
                layer_stats["filtered"] += 1
                return False
            record_uid = record.uid or (record.identifiers.openalex if record.identifiers else "") or record.title
            if not record_uid:
                return False
            role = "backward" if direction == "backward" else "forward"
            add_node(record, role, seed_uid)
            if direction == "backward":
                edge = {
                    "source": parent_uid,
                    "target": record_uid,
                    "type": "references",
                    "seed": seed_uid,
                    "layer": str(layer),
                }
            else:
                edge = {
                    "source": record_uid,
                    "target": parent_uid,
                    "type": "cites",
                    "seed": seed_uid,
                    "layer": str(layer),
                }
            edges.append(edge)
            added = add_record(record)
            layer_stats = depth_stats.setdefault(
                str(layer),
                {"expanded_items": 0, "fetched": 0, "added": 0, "duplicates": 0, "filtered": 0},
            )
            if added:
                direction_stats[direction]["added"] += 1
                layer_stats["added"] += 1
            else:
                direction_stats[direction]["duplicates"] += 1
                layer_stats["duplicates"] += 1
            if layer < depth and record_uid not in frontier_seen:
                frontier_seen.add(record_uid)
                next_frontier.append(record)
            return added

        plans = normalize_seed_plans()
        role_count = len({role for plan in plans for role in str(plan.role or "relevance").split("+")})
        minimum_plans_before_yield_stop = min(len(plans), max(6, role_count * 2))
        emit_progress(event="start", current=0, total=len(plans), records=0, edges=0)
        for plan_index, plan in enumerate(plans, 1):
            check_cancelled()
            if len(output) >= max_records:
                stop_reason = "max_records"
                break
            if request_count() >= request_budget:
                stop_reason = "request_budget"
                break
            seed = plan.record
            seed_id = self._openalex_work_id(seed)
            if not seed_id:
                continue
            plan_output_before = len(output)
            remaining_plans = max(1, len(plans) - plan_index + 1)
            plan_record_budget = max(1, int(math.ceil((max_records - len(output)) / remaining_plans)))
            seed_uid = seed.uid or (seed.identifiers.openalex if seed.identifiers else "") or seed_id
            add_node(seed, "seed")
            add_node(seed, f"seed_{plan.role}", seed_uid)
            frontier = [seed]
            frontier_seen = {seed_uid}
            for layer in range(1, max(1, min(plan.depth, depth)) + 1):
                check_cancelled()
                next_frontier: List[PaperRecord] = []
                layer_output_before = len(output)
                layer_stats = depth_stats.setdefault(
                    str(layer),
                    {"expanded_items": 0, "fetched": 0, "added": 0, "duplicates": 0, "filtered": 0},
                )
                for current in frontier:
                    check_cancelled()
                    if (
                        len(output) >= max_records
                        or len(output) - plan_output_before >= plan_record_budget
                        or request_count() >= request_budget
                    ):
                        break
                    current_id = self._openalex_work_id(current)
                    if not current_id:
                        continue
                    layer_stats["expanded_items"] += 1
                    current_uid = current.uid or (current.identifiers.openalex if current.identifiers else "") or current_id
                    direction_jobs: Dict[str, Any] = {}
                    references = list(((getattr(current, "raw", None) or {}).get("referenced_works") or [])[:per_seed])
                    backward_key = (current_id, "backward", layer)
                    if (
                        references
                        and "backward" in plan.directions
                        and direction_stats["backward"]["added"] < direction_budget
                        and request_count() < request_budget
                        and backward_key not in expanded
                    ):
                        expanded.add(backward_key)
                        direction_jobs["backward"] = references

                    forward_key = (current_id, "forward", layer)
                    if (
                        "forward" in plan.directions
                        and direction_stats["forward"]["added"] < direction_budget
                        and request_count() + len(direction_jobs) < request_budget
                        and forward_key not in expanded
                    ):
                        expanded.add(forward_key)
                        direction_jobs["forward"] = current_id

                    direction_records: Dict[str, List[PaperRecord]] = {}
                    if direction_jobs:
                        workers = min(2, len(direction_jobs))
                        with ThreadPoolExecutor(max_workers=workers) as executor:
                            future_to_direction = {}
                            if "backward" in direction_jobs:
                                direction_stats["backward"]["requests"] += 1
                                future_to_direction[
                                    executor.submit(
                                        self._fetch_works,
                                        direction_jobs["backward"],
                                        attempts=request_attempts,
                                        timeout=request_timeout,
                                    )
                                ] = "backward"
                            if "forward" in direction_jobs:
                                direction_stats["forward"]["requests"] += 1
                                future_to_direction[
                                    executor.submit(
                                        self._fetch_forward_citations,
                                        direction_jobs["forward"],
                                        per_seed,
                                        field_ids=normalized_field_ids,
                                        attempts=request_attempts,
                                        timeout=request_timeout,
                                    )
                                ] = "forward"
                            for future, direction in future_to_direction.items():
                                check_cancelled()
                                try:
                                    direction_records[direction] = list(future.result() or [])
                                except ProviderError:
                                    direction_records[direction] = []

                    for direction in ("backward", "forward"):
                        records = direction_records.get(direction, [])
                        direction_stats[direction]["fetched"] += len(records)
                        layer_stats["fetched"] += len(records)
                        for record in records:
                            check_cancelled()
                            if (
                                len(output) >= max_records
                                or len(output) - plan_output_before >= plan_record_budget
                                or direction_stats[direction]["added"] >= direction_budget
                            ):
                                break
                            append_neighbor(
                                seed_uid=seed_uid,
                                parent_uid=current_uid,
                                record=record,
                                direction=direction,
                                layer=layer,
                                next_frontier=next_frontier,
                                frontier_seen=frontier_seen,
                            )
                    if len(output) >= max_records or len(output) - plan_output_before >= plan_record_budget:
                        break
                frontier = next_frontier
                layer_added = len(output) - layer_output_before
                if layer_added == 0 and layer < max(1, min(plan.depth, depth)):
                    break
                if (
                    not frontier
                    or len(output) >= max_records
                    or len(output) - plan_output_before >= plan_record_budget
                ):
                    break
            processed_plans += 1
            plan_added = len(output) - plan_output_before
            consecutive_empty_plans = consecutive_empty_plans + 1 if plan_added == 0 else 0
            emit_progress(event="seed_complete", current=plan_index, total=len(plans), records=len(output), edges=len(edges))

            if len(output) >= max_records:
                stop_reason = "max_records"
                break
            if request_count() >= request_budget:
                stop_reason = "request_budget"
                break
            if (
                processed_plans >= minimum_plans_before_yield_stop
                and consecutive_empty_plans >= 3
                and plan_index < len(plans)
            ):
                stop_reason = "low_yield"
                break

        if not stop_reason:
            stop_reason = "completed"
        frontier_state = {
            "planned_items": len(plans),
            "processed_items": processed_plans,
            "skipped_items": max(0, len(plans) - processed_plans),
            "request_count": request_count(),
            "request_budget": request_budget,
            "stop_reason": stop_reason,
            "direction_stats": direction_stats,
            "depth_stats": depth_stats,
        }

        return {"records": output, "nodes": list(nodes.values()), "edges": edges, "frontier": frontier_state}

    @classmethod
    def _normalize_field_ids(cls, field_ids: Optional[Sequence[str]]) -> List[str]:
        ids: List[str] = []
        for field_id in field_ids or []:
            normalized = cls._normalize_openalex_id(str(field_id))
            if normalized and normalized not in ids:
                ids.append(normalized)
        return ids

    @staticmethod
    def _field_filter_clause(field_ids: Sequence[str]) -> str:
        ids = [str(field_id).strip() for field_id in (field_ids or []) if str(field_id).strip()]
        return "primary_topic.field.id:" + "|".join(ids) if ids else ""

    @classmethod
    def _record_matches_field_ids(cls, record: PaperRecord, field_ids: Sequence[str]) -> bool:
        if not field_ids:
            return True
        raw = record.raw if isinstance(getattr(record, "raw", None), dict) else {}
        primary_topic = raw.get("primary_topic") or {}
        field = primary_topic.get("field") or {}
        work_field_id = cls._normalize_openalex_id(str(field.get("id") or ""))
        return bool(work_field_id and work_field_id in field_ids)

    def _base_params(self) -> Dict[str, str]:
        params: Dict[str, str] = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["mailto"] = self.email
        return params

    def _fetch_work(self, openalex_id: str, *, attempts: int = 3, timeout: int = 30) -> Optional[PaperRecord]:
        identifier = self._normalize_openalex_id(openalex_id)
        if not identifier:
            return None
        url = f"{self.BASE_URL}/{identifier}"
        headers = {"Accept": "application/json", "User-Agent": self._user_agent()}
        try:
            response, info = get_with_retries(
                "openalex",
                url,
                params=self._base_params(),
                headers=headers,
                timeout=timeout,
                query=identifier,
                attempts=attempts,
            )
            self.last_response_info = info
        except ProviderError as exc:
            self.last_response_info = {"method": "GET", "url": url, "status": "request_error", "elapsed_ms": None}
            raise exc

        if response.status_code >= 400:
            raise ProviderError("openalex", f"OpenAlex returned HTTP {response.status_code}.", status=response.status_code, body=response.text[:1000], query=identifier)
        try:
            work = response.json()
        except ValueError as exc:
            raise ProviderError("openalex", "OpenAlex returned a non-JSON citation response.", body=response.text[:1000], query=identifier) from exc
        return self._to_record(work) if isinstance(work, dict) else None

    def _fetch_works(
        self,
        openalex_ids: Sequence[str],
        *,
        attempts: int = 3,
        timeout: int = 30,
    ) -> List[PaperRecord]:
        identifiers: List[str] = []
        for value in openalex_ids or []:
            identifier = self._normalize_openalex_id(str(value or ""))
            if identifier and identifier not in identifiers:
                identifiers.append(identifier)
            if len(identifiers) >= 100:
                break
        if not identifiers:
            return []

        params = self._base_params()
        params.update({
            "filter": "openalex:" + "|".join(identifiers),
            "per-page": len(identifiers),
            "select": ",".join([
                "id",
                "doi",
                "title",
                "display_name",
                "publication_year",
                "publication_date",
                "type",
                "type_crossref",
                "authorships",
                "primary_location",
                "cited_by_count",
                "abstract_inverted_index",
                "open_access",
                "keywords",
                "concepts",
                "ids",
                "primary_topic",
                "referenced_works",
            ]),
        })
        headers = {"Accept": "application/json", "User-Agent": self._user_agent()}
        query = "|".join(identifiers)
        try:
            response, info = get_with_retries(
                "openalex",
                self.BASE_URL,
                params=params,
                headers=headers,
                timeout=timeout,
                query=query,
                attempts=attempts,
            )
            self.last_response_info = info
        except ProviderError as exc:
            self.last_response_info = {
                "method": "GET",
                "url": self.BASE_URL,
                "status": "request_error",
                "elapsed_ms": None,
            }
            raise exc

        if response.status_code >= 400:
            raise ProviderError(
                "openalex",
                f"OpenAlex returned HTTP {response.status_code}.",
                status=response.status_code,
                body=response.text[:1000],
                query=query,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                "openalex",
                "OpenAlex returned a non-JSON batched citation response.",
                body=response.text[:1000],
                query=query,
            ) from exc
        records = [
            self._to_record(work)
            for work in ((payload or {}).get("results") or [])
            if isinstance(work, dict)
        ]
        records_by_id = {self._openalex_work_id(record): record for record in records}
        return [records_by_id[identifier] for identifier in identifiers if identifier in records_by_id]

    def _fetch_forward_citations(
        self,
        seed_id: str,
        limit: int,
        field_ids: Optional[Sequence[str]] = None,
        *,
        attempts: int = 3,
        timeout: int = 30,
    ) -> List[PaperRecord]:
        params = self._base_params()
        filter_parts = [f"cites:{seed_id}"]
        field_clause = self._field_filter_clause(self._normalize_field_ids(field_ids))
        if field_clause:
            filter_parts.append(field_clause)
        params.update({
            "filter": ",".join(filter_parts),
            "sort": "cited_by_count:desc",
            "per-page": max(1, min(int(limit or 4), 10)),
            "select": ",".join([
                "id",
                "doi",
                "title",
                "display_name",
                "publication_year",
                "publication_date",
                "type",
                "type_crossref",
                "authorships",
                "primary_location",
                "cited_by_count",
                "abstract_inverted_index",
                "open_access",
                "keywords",
                "concepts",
                "ids",
                "primary_topic",
                "referenced_works",
            ]),
        })
        headers = {"Accept": "application/json", "User-Agent": self._user_agent()}
        try:
            response, info = get_with_retries(
                "openalex",
                self.BASE_URL,
                params=params,
                headers=headers,
                timeout=timeout,
                query=seed_id,
                attempts=attempts,
            )
            self.last_response_info = info
        except ProviderError as exc:
            self.last_response_info = {"method": "GET", "url": self.BASE_URL, "status": "request_error", "elapsed_ms": None}
            raise exc

        if response.status_code >= 400:
            raise ProviderError("openalex", f"OpenAlex returned HTTP {response.status_code}.", status=response.status_code, body=response.text[:1000], query=seed_id)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("openalex", "OpenAlex returned a non-JSON forward citation response.", body=response.text[:1000], query=seed_id) from exc
        return [self._to_record(work) for work in (payload.get("results") or []) if isinstance(work, dict)]

    def _user_agent(self) -> str:
        if self.email:
            return f"paperseek/1.0 (mailto:{self.email})"
        return "paperseek/1.0"

    def _to_record(self, work: Dict[str, Any]) -> PaperRecord:
        openalex_id = work.get("id") or ""
        title = self._clean_metadata_text(work.get("title") or work.get("display_name") or "")
        primary_location = work.get("primary_location") or {}
        source_obj = primary_location.get("source") or {}
        source_title = self._clean_metadata_text(source_obj.get("display_name") or "")
        landing_page = primary_location.get("landing_page_url") or ""
        pdf_url = (primary_location.get("pdf_url") or "")

        authors = []
        for authorship in work.get("authorships") or []:
            author_obj = authorship.get("author") or {}
            display = self._clean_metadata_text(author_obj.get("display_name") or "")
            if display:
                authors.append(PaperAuthor(display_name=display, wos_standard=display))

        keywords = self._extract_keywords(work)
        abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
        doi = normalize_doi(work.get("doi") or "")
        ids = work.get("ids") or {}

        work_type = work.get("type") or work.get("type_crossref") or ""
        record_url = openalex_id or landing_page
        cited_by_count = int(work.get("cited_by_count") or 0)

        return PaperRecord(
            uid=openalex_id or title,
            title=title,
            types=[work_type] if work_type else [],
            source_types=[work_type] if work_type else [],
            source=PaperSource(
                source_title=source_title,
                publish_year=work.get("publication_year"),
            ),
            names=PaperNames(authors=authors),
            links=PaperLinks(record=record_url, landing_page=landing_page, pdf=pdf_url),
            citations=[PaperCitation(db="OpenAlex", count=cited_by_count)] if cited_by_count else [],
            identifiers=PaperIdentifiers(
                doi=doi,
                openalex=openalex_id,
                pmid=(ids.get("pmid") or "").replace("https://pubmed.ncbi.nlm.nih.gov/", ""),
            ),
            keywords=PaperKeywords(author_keywords=keywords),
            abstract=abstract,
            provider="openalex",
            raw=work,
        )

    @staticmethod
    def _clean_metadata_text(value: Any) -> str:
        text = unescape(str(value or ""))
        text = re.sub(r"\\[nrt]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize_openalex_id(value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        return value.rstrip("/").split("/")[-1]

    def _openalex_work_id(self, record: PaperRecord) -> str:
        identifiers = record.identifiers
        value = (identifiers.openalex if identifiers else "") or record.uid or ""
        return self._normalize_openalex_id(value)

    @staticmethod
    def _extract_keywords(work: Dict[str, Any]) -> List[str]:
        terms = []
        for item in work.get("keywords") or []:
            value = item.get("display_name") or item.get("keyword") or item.get("name")
            if value and value not in terms:
                terms.append(value)
        if terms:
            return terms[:10]

        for item in work.get("concepts") or []:
            value = item.get("display_name")
            if value and value not in terms:
                terms.append(value)
        return terms[:10]


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


class GoogleScholarSerperProvider:
    BASE_URL = "https://google.serper.dev/scholar"

    def __init__(self, api_key: str = ""):
        self.api_keys = _split_api_keys(api_key)
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
                    time.sleep(_retry_delay(response, attempt, "googlescholar"))
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
        detail = _redact_request_text(last_exc)
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
