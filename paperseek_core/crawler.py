import re
from collections import Counter
from typing import Iterable

from paperseek_core.frontier import FrontierScheduler
from paperseek_core.harness.schemas import (
    CrawlerState,
    FrontierAction,
    FrontierOutcome,
    SelectorBatch,
)
from paperseek_core.planning import SearchPlan
from paperseek_core.query_view_selector import QueryViewSelection


class CrawlerController:
    """Policy layer that turns SearchPlan and selector feedback into actions."""

    def __init__(
        self,
        plan: SearchPlan,
        source: str,
        scheduler: FrontierScheduler,
        state: CrawlerState | None = None,
        supported_actions: Iterable[str] | None = None,
        max_citation_depth: int = 2,
    ):
        self.plan = plan
        self.source = str(source or "").strip().lower()
        self.scheduler = scheduler
        self.state = state or CrawlerState()
        self.query_view_by_action: dict[str, str] = {}
        self.query_source_by_action: dict[str, str] = {}
        self.supported_actions = set(
            supported_actions
            if supported_actions is not None
            else {"search", "read", "enrich", "expand_backward", "expand_forward"}
        )
        self.max_citation_depth = max(0, int(max_citation_depth or 0))

    def seed_query_views(
        self,
        selections: Iterable[QueryViewSelection],
        *,
        source: str | None = None,
    ) -> list[FrontierAction]:
        action_source = str(source or self.source).strip().lower()
        actions: list[FrontierAction] = []
        for selection in selections or []:
            if selection.compile_error or "exact_primary_duplicate" in selection.reason_codes:
                continue
            view = selection.view
            coverage = _view_plan_coverage(self.plan, selection)
            action = self.scheduler.make_action(
                "search",
                source=action_source,
                query=selection.compiled_query,
                expected_gain=max(0.0, selection.score),
                concept_gap_coverage=coverage,
                source_diversity_gain=0.1 if action_source != self.source else 0.0,
                estimated_cost=1.0,
                duplicate_risk=selection.lexical_overlap,
                reason_codes=[
                    f"query_view:{view.view_id}",
                    f"query_view_type:{view.view_type}",
                    *selection.reason_codes,
                ],
            )
            actions.append(action)
            self.query_view_by_action[action.action_id] = view.view_id
            self.query_source_by_action[action.action_id] = action_source
        accepted = self.scheduler.enqueue(actions)
        self.state = self.state.model_copy(
            update={"planned_actions": self.state.planned_actions + len(accepted)}
        )
        return accepted

    def observe_selector(
        self,
        batch: SelectorBatch,
        *,
        allow_follow_up_actions: bool = True,
        candidate_depths: dict[str, int] | None = None,
    ) -> list[FrontierAction]:
        selector_counts = Counter(self.state.selector_counts)
        concept_gaps = Counter(self.state.concept_gaps)
        concept_coverage = dict(self.state.concept_coverage)
        follow_up: list[FrontierAction] = []

        for decision in batch.decisions:
            selector_counts[decision.label] += 1
            if decision.label == "exclude":
                continue
            for concept, score in decision.concept_coverage.items():
                canonical = _canonical_concept(self.plan, concept)
                if not canonical:
                    continue
                concept_coverage[canonical] = max(
                    float(concept_coverage.get(canonical, 0.0) or 0.0),
                    min(1.0, max(0.0, float(score or 0.0))),
                )
            for concept in decision.missing_concepts:
                canonical = _canonical_concept(self.plan, concept)
                if canonical and concept_coverage.get(canonical, 0.0) < 0.7:
                    concept_gaps[canonical] += 1
            for action_type in decision.recommended_actions if allow_follow_up_actions else []:
                if action_type == "none":
                    continue
                if action_type not in self.supported_actions:
                    continue
                current_depth = max(0, int((candidate_depths or {}).get(decision.candidate_id, 0) or 0))
                if action_type.startswith("expand_") and current_depth >= self.max_citation_depth:
                    continue
                follow_up.append(
                    self.scheduler.make_action(
                        action_type,
                        source=self.source,
                        candidate_id=decision.candidate_id,
                        depth=current_depth + 1 if action_type.startswith("expand_") else current_depth,
                        expected_gain=max(0.0, decision.relevance_score),
                        concept_gap_coverage=float(len(decision.missing_concepts)) * 0.1,
                        citation_seed_quality=decision.relevance_score if action_type.startswith("expand_") else 0.0,
                        estimated_cost=1.0,
                        reason_codes=[f"selector_label:{decision.label}", "selector_recommended_action"],
                    )
                )

        concept_gaps = Counter(
            {
                concept: count
                for concept, count in concept_gaps.items()
                if count > 0 and concept_coverage.get(concept, 0.0) < 0.7
            }
        )
        accepted = self.scheduler.enqueue(follow_up)
        self.state = self.state.model_copy(
            update={
                "selector_counts": dict(selector_counts),
                "concept_gaps": dict(concept_gaps),
                "concept_coverage": concept_coverage,
                "planned_actions": self.state.planned_actions + len(accepted),
            }
        )
        self._boost_queries_for_gaps()
        return accepted

    def next_actions(self, limit: int = 1) -> list[FrontierAction]:
        gaps = self.concept_gaps()
        if self.scheduler.should_stop(gaps):
            self.state = self.state.model_copy(update={"stop_reason": self.scheduler.state.stop_reason})
            return []
        selected = self.scheduler.schedule(limit)
        self.state = self.state.model_copy(
            update={
                "decisions": [
                    *self.state.decisions,
                    {
                        "round": self.scheduler.state.round_index + 1,
                        "action_ids": [action.action_id for action in selected],
                        "action_types": [action.action_type for action in selected],
                        "concept_gaps": gaps,
                    },
                ]
            }
        )
        return selected

    def seed_citation_actions(
        self,
        batch: SelectorBatch,
        *,
        roles_by_candidate: dict[str, list[str]] | None = None,
        candidate_depths: dict[str, int] | None = None,
        max_actions: int = 8,
    ) -> list[FrontierAction]:
        """Plan role-aware citation actions from selector-approved seeds."""
        if self.source != "openalex":
            return []
        roles_by_candidate = roles_by_candidate or {}
        candidate_depths = candidate_depths or {}
        actions: list[FrontierAction] = []
        ranked = sorted(
            (decision for decision in batch.decisions if decision.label != "exclude"),
            key=lambda decision: (-decision.relevance_score, decision.candidate_id),
        )
        for decision in ranked:
            current_depth = max(0, int(candidate_depths.get(decision.candidate_id, 0) or 0))
            if current_depth >= self.max_citation_depth:
                continue
            roles = roles_by_candidate.get(decision.candidate_id) or ["relevance"]
            directions: list[str] = []
            if "relevance" in roles:
                directions.extend(["expand_backward", "expand_forward"])
            if "impact" in roles:
                directions.append("expand_backward")
            if "recent" in roles:
                directions.append("expand_forward")
            for action_type in _unique(directions):
                if action_type not in self.supported_actions:
                    continue
                actions.append(
                    self.scheduler.make_action(
                        action_type,
                        source=self.source,
                        candidate_id=decision.candidate_id,
                        depth=current_depth + 1,
                        expected_gain=decision.relevance_score,
                        citation_seed_quality=decision.relevance_score,
                        estimated_cost=1.0,
                        reason_codes=[
                            f"selector_label:{decision.label}",
                            *[f"citation_seed_role:{role}" for role in roles],
                        ],
                    )
                )
                if len(actions) >= max(0, int(max_actions or 0)):
                    break
            if len(actions) >= max(0, int(max_actions or 0)):
                break
        accepted = self.scheduler.enqueue(actions)
        self.state = self.state.model_copy(
            update={"planned_actions": self.state.planned_actions + len(accepted)}
        )
        return accepted

    def complete_action(self, outcome: FrontierOutcome) -> FrontierAction:
        action = self.scheduler.complete(outcome)
        self.state = self.state.model_copy(
            update={"completed_actions": self.state.completed_actions + 1}
        )
        return action

    def query_view_id(self, action: FrontierAction) -> str:
        if action.action_id in self.query_view_by_action:
            return self.query_view_by_action[action.action_id]
        for reason in action.reason_codes:
            if reason.startswith("query_view:"):
                return reason.split(":", 1)[1]
        return ""

    def query_source(self, action: FrontierAction) -> str:
        return self.query_source_by_action.get(action.action_id) or action.source or self.source

    def concept_gaps(self, limit: int = 8) -> list[str]:
        return [
            concept
            for concept, _ in sorted(
                self.state.concept_gaps.items(),
                key=lambda item: (-item[1], item[0]),
            )[:max(0, int(limit or 0))]
        ]

    def snapshot(self) -> tuple[CrawlerState, object]:
        return self.state, self.scheduler.snapshot()

    def _boost_queries_for_gaps(self) -> None:
        gaps = self.concept_gaps()
        if not gaps:
            return
        gap_terms = [_terms(gap) for gap in gaps]
        pending: list[FrontierAction] = []
        for action in self.scheduler.state.actions:
            if action.status != "pending" or action.action_type != "search":
                continue
            query_terms = _terms(action.query)
            coverage = max((_jaccard(query_terms, terms) for terms in gap_terms), default=0.0)
            pending.append(
                action.model_copy(
                    update={
                        "concept_gap_coverage": max(action.concept_gap_coverage, coverage),
                        "reason_codes": _unique([*action.reason_codes, "selector_gap_reprioritized"])
                        if coverage > 0
                        else action.reason_codes,
                    }
                )
            )
        self.scheduler.replace_pending(pending)


def _view_plan_coverage(plan: SearchPlan, selection: QueryViewSelection) -> float:
    view_terms = {
        token
        for group in selection.view.concept_groups
        for value in [group.label, *group.terms]
        for token in _terms(value)
    }
    concept_terms = [_terms(value) for value in plan.core_concepts]
    if not concept_terms:
        return 0.0
    return sum(1.0 for terms in concept_terms if terms & view_terms) / len(concept_terms)


def _clean_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:200]


def _canonical_concept(plan: SearchPlan, value: str) -> str:
    cleaned = _clean_phrase(value)
    if not cleaned:
        return ""
    value_terms = _terms(cleaned)
    best = ""
    best_score = 0.0
    for concept in plan.core_concepts:
        candidate = _clean_phrase(concept)
        if not candidate:
            continue
        if candidate.casefold() == cleaned.casefold():
            return candidate
        score = _jaccard(value_terms, _terms(candidate))
        if score > best_score:
            best = candidate
            best_score = score
    return best if best_score >= 0.5 else cleaned


def _terms(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold()) if len(token) > 1}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


__all__ = ["CrawlerController"]
