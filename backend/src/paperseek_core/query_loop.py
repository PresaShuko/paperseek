"""Structured query planning, bounded refinement, and portfolio execution."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from paperseek_core.errors import QuerySourceError
from paperseek_core.execution import NEVER_CANCELLED
from paperseek_core.models import (
    CheckpointDraft,
    CoreProgressEvent,
    PaperRecord,
    QueryHistoryEntry,
    QueryIterationMemory,
    QueryLoopBudget,
    QueryLoopRequest,
    QueryLoopResult,
    QueryLoopResumeState,
    QueryLoopSnapshot,
    RetrievalRequest,
    SearchPlan,
)
from paperseek_core.ports import CancellationToken, LLMPort, SourcePort, WorkflowObserver
from paperseek_core.query_compiler import (
    validate_source_query,
)
from paperseek_core.query_planning import (
    QueryLoopController,
    QueryPlanner,
    normalize_query,
)
from paperseek_core.query_portfolio import QueryPortfolioExecutor
from paperseek_core.retrieval import dedupe_documents
from paperseek_core.sources.contracts import SourceError, SourceSearchRequest


class QueryLoopPipeline:
    """Run the frozen query loop through explicit LLM, source, and observer ports."""

    def __init__(
        self,
        llm: LLMPort,
        source: SourcePort,
        observer: WorkflowObserver,
        *,
        cancellation: CancellationToken = NEVER_CANCELLED,
    ) -> None:
        self.llm = llm
        self.source = source
        self.observer = observer
        self.cancellation = cancellation
        self.planner = QueryPlanner(llm)
        self.controller = QueryLoopController()
        self.portfolio = QueryPortfolioExecutor(
            source,
            observer,
            self._checkpoint,
            cancellation,
        )
        self.source_context = ""

    async def run(self, request: QueryLoopRequest) -> QueryLoopResult:
        self.cancellation.raise_if_cancelled()
        self.source_context = request.source_context
        budget = request.budget
        self._event(
            "query.started",
            {
                "source": self.source.name,
                "target_min": budget.target_min,
                "target_max": budget.target_max,
                "retrieval_pool_max": budget.retrieval_pool_max,
                "max_iterations": budget.max_iterations,
            },
        )
        if request.resume is not None:
            state = self._validate_resume(request)
            self._event(
                "query.resumed",
                {
                    "phase": state.phase,
                    "iteration": state.iteration,
                    "portfolio_count": len(state.query_portfolio),
                },
            )
        else:
            plan = await self.planner.plan(
                request.question,
                portfolio_required=budget.query_portfolio_enabled,
                source_context=self.source_context,
            )
            self.cancellation.raise_if_cancelled()
            proposal = await self.planner.propose(
                self.source.name,
                request.question,
                plan,
                operation="generate",
                source_context=self.source_context,
            )
            self.cancellation.raise_if_cancelled()
            state = QueryLoopResumeState(
                phase="query_ready",
                question=request.question,
                source=self.source.name,
                search_plan=plan,
                current_query=proposal.query,
                warnings=proposal.warnings,
            )
            self._event(
                "query.planned",
                {
                    "source": self.source.name,
                    "intent": plan.intent,
                    "question_type": plan.question_type,
                    "current_query": proposal.query,
                    "query_views": [view.model_dump(mode="json") for view in plan.query_views],
                    "query_view_count": len(plan.query_views),
                    "warning_count": len(proposal.warnings),
                },
            )
            state = self._checkpoint(state, "query_ready", "query.plan")

        if state.phase not in {"query_primary_complete", "query_portfolio", "query_complete"}:
            state = await self._run_primary_loop(state, budget)
        if state.phase != "query_complete":
            state = await self.portfolio.run(state, budget)
            state = self._checkpoint(state, "query_complete", "query.complete")

        result = self._result(state, budget)
        self._event(
            "query.completed",
            {
                "source": self.source.name,
                "iteration": result.iterations,
                "total": result.total,
                "primary_count": len(result.primary_hits),
                "candidate_count": len(result.records),
                "portfolio_count": len(result.query_portfolio),
                "warning_count": len(result.warnings),
            },
        )
        return result

    def _validate_resume(self, request: QueryLoopRequest) -> QueryLoopResumeState:
        assert request.resume is not None
        resume = request.resume
        if resume.question.strip() != request.question.strip():
            raise QuerySourceError("query checkpoint question does not match the resumed request")
        if resume.source != self.source.name:
            raise QuerySourceError("query checkpoint source does not match the resumed request")
        return resume

    async def _run_primary_loop(
        self,
        state: QueryLoopResumeState,
        budget: QueryLoopBudget,
    ) -> QueryLoopResumeState:
        configured = max(1, int(budget.max_iterations))
        adaptive = (
            max(configured, int(budget.adaptive_max_iterations))
            if budget.adaptive_max_iterations is not None
            else max(configured + 8, configured * 3, 10)
        )
        pool_min = min(max(0, int(budget.retrieval_pool_min)), budget.target_max)
        while state.iteration < adaptive:
            self.cancellation.raise_if_cancelled()
            iteration = state.iteration + 1
            query = state.current_query
            validation = validate_source_query(self.source.name, query)
            if not validation.ok:
                raise QueryGenerationError(
                    f"{self.source.name} query failed preflight: {validation.issue}"
                )
            self._event(
                "query.request_started",
                {
                    "source": self.source.name,
                    "iteration": iteration,
                    "lane": "relevance",
                    "query": query,
                    "limit": self._primary_limit(budget),
                },
            )
            response = await self._primary_search_with_repair(
                state,
                query,
                iteration,
                budget,
            )
            query = response[0]
            source_result = response[1]
            hits = list(source_result.hits or [])
            total = int(source_result.metadata.total or 0)
            memory = self._record_iteration(
                list(state.query_iteration_memory),
                iteration,
                query,
                total,
                hits,
            )
            fallback_query = state.fallback_query
            fallback_total = state.fallback_total
            fallback_hits = list(state.fallback_hits)
            if total and hits:
                if (
                    not fallback_hits
                    or total <= budget.retrieval_pool_max
                    or fallback_total > budget.retrieval_pool_max
                ):
                    fallback_query = query
                    fallback_total = total
                    fallback_hits = list(hits)
            snapshot = QueryLoopSnapshot(
                iteration=iteration,
                configured_iterations=configured,
                adaptive_max_iterations=adaptive,
                total=total,
                target_min=budget.target_min,
                target_max=budget.target_max,
                retrieval_pool_min=pool_min,
                retrieval_pool_max=budget.retrieval_pool_max,
                history=[item.model_dump(mode="json") for item in state.history],
                query=query,
                hit_count=len(hits),
                top_titles=[record.title for record in hits[:5] if record.title],
                intent_terms=self._intent_terms(state.search_plan),
            )
            decision = self.controller.decide(snapshot)
            updated = state.model_copy(
                update={
                    "current_query": query,
                    "iteration": iteration,
                    "total": total,
                    "primary_hits": hits,
                    "query_iteration_memory": memory,
                    "fallback_query": fallback_query,
                    "fallback_total": fallback_total,
                    "fallback_hits": fallback_hits,
                }
            )
            self._event(
                "query.progress",
                {
                    "iteration": iteration,
                    "query": query,
                    "total": total,
                    "hit_count": len(hits),
                    "decision": decision.action,
                    "message": decision.message,
                    "reason": decision.reason,
                },
            )
            if decision.action in {"broaden", "narrow"}:
                proposal = await self.planner.propose(
                    self.source.name,
                    state.question,
                    state.search_plan,
                    operation=decision.action,
                    current_query=query,
                    feedback=decision.adjustment,
                    source_context=self.source_context,
                )
                warnings = self._merge_unique(updated.warnings, proposal.warnings)
                if normalize_query(proposal.query) == normalize_query(query):
                    terminal = self._unchanged_history(
                        iteration,
                        query,
                        total,
                        decision.action,
                        budget,
                    )
                    updated = updated.model_copy(
                        update={
                            "history": [*updated.history, terminal],
                            "warnings": warnings,
                            "terminal_status": terminal.action,
                        }
                    )
                    return self._checkpoint(
                        self._restore_visible_fallback(updated),
                        "query_primary_complete",
                        "query.primary",
                    )
                history = QueryHistoryEntry(
                    iteration=iteration,
                    query=query,
                    total=total,
                    action=decision.action,
                    next_query=proposal.query,
                    message=decision.message,
                    rationale=proposal.rationale,
                    controller_reason=decision.reason,
                )
                updated = updated.model_copy(
                    update={
                        "current_query": proposal.query,
                        "history": [*updated.history, history],
                        "warnings": warnings,
                    }
                )
                state = self._checkpoint(updated, "next_query", "query.iteration")
                continue
            history = QueryHistoryEntry(
                iteration=iteration,
                query=query,
                total=total,
                action=decision.action,
                next_query=None,
                message=decision.message,
                controller_reason=decision.reason,
            )
            updated = updated.model_copy(
                update={
                    "history": [*updated.history, history],
                    "terminal_status": decision.action,
                }
            )
            return self._checkpoint(
                self._restore_visible_fallback(updated),
                "query_primary_complete",
                "query.primary",
            )
        return self._checkpoint(
            self._restore_visible_fallback(state),
            "query_primary_complete",
            "query.primary",
        )

    async def _primary_search_with_repair(
        self,
        state: QueryLoopResumeState,
        query: str,
        iteration: int,
        budget: QueryLoopBudget,
    ) -> tuple[str, Any]:
        current = query
        repair_attempts = 0
        while True:
            request = SourceSearchRequest(
                query=current,
                limit=self._primary_limit(budget),
                page=1,
                lane="relevance",
                field_ids=budget.field_ids,
            )
            try:
                result = await self.source.search(request)
                self.cancellation.raise_if_cancelled()
                return current, result
            except SourceError as exc:
                if exc.status not in {400, 422} or repair_attempts >= 2:
                    self._primary_failed(iteration, exc)
                repair_attempts += 1
                proposal = await self.planner.propose(
                    self.source.name,
                    state.question,
                    state.search_plan,
                    operation="repair",
                    current_query=current,
                    feedback="The source rejected the query syntax; preserve intent and correct only source syntax.",
                    source_context=self.source_context,
                )
                if normalize_query(proposal.query) == normalize_query(current):
                    self._primary_failed(iteration, exc)
                current = proposal.query
            except Exception as exc:
                self._primary_failed(iteration, exc)

    def _primary_failed(self, iteration: int, exc: Exception) -> None:
        self._event(
            "query.failed",
            {
                "code": "query_primary_source_failed",
                "source": self.source.name,
                "iteration": iteration,
                "error_type": type(exc).__name__,
            },
        )
        raise QuerySourceError("The primary query failed without a recoverable source result.") from exc

    def _result(
        self,
        state: QueryLoopResumeState,
        budget: QueryLoopBudget,
    ) -> QueryLoopResult:
        supplemental = {}
        final_normalized = normalize_query(state.current_query)
        for item in state.query_iteration_memory:
            if item.records and normalize_query(item.query) != final_normalized:
                supplemental[f"query_iteration:{max(1, item.iteration)}"] = list(item.records)
        for view_id, records in state.portfolio_lane_results.items():
            if records:
                supplemental[f"query_view:{view_id}"] = list(records)
        records = dedupe_documents(
            [
                *state.primary_hits,
                *[record for values in state.portfolio_lane_results.values() for record in values],
            ]
        )
        retrieval = RetrievalRequest(
            question=state.question,
            query=state.current_query,
            primary_hits=state.primary_hits,
            supplemental_lanes=supplemental,
            lane_limit=budget.retrieval_lane_limit,
            ranking_candidate_limit=budget.ranking_candidate_limit,
            pool_max=budget.retrieval_pool_max,
            field_ids=budget.field_ids,
        )
        return QueryLoopResult(
            question=state.question,
            source=state.source,
            search_plan=state.search_plan,
            final_query=state.current_query,
            total=state.total,
            primary_hits=state.primary_hits,
            records=records,
            iterations=state.iteration,
            history=state.history,
            query_iteration_memory=state.query_iteration_memory,
            query_view_selection=state.query_view_selection,
            query_portfolio=state.query_portfolio,
            terminal_status=state.terminal_status,
            warnings=state.warnings,
            retrieval_request=retrieval,
        )

    def _checkpoint(
        self,
        state: QueryLoopResumeState,
        phase: str,
        step_key: str,
    ) -> QueryLoopResumeState:
        self.cancellation.raise_if_cancelled()
        current = state.model_copy(update={"phase": phase})
        payload = {
            "source": current.source,
            "question": current.question,
            "phase": phase,
            "iteration": current.iteration,
            "query": current.current_query,
            "portfolio": [item.view_id for item in current.query_portfolio],
        }
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.observer.on_checkpoint(
            CheckpointDraft(
                step_key=step_key,
                idempotency_key=f"query:{phase}:{digest}",
                state=current.model_dump(mode="json"),
                workflow_version="m2.query-loop.v1",
            )
        )
        return current

    def _restore_visible_fallback(
        self,
        state: QueryLoopResumeState,
    ) -> QueryLoopResumeState:
        if state.total != 0 or state.primary_hits or not state.fallback_hits:
            return state
        history = QueryHistoryEntry(
            iteration=state.iteration,
            query=state.current_query,
            total=0,
            action="fallback",
            next_query=state.fallback_query,
            message=(
                "The latest query returned 0 records; fell back to the most recent non-empty "
                "candidate pool for downstream retrieval and ranking."
            ),
        )
        return state.model_copy(
            update={
                "current_query": state.fallback_query,
                "total": state.fallback_total,
                "primary_hits": state.fallback_hits,
                "history": [*state.history, history],
                "warnings": self._merge_unique(
                    state.warnings,
                    ["query_terminal_zero_last_nonempty_retained"],
                ),
            }
        )

    @staticmethod
    def _record_iteration(
        memory: list[QueryIterationMemory],
        iteration: int,
        query: str,
        total: int,
        records: list[PaperRecord],
    ) -> list[QueryIterationMemory]:
        records = dedupe_documents(records)[:100]
        normalized = normalize_query(query)
        if not records or not normalized:
            return memory
        entry = QueryIterationMemory(
            iteration=iteration,
            query=query,
            total=total,
            records=records,
        )
        output = list(memory)
        for index, existing in enumerate(output):
            if normalize_query(existing.query) == normalized:
                output[index] = entry
                break
        else:
            output.append(entry)
        return output[-12:]

    @staticmethod
    def _unchanged_history(
        iteration: int,
        query: str,
        total: int,
        attempted_action: str,
        budget: QueryLoopBudget,
    ) -> QueryHistoryEntry:
        attempted = "broader" if attempted_action == "broaden" else "narrower"
        if total == 0:
            action = "empty"
            message = f"No records found and the {attempted} query was unchanged; stopped instead of repeating the same request."
        elif total < budget.target_min:
            action = "accept_low"
            message = f"Accepted {total} records below the target minimum because the {attempted} query was unchanged."
        elif total > budget.retrieval_pool_max:
            action = "accept_high"
            message = f"Accepted {total} records above the LLM pre-ranking safety pool because the {attempted} query was unchanged; the fused candidate pool will be truncated before LLM ranking."
        elif total > budget.target_max:
            action = "accept_pool"
            message = f"Accepted {total} records for downstream pre-ranking because the {attempted} query was unchanged."
        else:
            action = "accept"
            message = f"Accepted {total} records because the {attempted} query was unchanged."
        return QueryHistoryEntry(
            iteration=iteration,
            query=query,
            total=total,
            action=action,
            next_query=None,
            message=message,
        )

    def _primary_limit(self, budget: QueryLoopBudget) -> int:
        output_limit = max(1, min(int(budget.target_max or 50), 50))
        if self.source.name == "wos":
            return output_limit
        return min(max(output_limit * 2, output_limit), 100)

    @staticmethod
    def _intent_terms(plan: SearchPlan) -> list[str]:
        return [
            *plan.core_concepts,
            *plan.must_have_facets,
            *plan.likely_synonyms,
            plan.required_relation,
        ]

    @staticmethod
    def _merge_unique(values: Iterable[str], additions: Iterable[str]) -> list[str]:
        return list(dict.fromkeys([*values, *additions]))

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.cancellation.raise_if_cancelled()
        self.observer.on_event(
            CoreProgressEvent(event_type=event_type, stage="query", payload=payload)
        )


__all__ = ["QueryLoopPipeline"]
