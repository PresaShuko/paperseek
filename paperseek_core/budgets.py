from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_SEARCH_BUDGET = "fast"
SEARCH_BUDGET_NAMES = ("fast", "medium", "high", "max")


@dataclass(frozen=True)
class SearchBudgetPreset:
    llm_thinking_enabled: bool
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
    candidate_selector_max_llm_calls: int
    crawler_max_reader_requests: int
    crawler_max_citation_requests: int
    crawler_max_wall_seconds: float

    def values(self) -> dict[str, int | float | bool]:
        return asdict(self)


# Fast minimizes requests and disables model thinking where the endpoint has an
# explicit switch. Higher levels widen recall and ranking capacity.
SEARCH_BUDGET_PRESETS = {
    "fast": SearchBudgetPreset(
        llm_thinking_enabled=False,
        max_iterations=5,
        query_portfolio_max=3,
        query_portfolio_limit=100,
        retrieval_lane_limit=500,
        retrieval_pool_max=3000,
        ranking_candidate_limit=256,
        citation_seed_count=3,
        citation_per_seed=4,
        citation_max_records=40,
        citation_depth=2,
        candidate_selector_max_llm_calls=24,
        crawler_max_reader_requests=8,
        crawler_max_citation_requests=8,
        crawler_max_wall_seconds=300.0,
    ),
    "medium": SearchBudgetPreset(
        llm_thinking_enabled=True,
        max_iterations=7,
        query_portfolio_max=3,
        query_portfolio_limit=100,
        retrieval_lane_limit=750,
        retrieval_pool_max=4500,
        ranking_candidate_limit=384,
        citation_seed_count=8,
        citation_per_seed=6,
        citation_max_records=80,
        citation_depth=2,
        candidate_selector_max_llm_calls=36,
        crawler_max_reader_requests=12,
        crawler_max_citation_requests=16,
        crawler_max_wall_seconds=480.0,
    ),
    "high": SearchBudgetPreset(
        llm_thinking_enabled=True,
        max_iterations=9,
        query_portfolio_max=4,
        query_portfolio_limit=100,
        retrieval_lane_limit=1000,
        retrieval_pool_max=7000,
        ranking_candidate_limit=512,
        citation_seed_count=16,
        citation_per_seed=8,
        citation_max_records=160,
        citation_depth=3,
        candidate_selector_max_llm_calls=48,
        crawler_max_reader_requests=20,
        crawler_max_citation_requests=24,
        crawler_max_wall_seconds=720.0,
    ),
    "max": SearchBudgetPreset(
        llm_thinking_enabled=True,
        max_iterations=12,
        query_portfolio_max=6,
        query_portfolio_limit=100,
        retrieval_lane_limit=1000,
        retrieval_pool_max=10000,
        ranking_candidate_limit=1024,
        citation_seed_count=30,
        citation_per_seed=10,
        citation_max_records=320,
        citation_depth=3,
        candidate_selector_max_llm_calls=96,
        crawler_max_reader_requests=32,
        crawler_max_citation_requests=48,
        crawler_max_wall_seconds=1200.0,
    ),
}


def normalize_search_budget(value: Any, *, default: str = DEFAULT_SEARCH_BUDGET) -> str:
    normalized = str(value or default).strip().lower()
    if normalized not in SEARCH_BUDGET_PRESETS:
        raise ValueError(f"search budget must be one of {', '.join(SEARCH_BUDGET_NAMES)}")
    return normalized


def search_budget_preset(value: Any) -> SearchBudgetPreset:
    return SEARCH_BUDGET_PRESETS[normalize_search_budget(value)]


def apply_search_budget(config: Any, value: Any) -> Any:
    name = normalize_search_budget(value)
    preset = SEARCH_BUDGET_PRESETS[name]
    config.search_budget = name
    for field_name, field_value in preset.values().items():
        setattr(config, field_name, field_value)
    return config
