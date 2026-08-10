from __future__ import annotations

from dataclasses import dataclass

from paperseek_core.models import QueryLoopBudget


@dataclass(frozen=True, slots=True)
class SearchBudgetPreset:
    max_iterations: int
    query_portfolio_max: int
    query_portfolio_limit: int
    retrieval_lane_limit: int
    retrieval_pool_max: int
    ranking_candidate_limit: int
    citation_seed_count: int
    citation_per_seed: int
    citation_max_records: int
    citation_depth: int


SEARCH_BUDGET_PRESETS = {
    "fast": SearchBudgetPreset(5, 3, 100, 500, 3000, 256, 3, 4, 40, 2),
    "medium": SearchBudgetPreset(7, 3, 100, 750, 4500, 384, 8, 6, 80, 2),
    "high": SearchBudgetPreset(9, 4, 100, 1000, 7000, 512, 16, 8, 160, 3),
    "max": SearchBudgetPreset(12, 6, 100, 1000, 10000, 1024, 30, 10, 320, 3),
}


def workflow_budget(name: str, *, field_ids: tuple[str, ...] = ()) -> tuple[QueryLoopBudget, SearchBudgetPreset]:
    try:
        preset = SEARCH_BUDGET_PRESETS[name]
    except KeyError as exc:
        raise ValueError("Unsupported search budget.") from exc
    return (
        QueryLoopBudget(
            max_iterations=preset.max_iterations,
            query_portfolio_max=preset.query_portfolio_max,
            query_portfolio_limit=preset.query_portfolio_limit,
            retrieval_lane_limit=preset.retrieval_lane_limit,
            retrieval_pool_max=preset.retrieval_pool_max,
            ranking_candidate_limit=preset.ranking_candidate_limit,
            field_ids=field_ids,
        ),
        preset,
    )


__all__ = ["SEARCH_BUDGET_PRESETS", "SearchBudgetPreset", "workflow_budget"]
