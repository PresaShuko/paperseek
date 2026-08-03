import hashlib
import time
from typing import Iterable

from paperseek_core.harness.schemas import (
    ActionFrontierState,
    FrontierAction,
    FrontierBudget,
    FrontierOutcome,
)


class FrontierScheduler:
    """Deterministic, budget-aware scheduler for search and paper actions."""

    def __init__(
        self,
        state: ActionFrontierState | None = None,
        *,
        low_yield_threshold: int = 1,
        low_yield_round_limit: int = 2,
    ):
        now = time.monotonic()
        self.state = state or ActionFrontierState(started_at_monotonic=now)
        # A monotonic timestamp is process-local and cannot be trusted after a
        # checkpoint is restored in another process. Persist elapsed time and
        # start a fresh local interval whenever a scheduler is constructed.
        self.state = self.state.model_copy(update={"started_at_monotonic": now})
        self.low_yield_threshold = max(0, int(low_yield_threshold or 0))
        self.low_yield_round_limit = max(1, int(low_yield_round_limit or 1))

    def enqueue(self, actions: Iterable[FrontierAction]) -> list[FrontierAction]:
        existing = {_action_identity(action) for action in self.state.actions}
        accepted: list[FrontierAction] = []
        all_actions = list(self.state.actions)
        for action in actions or []:
            identity = _action_identity(action)
            if identity in existing:
                continue
            existing.add(identity)
            normalized = self._with_priority(action.model_copy(update={"status": "pending"}))
            all_actions.append(normalized)
            accepted.append(normalized)
        stop_reason = self.state.stop_reason
        if accepted and any(self._budget_allows(action) for action in accepted):
            stop_reason = ""
        self.state = self.state.model_copy(update={"actions": all_actions, "stop_reason": stop_reason})
        return accepted

    def schedule(self, limit: int = 1) -> list[FrontierAction]:
        if self.should_stop():
            return []
        available = [
            self._with_priority(action)
            for action in self.state.actions
            if action.status == "pending" and self._budget_allows(action)
        ]
        selected = sorted(available, key=lambda action: (-action.priority, action.action_id))[:max(0, int(limit or 0))]
        selected_ids = {action.action_id for action in selected}
        updated = [
            action.model_copy(update={"status": "running"}) if action.action_id in selected_ids else action
            for action in self.state.actions
        ]
        self.state = self.state.model_copy(update={"actions": updated})
        return [action.model_copy(update={"status": "running"}) for action in selected]

    def complete(self, outcome: FrontierOutcome) -> FrontierAction:
        target = next((action for action in self.state.actions if action.action_id == outcome.action_id), None)
        if target is None:
            raise KeyError(f"unknown frontier action: {outcome.action_id}")
        status = outcome.status
        failure_penalty = target.failure_penalty + (1.0 if status == "failed" else 0.0)
        reason_codes = list(target.reason_codes)
        if status == "failed" and "action_failed" not in reason_codes:
            reason_codes.append("action_failed")
        completed = self._with_priority(
            target.model_copy(
                update={
                    "status": status,
                    "failure_penalty": failure_penalty,
                    "reason_codes": reason_codes,
                }
            )
        )
        actions = [completed if action.action_id == outcome.action_id else action for action in self.state.actions]
        budget = self._consume_budget(self.state.budget, target, outcome)
        newly_relevant = (
            outcome.newly_relevant_count
            if outcome.newly_relevant_count is not None
            else outcome.include_count
        )
        useful = newly_relevant + outcome.concept_gap_reduction
        low_yield_rounds = 0 if useful > self.low_yield_threshold else self.state.low_yield_rounds + 1
        self.state = self.state.model_copy(
            update={
                "actions": actions,
                "outcomes": [*self.state.outcomes, outcome],
                "budget": budget,
                "round_index": self.state.round_index + 1,
                "low_yield_rounds": low_yield_rounds,
            }
        )
        return completed

    def release(self, action_id: str, reason_code: str = "action_interrupted") -> FrontierAction:
        target = next((action for action in self.state.actions if action.action_id == action_id), None)
        if target is None:
            raise KeyError(f"unknown frontier action: {action_id}")
        released = target.model_copy(
            update={
                "status": "pending",
                "reason_codes": list(dict.fromkeys([*target.reason_codes, reason_code])),
            }
        )
        self.state = self.state.model_copy(
            update={
                "actions": [
                    released if action.action_id == action_id else action
                    for action in self.state.actions
                ],
                "stop_reason": "",
            }
        )
        return released

    def should_stop(self, concept_gaps: Iterable[str] | None = None) -> bool:
        if self.state.stop_reason:
            return True
        reason = self._budget_stop_reason()
        pending = [action for action in self.state.actions if action.status == "pending" and self._budget_allows(action)]
        gaps = [str(value).strip() for value in (concept_gaps or []) if str(value).strip()]
        if not reason and not pending:
            reason = "frontier_empty"
        if not reason and self.state.low_yield_rounds >= self.low_yield_round_limit and not gaps:
            reason = "marginal_gain_exhausted"
        if reason:
            self.state = self.state.model_copy(update={"stop_reason": reason})
            return True
        return False

    def snapshot(self) -> ActionFrontierState:
        now = time.monotonic()
        elapsed = self.state.elapsed_seconds + max(0.0, now - self.state.started_at_monotonic)
        self.state = self.state.model_copy(
            update={"elapsed_seconds": elapsed, "started_at_monotonic": now}
        )
        return self.state

    def replace_pending(self, actions: Iterable[FrontierAction]) -> None:
        updates = {action.action_id: self._with_priority(action) for action in actions or []}
        self.state = self.state.model_copy(
            update={
                "actions": [
                    updates.get(action.action_id, action) if action.status == "pending" else action
                    for action in self.state.actions
                ]
            }
        )

    @staticmethod
    def make_action(
        action_type: str,
        *,
        source: str = "",
        query: str = "",
        candidate_id: str = "",
        depth: int = 0,
        expected_gain: float = 0.0,
        concept_gap_coverage: float = 0.0,
        source_diversity_gain: float = 0.0,
        citation_seed_quality: float = 0.0,
        estimated_cost: float = 1.0,
        duplicate_risk: float = 0.0,
        failure_penalty: float = 0.0,
        reason_codes: list[str] | None = None,
    ) -> FrontierAction:
        raw = "\0".join((action_type, source, query, candidate_id, str(depth)))
        action_id = f"{action_type}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"
        return FrontierAction(
            action_id=action_id,
            action_type=action_type,
            source=source,
            query=query,
            candidate_id=candidate_id,
            depth=depth,
            expected_gain=expected_gain,
            concept_gap_coverage=concept_gap_coverage,
            source_diversity_gain=source_diversity_gain,
            citation_seed_quality=citation_seed_quality,
            estimated_cost=estimated_cost,
            duplicate_risk=duplicate_risk,
            failure_penalty=failure_penalty,
            reason_codes=list(reason_codes or []),
        )

    @staticmethod
    def _with_priority(action: FrontierAction) -> FrontierAction:
        priority = (
            action.expected_gain
            + action.concept_gap_coverage
            + action.source_diversity_gain
            + action.citation_seed_quality
            - action.estimated_cost
            - action.duplicate_risk
            - action.failure_penalty
        )
        return action.model_copy(update={"priority": round(priority, 6)})

    def _budget_allows(self, action: FrontierAction) -> bool:
        budget = self.state.budget
        if budget.max_candidates and budget.candidate_count >= budget.max_candidates:
            return False
        if budget.max_tool_requests and budget.tool_requests >= budget.max_tool_requests:
            return False
        if action.action_type == "search":
            return budget.source_requests < budget.max_source_requests
        if action.action_type in {"read", "enrich"}:
            return budget.reader_requests < budget.max_reader_requests
        return budget.citation_requests < budget.max_citation_requests

    def _budget_stop_reason(self) -> str:
        budget = self.state.budget
        if budget.max_candidates and budget.candidate_count >= budget.max_candidates:
            return "candidate_budget_exhausted"
        if budget.max_tool_requests and budget.tool_requests >= budget.max_tool_requests:
            return "tool_request_budget_exhausted"
        elapsed = self.state.elapsed_seconds + max(0.0, time.monotonic() - self.state.started_at_monotonic)
        if budget.max_wall_seconds and elapsed >= budget.max_wall_seconds:
            return "wall_time_budget_exhausted"
        action_types = {action.action_type for action in self.state.actions if action.status == "pending"}
        if action_types == {"search"} and budget.source_requests >= budget.max_source_requests:
            return "source_request_budget_exhausted"
        if action_types and action_types <= {"read", "enrich"} and budget.reader_requests >= budget.max_reader_requests:
            return "reader_request_budget_exhausted"
        if action_types and action_types <= {"expand_backward", "expand_forward"} and budget.citation_requests >= budget.max_citation_requests:
            return "citation_request_budget_exhausted"
        return ""

    @staticmethod
    def _consume_budget(
        budget: FrontierBudget,
        action: FrontierAction,
        outcome: FrontierOutcome,
    ) -> FrontierBudget:
        update = {
            "candidate_count": budget.candidate_count + outcome.added_unique,
            "tool_requests": budget.tool_requests + 1,
        }
        if action.action_type == "search":
            update["source_requests"] = budget.source_requests + 1
        elif action.action_type in {"read", "enrich"}:
            update["reader_requests"] = budget.reader_requests + 1
        else:
            update["citation_requests"] = budget.citation_requests + 1
        return budget.model_copy(update=update)


def _action_identity(action: FrontierAction) -> tuple[str, str, str, str, int]:
    return (
        action.action_type,
        action.source.strip().casefold(),
        " ".join(action.query.split()).casefold(),
        action.candidate_id.strip().casefold(),
        action.depth,
    )


__all__ = ["FrontierScheduler"]
