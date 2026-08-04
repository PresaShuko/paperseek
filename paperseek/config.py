
import os
import re
from dataclasses import dataclass, field

from paperseek_core.budgets import (
    DEFAULT_SEARCH_BUDGET,
    normalize_search_budget,
    search_budget_preset,
)
from paperseek.disciplines import normalize_source_filter_values
from paperseek.source_metadata import supported_source_ids


_DEFAULT_BUDGET = search_budget_preset(DEFAULT_SEARCH_BUDGET)


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw not in (None, "") else int(default)
    except (TypeError, ValueError):
        value = int(default)
    return max(minimum, value)


def _float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    try:
        value = float(raw) if raw not in (None, "") else float(default)
    except (TypeError, ValueError):
        value = float(default)
    return max(minimum, value)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return bool(default)
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _tuple_env(name: str) -> tuple[str, ...]:
    values = re.split(r"[,;\s]+", str(os.environ.get(name) or ""))
    return tuple(dict.fromkeys(value.strip().lower() for value in values if value.strip()))


@dataclass
class AgentConfig:
    data_source: str = "openalex"
    search_budget: str = DEFAULT_SEARCH_BUDGET
    llm_thinking_enabled: bool = True
    wos_api_key: str = ""
    openalex_api_key: str = ""
    openalex_email: str = ""
    crossref_email: str = ""
    semantic_scholar_api_key: str = ""
    pubmed_api_key: str = ""
    pubmed_email: str = ""
    pubmed_tool: str = "paperseek"
    serper_api_key: str = ""
    llm_api_key: str = ""
    llm_provider: str = "openai"
    llm_api_type: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    llm_max_tokens: int = 2048
    ranking_llm_timeout_seconds: int = 60
    wos_db: str = "WOS"
    search_field: str = ""
    discipline_fields: tuple[str, ...] = field(default_factory=tuple)
    fetch_abstracts: bool = False
    expand_citations: bool = True
    citation_seed_count: int = _DEFAULT_BUDGET.citation_seed_count
    citation_per_seed: int = _DEFAULT_BUDGET.citation_per_seed
    citation_max_records: int = _DEFAULT_BUDGET.citation_max_records
    citation_depth: int = _DEFAULT_BUDGET.citation_depth
    ranking_batch_size: int = 8
    ranking_concurrency: int = 16
    ranking_candidate_limit: int = _DEFAULT_BUDGET.ranking_candidate_limit
    target_min: int = 5
    target_max: int = 50
    max_iterations: int = _DEFAULT_BUDGET.max_iterations
    retrieval_pool_max: int = _DEFAULT_BUDGET.retrieval_pool_max
    retrieval_pool_min: int = 5
    retrieval_lane_limit: int = _DEFAULT_BUDGET.retrieval_lane_limit
    retrieval_rrf_k: int = 60
    retrieval_embedding_provider: str = "local"
    retrieval_embedding_model: str = "qwen3-embedding:8b,bge-large-zh:latest"
    retrieval_embedding_base_url: str = ""
    retrieval_embedding_api_key: str = ""
    retrieval_reranker_provider: str = ""
    retrieval_reranker_model: str = "qwen3-reranker:8b"
    retrieval_reranker_base_url: str = ""
    retrieval_reranker_api_key: str = ""
    retrieval_crossref_enrichment: bool = False
    query_portfolio_enabled: bool = True
    query_portfolio_max: int = _DEFAULT_BUDGET.query_portfolio_max
    query_portfolio_limit: int = _DEFAULT_BUDGET.query_portfolio_limit
    search_loop_backend: str = "auto"
    crawler_enabled: bool = False
    crawler_sources: tuple[str, ...] = field(default_factory=tuple)
    candidate_selector_enabled: bool = False
    citation_feedback_enabled: bool = False
    crawler_intermediate_selector_enabled: bool = False
    candidate_selector_batch_size: int = 12
    candidate_selector_concurrency: int = 2
    candidate_selector_max_llm_calls: int = _DEFAULT_BUDGET.candidate_selector_max_llm_calls
    candidate_selector_max_attempts: int = 2
    candidate_selector_exclude_score_max: float = 0.25
    candidate_selector_keep_uncertain: bool = True
    crawler_selector_sample_size: int = 24
    crawler_max_reader_requests: int = _DEFAULT_BUDGET.crawler_max_reader_requests
    crawler_max_citation_requests: int = _DEFAULT_BUDGET.crawler_max_citation_requests
    crawler_max_wall_seconds: float = _DEFAULT_BUDGET.crawler_max_wall_seconds
    crawler_low_yield_round_limit: int = 2

    @classmethod
    def from_env(cls) -> "AgentConfig":
        provider = os.environ.get("LLM_PROVIDER", "openai").lower()
        api_type = os.environ.get("LLM_API_TYPE", "") or default_api_type(provider)
        search_budget = normalize_search_budget(os.environ.get("SEARCH_BUDGET", DEFAULT_SEARCH_BUDGET))
        budget = search_budget_preset(search_budget)
        return cls(
            search_budget=search_budget,
            llm_thinking_enabled=True,
            wos_api_key=os.environ.get("WOS_API_KEY", ""),
            data_source=os.environ.get("DATA_SOURCE", "openalex").lower(),
            openalex_api_key=os.environ.get("OPENALEX_API_KEY", ""),
            openalex_email=os.environ.get("OPENALEX_EMAIL", ""),
            crossref_email=os.environ.get("CROSSREF_EMAIL", ""),
            semantic_scholar_api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""),
            pubmed_api_key=os.environ.get("PUBMED_API_KEY", ""),
            pubmed_email=os.environ.get("PUBMED_EMAIL", ""),
            pubmed_tool=os.environ.get("PUBMED_TOOL", "paperseek"),
            serper_api_key=os.environ.get("SERPER_API_KEYS", "") or os.environ.get("SERPER_API_KEY", ""),
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
            llm_provider=provider,
            llm_api_type=api_type,
            llm_model=os.environ.get("LLM_MODEL") or default_model(provider),
            llm_base_url=os.environ.get("LLM_BASE_URL") or default_base_url(provider, api_type),
            llm_max_tokens=_int_env("LLM_MAX_TOKENS", 2048),
            ranking_llm_timeout_seconds=_int_env("RANKING_LLM_TIMEOUT_SECONDS", 60, minimum=10),
            wos_db=os.environ.get("WOS_DB", "WOS"),
            search_field=os.environ.get("SEARCH_FIELD", ""),
            discipline_fields=os.environ.get("DISCIPLINE_FIELDS", ""),
            fetch_abstracts=os.environ.get("FETCH_ABSTRACTS", "").lower() in ("1", "true", "yes"),
            expand_citations=os.environ.get("EXPAND_CITATIONS", "true").lower() not in ("0", "false", "no"),
            citation_seed_count=_int_env("CITATION_SEED_COUNT", budget.citation_seed_count),
            citation_per_seed=_int_env("CITATION_PER_SEED", budget.citation_per_seed),
            citation_max_records=_int_env("CITATION_MAX_RECORDS", budget.citation_max_records),
            citation_depth=_int_env("CITATION_DEPTH", budget.citation_depth),
            ranking_batch_size=_int_env("RANKING_BATCH_SIZE", 8, minimum=1),
            ranking_concurrency=_int_env("RANKING_CONCURRENCY", 16, minimum=1),
            ranking_candidate_limit=_int_env(
                "RANKING_CANDIDATE_LIMIT",
                budget.ranking_candidate_limit,
                minimum=1,
            ),
            target_min=_int_env("TARGET_MIN", 5),
            target_max=_int_env("TARGET_MAX", 50, minimum=1),
            max_iterations=_int_env("MAX_ITERATIONS", budget.max_iterations, minimum=1),
            retrieval_pool_max=_int_env("RETRIEVAL_POOL_MAX", budget.retrieval_pool_max, minimum=1),
            retrieval_pool_min=_int_env("RETRIEVAL_POOL_MIN", 5),
            retrieval_lane_limit=_int_env("RETRIEVAL_LANE_LIMIT", budget.retrieval_lane_limit, minimum=1),
            retrieval_rrf_k=_int_env("RETRIEVAL_RRF_K", 60, minimum=1),
            retrieval_embedding_provider=os.environ.get("RETRIEVAL_EMBEDDING_PROVIDER", "local").strip().lower() or "local",
            retrieval_embedding_model=os.environ.get("RETRIEVAL_EMBEDDING_MODEL", "qwen3-embedding:8b,bge-large-zh:latest"),
            retrieval_embedding_base_url=os.environ.get("RETRIEVAL_EMBEDDING_BASE_URL", ""),
            retrieval_embedding_api_key=os.environ.get("RETRIEVAL_EMBEDDING_API_KEY", ""),
            retrieval_reranker_provider=os.environ.get("RETRIEVAL_RERANKER_PROVIDER", "").strip().lower(),
            retrieval_reranker_model=os.environ.get("RETRIEVAL_RERANKER_MODEL", "qwen3-reranker:8b"),
            retrieval_reranker_base_url=os.environ.get("RETRIEVAL_RERANKER_BASE_URL", ""),
            retrieval_reranker_api_key=os.environ.get("RETRIEVAL_RERANKER_API_KEY", ""),
            retrieval_crossref_enrichment=os.environ.get("RETRIEVAL_CROSSREF_ENRICHMENT", "").lower() in ("1", "true", "yes"),
            query_portfolio_enabled=os.environ.get("QUERY_PORTFOLIO_ENABLED", "true").lower() not in ("0", "false", "no"),
            query_portfolio_max=_int_env("QUERY_PORTFOLIO_MAX", budget.query_portfolio_max, minimum=1),
            query_portfolio_limit=_int_env("QUERY_PORTFOLIO_LIMIT", budget.query_portfolio_limit, minimum=1),
            search_loop_backend=os.environ.get("SEARCH_LOOP_BACKEND", "auto").strip().lower() or "auto",
            crawler_enabled=_bool_env("PAPERSEEK_CRAWLER", False),
            crawler_sources=_tuple_env("PAPERSEEK_CRAWLER_SOURCES"),
            candidate_selector_enabled=_bool_env("PAPERSEEK_CANDIDATE_SELECTOR", False),
            citation_feedback_enabled=_bool_env("PAPERSEEK_CITATION_FEEDBACK", False),
            crawler_intermediate_selector_enabled=_bool_env("CRAWLER_INTERMEDIATE_SELECTOR", False),
            candidate_selector_batch_size=_int_env("CANDIDATE_SELECTOR_BATCH_SIZE", 12, minimum=1),
            candidate_selector_concurrency=_int_env("CANDIDATE_SELECTOR_CONCURRENCY", 2, minimum=1),
            candidate_selector_max_llm_calls=_int_env(
                "CANDIDATE_SELECTOR_MAX_LLM_CALLS",
                budget.candidate_selector_max_llm_calls,
            ),
            candidate_selector_max_attempts=_int_env("CANDIDATE_SELECTOR_MAX_ATTEMPTS", 2, minimum=1),
            candidate_selector_exclude_score_max=min(
                1.0,
                _float_env("CANDIDATE_SELECTOR_EXCLUDE_SCORE_MAX", 0.25),
            ),
            candidate_selector_keep_uncertain=_bool_env("CANDIDATE_SELECTOR_KEEP_UNCERTAIN", True),
            crawler_selector_sample_size=_int_env("CRAWLER_SELECTOR_SAMPLE_SIZE", 24, minimum=1),
            crawler_max_reader_requests=_int_env(
                "CRAWLER_MAX_READER_REQUESTS",
                budget.crawler_max_reader_requests,
            ),
            crawler_max_citation_requests=_int_env(
                "CRAWLER_MAX_CITATION_REQUESTS",
                budget.crawler_max_citation_requests,
            ),
            crawler_max_wall_seconds=_float_env(
                "CRAWLER_MAX_WALL_SECONDS",
                budget.crawler_max_wall_seconds,
                minimum=1.0,
            ),
            crawler_low_yield_round_limit=_int_env("CRAWLER_LOW_YIELD_ROUND_LIMIT", 2, minimum=1),
        )

    def validate(self):
        missing = []
        self.search_budget = normalize_search_budget(self.search_budget)
        self.data_source = (self.data_source or "openalex").lower()
        if self.data_source not in supported_source_ids():
            raise ValueError(f"DATA_SOURCE must be one of {', '.join(supported_source_ids())}, got '{self.data_source}'")
        crawler_sources = self.crawler_sources or ()
        if isinstance(crawler_sources, str):
            crawler_sources = re.split(r"[,;\s]+", crawler_sources)
        self.crawler_sources = tuple(
            dict.fromkeys(str(value or "").strip().lower() for value in crawler_sources if str(value or "").strip())
        )
        invalid_crawler_sources = [
            source for source in self.crawler_sources if source not in supported_source_ids()
        ]
        if invalid_crawler_sources:
            raise ValueError(
                "PAPERSEEK_CRAWLER_SOURCES must contain only supported sources; "
                f"got {', '.join(invalid_crawler_sources)}"
            )
        self.discipline_fields = normalize_source_filter_values(self.data_source, self.discipline_fields)
        if self.data_source == "wos" and not self.wos_api_key:
            missing.append("WOS_API_KEY")
        if self.data_source == "googlescholar" and not self.serper_api_key:
            missing.append("SERPER_API_KEY")
        self.llm_provider = (self.llm_provider or "openai").lower()
        self.llm_api_type = (self.llm_api_type or default_api_type(self.llm_provider)).lower()
        if not self.llm_api_key and self.llm_provider != "ollama":
            missing.append("LLM_API_KEY")
        if self.llm_provider not in SUPPORTED_LLM_PROVIDERS:
            raise ValueError(f"LLM_PROVIDER must be one of {', '.join(SUPPORTED_LLM_PROVIDERS)}, got '{self.llm_provider}'")
        if self.llm_api_type not in SUPPORTED_LLM_API_TYPES:
            raise ValueError(f"LLM_API_TYPE must be one of {', '.join(SUPPORTED_LLM_API_TYPES)}, got '{self.llm_api_type}'")
        if missing:
            raise ValueError(
                f"Missing required configuration: {', '.join(missing)}. "
                f"Set them via environment variables or CLI flags."
            )


SUPPORTED_LLM_PROVIDERS = (
    "openai",
    "anthropic",
    "google",
    "deepseek",
    "cstcloud",
    "dashscope",
    "moonshot",
    "zhipu",
    "siliconflow",
    "openrouter",
    "nvidia",
    "volcengine",
    "hunyuan",
    "qianfan",
    "modelscope",
    "ollama",
    "custom",
)

SUPPORTED_LLM_API_TYPES = ("openai_chat", "openai_responses", "anthropic_messages")


def default_api_type(provider: str) -> str:
    provider = (provider or "openai").lower()
    if provider == "anthropic":
        return "anthropic_messages"
    if provider == "openai":
        return "openai_responses"
    return "openai_chat"


def default_model(provider: str) -> str:
    provider = (provider or "openai").lower()
    models = {
        "openai": "gpt-5.4-mini",
        "anthropic": "claude-sonnet-4-6",
        "google": "gemini-3.5-flash",
        "deepseek": "deepseek-v4-flash",
        "cstcloud": "deepseek-v4-flash",
        "dashscope": "qwen3.6-plus",
        "moonshot": "kimi-k2.6",
        "zhipu": "glm-5.1",
        "siliconflow": "deepseek-ai/DeepSeek-V4-Flash",
        "openrouter": "openai/gpt-5.4-mini",
        "nvidia": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "volcengine": "doubao-seed-2-0-mini-260428",
        "hunyuan": "hunyuan-turbos-latest",
        "qianfan": "ernie-5.0",
        "modelscope": "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "ollama": "qwen3:8b",
        "custom": "",
    }
    return models.get(provider, "")


def default_base_url(provider: str, api_type: str = "") -> str:
    provider = (provider or "openai").lower()
    api_type = (api_type or default_api_type(provider)).lower()
    urls = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com",
        "google": "https://generativelanguage.googleapis.com/v1beta/openai",
        "deepseek": "https://api.deepseek.com",
        "cstcloud": "https://uni-api.cstcloud.cn/v1",
        "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "moonshot": "https://api.moonshot.ai/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "siliconflow": "https://api.siliconflow.cn/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "nvidia": "https://integrate.api.nvidia.com/v1",
        "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
        "hunyuan": "https://tokenhub.tencentmaas.com/v1",
        "qianfan": "https://qianfan.baidubce.com/v2",
        "modelscope": "https://api-inference.modelscope.cn/v1",
        "ollama": "http://127.0.0.1:11434/v1",
        "custom": "",
    }
    if api_type == "anthropic_messages" and provider == "anthropic":
        return "https://api.anthropic.com"
    return urls.get(provider, "")
