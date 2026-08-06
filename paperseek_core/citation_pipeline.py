from __future__ import annotations

import time
from typing import Any

from paperseek_core.disciplines import openalex_field_ids
from paperseek_core.harness import CITATION_RETRY_REDUCED
from paperseek_core.sources.contracts import ProviderError
from paperseek_core.sources.openalex import OpenAlexProvider


class CitationExpansionPipeline:
    """Execute bounded OpenAlex citation expansion for an active search run."""

    def __init__(self, host: Any):
        self.host = host

    def run(self, question: str, hits: list) -> list:
        host = self.host
        candidates = host._dedupe_documents(list(hits or []))
        # Queue insertion returns only records that are new to the ledger. A
        # paper discovered during an earlier query iteration is still part of
        # the fused retrieval pool and must continue to citation/ranking.
        host._enqueue_candidate_queue(candidates, "retrieval")
        host.citation_map = host._empty_citation_map(
            enabled=getattr(host.config, "expand_citations", True),
            initial_candidates=len(candidates),
            candidate_pool=len(candidates),
        )
        if not candidates:
            return candidates
        if not getattr(host.config, "expand_citations", True):
            return candidates
        if host.data_source != "openalex" or not isinstance(host.provider, OpenAlexProvider):
            host._emit_log("Citation expansion skipped: this data source does not support OpenAlex citation traversal yet.")
            host.citation_map.update({"supported": False, "status": "unsupported"})
            return candidates
        last_source_status = str((getattr(host.provider, "last_response_info", {}) or {}).get("status") or "")
        if last_source_status == "429":
            host._emit_log("Citation expansion skipped because OpenAlex is rate limiting this run; keeping the current candidate pool.")
            host.citation_map.update({"supported": True, "status": "rate_limited"})
            host._emit_ranking_step(
                "citation_expansion",
                "skipped",
                "Citation expansion",
                current=0,
                total=1,
                detail="OpenAlex returned 429 during retrieval; citation traversal was skipped to avoid blocking the run.",
            )
            return candidates

        host._check_cancelled()
        seed_selection_limit = host._citation_seed_selection_limit()
        seed_candidates = host._citation_seed_candidate_pool(candidates, seed_selection_limit)
        if len(candidates) > len(seed_candidates):
            host._emit_log(
                "Citation seed selection pool truncated: "
                f"candidates={len(candidates)}; seed_selection_limit={seed_selection_limit}."
            )
        host._emit_log(
            "Citation expansion started: selecting seed papers from the fused retrieval order "
            "before traversing references and citing works."
        )
        host._emit_ranking_step(
            "citation_seed_ranking",
            "processing",
            "Citation seed selection",
            current=0,
            total=max(1, len(seed_candidates)),
            detail="Selecting a bounded, query-view-diversified seed pool from the existing fused retrieval order.",
        )
        seed_ranked = [
            {
                "document": document,
                "score": 10,
                "reasoning": "Selected from the fused retrieval order.",
                **host._retrieval_entry_metadata(document),
            }
            for document in seed_candidates
        ]
        host._check_cancelled()
        host._emit_ranking_step(
            "citation_seed_ranking",
            "complete",
            "Citation seed selection",
            current=len(seed_candidates),
            total=max(1, len(seed_candidates)),
            detail="Seed selection completed without an additional LLM scoring pass.",
        )
        seed_limit = max(1, int(getattr(host.config, "citation_seed_count", 30) or 30))
        citation_depth = max(1, min(int(getattr(host.config, "citation_depth", 2) or 2), 3))
        citation_plan = host._plan_citation_expansion(
            candidate_count=len(candidates),
            seed_ranking_count=len(seed_candidates),
            seed_count=seed_limit,
            depth=citation_depth,
        )
        seed_plans = host._build_citation_seed_plans(seed_ranked, candidates, citation_plan)
        seeds = [plan.record for plan in seed_plans]
        if not seed_plans:
            host._emit_log("Citation expansion skipped: no seed papers available.")
            host.citation_map.update({"status": "no_seeds"})
            host._emit_ranking_step(
                "citation_expansion",
                "skipped",
                "Citation expansion",
                current=0,
                total=max(1, seed_limit),
                detail="No seed papers were available for citation traversal.",
            )
            return candidates

        host._emit_ranking_step(
            "citation_expansion",
            "processing",
            "Citation expansion",
            current=0,
            total=max(1, len(seed_plans)),
            detail=f"Traversing citation neighborhoods for {len(seed_plans)} seed papers across relevance, impact, and recency plans.",
            seed_count=len(seeds),
            citation_depth=citation_depth,
        )
        try:
            traversal_per_seed = max(1, int(getattr(host.config, "citation_per_seed", 4) or 4))
        except (TypeError, ValueError):
            traversal_per_seed = 4
        try:
            traversal_max_records = max(1, int(getattr(host.config, "citation_max_records", 160) or 160))
        except (TypeError, ValueError):
            traversal_max_records = 160
        traversal_depth = citation_depth
        citation_data = None
        retry_attempts = 0
        citation_progress_state = {"last_emit": 0.0, "last_current": -1}

        def emit_citation_progress(progress: dict) -> None:
            host._check_cancelled()
            event = str(progress.get("event") or "")
            total = max(1, int(progress.get("total") or len(seed_plans) or 1))
            current = max(0, min(total, int(progress.get("current") or 0)))
            records = max(0, int(progress.get("records") or 0))
            now = time.perf_counter()
            step = max(1, total // 10)
            should_emit = (
                event == "start"
                or current >= total
                or current % step == 0
                or (current != citation_progress_state["last_current"] and now - citation_progress_state["last_emit"] >= 5.0)
            )
            if not should_emit:
                return
            citation_progress_state["last_emit"] = now
            citation_progress_state["last_current"] = current
            host._emit_log(f"Citation expansion progress: {current}/{total} seed plans processed; added={records}.")
            host._emit_ranking_step(
                "citation_expansion",
                "processing",
                "Citation expansion",
                current=current,
                total=total,
                detail=f"Traversing OpenAlex citation neighborhoods; added {records} candidates so far.",
                seed_count=len(seeds),
                citation_depth=traversal_depth,
                added_candidates=records,
            )

        while citation_data is None:
            host._check_cancelled()
            try:
                try:
                    citation_data = host.provider.citation_neighbors_with_graph(
                        seeds,
                        per_seed=traversal_per_seed,
                        max_records=traversal_max_records,
                        field_ids=openalex_field_ids(host.discipline_fields),
                        seed_plans=seed_plans,
                        depth=traversal_depth,
                        cancel_check=host._check_cancelled,
                        progress_callback=emit_citation_progress,
                        request_attempts=1,
                        request_timeout=10,
                    )
                except TypeError as exc:
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    citation_data = host.provider.citation_neighbors_with_graph(
                        seeds,
                        per_seed=traversal_per_seed,
                        max_records=traversal_max_records,
                        field_ids=openalex_field_ids(host.discipline_fields),
                        seed_plans=seed_plans,
                        depth=traversal_depth,
                    )
            except ProviderError as exc:
                host._observe_citation_traversal(
                    status="error",
                    seed_count=len(seeds),
                    depth=traversal_depth,
                    per_seed=traversal_per_seed,
                    max_records=traversal_max_records,
                    candidate_pool=len(candidates),
                    error=exc,
                )
                decision = host._recover_citation_error(
                    exc,
                    seed_count=len(seeds),
                    depth=traversal_depth,
                    per_seed=traversal_per_seed,
                    max_records=traversal_max_records,
                    retry_attempts=retry_attempts,
                    max_retries=1,
                )
                if decision.action == CITATION_RETRY_REDUCED:
                    retry_attempts += 1
                    traversal_per_seed = decision.per_seed
                    traversal_max_records = decision.max_records
                    traversal_depth = decision.depth
                    host._emit_log(
                        "Citation expansion retrying with a reduced traversal budget: "
                        f"per_seed={traversal_per_seed}; max_records={traversal_max_records}; depth={traversal_depth}."
                    )
                    host._emit_ranking_step(
                        "citation_expansion",
                        "processing",
                        "Citation expansion",
                        current=0,
                        total=max(1, len(seeds)),
                        detail="Citation traversal failed once; retrying with a reduced traversal budget.",
                        seed_count=len(seeds),
                        citation_depth=traversal_depth,
                    )
                    continue
                host._check_cancelled()
                host._emit_log(f"Citation expansion skipped after OpenAlex error: {exc}")
                host.citation_map.update({"status": "error", "error": str(exc)})
                host._emit_ranking_step(
                    "citation_expansion",
                    "error",
                    "Citation expansion",
                    current=0,
                    total=max(1, len(seeds)),
                    detail=f"Citation traversal failed: {exc}",
                    seed_count=len(seeds),
                )
                return candidates

        host._check_cancelled()
        related = citation_data.get("records", [])
        citation_frontier = dict(citation_data.get("frontier") or {})
        citation_evidence = host._citation_evidence_by_key(related, citation_data)
        added_related = host._enqueue_candidate_queue(
            related,
            "citation_expansion",
            evidence_by_key=citation_evidence,
        )
        candidates = candidates + added_related
        added = len(added_related)
        host._observe_citation_traversal(
            status="complete",
            seed_count=len(seeds),
            depth=traversal_depth,
            per_seed=traversal_per_seed,
            max_records=traversal_max_records,
            added_candidates=added,
            candidate_pool=len(candidates),
            frontier=citation_frontier,
        )
        host.citation_map.update({
            "enabled": True,
            "supported": True,
            "status": "complete",
            "initial_candidates": len(hits or []),
            "seed_count": len(seeds),
            "seed_plan_counts": host._citation_seed_plan_counts(seed_plans),
            "citation_depth": traversal_depth,
            "frontier": citation_frontier,
            "added_candidates": added,
            "candidate_pool": len(candidates),
            "nodes": citation_data.get("nodes", []),
            "edges": citation_data.get("edges", []),
        })
        frontier_stop = str(citation_frontier.get("stop_reason") or "completed")
        frontier_requests = int(citation_frontier.get("request_count") or 0)
        host._emit_log(
            f"Citation expansion completed: added {added} citation-neighbor candidates; "
            f"candidate pool={len(candidates)}; frontier_stop={frontier_stop}; requests={frontier_requests}."
        )
        host._emit_ranking_step(
            "citation_expansion",
            "complete",
            "Citation expansion",
            current=len(seeds),
            total=max(1, len(seeds)),
            detail=(
                f"Added {added} citation-neighbor candidates; candidate pool={len(candidates)}; "
                f"frontier stop={frontier_stop}; requests={frontier_requests}."
            ),
            seed_count=len(seeds),
            candidate_count=len(candidates),
            added_candidates=added,
            citation_depth=traversal_depth,
        )
        candidates = host._refuse_candidates_after_citation(question, candidates)
        host.citation_map["candidate_pool"] = len(candidates)
        return candidates
