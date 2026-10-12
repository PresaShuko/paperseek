"""Bounded citation planning, traversal recovery, provenance, and checkpoints."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from paperseek_core.models import (
    CheckpointDraft,
    CitationEdge,
    CitationExpansionRequest,
    CitationExpansionResult,
    CitationSeedPlan,
    CitationSourceRequest,
    CitationSourceResult,
    CoreProgressEvent,
    PaperRecord,
)
from paperseek_core.execution import NEVER_CANCELLED, record_checkpoint
from paperseek_core.http_retry import failure_details
from paperseek_core.ports import CancellationToken, CitationPort, WorkflowObserver
from paperseek_core.document_identity import document_key
from paperseek_core.sources.contracts import SourceError


def _citation_count(document: PaperRecord) -> int:
    return sum(int(citation.count or 0) for citation in document.citations)


def _seed_key(document: PaperRecord) -> str:
    identifiers = document.identifiers
    for value in (
        identifiers.openalex if identifiers else "",
        identifiers.doi if identifiers else "",
        document.uid,
        document.title,
    ):
        normalized = str(value or "").strip().casefold()
        if normalized:
            return normalized
    return ""


def _ranked_entry(entry: Any) -> tuple[PaperRecord | None, float]:
    if isinstance(entry, tuple) and len(entry) >= 2:
        return entry[0], float(entry[1] or 0)
    if isinstance(entry, dict):
        return entry.get("document"), float(entry.get("score") or 0)
    document = getattr(entry, "document", None)
    return document, float(getattr(entry, "score", 0) or 0)


def build_seed_plans(
    seed_ranked: list[Any],
    candidates: list[PaperRecord],
    *,
    seed_limit: int,
    depth: int,
) -> list[CitationSeedPlan]:
    """Preserve the frozen relevance/impact/recent seed quotas and ordering."""
    seed_limit = max(1, int(seed_limit or 1))
    depth = max(1, min(int(depth or 1), 3))
    relevance_quota = max(1, seed_limit // 2)
    impact_quota = max(1, seed_limit // 4) if seed_limit > 1 else 0
    recent_quota = max(0, seed_limit - relevance_quota - impact_quota)
    plans: list[CitationSeedPlan] = []
    index_by_key: dict[str, int] = {}

    def add_plan(document: PaperRecord | None, role: str, directions: tuple[str, ...]) -> None:
        if document is None:
            return
        key = _seed_key(document)
        if not key or (len(plans) >= seed_limit and key not in index_by_key):
            return
        if key in index_by_key:
            index = index_by_key[key]
            existing = plans[index]
            merged_directions = tuple(dict.fromkeys((*existing.directions, *directions)))
            roles = existing.role.split("+")
            merged_role = existing.role if role in roles else f"{existing.role}+{role}"
            plans[index] = existing.model_copy(
                update={"directions": merged_directions, "role": merged_role, "depth": max(existing.depth, depth)}
            )
            return
        index_by_key[key] = len(plans)
        plans.append(
            CitationSeedPlan(record=document, role=role, directions=directions, depth=depth)
        )

    ranked = [_ranked_entry(entry) for entry in seed_ranked]
    relevant = [document for document, score in ranked if document is not None and score >= 7]
    if len(relevant) < relevance_quota:
        for document, _ in ranked:
            if document is not None and document not in relevant:
                relevant.append(document)
            if len(relevant) >= relevance_quota:
                break
    for document in relevant[:relevance_quota]:
        add_plan(document, "relevance", ("backward", "forward"))

    impact = sorted(
        candidates,
        key=lambda document: (
            _citation_count(document),
            document.source.publish_year if document.source and document.source.publish_year else 0,
        ),
        reverse=True,
    )
    for document in impact[:impact_quota]:
        add_plan(document, "impact", ("backward",))

    recent = sorted(
        candidates,
        key=lambda document: (
            document.source.publish_year if document.source and document.source.publish_year else 0,
            _citation_count(document),
        ),
        reverse=True,
    )
    for document in recent[:recent_quota]:
        add_plan(document, "recent", ("forward",))

    if len(plans) < seed_limit:
        for document, _ in ranked:
            add_plan(document, "relevance", ("backward", "forward"))
            if len(plans) >= seed_limit:
                break

    buckets: dict[str, list[CitationSeedPlan]] = {"relevance": [], "impact": [], "recent": []}
    for plan in plans:
        roles = set(plan.role.split("+"))
        bucket = "recent" if "recent" in roles else "impact" if "impact" in roles else "relevance"
        buckets[bucket].append(plan)
    interleaved: list[CitationSeedPlan] = []
    while any(buckets.values()):
        for role in ("relevance", "impact", "recent"):
            if buckets[role]:
                interleaved.append(buckets[role].pop(0))
    return interleaved


def _plan_counts(plans: list[CitationSeedPlan]) -> dict[str, int]:
    counts = {"relevance": 0, "impact": 0, "recent": 0}
    for plan in plans:
        for role in plan.role.split("+"):
            if role in counts:
                counts[role] += 1
    return counts


def select_seed_candidates(
    candidates: list[PaperRecord],
    lanes: dict[str, list[PaperRecord]],
    view_types: dict[str, str],
    *,
    limit: int,
) -> list[PaperRecord]:
    """Preserve the frozen successor-view and other-view seed quotas."""
    candidate_by_key = {document_key(document): document for document in candidates}
    selected: list[PaperRecord] = []
    selected_keys: set[str] = set()

    def add(documents: list[PaperRecord], quota: int) -> None:
        added = 0
        for document in documents:
            key = document_key(document)
            if not key or key not in candidate_by_key or key in selected_keys:
                continue
            selected.append(candidate_by_key[key])
            selected_keys.add(key)
            added += 1
            if len(selected) >= limit or added >= quota:
                break

    successors = [view for view, kind in view_types.items() if kind == "successor_paradigm" and view in lanes]
    for view in successors:
        add(lanes[view], max(1, limit // 2))
        if len(selected) >= limit:
            return selected
    others = [view for view in lanes if view not in successors]
    quota = max(1, max(0, limit * 3 // 4 - len(selected)) // max(1, len(others)))
    for view in others:
        add(lanes[view], quota)
        if len(selected) >= limit:
            return selected
    add(candidates, limit - len(selected))
    return selected


def _aliases(document: PaperRecord) -> set[str]:
    aliases = {document_key(document)} if document_key(document) else set()
    identifiers = document.identifiers
    for name in ("doi", "openalex", "arxiv", "semanticscholar", "pmid"):
        value = str(getattr(identifiers, name, "") if identifiers else "").strip().casefold()
        if value:
            aliases.add(f"{name}:{value}")
    uid = str(document.uid or "").strip().casefold()
    if uid:
        aliases.add(f"uid:{uid}")
    return aliases


def _dedupe(documents: list[PaperRecord]) -> list[PaperRecord]:
    output: list[PaperRecord] = []
    seen: set[str] = set()
    for document in documents:
        aliases = _aliases(document)
        if not aliases or aliases & seen:
            continue
        seen.update(aliases)
        output.append(document)
    return output


class CitationPipeline:
    def __init__(
        self,
        source: Any,
        observer: WorkflowObserver,
        *,
        cancellation: CancellationToken = NEVER_CANCELLED,
    ) -> None:
        self.source = source
        self.observer = observer
        self.cancellation = cancellation

    async def run(self, request: CitationExpansionRequest) -> CitationExpansionResult:
        self.cancellation.raise_if_cancelled()
        candidates = _dedupe(list(request.candidates))
        supported = bool(
            getattr(getattr(self.source, "capabilities", None), "supports_citation_expansion", False)
            and isinstance(self.source, CitationPort)
        )
        citation_map: dict[str, Any] = {
            "enabled": bool(request.enabled),
            "supported": supported,
            "status": "waiting",
            "initial_candidates": len(candidates),
            "seed_count": 0,
            "added_candidates": 0,
            "candidate_pool": len(candidates),
            "nodes": [],
            "edges": [],
        }
        if not candidates or not request.enabled:
            return CitationExpansionResult(candidates=candidates, citation_map=citation_map)
        if not supported:
            citation_map.update({"supported": False, "status": "unsupported"})
            self._event("citation.skipped", {"code": "citation_expansion_unsupported"})
            return CitationExpansionResult(candidates=candidates, citation_map=citation_map)
        if request.source_rate_limited:
            code = "citation_expansion_skipped_rate_limited"
            citation_map.update({"supported": True, "status": "rate_limited"})
            self._event("citation.degraded", {"code": code})
            return CitationExpansionResult(candidates=candidates, citation_map=citation_map, warnings=[code])

        seed_count = max(1, int(request.seed_count or 30))
        depth = max(1, min(int(request.depth or 2), 3))
        selection_limit = max(seed_count * 4, 64)
        seed_candidates = _dedupe(list(request.seed_candidates or candidates))[:selection_limit]
        seed_ranked = [(document, 10) for document in seed_candidates]
        plans = build_seed_plans(seed_ranked, candidates, seed_limit=seed_count, depth=depth)
        if not plans:
            citation_map["status"] = "no_seeds"
            self._event("citation.skipped", {"code": "citation_expansion_no_seeds"})
            return CitationExpansionResult(candidates=candidates, citation_map=citation_map)

        per_seed = max(1, int(request.per_seed or 4))
        max_records = max(1, int(request.max_records or 160))
        self._event(
            "citation.started",
            {
                "candidate_count": len(candidates),
                "seed_count": len(plans),
                "depth": depth,
                "per_seed": per_seed,
                "max_records": max_records,
            },
        )
        traversal: CitationSourceResult | None = None
        for attempt in range(2):
            self.cancellation.raise_if_cancelled()
            source_request = CitationSourceRequest(
                seed_plans=plans,
                per_seed=per_seed,
                max_records=max_records,
                field_ids=request.field_ids,
                depth=depth,
                request_attempts=3,
                request_timeout=10,
            )
            try:
                traversal = await self.source.traverse_citations(source_request)
                self.cancellation.raise_if_cancelled()
                break
            except Exception as exc:
                if attempt == 0 and self._retryable(exc):
                    per_seed = max(1, per_seed // 2)
                    max_records = max(1, max_records // 2)
                    depth = 1
                    self._event(
                        "citation.retrying",
                        {
                            "code": "citation_retry_reduced",
                            "per_seed": per_seed,
                            "max_records": max_records,
                            "depth": depth,
                        },
                    )
                    continue
                code = "citation_expansion_failed_base_candidates_retained"
                citation_map.update({"status": "error", "error_type": type(exc).__name__})
                self._event("citation.degraded", {"code": code, "error_type": type(exc).__name__, **failure_details(exc)})
                return CitationExpansionResult(
                    candidates=candidates,
                    citation_map=citation_map,
                    warnings=[code],
                )

        if traversal is None:
            raise AssertionError("citation traversal finished without a result")
        related = _dedupe(list(traversal.records))
        combined = _dedupe([*candidates, *related])
        added = combined[len(candidates):]
        edges = [edge.to_citation_map() for edge in traversal.edges]
        citation_map.update(
            {
                "enabled": True,
                "supported": True,
                "status": "complete",
                "initial_candidates": len(candidates),
                "seed_count": len(plans),
                "seed_plan_counts": _plan_counts(plans),
                "citation_depth": depth,
                "frontier": dict(traversal.frontier),
                "added_candidates": len(added),
                "candidate_pool": len(combined),
                "nodes": list(traversal.nodes),
                "edges": edges,
            }
        )
        provenance = self._provenance(added, traversal.edges)
        if self.observer.on_checkpoint is not None:
            checkpoint = CheckpointDraft(
                step_key="expand_citations",
                idempotency_key=self._idempotency_key(plans, per_seed, max_records, depth),
                state={
                    "citation_frontier": dict(traversal.frontier),
                    "citation_map": citation_map,
                    "candidate_ids": [document.uid for document in combined],
                    "candidates": [document.model_dump(mode="json") for document in combined],
                    "provenance_by_identity": provenance,
                    "warnings": [],
                    "resume_from_stage": "post_citation",
                },
                workflow_version="m2.citation.v1",
            )
            self.cancellation.raise_if_cancelled()
            await record_checkpoint(self.observer, checkpoint)
        self._event(
            "citation.progress",
            {"processed_seeds": len(plans), "seed_count": len(plans), "added_candidates": len(added)},
        )
        self._event(
            "citation.completed",
            {
                "seed_count": len(plans),
                "added_candidates": len(added),
                "candidate_count": len(combined),
                "frontier_stop": str(traversal.frontier.get("stop_reason") or "completed"),
            },
        )
        return CitationExpansionResult(
            candidates=combined,
            citation_map=citation_map,
            provenance_by_identity=provenance,
        )

    @staticmethod
    def _provenance(
        records: list[PaperRecord],
        edges: list[CitationEdge],
    ) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for record in records:
            record_ids = {record.uid}
            if record.identifiers and record.identifiers.openalex:
                record_ids.add(record.identifiers.openalex)
            paths = [
                {
                    "seed_id": edge.seed_id,
                    "parent_id": edge.parent_id,
                    "direction": edge.direction,
                    "depth": edge.depth,
                }
                for edge in edges
                if edge.record_id in record_ids
            ]
            detail = {"citation_paths": paths, "detail": f"citation_paths={len(paths)}"}
            output[record.uid] = detail
            key = document_key(record)
            if key:
                output[key] = detail
        return output

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        if failure_details(exc).get("attempts"):
            return False  # The individual request already exhausted its retries.
        if not isinstance(exc, SourceError):
            return True
        return exc.status is None or exc.status == 429 or int(exc.status) >= 500

    @staticmethod
    def _idempotency_key(
        plans: list[CitationSeedPlan],
        per_seed: int,
        max_records: int,
        depth: int,
    ) -> str:
        payload = {
            "seeds": [
                {
                    "uid": plan.record.uid,
                    "role": plan.role,
                    "directions": plan.directions,
                    "depth": min(plan.depth, depth),
                }
                for plan in plans
            ],
            "per_seed": per_seed,
            "max_records": max_records,
            "depth": depth,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"citation:{digest}"

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.cancellation.raise_if_cancelled()
        self.observer.on_event(
            CoreProgressEvent(event_type=event_type, stage="citation", payload=payload)
        )


__all__ = ["CitationPipeline", "build_seed_plans"]
