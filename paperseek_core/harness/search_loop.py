
import re

from typing import Any, Callable

from paperseek_core.harness.errors import classify_error
from paperseek_core.harness.schemas import (
    ACTION_ACCEPT,
    ACTION_ACCEPT_HIGH,
    ACTION_ACCEPT_LOW,
    ACTION_ACCEPT_POOL,
    ACTION_BROADEN,
    ACTION_EMPTY,
    ACTION_NARROW,
    CITATION_RETRY_REDUCED,
    CITATION_SKIP_EXPANSION,
    RECOVERY_BROADEN_QUERY,
    RECOVERY_FAIL,
    RECOVERY_REPAIR_QUERY,
    RECOVERY_SIMPLIFY_QUERY,
    RANKING_KEEP_LOCAL_ORDER,
    RANKING_RETRY_LOWER_CONCURRENCY,
    RANKING_RETRY_SAME_TIER,
    QueryLoopDecision,
    QueryLoopSnapshot,
    QueryValidation,
    CandidateQueueEvent,
    CandidateQueueState,
    CitationFrontierState,
    CitationPlanningDecision,
    CitationRecoveryDecision,
    CitationTraversalObservation,
    RankingBatchObservation,
    RankingRecoveryDecision,
    SearchRunState,
    SourceRecoveryDecision,
    SourceObservation,
)
from paperseek_core.harness.query_contract import validate_source_query


_TITLE_DRIFT_STOPWORDS = {
    "about",
    "across",
    "after",
    "against",
    "analysis",
    "and",
    "are",
    "based",
    "between",
    "boundaries",
    "case",
    "concept",
    "concepts",
    "core",
    "data",
    "effect",
    "effects",
    "from",
    "how",
    "intent",
    "into",
    "likely",
    "literature",
    "method",
    "methods",
    "model",
    "models",
    "not",
    "only",
    "paper",
    "papers",
    "query",
    "research",
    "result",
    "results",
    "search",
    "study",
    "studies",
    "synonyms",
    "that",
    "the",
    "their",
    "this",
    "through",
    "using",
    "what",
    "when",
    "where",
    "with",
}
_TITLE_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{1,}|[\u4e00-\u9fff]{2,}")


def _normalise_title_signal_terms(terms: list[str], *, limit: int = 16) -> list[str]:
    seen: set[str] = set()
    clean_terms: list[str] = []
    for term in terms:
        for match in _TITLE_TERM_RE.findall(str(term or "")):
            clean = match.strip("-").lower()
            if len(clean) < 3 and not match.isupper():
                continue
            if clean in _TITLE_DRIFT_STOPWORDS or clean in seen:
                continue
            seen.add(clean)
            clean_terms.append(clean)
            if len(clean_terms) >= limit:
                return clean_terms
    return clean_terms


def _title_feedback_drift(snapshot: QueryLoopSnapshot) -> tuple[bool, str, str]:
    titles = [str(title or "").strip() for title in snapshot.top_titles[:5] if str(title or "").strip()]
    if len(titles) < 3:
        return False, "", ""
    signal_terms = _normalise_title_signal_terms(list(snapshot.intent_terms or []) or [snapshot.query])
    if len(signal_terms) < 3:
        return False, "", ""
    title_text = " ".join(titles).lower()
    covered = [term for term in signal_terms if term in title_text]
    coverage = len(covered) / max(1, len(signal_terms))
    drifted = len(covered) == 0 or (len(signal_terms) >= 6 and len(covered) < 2 and coverage < 0.20)
    if not drifted:
        return False, "", ""
    missing = [term for term in signal_terms if term not in covered][:6]
    adjustment = (
        "top returned titles appear off-intent; preserve the core intent and redirect the query toward "
        f"missing facets: {', '.join(missing)}"
    )
    reason = (
        f"Title-intent coverage was low before accepting the count "
        f"({len(covered)}/{len(signal_terms)} signal terms matched in the top titles)."
    )
    return True, adjustment, reason


def _contiguous_broad_narrowing_totals(snapshot: QueryLoopSnapshot, pool_max: int) -> list[int]:
    """Return the immediately preceding over-budget counts from narrowing rounds."""
    totals: list[int] = []
    for row in reversed(snapshot.history):
        action = str(row.get("action") or "").strip().lower()
        if action in {"repair", "sanitize"}:
            continue
        if action != ACTION_NARROW:
            break
        try:
            row_total = int(row.get("total"))
        except (TypeError, ValueError):
            break
        if row_total <= pool_max:
            break
        totals.append(row_total)
    totals.reverse()
    return totals


def _broad_narrowing_has_stalled(previous_totals: list[int], current_total: int) -> bool:
    """Treat two consecutive reductions below 10 percent as a stalled revision loop."""
    sequence = [*previous_totals[-2:], current_total]
    if len(sequence) < 3:
        return False
    reductions = [
        (before - after) / max(1, before)
        for before, after in zip(sequence, sequence[1:])
    ]
    return all(reduction < 0.10 for reduction in reductions)


class SearchLoopController:

    def preflight(self, state: SearchRunState, query: str) -> tuple[SearchRunState, QueryValidation]:
        current = state.with_current_query(query)
        validation = validate_source_query(current.source, current.current_query).model_copy(update={"stage": "preflight"})
        updated = current.model_copy(update={"validations": [*current.validations, validation]})
        return updated, validation

    def source_search(
        self,
        state: SearchRunState,
        query: str,
        search_fn: Callable[[str], Any],
    ) -> tuple[SearchRunState, Any, Exception | None]:
        current = state.with_current_query(query)
        try:
            return current, search_fn(query), None
        except Exception as exc:
            return current.with_error(classify_error(exc, stage="source_search", source=current.source, query=query)), None, exc

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
        observation = classify_error(error, stage="source_recovery", source=state.source, query=query or state.current_query)
        status = observation.status
        attempts = max(0, int(repair_attempts or 0))
        max_attempts = max(0, int(max_repair_attempts or 0))

        if status == 512 and has_server_error_variant:
            decision = SourceRecoveryDecision(
                action=RECOVERY_SIMPLIFY_QUERY,
                retryable=True,
                message="Source returned a server-side query error; try a simpler supported query variant.",
                reason="A deterministic simplified variant is available for this provider error.",
            )
        elif allow_broaden_query and status == 400:
            decision = SourceRecoveryDecision(
                action=RECOVERY_BROADEN_QUERY,
                retryable=True,
                message="Source rejected the query syntax; ask the query generator for a broader replacement.",
                reason="The provider reported a query-syntax error that can be recovered by replacing the query.",
            )
        elif observation.retryable and attempts < max_attempts:
            decision = SourceRecoveryDecision(
                action=RECOVERY_REPAIR_QUERY,
                retryable=True,
                message="Source rejected the query; repair source syntax and retry.",
                reason="The provider error is classified as retryable and repair budget remains.",
            )
        else:
            decision = SourceRecoveryDecision(
                action=RECOVERY_FAIL,
                retryable=False,
                message="Source error is not recoverable within the current budget.",
                reason="No applicable recovery route remains for this error.",
            )
        return state.with_recovery_decision(decision), decision

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
        error_observation = classify_error(error, stage="ranking_batch", source=state.source, query=state.current_query)
        observation = RankingBatchObservation(
            step_id=step_id,
            batch_index=max(0, int(batch_index or 0)),
            batch_count=max(0, int(batch_count or 0)),
            concurrency=max(0, int(concurrency or 0)),
            candidate_count=max(0, int(candidate_count or 0)),
            error_type=error_observation.error_type,
            message=error_observation.message,
            retryable=error_observation.retryable,
            rate_limited=bool(rate_limited),
        )
        return state.with_ranking_batch_observation(observation), observation

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
        current = max(0, int(concurrency or 0))
        next_tier = max(0, int(next_concurrency or 0))
        batch_count = max(0, int(failed_batches or 0))
        candidate_count = max(0, int(failed_candidates or 0))
        if next_tier >= 4 and next_tier == current:
            decision = RankingRecoveryDecision(
                action=RANKING_RETRY_SAME_TIER,
                step_id=step_id,
                concurrency=current,
                next_concurrency=next_tier,
                failed_batches=batch_count,
                failed_candidates=candidate_count,
                message=f"Retry {batch_count} ranking batch(es) once at concurrency={current}.",
                reason="The batch returned no valid scores; a same-tier retry can recover format drift without reducing throughput.",
                retryable=True,
            )
        elif next_tier >= 4:
            decision = RankingRecoveryDecision(
                action=RANKING_RETRY_LOWER_CONCURRENCY,
                step_id=step_id,
                concurrency=current,
                next_concurrency=next_tier,
                failed_batches=batch_count,
                failed_candidates=candidate_count,
                message=f"Retry {batch_count} failed ranking batch(es) with lower concurrency={next_tier}.",
                reason="Rate limit or transient batch failures can often recover at a lower concurrency tier."
                if rate_limited
                else "A lower concurrency tier remains available for failed ranking batches.",
                retryable=True,
            )
        else:
            decision = RankingRecoveryDecision(
                action=RANKING_KEEP_LOCAL_ORDER,
                step_id=step_id,
                concurrency=current,
                next_concurrency=0,
                failed_batches=batch_count,
                failed_candidates=candidate_count,
                message=f"Keep local pre-ranking order for {candidate_count} candidate(s) after ranking failures.",
                reason="No lower concurrency tier remains; preserve output instead of failing the whole search.",
                retryable=False,
            )
        return state.with_ranking_recovery_decision(decision), decision

    def plan_citation_expansion(
        self,
        state: SearchRunState,
        *,
        candidate_count: int = 0,
        seed_ranking_count: int = 0,
        configured_seed_count: int = 30,
        configured_depth: int = 2,
    ) -> tuple[SearchRunState, CitationPlanningDecision]:
        seed_limit = max(1, int(configured_seed_count or 30))
        depth = max(1, min(int(configured_depth or 2), 3))
        relevance_quota = max(1, seed_limit // 2)
        impact_quota = max(1, seed_limit // 4) if seed_limit > 1 else 0
        recent_quota = max(0, seed_limit - relevance_quota - impact_quota)
        decision = CitationPlanningDecision(
            seed_limit=seed_limit,
            depth=depth,
            relevance_quota=relevance_quota,
            impact_quota=impact_quota,
            recent_quota=recent_quota,
            candidate_count=max(0, int(candidate_count or 0)),
            seed_ranking_count=max(0, int(seed_ranking_count or 0)),
            message=(
                f"Plan citation expansion with up to {seed_limit} seed paper(s), "
                f"depth={depth}, and relevance/impact/recent quotas "
                f"{relevance_quota}/{impact_quota}/{recent_quota}."
            ),
            reason="Use separate seed roles so citation traversal covers semantic relevance, high-impact anchors, and recent work.",
        )
        return state.with_citation_planning_decision(decision), decision

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
        frontier: dict | CitationFrontierState | None = None,
        error: Exception | None = None,
    ) -> tuple[SearchRunState, CitationTraversalObservation]:
        error_observation = classify_error(error, stage="citation_expansion", source=state.source, query=state.current_query) if error else None
        observation = CitationTraversalObservation(
            status=str(status or ""),
            seed_count=max(0, int(seed_count or 0)),
            depth=max(0, int(depth or 0)),
            per_seed=max(0, int(per_seed or 0)),
            max_records=max(0, int(max_records or 0)),
            added_candidates=max(0, int(added_candidates or 0)),
            candidate_pool=max(0, int(candidate_pool or 0)),
            error_type=error_observation.error_type if error_observation else "",
            message=error_observation.message if error_observation else "",
            frontier=(
                frontier
                if isinstance(frontier, CitationFrontierState)
                else CitationFrontierState.model_validate(frontier or {})
            ),
        )
        return state.with_citation_traversal_observation(observation), observation

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
        observation = classify_error(error, stage="citation_expansion", source=state.source, query=state.current_query)
        attempts = max(0, int(retry_attempts or 0))
        retries = max(0, int(max_retries or 0))
        if seed_count > 0 and attempts < retries and (observation.retryable or observation.status is None):
            reduced_per_seed = max(1, min(int(per_seed or 1), max(1, int(per_seed or 1) // 2 or 1)))
            reduced_max_records = max(1, min(int(max_records or 1), max(1, int(max_records or 1) // 2 or 1)))
            decision = CitationRecoveryDecision(
                action=CITATION_RETRY_REDUCED,
                retryable=True,
                per_seed=reduced_per_seed,
                max_records=reduced_max_records,
                depth=1,
                message="Retry citation expansion once with a reduced traversal budget.",
                reason="Citation traversal is optional; a smaller retry can recover transient source failures without blocking final results.",
            )
        else:
            decision = CitationRecoveryDecision(
                action=CITATION_SKIP_EXPANSION,
                retryable=False,
                per_seed=0,
                max_records=0,
                depth=0,
                message="Skip citation expansion and keep the current candidate pool.",
                reason="Citation expansion remains optional and the retry budget is exhausted or unavailable.",
            )
        return state.with_citation_recovery_decision(decision), decision

    def update_candidate_queue(
        self,
        state: SearchRunState,
        *,
        candidate_keys: list[str],
        origin: str = "",
    ) -> tuple[SearchRunState, CandidateQueueEvent]:
        queue = state.candidate_queue
        existing = set(queue.keys)
        keys = list(queue.keys)
        added = 0
        duplicates = 0
        for raw_key in candidate_keys or []:
            key = str(raw_key or "").strip()
            if not key:
                continue
            if key in existing:
                duplicates += 1
                continue
            existing.add(key)
            keys.append(key)
            added += 1
        label = str(origin or "unknown")
        origin_counts = dict(queue.origin_counts)
        origin_counts[label] = int(origin_counts.get(label, 0) or 0) + added
        event = CandidateQueueEvent(
            origin=label,
            incoming=len([key for key in candidate_keys or [] if str(key or "").strip()]),
            added=added,
            duplicates=duplicates,
            total=len(keys),
            sample_keys=keys[-min(5, added):] if added else [],
        )
        updated_queue = CandidateQueueState(
            keys=keys,
            records=list(queue.records),
            ledger=dict(queue.ledger),
            origin_counts=origin_counts,
            duplicate_count=int(queue.duplicate_count or 0) + duplicates,
            events=[*queue.events, event],
        )
        return state.with_candidate_queue(updated_queue), event

    def evaluate(self, state: SearchRunState, snapshot: QueryLoopSnapshot) -> tuple[SearchRunState, QueryLoopDecision]:
        validation = validate_source_query(state.source, state.current_query).model_copy(update={"stage": "post_search"})
        observation = SourceObservation(
            iteration=snapshot.iteration,
            query=state.current_query,
            total=max(0, int(snapshot.total or 0)),
            hit_count=max(0, int(snapshot.hit_count or 0)),
            top_titles=list(snapshot.top_titles or []),
        )
        decision = self.decide(snapshot)
        terminal_status = decision.action if decision.terminal else state.terminal_status
        updated = state.model_copy(update={
            "validations": [*state.validations, validation],
            "observations": [*state.observations, observation],
            "decisions": [*state.decisions, decision],
            "terminal_status": terminal_status,
        })
        return updated, decision

    def decide(self, snapshot: QueryLoopSnapshot) -> QueryLoopDecision:
        total = max(0, int(snapshot.total or 0))
        iteration = max(1, int(snapshot.iteration or 1))
        configured = max(1, int(snapshot.configured_iterations or 1))
        adaptive = max(configured, int(snapshot.adaptive_max_iterations or configured))
        target_min = max(0, int(snapshot.target_min or 0))
        target_max = max(1, int(snapshot.target_max or 1))
        pool_min = max(0, int(snapshot.retrieval_pool_min or 0))
        pool_max = max(1, int(snapshot.retrieval_pool_max or target_max))

        if total == 0:
            if snapshot.consecutive_zero_results >= 3 or iteration >= adaptive:
                return QueryLoopDecision(
                    action=ACTION_EMPTY,
                    terminal=True,
                    message="No records found before the iteration limit was reached.",
                    adjustment="zero records",
                    reason="Stop only after repeated zero-result searches or the adaptive hard iteration budget.",
                )
            return QueryLoopDecision(
                action=ACTION_BROADEN,
                message="No records found; generated a broader query.",
                adjustment="too few or zero records",
                reason="Zero-result searches should broaden beyond the configured soft iteration count until the adaptive budget is exhausted.",
            )

        drifted, drift_adjustment, drift_reason = _title_feedback_drift(snapshot)
        if drifted and iteration < configured:
            return QueryLoopDecision(
                action=ACTION_NARROW,
                message=f"{total} records found, but the top returned titles appear off-intent; generated a redirected query.",
                adjustment=drift_adjustment,
                reason=drift_reason,
            )

        if target_min <= total <= target_max:
            return QueryLoopDecision(
                action=ACTION_ACCEPT,
                terminal=True,
                message=f"Accepted {total} records within the target range.",
                reason="The source count is inside the user-facing target range.",
            )

        if total < target_min:
            if total < pool_min and iteration < adaptive:
                return QueryLoopDecision(
                    action=ACTION_BROADEN,
                    message=f"Only {total} records found, below the target minimum of {target_min}; generated a broader query.",
                    adjustment=f"below target minimum {target_min}",
                    reason="The candidate pool is too small for robust downstream ranking.",
                )
            return QueryLoopDecision(
                action=ACTION_ACCEPT_LOW,
                terminal=True,
                message=f"Accepted {total} records at the iteration limit, below the target minimum of {target_min}.",
                adjustment=f"below target minimum {target_min}",
                reason="A small non-empty candidate pool can still be ranked after the adaptive budget is exhausted.",
            )

        if total > pool_max:
            previous_broad_totals = _contiguous_broad_narrowing_totals(snapshot, pool_max)
            stalled = _broad_narrowing_has_stalled(previous_broad_totals, total)
            if iteration < adaptive and not (iteration >= configured and stalled):
                previous_total = previous_broad_totals[-1] if previous_broad_totals else None
                trend = ""
                if previous_total is not None:
                    trend = (
                        f" The preceding broad query returned {previous_total} records; "
                        "use the title feedback to choose a different, intent-preserving constraint."
                    )
                return QueryLoopDecision(
                    action=ACTION_NARROW,
                    message=(
                        f"{total} records exceed the bounded retrieval pool of {pool_max}; "
                        "generated a narrower query before candidate materialization."
                    ),
                    adjustment=(
                        f"reduce the source result count toward {pool_max} or fewer by tightening one central "
                        "facet supported by the interpreted intent and returned titles; preserve the core intent."
                        f"{trend}"
                    ),
                    reason=(
                        "A database-wide count above the retrieval pool should be narrowed before bounded "
                        "retrieval; relevant top titles alone are not sufficient evidence to accept the long tail."
                    ),
                )
            stop_reason = (
                "successive narrowing rounds no longer reduced the broad source count meaningfully"
                if stalled
                else f"the adaptive hard limit of {adaptive} iterations was reached"
            )
            return QueryLoopDecision(
                action=ACTION_ACCEPT_HIGH,
                terminal=True,
                message=(
                    f"Accepted a broad source result set of {total} records after {stop_reason}; "
                    f"bounded retrieval lanes will cap the materialized candidate pool at {pool_max} before LLM ranking."
                ),
                adjustment=f"above LLM pre-ranking safety pool {pool_max}",
                reason=(
                    "Further query revision is unlikely to improve the source count within the remaining loop "
                    "budget, while downstream retrieval remains bounded."
                ),
            )

        if total > target_max:
            return QueryLoopDecision(
                action=ACTION_ACCEPT_POOL,
                terminal=True,
                message=f"Accepted {total} records for downstream pre-ranking; final displayed results are selected after retrieval fusion and LLM ranking.",
                adjustment=f"above target maximum {target_max}",
                reason="The count is above the display target but inside the safe retrieval pool, so downstream fusion should handle it.",
            )

        return QueryLoopDecision(
            action=ACTION_ACCEPT,
            terminal=True,
            message=f"Accepted {total} records within the target range.",
            reason="Fallback accept for a valid non-empty candidate pool.",
        )
