from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Sequence
import math
import re

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
from paperseek_core.sources.contracts import CitationSeedPlan, ProviderError, ProviderSearchResult, SearchMetadata
from paperseek_core.sources.http import get_with_retries
from paperseek_core.sources.normalization import normalize_doi, reconstruct_abstract

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
                        executor = ThreadPoolExecutor(max_workers=workers)
                        try:
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
                            pending = set(future_to_direction)
                            while pending:
                                done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                                check_cancelled()
                                for future in done:
                                    direction = future_to_direction[future]
                                    try:
                                        direction_records[direction] = list(future.result() or [])
                                    except ProviderError:
                                        direction_records[direction] = []
                        except BaseException:
                            executor.shutdown(wait=False, cancel_futures=True)
                            executor = None
                            raise
                        finally:
                            if executor is not None:
                                executor.shutdown(wait=True)

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
