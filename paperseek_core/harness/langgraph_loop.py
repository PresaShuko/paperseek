
from typing import Any, Callable, Dict

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from paperseek_core.harness.errors import classify_error
from paperseek_core.harness.native_loop import NativeQueryLoopRunner
from paperseek_core.harness.query_contract import validate_source_query
from paperseek_core.harness.schemas import (
    QueryLoopDecision,
    QueryLoopSnapshot,
    QueryValidation,
    CandidateQueueEvent,
    FrontierCycleResult,
    FrontierOutcome,
    CitationPlanningDecision,
    CitationRecoveryDecision,
    CitationTraversalObservation,
    RankingBatchObservation,
    RankingRecoveryDecision,
    SearchRunState,
    SourceObservation,
    SourceRecoveryDecision,
)


class LangGraphQueryLoopRunner:
    backend_used = "langgraph"

    def __init__(self):
        self.native = NativeQueryLoopRunner()
        self._graphs: Dict[str, Any] = {}

    def _graph(self, name: str, builder: Callable[[], Any]) -> Any:
        graph = self._graphs.get(name)
        if graph is None:
            graph = builder()
            self._graphs[name] = graph
        return graph

    def _invoke_graph(self, name: str, builder: Callable[[], Any], payload: Dict[str, Any]) -> Dict[str, Any] | None:
        try:
            return self._graph(name, builder).invoke(payload)
        except Exception:
            return None

    def run_frontier_cycle(
        self,
        controller: Any,
        execute_fn: Callable[[Any], Any],
        select_fn: Callable[[Any, Any], FrontierOutcome],
        *,
        passthrough_exceptions: tuple[type[BaseException], ...] = (),
    ) -> FrontierCycleResult:
        payload = {
            "controller": controller,
            "execute_fn": execute_fn,
            "select_fn": select_fn,
            "passthrough_exceptions": passthrough_exceptions,
            "scheduled": False,
            "action": None,
            "execution": None,
            "outcome": None,
            "stop_reason": "",
        }
        try:
            graph = self._graph("frontier_cycle", self._build_frontier_cycle_graph)
        except Exception:
            return self.native.run_frontier_cycle(
                controller,
                execute_fn,
                select_fn,
                passthrough_exceptions=passthrough_exceptions,
            ).model_copy(update={"backend_used": "native_fallback"})
        try:
            result = graph.invoke(payload)
        except passthrough_exceptions:
            running = next(
                (action for action in controller.scheduler.state.actions if action.status == "running"),
                None,
            )
            if running is not None:
                controller.scheduler.release(running.action_id)
            raise
        except Exception as exc:
            running = next(
                (action for action in controller.scheduler.state.actions if action.status == "running"),
                None,
            )
            if running is not None:
                outcome = FrontierOutcome(
                    action_id=running.action_id,
                    status="failed",
                    error=f"LangGraphCycleError: {exc.__class__.__name__}: {exc}",
                )
                controller.complete_action(outcome)
                return FrontierCycleResult(
                    scheduled=True,
                    action=running,
                    outcome=outcome,
                    stop_reason=str(controller.scheduler.state.stop_reason or controller.state.stop_reason or ""),
                    backend_used="langgraph_error",
                )
            return FrontierCycleResult(
                scheduled=False,
                stop_reason=str(controller.scheduler.state.stop_reason or controller.state.stop_reason or ""),
                backend_used="langgraph_error",
            )
        action = result.get("action")
        outcome = result.get("outcome")
        if isinstance(action, dict):
            from paperseek_core.harness.schemas import FrontierAction

            action = FrontierAction.model_validate(action)
        if isinstance(outcome, dict):
            outcome = FrontierOutcome.model_validate(outcome)
        return FrontierCycleResult(
            scheduled=bool(result.get("scheduled")),
            action=action,
            execution=result.get("execution"),
            outcome=outcome,
            stop_reason=str(result.get("stop_reason") or ""),
            backend_used=self.backend_used,
        )

    def decide(self, snapshot: QueryLoopSnapshot) -> QueryLoopDecision:
        return self.native.decide(snapshot)

    def evaluate(self, state: SearchRunState, snapshot: QueryLoopSnapshot) -> tuple[SearchRunState, QueryLoopDecision]:
        result = self._invoke_graph("evaluate", self._build_graph, {
            "run_state": state,
            "snapshot": snapshot,
            "validation": None,
            "observation": None,
            "decision": None,
        })
        if result is None:
            return self.native.evaluate(state, snapshot)
        updated = result.get("run_state")
        decision = result.get("decision")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(decision, dict):
            decision = QueryLoopDecision(**decision)
        if isinstance(updated, SearchRunState) and isinstance(decision, QueryLoopDecision):
            return updated, decision
        return self.native.evaluate(state, snapshot)

    def preflight(self, state: SearchRunState, query: str) -> tuple[SearchRunState, QueryValidation]:
        result = self._invoke_graph("preflight", self._build_preflight_graph, {"run_state": state, "query": query, "validation": None})
        if result is None:
            return self.native.preflight(state, query)
        updated = result.get("run_state")
        validation = result.get("validation")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(validation, dict):
            validation = QueryValidation(**validation)
        if isinstance(updated, SearchRunState) and isinstance(validation, QueryValidation):
            return updated, validation
        return self.native.preflight(state, query)

    def source_search(
        self,
        state: SearchRunState,
        query: str,
        search_fn: Callable[[str], Any],
    ) -> tuple[SearchRunState, Any, Exception | None]:
        result = self._invoke_graph("source_search", self._build_source_search_graph, {
            "run_state": state,
            "query": query,
            "search_fn": search_fn,
            "result": None,
            "error": None,
        })
        if result is None:
            return self.native.source_search(state, query, search_fn)
        updated = result.get("run_state")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(updated, SearchRunState):
            return updated, result.get("result"), result.get("error")
        return self.native.source_search(state, query, search_fn)

    def recover_source_error(
        self,
        state: SearchRunState,
        error: Exception,
        *,
        query: str = "",
        repair_attempts: int = 0,
        max_repair_attempts: int = 2,
        has_server_error_variant: bool = False,
        allow_broaden_query: bool = False,
    ) -> tuple[SearchRunState, SourceRecoveryDecision]:
        result = self._invoke_graph("source_recovery", self._build_source_recovery_graph, {
            "run_state": state,
            "error": error,
            "query": query,
            "repair_attempts": repair_attempts,
            "max_repair_attempts": max_repair_attempts,
            "has_server_error_variant": has_server_error_variant,
            "allow_broaden_query": allow_broaden_query,
            "decision": None,
        })
        if result is None:
            return self.native.recover_source_error(
                state,
                error,
                query=query,
                repair_attempts=repair_attempts,
                max_repair_attempts=max_repair_attempts,
                has_server_error_variant=has_server_error_variant,
                allow_broaden_query=allow_broaden_query,
            )
        updated = result.get("run_state")
        decision = result.get("decision")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(decision, dict):
            decision = SourceRecoveryDecision(**decision)
        if isinstance(updated, SearchRunState) and isinstance(decision, SourceRecoveryDecision):
            return updated, decision
        return self.native.recover_source_error(
            state,
            error,
            query=query,
            repair_attempts=repair_attempts,
            max_repair_attempts=max_repair_attempts,
            has_server_error_variant=has_server_error_variant,
            allow_broaden_query=allow_broaden_query,
        )

    def observe_ranking_batch_error(
        self,
        state: SearchRunState,
        error: Exception,
        *,
        step_id: str = "",
        batch_index: int = 0,
        batch_count: int = 0,
        concurrency: int = 0,
        candidate_count: int = 0,
        rate_limited: bool = False,
    ) -> tuple[SearchRunState, RankingBatchObservation]:
        result = self._invoke_graph("ranking_batch_error", self._build_ranking_batch_error_graph, {
            "run_state": state,
            "error": error,
            "step_id": step_id,
            "batch_index": batch_index,
            "batch_count": batch_count,
            "concurrency": concurrency,
            "candidate_count": candidate_count,
            "rate_limited": rate_limited,
            "observation": None,
        })
        if result is None:
            return self.native.observe_ranking_batch_error(
                state,
                error,
                step_id=step_id,
                batch_index=batch_index,
                batch_count=batch_count,
                concurrency=concurrency,
                candidate_count=candidate_count,
                rate_limited=rate_limited,
            )
        updated = result.get("run_state")
        observation = result.get("observation")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(observation, dict):
            observation = RankingBatchObservation(**observation)
        if isinstance(updated, SearchRunState) and isinstance(observation, RankingBatchObservation):
            return updated, observation
        return self.native.observe_ranking_batch_error(
            state,
            error,
            step_id=step_id,
            batch_index=batch_index,
            batch_count=batch_count,
            concurrency=concurrency,
            candidate_count=candidate_count,
            rate_limited=rate_limited,
        )

    def recover_ranking_failures(
        self,
        state: SearchRunState,
        *,
        step_id: str = "",
        concurrency: int = 0,
        next_concurrency: int = 0,
        failed_batches: int = 0,
        failed_candidates: int = 0,
        rate_limited: bool = False,
    ) -> tuple[SearchRunState, RankingRecoveryDecision]:
        result = self._invoke_graph("ranking_recovery", self._build_ranking_recovery_graph, {
            "run_state": state,
            "step_id": step_id,
            "concurrency": concurrency,
            "next_concurrency": next_concurrency,
            "failed_batches": failed_batches,
            "failed_candidates": failed_candidates,
            "rate_limited": rate_limited,
            "decision": None,
        })
        if result is None:
            return self.native.recover_ranking_failures(
                state,
                step_id=step_id,
                concurrency=concurrency,
                next_concurrency=next_concurrency,
                failed_batches=failed_batches,
                failed_candidates=failed_candidates,
                rate_limited=rate_limited,
            )
        updated = result.get("run_state")
        decision = result.get("decision")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(decision, dict):
            decision = RankingRecoveryDecision(**decision)
        if isinstance(updated, SearchRunState) and isinstance(decision, RankingRecoveryDecision):
            return updated, decision
        return self.native.recover_ranking_failures(
            state,
            step_id=step_id,
            concurrency=concurrency,
            next_concurrency=next_concurrency,
            failed_batches=failed_batches,
            failed_candidates=failed_candidates,
            rate_limited=rate_limited,
        )

    def plan_citation_expansion(
        self,
        state: SearchRunState,
        *,
        candidate_count: int = 0,
        seed_ranking_count: int = 0,
        configured_seed_count: int = 30,
        configured_depth: int = 2,
    ) -> tuple[SearchRunState, CitationPlanningDecision]:
        result = self._invoke_graph("citation_planning", self._build_citation_planning_graph, {
            "run_state": state,
            "candidate_count": candidate_count,
            "seed_ranking_count": seed_ranking_count,
            "configured_seed_count": configured_seed_count,
            "configured_depth": configured_depth,
            "decision": None,
        })
        if result is None:
            return self.native.plan_citation_expansion(
                state,
                candidate_count=candidate_count,
                seed_ranking_count=seed_ranking_count,
                configured_seed_count=configured_seed_count,
                configured_depth=configured_depth,
            )
        updated = result.get("run_state")
        decision = result.get("decision")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(decision, dict):
            decision = CitationPlanningDecision(**decision)
        if isinstance(updated, SearchRunState) and isinstance(decision, CitationPlanningDecision):
            return updated, decision
        return self.native.plan_citation_expansion(
            state,
            candidate_count=candidate_count,
            seed_ranking_count=seed_ranking_count,
            configured_seed_count=configured_seed_count,
            configured_depth=configured_depth,
        )

    def observe_citation_traversal(
        self,
        state: SearchRunState,
        *,
        status: str,
        seed_count: int = 0,
        depth: int = 0,
        per_seed: int = 0,
        max_records: int = 0,
        added_candidates: int = 0,
        candidate_pool: int = 0,
        frontier: dict | None = None,
        error: Exception | None = None,
    ) -> tuple[SearchRunState, CitationTraversalObservation]:
        result = self._invoke_graph("citation_observation", self._build_citation_observation_graph, {
            "run_state": state,
            "status": status,
            "seed_count": seed_count,
            "depth": depth,
            "per_seed": per_seed,
            "max_records": max_records,
            "added_candidates": added_candidates,
            "candidate_pool": candidate_pool,
            "frontier": frontier,
            "error": error,
            "observation": None,
        })
        if result is None:
            return self.native.observe_citation_traversal(
                state,
                status=status,
                seed_count=seed_count,
                depth=depth,
                per_seed=per_seed,
                max_records=max_records,
                added_candidates=added_candidates,
                candidate_pool=candidate_pool,
                frontier=frontier,
                error=error,
            )
        updated = result.get("run_state")
        observation = result.get("observation")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(observation, dict):
            observation = CitationTraversalObservation(**observation)
        if isinstance(updated, SearchRunState) and isinstance(observation, CitationTraversalObservation):
            return updated, observation
        return self.native.observe_citation_traversal(
            state,
            status=status,
            seed_count=seed_count,
            depth=depth,
            per_seed=per_seed,
            max_records=max_records,
            added_candidates=added_candidates,
            candidate_pool=candidate_pool,
            frontier=frontier,
            error=error,
        )

    def recover_citation_error(
        self,
        state: SearchRunState,
        error: Exception,
        *,
        seed_count: int = 0,
        depth: int = 0,
        per_seed: int = 0,
        max_records: int = 0,
        retry_attempts: int = 0,
        max_retries: int = 1,
    ) -> tuple[SearchRunState, CitationRecoveryDecision]:
        result = self._invoke_graph("citation_recovery", self._build_citation_recovery_graph, {
            "run_state": state,
            "error": error,
            "seed_count": seed_count,
            "depth": depth,
            "per_seed": per_seed,
            "max_records": max_records,
            "retry_attempts": retry_attempts,
            "max_retries": max_retries,
            "decision": None,
        })
        if result is None:
            return self.native.recover_citation_error(
                state,
                error,
                seed_count=seed_count,
                depth=depth,
                per_seed=per_seed,
                max_records=max_records,
                retry_attempts=retry_attempts,
                max_retries=max_retries,
            )
        updated = result.get("run_state")
        decision = result.get("decision")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(decision, dict):
            decision = CitationRecoveryDecision(**decision)
        if isinstance(updated, SearchRunState) and isinstance(decision, CitationRecoveryDecision):
            return updated, decision
        return self.native.recover_citation_error(
            state,
            error,
            seed_count=seed_count,
            depth=depth,
            per_seed=per_seed,
            max_records=max_records,
            retry_attempts=retry_attempts,
            max_retries=max_retries,
        )

    def update_candidate_queue(
        self,
        state: SearchRunState,
        *,
        candidate_keys: list[str],
        origin: str = "",
    ) -> tuple[SearchRunState, CandidateQueueEvent]:
        result = self._invoke_graph("candidate_queue", self._build_candidate_queue_graph, {
            "run_state": state,
            "candidate_keys": list(candidate_keys or []),
            "origin": origin,
            "event": None,
        })
        if result is None:
            return self.native.update_candidate_queue(state, candidate_keys=candidate_keys, origin=origin)
        updated = result.get("run_state")
        event = result.get("event")
        if isinstance(updated, dict):
            updated = SearchRunState(**updated)
        if isinstance(event, dict):
            event = CandidateQueueEvent(**event)
        if isinstance(updated, SearchRunState) and isinstance(event, CandidateQueueEvent):
            return updated, event
        return self.native.update_candidate_queue(state, candidate_keys=candidate_keys, origin=origin)

    def _build_frontier_cycle_graph(self):
        graph = StateGraph(dict)

        def schedule_node(state: Dict[str, Any]) -> Dict[str, Any]:
            controller = state["controller"]
            actions = controller.next_actions(1)
            return {
                **state,
                "scheduled": bool(actions),
                "action": actions[0] if actions else None,
            }

        def execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
            action = state["action"]
            try:
                execution = state["execute_fn"](action)
                return {**state, "execution": execution, "outcome": None}
            except state.get("passthrough_exceptions") or ():
                raise
            except Exception as exc:
                return {
                    **state,
                    "execution": None,
                    "outcome": FrontierOutcome(
                        action_id=action.action_id,
                        status="failed",
                        error=f"{exc.__class__.__name__}: {exc}",
                    ),
                }

        def select_node(state: Dict[str, Any]) -> Dict[str, Any]:
            action = state["action"]
            try:
                outcome = state["select_fn"](action, state.get("execution"))
                if not isinstance(outcome, FrontierOutcome):
                    raise TypeError("frontier select_fn must return FrontierOutcome")
                return {**state, "outcome": outcome}
            except state.get("passthrough_exceptions") or ():
                raise
            except Exception as exc:
                return {
                    **state,
                    "outcome": FrontierOutcome(
                        action_id=action.action_id,
                        status="failed",
                        error=f"{exc.__class__.__name__}: {exc}",
                    ),
                }

        def decide_node(state: Dict[str, Any]) -> Dict[str, Any]:
            state["controller"].complete_action(state["outcome"])
            return state

        def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
            controller = state["controller"]
            return {
                **state,
                "stop_reason": str(
                    controller.scheduler.state.stop_reason or controller.state.stop_reason or ""
                ),
            }

        graph.add_node("schedule", RunnableLambda(schedule_node))
        graph.add_node("execute", RunnableLambda(execute_node))
        graph.add_node("select", RunnableLambda(select_node))
        graph.add_node("decide", RunnableLambda(decide_node))
        graph.add_node("finalize", RunnableLambda(finalize_node))
        graph.set_entry_point("schedule")
        graph.add_conditional_edges(
            "schedule",
            lambda state: "execute" if state.get("scheduled") else "finalize",
            {"execute": "execute", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "execute",
            lambda state: "decide" if state.get("outcome") is not None else "select",
            {"decide": "decide", "select": "select"},
        )
        graph.add_edge("select", "decide")
        graph.add_edge("decide", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _build_graph(self):
        graph = StateGraph(dict)

        def decide_node(state: Dict[str, Any]) -> Dict[str, Any]:
            return {**state, "decision": self.native.decide(state["snapshot"])}

        def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
            run_state: SearchRunState = state["run_state"]
            return {
                **state,
                "validation": validate_source_query(run_state.source, run_state.current_query).model_copy(update={"stage": "post_search"}),
            }

        def observe_node(state: Dict[str, Any]) -> Dict[str, Any]:
            run_state: SearchRunState = state["run_state"]
            snapshot: QueryLoopSnapshot = state["snapshot"]
            return {
                **state,
                "observation": SourceObservation(
                    iteration=snapshot.iteration,
                    query=run_state.current_query,
                    total=max(0, int(snapshot.total or 0)),
                    hit_count=max(0, int(snapshot.hit_count or 0)),
                    top_titles=list(snapshot.top_titles or []),
                )
            }

        def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
            run_state: SearchRunState = state["run_state"]
            decision = state["decision"]
            terminal_status = decision.action if decision.terminal else run_state.terminal_status
            return {
                **state,
                "run_state": run_state.model_copy(update={
                    "validations": [*run_state.validations, state["validation"]],
                    "observations": [*run_state.observations, state["observation"]],
                    "decisions": [*run_state.decisions, decision],
                    "terminal_status": terminal_status,
                })
            }

        graph.add_node("validate", RunnableLambda(validate_node))
        graph.add_node("observe", RunnableLambda(observe_node))
        graph.add_node("decide", RunnableLambda(decide_node))
        graph.add_node("finalize", RunnableLambda(finalize_node))
        graph.set_entry_point("validate")
        graph.add_edge("validate", "observe")
        graph.add_edge("observe", "decide")
        graph.add_edge("decide", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _build_preflight_graph(self):
        graph = StateGraph(dict)

        def preflight_node(state: Dict[str, Any]) -> Dict[str, Any]:
            run_state: SearchRunState = state["run_state"].with_current_query(state.get("query", ""))
            validation = validate_source_query(run_state.source, run_state.current_query).model_copy(update={"stage": "preflight"})
            updated = run_state.model_copy(update={"validations": [*run_state.validations, validation]})
            return {**state, "run_state": updated, "validation": validation}

        graph.add_node("preflight", RunnableLambda(preflight_node))
        graph.set_entry_point("preflight")
        graph.add_edge("preflight", END)
        return graph.compile()

    def _build_source_search_graph(self):
        graph = StateGraph(dict)

        def source_search_node(state: Dict[str, Any]) -> Dict[str, Any]:
            run_state: SearchRunState = state["run_state"].with_current_query(state.get("query", ""))
            search_fn = state["search_fn"]
            try:
                result = search_fn(run_state.current_query)
                return {**state, "run_state": run_state, "result": result, "error": None}
            except Exception as exc:
                updated = run_state.with_error(
                    classify_error(exc, stage="source_search", source=run_state.source, query=run_state.current_query)
                )
                return {**state, "run_state": updated, "result": None, "error": exc}

        graph.add_node("source_search", RunnableLambda(source_search_node))
        graph.set_entry_point("source_search")
        graph.add_edge("source_search", END)
        return graph.compile()

    def _build_source_recovery_graph(self):
        graph = StateGraph(dict)

        def recover_node(state: Dict[str, Any]) -> Dict[str, Any]:
            updated, decision = self.native.recover_source_error(
                state["run_state"],
                state["error"],
                query=state.get("query", ""),
                repair_attempts=int(state.get("repair_attempts") or 0),
                max_repair_attempts=int(state.get("max_repair_attempts") or 0),
                has_server_error_variant=bool(state.get("has_server_error_variant")),
                allow_broaden_query=bool(state.get("allow_broaden_query")),
            )
            return {**state, "run_state": updated, "decision": decision}

        graph.add_node("recover_source_error", RunnableLambda(recover_node))
        graph.set_entry_point("recover_source_error")
        graph.add_edge("recover_source_error", END)
        return graph.compile()

    def _build_ranking_batch_error_graph(self):
        graph = StateGraph(dict)

        def observe_node(state: Dict[str, Any]) -> Dict[str, Any]:
            updated, observation = self.native.observe_ranking_batch_error(
                state["run_state"],
                state["error"],
                step_id=state.get("step_id", ""),
                batch_index=int(state.get("batch_index") or 0),
                batch_count=int(state.get("batch_count") or 0),
                concurrency=int(state.get("concurrency") or 0),
                candidate_count=int(state.get("candidate_count") or 0),
                rate_limited=bool(state.get("rate_limited")),
            )
            return {**state, "run_state": updated, "observation": observation}

        graph.add_node("observe_ranking_batch_error", RunnableLambda(observe_node))
        graph.set_entry_point("observe_ranking_batch_error")
        graph.add_edge("observe_ranking_batch_error", END)
        return graph.compile()

    def _build_ranking_recovery_graph(self):
        graph = StateGraph(dict)

        def recover_node(state: Dict[str, Any]) -> Dict[str, Any]:
            updated, decision = self.native.recover_ranking_failures(
                state["run_state"],
                step_id=state.get("step_id", ""),
                concurrency=int(state.get("concurrency") or 0),
                next_concurrency=int(state.get("next_concurrency") or 0),
                failed_batches=int(state.get("failed_batches") or 0),
                failed_candidates=int(state.get("failed_candidates") or 0),
                rate_limited=bool(state.get("rate_limited")),
            )
            return {**state, "run_state": updated, "decision": decision}

        graph.add_node("recover_ranking_failures", RunnableLambda(recover_node))
        graph.set_entry_point("recover_ranking_failures")
        graph.add_edge("recover_ranking_failures", END)
        return graph.compile()

    def _build_citation_planning_graph(self):
        graph = StateGraph(dict)

        def plan_node(state: Dict[str, Any]) -> Dict[str, Any]:
            updated, decision = self.native.plan_citation_expansion(
                state["run_state"],
                candidate_count=int(state.get("candidate_count") or 0),
                seed_ranking_count=int(state.get("seed_ranking_count") or 0),
                configured_seed_count=int(state.get("configured_seed_count") or 30),
                configured_depth=int(state.get("configured_depth") or 2),
            )
            return {**state, "run_state": updated, "decision": decision}

        graph.add_node("plan_citation_expansion", RunnableLambda(plan_node))
        graph.set_entry_point("plan_citation_expansion")
        graph.add_edge("plan_citation_expansion", END)
        return graph.compile()

    def _build_citation_observation_graph(self):
        graph = StateGraph(dict)

        def observe_node(state: Dict[str, Any]) -> Dict[str, Any]:
            updated, observation = self.native.observe_citation_traversal(
                state["run_state"],
                status=state.get("status", ""),
                seed_count=int(state.get("seed_count") or 0),
                depth=int(state.get("depth") or 0),
                per_seed=int(state.get("per_seed") or 0),
                max_records=int(state.get("max_records") or 0),
                added_candidates=int(state.get("added_candidates") or 0),
                candidate_pool=int(state.get("candidate_pool") or 0),
                frontier=state.get("frontier"),
                error=state.get("error"),
            )
            return {**state, "run_state": updated, "observation": observation}

        graph.add_node("observe_citation_traversal", RunnableLambda(observe_node))
        graph.set_entry_point("observe_citation_traversal")
        graph.add_edge("observe_citation_traversal", END)
        return graph.compile()

    def _build_citation_recovery_graph(self):
        graph = StateGraph(dict)

        def recover_node(state: Dict[str, Any]) -> Dict[str, Any]:
            updated, decision = self.native.recover_citation_error(
                state["run_state"],
                state["error"],
                seed_count=int(state.get("seed_count") or 0),
                depth=int(state.get("depth") or 0),
                per_seed=int(state.get("per_seed") or 0),
                max_records=int(state.get("max_records") or 0),
                retry_attempts=int(state.get("retry_attempts") or 0),
                max_retries=int(state.get("max_retries") or 1),
            )
            return {**state, "run_state": updated, "decision": decision}

        graph.add_node("recover_citation_error", RunnableLambda(recover_node))
        graph.set_entry_point("recover_citation_error")
        graph.add_edge("recover_citation_error", END)
        return graph.compile()

    def _build_candidate_queue_graph(self):
        graph = StateGraph(dict)

        def queue_node(state: Dict[str, Any]) -> Dict[str, Any]:
            updated, event = self.native.update_candidate_queue(
                state["run_state"],
                candidate_keys=list(state.get("candidate_keys") or []),
                origin=state.get("origin", ""),
            )
            return {**state, "run_state": updated, "event": event}

        graph.add_node("update_candidate_queue", RunnableLambda(queue_node))
        graph.set_entry_point("update_candidate_queue")
        graph.add_edge("update_candidate_queue", END)
        return graph.compile()
