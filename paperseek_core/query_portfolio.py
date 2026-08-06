from __future__ import annotations

import re
from typing import Any

from paperseek_core.harness import QueryPortfolioExecution, SearchRunState
from paperseek_core.query_compiler import supports_query_portfolio
from paperseek_core.query_view_selector import select_query_views
from paperseek_core.retrieval import RetrievalLane, document_key


class QueryPortfolioPipeline:
    """Execute bounded complementary query views for an active search run."""

    def __init__(self, host: Any):
        self.host = host

    def run(self, question: str, final_query: str, primary_hits: list, history: list) -> list:
        host = self.host
        if not supports_query_portfolio(host.data_source):
            return list(primary_hits or [])
        if not bool(getattr(host.config, "query_portfolio_enabled", True)):
            return list(primary_hits or [])
        if not host.search_plan or not host.search_plan.query_views:
            return list(primary_hits or [])

        try:
            max_views = max(1, min(int(getattr(host.config, "query_portfolio_max", 3) or 3), 6))
        except (TypeError, ValueError):
            max_views = 3
        try:
            per_view_limit = max(1, min(int(getattr(host.config, "query_portfolio_limit", 100) or 100), 100))
        except (TypeError, ValueError):
            per_view_limit = 100

        selections = select_query_views(
            host.search_plan,
            host.data_source,
            final_query,
            max_views,
        )
        host.query_view_selection = [item.audit_payload() for item in selections]
        ranked_selections = sorted(
            selections,
            key=lambda item: (-item.score, item.original_index),
        )
        host._emit_log(
            "Query view selector completed: "
            + "; ".join(
                f"{item.view.view_id}={'selected' if item.selected else 'reserve'}"
                f" score={item.score:.3f} overlap={item.lexical_overlap:.3f}"
                for item in ranked_selections
            )
        )

        combined = list(primary_hits or [])
        seen_keys = {document_key(document) for document in combined if document_key(document)}
        seen_queries = {
            re.sub(r"\s+", " ", str(value or "")).strip().casefold()
            for value in [final_query, *[row.get("query") for row in history], *[row.get("next_query") for row in history]]
            if value
        }
        host._emit_log(
            f"Query portfolio started: source={host.data_source}; candidate_views={len(host.search_plan.query_views)}; "
            f"request_budget={max_views}; per_view_limit={per_view_limit}."
        )

        completed_view_ids = {
            str(item.get("view_id") or "")
            for item in host.query_portfolio
            if isinstance(item, dict) and item.get("view_id")
        }
        requests_started = sum(
            1
            for item in host.query_portfolio
            if isinstance(item, dict) and item.get("status") == "completed"
        )
        for selection in ranked_selections:
            view = selection.view
            if view.view_id in completed_view_ids:
                continue
            host._check_cancelled()
            execution = None
            compiled_query = selection.compiled_query
            if selection.compile_error:
                execution = QueryPortfolioExecution(
                    view_id=view.view_id,
                    view_type=view.view_type,
                    purpose=view.purpose,
                    query=compiled_query,
                    status="failed",
                    error=selection.compile_error,
                    selector_score=selection.score,
                    selector_overlap=selection.lexical_overlap,
                    selector_reasons=selection.reason_codes,
                )
            elif "exact_primary_duplicate" in selection.reason_codes:
                execution = QueryPortfolioExecution(
                    view_id=view.view_id,
                    view_type=view.view_type,
                    purpose=view.purpose,
                    query=compiled_query,
                    status="skipped_duplicate",
                    selector_score=selection.score,
                    selector_overlap=selection.lexical_overlap,
                    selector_reasons=selection.reason_codes,
                )
            elif requests_started >= max_views:
                execution = QueryPortfolioExecution(
                    view_id=view.view_id,
                    view_type=view.view_type,
                    purpose=view.purpose,
                    query=compiled_query,
                    status="skipped_budget",
                    selector_score=selection.score,
                    selector_overlap=selection.lexical_overlap,
                    selector_reasons=host._merge_unique(selection.reason_codes, ["query_view_request_budget"]),
                )
            else:
                try:
                    portfolio_query = host._apply_discipline_filter(compiled_query)
                    normalized_query = re.sub(r"\s+", " ", portfolio_query).strip().casefold()
                    if not normalized_query or normalized_query in seen_queries:
                        execution = QueryPortfolioExecution(
                            view_id=view.view_id,
                            view_type=view.view_type,
                            purpose=view.purpose,
                            query=portfolio_query,
                            status="skipped_duplicate",
                            selector_score=selection.score,
                            selector_overlap=selection.lexical_overlap,
                            selector_reasons=selection.reason_codes,
                        )
                    else:
                        seen_queries.add(normalized_query)
                        if host.search_run_state is None:
                            host.search_run_state = SearchRunState(question=question, source=host.data_source, current_query=final_query)
                        host.search_run_state, validation = host.search_loop.preflight(host.search_run_state, portfolio_query)
                        if not validation.ok:
                            raise ValueError(validation.issue)
                        host._emit_log(
                            f"Query portfolio request started: view={view.view_id}; purpose={view.purpose or 'complementary recall'}; "
                            f"query={portfolio_query}"
                        )
                        requests_started += 1
                        host.search_run_state, result, search_error = host.search_loop.source_search(
                            host.search_run_state,
                            portfolio_query,
                            lambda query: host._provider_search_lane(
                                query,
                                RetrievalLane.RELEVANCE,
                                per_view_limit,
                                page=1,
                            ),
                        )
                        if search_error is not None:
                            raise search_error
                        view_hits = list(getattr(result, "hits", []) or [])
                        total = int(getattr(getattr(result, "metadata", None), "total", 0) or 0)
                        added = 0
                        for document in view_hits:
                            key = document_key(document)
                            if key and key in seen_keys:
                                continue
                            if key:
                                seen_keys.add(key)
                            combined.append(document)
                            added += 1
                        host.query_portfolio_lane_results[view.view_id] = view_hits
                        execution = QueryPortfolioExecution(
                            view_id=view.view_id,
                            view_type=view.view_type,
                            purpose=view.purpose,
                            query=portfolio_query,
                            total=total,
                            hit_count=len(view_hits),
                            added_unique=added,
                            selector_score=selection.score,
                            selector_overlap=selection.lexical_overlap,
                            selector_reasons=selection.reason_codes,
                        )
                        host._emit_log(
                            f"Query portfolio view completed: view={view.view_id}; total={total}; "
                            f"returned={len(view_hits)}; added_unique={added}."
                        )
                except Exception as exc:
                    execution = QueryPortfolioExecution(
                        view_id=view.view_id,
                        view_type=view.view_type,
                        purpose=view.purpose,
                        query=compiled_query,
                        status="failed",
                        error=f"{exc.__class__.__name__}: {exc}",
                        selector_score=selection.score,
                        selector_overlap=selection.lexical_overlap,
                        selector_reasons=selection.reason_codes,
                    )
                    host._emit_log(
                        f"Query portfolio view skipped after error: view={view.view_id}; {exc.__class__.__name__}: {exc}"
                    )

            execution_payload = execution.model_dump()
            host.query_portfolio.append(execution_payload)
            if host.search_run_state is not None:
                host.search_run_state = host.search_run_state.with_query_portfolio_execution(execution)
            history.append(
                {
                    "iteration": host.last_iteration,
                    "query": execution.query,
                    "total": execution.total if execution.status == "completed" else None,
                    "action": "portfolio",
                    "next_query": None,
                    "message": (
                        f"Query view {execution.view_id} {execution.status}; "
                        f"returned {execution.hit_count} and added {execution.added_unique} unique candidates."
                    ),
                    "view_id": execution.view_id,
                    "view_type": execution.view_type,
                    "purpose": execution.purpose,
                    "status": execution.status,
                    "selector_score": execution.selector_score,
                    "selector_overlap": execution.selector_overlap,
                    "selector_reasons": execution.selector_reasons,
                }
            )
            host._emit_stage(
                "search",
                "processing",
                total=host.last_total,
                history=history,
                final_query=final_query,
                query_view_selection=list(host.query_view_selection),
                query_portfolio=list(host.query_portfolio),
                preview=host._preview_hits(combined),
            )
            host._save_checkpoint(
                "query_execution",
                records=combined,
                metadata={"phase": "query_portfolio", "completed_view_ids": sorted(completed_view_ids | {view.view_id})},
            )
            completed_view_ids.add(view.view_id)

        host._emit_log(
            f"Query portfolio completed: views={len(host.query_portfolio)}; unique_loaded_candidates={len(combined)}."
        )
        host._emit_stage(
            "search",
            "complete",
            total=host.last_total,
            history=history,
            final_query=final_query,
            query_view_selection=list(host.query_view_selection),
            query_portfolio=list(host.query_portfolio),
            preview=host._preview_hits(combined),
        )
        return host._dedupe_documents(combined)
