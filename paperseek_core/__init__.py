
from typing import Callable

from paperseek_core.agent import LiteratureSearchAgent, PaperSeekAgent, WosSearchAgent
from paperseek_core.budgets import SEARCH_BUDGET_NAMES, apply_search_budget
from paperseek_core.config import LLMConfig, SearchConfig, SourceConfig, build_runtime_config
from paperseek_core.llm import create_llm_client

__version__ = "0.3.0"


def run_search(
    question: str,
    search_config: SearchConfig | None = None,
    source_config: SourceConfig | None = None,
    llm_config: LLMConfig | None = None,
    event_handler: Callable[[dict], None] | None = None,
) -> dict:
    config = build_runtime_config(search_config, source_config, llm_config)
    llm = create_llm_client(config)
    return PaperSeekAgent(config, llm).search(question, event_handler=event_handler)


__all__ = [
    "LLMConfig",
    "LiteratureSearchAgent",
    "PaperSeekAgent",
    "SearchConfig",
    "SEARCH_BUDGET_NAMES",
    "SourceConfig",
    "WosSearchAgent",
    "__version__",
    "apply_search_budget",
    "run_search",
]
