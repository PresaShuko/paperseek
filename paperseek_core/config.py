
from dataclasses import dataclass, field

from paperseek_core.budgets import DEFAULT_SEARCH_BUDGET, search_budget_preset
from paperseek_core.disciplines import normalize_source_filter_values


_DEFAULT_BUDGET = search_budget_preset(DEFAULT_SEARCH_BUDGET)


@dataclass
class SearchConfig:
    data_source: str = "openalex"
    search_budget: str = DEFAULT_SEARCH_BUDGET
    llm_thinking_enabled: bool = _DEFAULT_BUDGET.llm_thinking_enabled
    target_min: int = 5
    target_max: int = 50
    max_iterations: int = _DEFAULT_BUDGET.max_iterations
    search_field: str = ""
    discipline_fields: tuple[str, ...] = field(default_factory=tuple)
    expand_citations: bool = True
    fetch_abstracts: bool = False
    citation_seed_count: int = _DEFAULT_BUDGET.citation_seed_count
    citation_per_seed: int = _DEFAULT_BUDGET.citation_per_seed
    citation_max_records: int = _DEFAULT_BUDGET.citation_max_records
    citation_depth: int = _DEFAULT_BUDGET.citation_depth
    ranking_candidate_limit: int = _DEFAULT_BUDGET.ranking_candidate_limit
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


@dataclass
class LLMConfig:
    provider: str = "openai"
    api_type: str = "openai_responses"
    model: str = "gpt-5.4-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    max_tokens: int = 2048


@dataclass
class SourceConfig:
    wos_api_key: str = ""
    wos_db: str = "WOS"
    openalex_api_key: str = ""
    openalex_email: str = ""
    crossref_email: str = ""
    semantic_scholar_api_key: str = ""
    pubmed_api_key: str = ""
    pubmed_email: str = ""
    pubmed_tool: str = "paperseek"
    serper_api_key: str = ""


@dataclass
class RuntimeConfig:
    data_source: str
    search_budget: str
    llm_thinking_enabled: bool
    target_min: int
    target_max: int
    max_iterations: int
    search_field: str
    discipline_fields: tuple[str, ...]
    expand_citations: bool
    fetch_abstracts: bool
    citation_seed_count: int
    citation_per_seed: int
    citation_max_records: int
    citation_depth: int
    ranking_candidate_limit: int
    retrieval_pool_max: int
    retrieval_pool_min: int
    retrieval_lane_limit: int
    retrieval_rrf_k: int
    retrieval_embedding_provider: str
    retrieval_embedding_model: str
    retrieval_embedding_base_url: str
    retrieval_embedding_api_key: str
    retrieval_reranker_provider: str
    retrieval_reranker_model: str
    retrieval_reranker_base_url: str
    retrieval_reranker_api_key: str
    retrieval_crossref_enrichment: bool
    query_portfolio_enabled: bool
    query_portfolio_max: int
    query_portfolio_limit: int
    search_loop_backend: str
    crawler_enabled: bool
    crawler_sources: tuple[str, ...]
    candidate_selector_enabled: bool
    citation_feedback_enabled: bool
    crawler_intermediate_selector_enabled: bool
    candidate_selector_batch_size: int
    candidate_selector_concurrency: int
    candidate_selector_max_llm_calls: int
    candidate_selector_max_attempts: int
    candidate_selector_exclude_score_max: float
    candidate_selector_keep_uncertain: bool
    crawler_selector_sample_size: int
    crawler_max_reader_requests: int
    crawler_max_citation_requests: int
    crawler_max_wall_seconds: float
    crawler_low_yield_round_limit: int
    llm_provider: str
    llm_api_type: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    llm_max_tokens: int
    wos_api_key: str
    wos_db: str
    openalex_api_key: str
    openalex_email: str
    crossref_email: str
    semantic_scholar_api_key: str
    pubmed_api_key: str
    pubmed_email: str
    pubmed_tool: str
    serper_api_key: str


def build_runtime_config(
    search: SearchConfig | None = None,
    source: SourceConfig | None = None,
    llm: LLMConfig | None = None,
) -> RuntimeConfig:
    search = search or SearchConfig()
    source = source or SourceConfig()
    llm = llm or LLMConfig()
    data_source = (search.data_source or "openalex").lower()
    return RuntimeConfig(
        data_source=data_source,
        search_budget=search.search_budget,
        llm_thinking_enabled=search.llm_thinking_enabled,
        target_min=search.target_min,
        target_max=search.target_max,
        max_iterations=search.max_iterations,
        search_field=search.search_field,
        discipline_fields=normalize_source_filter_values(data_source, search.discipline_fields),
        expand_citations=search.expand_citations,
        fetch_abstracts=search.fetch_abstracts,
        citation_seed_count=search.citation_seed_count,
        citation_per_seed=search.citation_per_seed,
        citation_max_records=search.citation_max_records,
        citation_depth=search.citation_depth,
        ranking_candidate_limit=search.ranking_candidate_limit,
        retrieval_pool_max=search.retrieval_pool_max,
        retrieval_pool_min=search.retrieval_pool_min,
        retrieval_lane_limit=search.retrieval_lane_limit,
        retrieval_rrf_k=search.retrieval_rrf_k,
        retrieval_embedding_provider=search.retrieval_embedding_provider,
        retrieval_embedding_model=search.retrieval_embedding_model,
        retrieval_embedding_base_url=search.retrieval_embedding_base_url,
        retrieval_embedding_api_key=search.retrieval_embedding_api_key,
        retrieval_reranker_provider=search.retrieval_reranker_provider,
        retrieval_reranker_model=search.retrieval_reranker_model,
        retrieval_reranker_base_url=search.retrieval_reranker_base_url,
        retrieval_reranker_api_key=search.retrieval_reranker_api_key,
        retrieval_crossref_enrichment=search.retrieval_crossref_enrichment,
        query_portfolio_enabled=search.query_portfolio_enabled,
        query_portfolio_max=search.query_portfolio_max,
        query_portfolio_limit=search.query_portfolio_limit,
        search_loop_backend=search.search_loop_backend,
        crawler_enabled=search.crawler_enabled,
        crawler_sources=tuple(search.crawler_sources or ()),
        candidate_selector_enabled=search.candidate_selector_enabled,
        citation_feedback_enabled=search.citation_feedback_enabled,
        crawler_intermediate_selector_enabled=search.crawler_intermediate_selector_enabled,
        candidate_selector_batch_size=search.candidate_selector_batch_size,
        candidate_selector_concurrency=search.candidate_selector_concurrency,
        candidate_selector_max_llm_calls=search.candidate_selector_max_llm_calls,
        candidate_selector_max_attempts=search.candidate_selector_max_attempts,
        candidate_selector_exclude_score_max=search.candidate_selector_exclude_score_max,
        candidate_selector_keep_uncertain=search.candidate_selector_keep_uncertain,
        crawler_selector_sample_size=search.crawler_selector_sample_size,
        crawler_max_reader_requests=search.crawler_max_reader_requests,
        crawler_max_citation_requests=search.crawler_max_citation_requests,
        crawler_max_wall_seconds=search.crawler_max_wall_seconds,
        crawler_low_yield_round_limit=search.crawler_low_yield_round_limit,
        llm_provider=(llm.provider or "openai").lower(),
        llm_api_type=(llm.api_type or "openai_responses").lower(),
        llm_model=llm.model,
        llm_base_url=llm.base_url,
        llm_api_key=llm.api_key,
        llm_max_tokens=llm.max_tokens,
        wos_api_key=source.wos_api_key,
        wos_db=source.wos_db or "WOS",
        openalex_api_key=source.openalex_api_key,
        openalex_email=source.openalex_email,
        crossref_email=source.crossref_email,
        semantic_scholar_api_key=source.semantic_scholar_api_key,
        pubmed_api_key=source.pubmed_api_key,
        pubmed_email=source.pubmed_email,
        pubmed_tool=source.pubmed_tool or "paperseek",
        serper_api_key=source.serper_api_key,
    )
