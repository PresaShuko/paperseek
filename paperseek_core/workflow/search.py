from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from paperseek_core.checkpoints import paper_records_from_checkpoint
from paperseek_core.harness import ACTION_BROADEN, ACTION_NARROW, SearchRunState
from paperseek_core.workflow.query_execution import QueryExecutionPipeline


@dataclass
class SearchLoopContext:
    question: str
    query: str
    history: list[dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    total: int = 0
    hits: list[Any] = field(default_factory=list)
    fallback_query: str = ""
    fallback_total: int = 0
    fallback_hits: list[Any] = field(default_factory=list)


class SearchWorkflowExecutor:
    """Coordinate query planning, bounded refinement, and downstream completion."""

    _COMPLETION_STAGES = {
        "candidate_merge",
        "citation_layer",
        "pre_rank",
        "ranking_batch",
        "ranking_complete",
    }

    def __init__(
        self,
        host: Any,
        *,
        make_starter_safe_query: Callable[[str], str],
        server_error_query_variants: Callable[[str], list[str]],
        queries_equivalent: Callable[[str, str], bool],
    ) -> None:
        self.host = host
        self.queries_equivalent = queries_equivalent
        self.query_execution = QueryExecutionPipeline(
            host,
            make_starter_safe_query=make_starter_safe_query,
            server_error_query_variants=server_error_query_variants,
            queries_equivalent=queries_equivalent,
        )

    def run(self, question: str, *, verbose: bool = False) -> dict[str, Any]:
        host = self.host
        host.run_question = question
        host.query_portfolio_lane_results = {}
        host.query_iteration_results = []

        context, completed = self._restore_or_start(question)
        if completed is not None:
            return completed
        assert context is not None

        configured_iterations = max(1, int(getattr(host.config, "max_iterations", 5) or 5))
        adaptive_max_iterations = host._adaptive_max_iterations(configured_iterations)
        self._run_query_loop(
            context,
            configured_iterations=configured_iterations,
            adaptive_max_iterations=adaptive_max_iterations,
            verbose=verbose,
        )
        if context.iteration > configured_iterations or (not context.hits and context.total == 0):
            if verbose:
                print(
                    f"[Done] {context.total} total results after {context.iteration} iterations.",
                    file=sys.stderr,
                )

        self._restore_last_nonempty_result(context)
        return self._finish_query_phase(context)

    def _restore_or_start(self, question: str) -> tuple[SearchLoopContext | None, dict[str, Any] | None]:
        host = self.host
        checkpoint = host.resume_checkpoint
        if checkpoint is None:
            return self._start_new(question), None

        host._restore_checkpoint_state(checkpoint)
        history = list(checkpoint.history)
        host.iteration_history = history
        query = checkpoint.current_query
        iteration = int(checkpoint.iteration or 0)
        total = int(checkpoint.total or 0)
        restored_records = paper_records_from_checkpoint(checkpoint.records)
        phase = str((checkpoint.metadata or {}).get("phase") or "")

        if checkpoint.stage in self._COMPLETION_STAGES:
            return None, host._complete_search_pipeline(
                question,
                query,
                total,
                restored_records,
                history,
                iteration,
                checkpoint=checkpoint,
            )
        if checkpoint.stage == "query_execution" and phase in {"query_primary_complete", "query_portfolio"}:
            hits = restored_records
            if phase == "query_portfolio":
                host.query_portfolio_lane_results["checkpoint"] = list(hits)
            hits = host._execute_query_portfolio(question, query, hits, history)
            host._save_checkpoint(
                "query_execution",
                records=hits,
                metadata={"phase": "query_complete", "resume_from_stage": "query_execution"},
            )
            return None, host._complete_search_pipeline(question, query, total, hits, history, iteration)
        if checkpoint.stage == "query_execution" and phase == "query_complete":
            return None, host._complete_search_pipeline(
                question,
                query,
                total,
                restored_records,
                history,
                iteration,
            )

        host._emit_log(
            f"Resuming query loop from durable checkpoint: stage={checkpoint.stage}; "
            f"phase={phase or 'query_ready'}; next_iteration={iteration + 1}."
        )
        return (
            SearchLoopContext(
                question=question,
                query=query,
                history=history,
                iteration=iteration,
                total=total,
                fallback_query=str((checkpoint.metadata or {}).get("fallback_query") or ""),
                fallback_total=int((checkpoint.metadata or {}).get("fallback_total") or 0),
                fallback_hits=restored_records,
            ),
            None,
        )

    def _start_new(self, question: str) -> SearchLoopContext:
        host = self.host
        host.iteration_history = []
        host.current_query = ""
        host.last_total = 0
        host.last_iteration = 0
        host.search_plan = None
        host.query_view_selection = []
        host.query_portfolio = []
        host.search_intent = host._analyze_intent(question)
        if host.search_intent:
            host._emit_stage("query", "processing", source=host.data_source, intent=host.search_intent)
        query = host._source_safe_query(host._apply_discipline_filter(host._generate_query(question)))
        host.search_run_state = SearchRunState(
            question=question,
            source=host.data_source,
            current_query=query,
            search_plan=host.search_plan.model_dump() if host.search_plan else {},
        )
        host.current_query = query
        context = SearchLoopContext(question=question, query=query)
        host.iteration_history = context.history
        host._save_checkpoint(
            "search_plan",
            metadata={"phase": "query_ready", "resume_from_stage": "search_plan"},
        )
        return context

    def _run_query_loop(
        self,
        context: SearchLoopContext,
        *,
        configured_iterations: int,
        adaptive_max_iterations: int,
        verbose: bool,
    ) -> None:
        host = self.host
        while context.iteration < adaptive_max_iterations:
            host._check_cancelled()
            context.iteration += 1
            host.last_iteration = context.iteration
            execution = self.query_execution.run(
                question=context.question,
                query=context.query,
                iteration=context.iteration,
                history=context.history,
                verbose=verbose,
            )
            context.query = execution.query
            if execution.retry_iteration:
                continue

            result = execution.result
            context.total = result.metadata.total if result.metadata and result.metadata.total is not None else 0
            context.hits = result.hits or []
            self._record_iteration_result(context, verbose=verbose)
            decision = host._query_loop_decision(
                context.query,
                context.hits,
                context.total,
                context.iteration,
                configured_iterations,
                adaptive_max_iterations,
                context.history,
            )
            if decision.action in {ACTION_BROADEN, ACTION_NARROW}:
                if self._revise_query(context, decision, adaptive_max_iterations):
                    continue
                break
            self._accept_query(context, decision)
            break

    def _record_iteration_result(self, context: SearchLoopContext, *, verbose: bool) -> None:
        host = self.host
        host._record_query_iteration(context.iteration, context.query, context.total, context.hits)
        host.last_total = int(context.total or 0)
        if context.total and context.hits:
            pool_max = host._retrieval_pool_max()
            if (
                not context.fallback_hits
                or int(context.total or 0) <= pool_max
                or int(context.fallback_total or 0) > pool_max
            ):
                context.fallback_query = context.query
                context.fallback_total = int(context.total or 0)
                context.fallback_hits = list(context.hits)
        if verbose:
            print(f"[Iteration {context.iteration}] Total results: {context.total}", file=sys.stderr)

    def _revise_query(self, context: SearchLoopContext, decision: Any, adaptive_max_iterations: int) -> bool:
        host = self.host
        current_query = context.query
        if decision.action == ACTION_BROADEN:
            feedback = host._result_feedback(
                current_query,
                context.hits,
                context.total,
                decision.adjustment or "too few or zero records",
            )
            revised_query = host._apply_discipline_filter(
                host._broaden_query(context.question, current_query, feedback)
            )
            attempted_action = "broader"
        else:
            feedback = host._result_feedback(current_query, context.hits, context.total, decision.adjustment)
            revised_query = host._apply_discipline_filter(
                host._narrow_query(context.question, current_query, feedback)
            )
            attempted_action = "narrower"
            if (
                self.queries_equivalent(current_query, revised_query)
                and context.total > host._retrieval_pool_max()
                and context.iteration < adaptive_max_iterations
            ):
                retry_feedback = (
                    f"{feedback}\n"
                    "The previous narrowing response did not change the query. "
                    "Return a different valid query that adds a missing central facet, stricter phrase, method, domain, population, or publication-type term from the interpreted intent. "
                    "Do not remove existing core intent terms."
                )
                revised_query = host._apply_discipline_filter(
                    host._narrow_query(context.question, current_query, retry_feedback)
                )

        query_audit = host._consume_query_audit()
        if self.queries_equivalent(current_query, revised_query):
            host._complete_after_unchanged_revision(
                context.history,
                context.iteration,
                current_query,
                context.total,
                context.hits,
                attempted_action,
            )
            host._save_checkpoint(
                "query_execution",
                records=context.hits,
                metadata={"phase": "query_primary_complete"},
            )
            return False

        context.query = revised_query
        context.history.append(
            {
                "iteration": context.iteration,
                "query": current_query,
                "total": context.total,
                "action": decision.action,
                "next_query": revised_query,
                "message": decision.message,
                "rationale": query_audit,
                "controller_reason": decision.reason,
            }
        )
        host._set_search_state_query(revised_query)
        host._emit_stage(
            "search",
            "processing",
            total=context.total,
            history=context.history,
            final_query=revised_query,
            preview=host._preview_hits(context.hits),
        )
        host._save_checkpoint(
            "query_execution",
            records=context.fallback_hits,
            metadata={
                "phase": "next_query",
                "fallback_query": context.fallback_query,
                "fallback_total": context.fallback_total,
            },
        )
        return True

    def _accept_query(self, context: SearchLoopContext, decision: Any) -> None:
        host = self.host
        context.history.append(
            {
                "iteration": context.iteration,
                "query": context.query,
                "total": context.total,
                "action": decision.action,
                "next_query": None,
                "message": decision.message,
                "controller_reason": decision.reason,
            }
        )
        host._save_checkpoint(
            "query_execution",
            records=context.hits,
            metadata={"phase": "query_primary_complete"},
        )
        host._emit_stage(
            "search",
            "complete",
            total=context.total,
            history=context.history,
            final_query=context.query,
            preview=host._preview_hits(context.hits),
        )

    def _restore_last_nonempty_result(self, context: SearchLoopContext) -> None:
        host = self.host
        if context.total != 0 or context.hits or not context.fallback_hits:
            return
        zero_query = context.query
        context.query = context.fallback_query
        context.total = context.fallback_total
        context.hits = context.fallback_hits
        host.last_total = int(context.total or 0)
        host._set_search_state_query(context.query)
        context.history.append(
            {
                "iteration": context.iteration,
                "query": zero_query,
                "total": 0,
                "action": "fallback",
                "next_query": context.query,
                "message": (
                    "The latest query returned 0 records; fell back to the most recent non-empty "
                    "candidate pool for downstream retrieval and ranking."
                ),
            }
        )
        host._emit_stage(
            "search",
            "complete",
            total=context.total,
            history=context.history,
            final_query=context.query,
            preview=host._preview_hits(context.hits),
        )

    def _finish_query_phase(self, context: SearchLoopContext) -> dict[str, Any]:
        host = self.host
        context.hits = host._execute_query_portfolio(
            context.question,
            context.query,
            context.hits,
            context.history,
        )
        if context.total == 0 and context.hits:
            context.total = len(context.hits)
            host.last_total = context.total
        host._set_search_state_query(context.query)
        host._save_checkpoint(
            "query_execution",
            records=context.hits,
            metadata={"phase": "query_complete", "resume_from_stage": "query_execution"},
        )
        return host._complete_search_pipeline(
            context.question,
            context.query,
            context.total,
            context.hits,
            context.history,
            context.iteration,
        )
