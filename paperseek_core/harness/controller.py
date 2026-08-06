
from typing import Any, Callable, Dict

from paperseek_core.harness.native_loop import NativeQueryLoopRunner
from paperseek_core.harness.schemas import (
    QueryLoopDecision,
    QueryLoopSnapshot,
    QueryValidation,
    CandidateQueueEvent,
    CitationPlanningDecision,
    CitationRecoveryDecision,
    CitationTraversalObservation,
    RankingBatchObservation,
    RankingRecoveryDecision,
    SearchRunState,
    SourceRecoveryDecision,
)


class SearchLoopController:
    """Stable query-iteration controller backed by the native runner."""

    def __init__(self, backend: str = "native"):
        self.backend_requested = (backend or "native").strip().lower()
        self.import_error = ""
        if self.backend_requested not in {"", "auto", "native"}:
            self.import_error = (
                f"Search loop backend '{self.backend_requested}' is no longer supported; using native"
            )
        self.runner = NativeQueryLoopRunner()
        self.backend_used = self.runner.backend_used

    @classmethod
    def from_config(cls, config: Any) -> "SearchLoopController":
        backend = getattr(config, "search_loop_backend", None) or getattr(config, "harness_backend", None) or "native"
        return cls(backend=backend)

    def summary(self) -> Dict[str, str]:
        payload = {
            "backend_requested": self.backend_requested,
            "backend_used": self.backend_used,
        }
        if self.import_error:
            payload["fallback_reason"] = self.import_error
        return payload

    def decide(self, snapshot: QueryLoopSnapshot) -> QueryLoopDecision:
        return self.runner.decide(snapshot)

    def evaluate(self, state: SearchRunState, snapshot: QueryLoopSnapshot) -> tuple[SearchRunState, QueryLoopDecision]:
        return self.runner.evaluate(state, snapshot)

    def preflight(self, state: SearchRunState, query: str) -> tuple[SearchRunState, QueryValidation]:
        return self.runner.preflight(state, query)

    def source_search(
        self,
        state: SearchRunState,
        query: str,
        search_fn: Callable[[str], Any],
    ) -> tuple[SearchRunState, Any, Exception | None]:
        return self.runner.source_search(state, query, search_fn)

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
        return self.runner.recover_source_error(
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
        return self.runner.observe_ranking_batch_error(
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
        return self.runner.recover_ranking_failures(
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
        return self.runner.plan_citation_expansion(
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
        return self.runner.observe_citation_traversal(
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
        return self.runner.recover_citation_error(
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
        return self.runner.update_candidate_queue(state, candidate_keys=candidate_keys, origin=origin)
