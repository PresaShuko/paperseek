
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


ACTION_ACCEPT = "accept"
ACTION_ACCEPT_HIGH = "accept_high"
ACTION_ACCEPT_LOW = "accept_low"
ACTION_ACCEPT_POOL = "accept_pool"
ACTION_BROADEN = "broaden"
ACTION_EMPTY = "empty"
ACTION_NARROW = "narrow"

RECOVERY_BROADEN_QUERY = "broaden_query"
RECOVERY_FAIL = "fail"
RECOVERY_REPAIR_QUERY = "repair_query"
RECOVERY_SIMPLIFY_QUERY = "simplify_query"

RANKING_KEEP_LOCAL_ORDER = "keep_local_order"
RANKING_RETRY_LOWER_CONCURRENCY = "retry_lower_concurrency"
RANKING_RETRY_SAME_TIER = "retry_same_tier"

CITATION_RETRY_REDUCED = "retry_reduced"
CITATION_SKIP_EXPANSION = "skip_citation_expansion"

class QueryLoopSnapshot(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    iteration: int
    configured_iterations: int
    adaptive_max_iterations: int
    total: int
    target_min: int
    target_max: int
    retrieval_pool_min: int
    retrieval_pool_max: int
    history: List[Dict[str, Any]] = Field(default_factory=list)
    query: str = ""
    hit_count: int = 0
    top_titles: List[str] = Field(default_factory=list)
    intent_terms: List[str] = Field(default_factory=list)

    @property
    def consecutive_zero_results(self) -> int:
        if self.total != 0:
            return 0
        count = 1
        for row in reversed(self.history):
            if row.get("total") == 0:
                count += 1
                continue
            if row.get("action") in {"sanitize", "repair"}:
                continue
            break
        return count


class QueryLoopDecision(BaseModel):
    action: str
    message: str
    adjustment: str = ""
    terminal: bool = False
    reason: str = ""


class QueryProposal(BaseModel):
    """Validated source-query proposal returned by an LLM decision step."""

    query: str = Field(min_length=1)
    rationale: str = ""


class QueryValidation(BaseModel):
    stage: str = ""
    source: str
    query: str = ""
    ok: bool
    issue: str = ""


class SourceObservation(BaseModel):
    iteration: int
    query: str
    total: int = 0
    hit_count: int = 0
    top_titles: List[str] = Field(default_factory=list)


class ErrorObservation(BaseModel):
    stage: str
    source: str = ""
    query: str = ""
    error_type: str
    status: int | None = None
    message: str = ""
    retryable: bool = False


class SourceRecoveryDecision(BaseModel):
    action: str
    message: str = ""
    reason: str = ""
    retryable: bool = False


class RankingBatchObservation(BaseModel):
    step_id: str = ""
    batch_index: int = 0
    batch_count: int = 0
    concurrency: int = 0
    candidate_count: int = 0
    error_type: str = ""
    message: str = ""
    retryable: bool = False
    rate_limited: bool = False


class RankingScoreEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str = Field(min_length=1)
    score: float
    reasoning: str = ""


class RankingRecoveryDecision(BaseModel):
    action: str
    step_id: str = ""
    concurrency: int = 0
    next_concurrency: int = 0
    failed_batches: int = 0
    failed_candidates: int = 0
    message: str = ""
    reason: str = ""
    retryable: bool = False


class CitationPlanningDecision(BaseModel):
    seed_limit: int
    depth: int
    relevance_quota: int
    impact_quota: int
    recent_quota: int
    candidate_count: int = 0
    seed_ranking_count: int = 0
    message: str = ""
    reason: str = ""


class CitationFrontierDirectionStats(BaseModel):
    budget: int = 0
    requests: int = 0
    fetched: int = 0
    added: int = 0
    duplicates: int = 0
    filtered: int = 0


class CitationFrontierDepthStats(BaseModel):
    expanded_items: int = 0
    fetched: int = 0
    added: int = 0
    duplicates: int = 0
    filtered: int = 0


class CitationFrontierState(BaseModel):
    planned_items: int = 0
    processed_items: int = 0
    skipped_items: int = 0
    request_count: int = 0
    request_budget: int = 0
    stop_reason: str = ""
    direction_stats: Dict[str, CitationFrontierDirectionStats] = Field(default_factory=dict)
    depth_stats: Dict[str, CitationFrontierDepthStats] = Field(default_factory=dict)


class CitationTraversalObservation(BaseModel):
    status: str
    seed_count: int = 0
    depth: int = 0
    per_seed: int = 0
    max_records: int = 0
    added_candidates: int = 0
    candidate_pool: int = 0
    error_type: str = ""
    message: str = ""
    frontier: CitationFrontierState = Field(default_factory=CitationFrontierState)


class CitationRecoveryDecision(BaseModel):
    action: str
    retryable: bool = False
    per_seed: int = 0
    max_records: int = 0
    depth: int = 0
    message: str = ""
    reason: str = ""


class CandidateQueueEvent(BaseModel):
    origin: str = ""
    incoming: int = 0
    added: int = 0
    duplicates: int = 0
    total: int = 0
    sample_keys: List[str] = Field(default_factory=list)


class CandidateLifecycleEvent(BaseModel):
    stage: str = ""
    action: str = ""
    origin: str = ""
    detail: str = ""


class CandidateCitationPath(BaseModel):
    seed_id: str = ""
    parent_id: str = ""
    direction: str = ""
    depth: int = 0


class CandidateEvidence(BaseModel):
    candidate_id: str
    title: str = ""
    doi: str = ""
    arxiv: str = ""
    pmid: str = ""
    openalex: str = ""
    semanticscholar: str = ""
    year: int | None = None
    citations: int | None = None
    sources: List[str] = Field(default_factory=list)
    origins: List[str] = Field(default_factory=list)
    query_views: List[str] = Field(default_factory=list)
    retrieval_lanes: List[str] = Field(default_factory=list)
    source_ranks: Dict[str, int] = Field(default_factory=dict)
    citation_paths: List[CandidateCitationPath] = Field(default_factory=list)
    concept_coverage: Dict[str, float] = Field(default_factory=dict)
    ranking_gate_label: str = "unseen"
    ranking_gate_reason_codes: List[str] = Field(default_factory=list)
    retrieval_score: float | None = None
    rerank_score: float | None = None
    llm_score: float | None = None
    lifecycle: List[CandidateLifecycleEvent] = Field(default_factory=list)


class CandidateQueueState(BaseModel):
    keys: List[str] = Field(default_factory=list)
    records: List[Dict[str, str]] = Field(default_factory=list)
    ledger: Dict[str, CandidateEvidence] = Field(default_factory=dict)
    origin_counts: Dict[str, int] = Field(default_factory=dict)
    duplicate_count: int = 0
    events: List[CandidateQueueEvent] = Field(default_factory=list)


class QueryPortfolioExecution(BaseModel):
    view_id: str
    source: str = ""
    view_type: str = ""
    purpose: str = ""
    query: str
    total: int = 0
    hit_count: int = 0
    added_unique: int = 0
    status: str = "completed"
    error: str = ""
    selector_score: float = 0.0
    selector_overlap: float = 0.0
    selector_reasons: List[str] = Field(default_factory=list)


class SearchRunState(BaseModel):
    question: str
    source: str
    current_query: str = ""
    validations: List[QueryValidation] = Field(default_factory=list)
    observations: List[SourceObservation] = Field(default_factory=list)
    decisions: List[QueryLoopDecision] = Field(default_factory=list)
    errors: List[ErrorObservation] = Field(default_factory=list)
    recovery_decisions: List[SourceRecoveryDecision] = Field(default_factory=list)
    ranking_batch_observations: List[RankingBatchObservation] = Field(default_factory=list)
    ranking_recovery_decisions: List[RankingRecoveryDecision] = Field(default_factory=list)
    citation_planning_decisions: List[CitationPlanningDecision] = Field(default_factory=list)
    citation_traversal_observations: List[CitationTraversalObservation] = Field(default_factory=list)
    citation_recovery_decisions: List[CitationRecoveryDecision] = Field(default_factory=list)
    candidate_queue: CandidateQueueState = Field(default_factory=CandidateQueueState)
    search_plan: Dict[str, Any] = Field(default_factory=dict)
    query_portfolio: List[QueryPortfolioExecution] = Field(default_factory=list)
    terminal_status: str = ""

    def with_current_query(self, query: str) -> "SearchRunState":
        return self.model_copy(update={"current_query": query or ""})

    def with_error(self, error: ErrorObservation) -> "SearchRunState":
        return self.model_copy(update={"errors": [*self.errors, error]})

    def with_recovery_decision(self, decision: SourceRecoveryDecision) -> "SearchRunState":
        return self.model_copy(update={"recovery_decisions": [*self.recovery_decisions, decision]})

    def with_ranking_batch_observation(self, observation: RankingBatchObservation) -> "SearchRunState":
        return self.model_copy(update={"ranking_batch_observations": [*self.ranking_batch_observations, observation]})

    def with_ranking_recovery_decision(self, decision: RankingRecoveryDecision) -> "SearchRunState":
        return self.model_copy(update={"ranking_recovery_decisions": [*self.ranking_recovery_decisions, decision]})

    def with_citation_planning_decision(self, decision: CitationPlanningDecision) -> "SearchRunState":
        return self.model_copy(update={"citation_planning_decisions": [*self.citation_planning_decisions, decision]})

    def with_citation_traversal_observation(self, observation: CitationTraversalObservation) -> "SearchRunState":
        return self.model_copy(update={"citation_traversal_observations": [*self.citation_traversal_observations, observation]})

    def with_citation_recovery_decision(self, decision: CitationRecoveryDecision) -> "SearchRunState":
        return self.model_copy(update={"citation_recovery_decisions": [*self.citation_recovery_decisions, decision]})

    def with_candidate_queue(self, queue: CandidateQueueState) -> "SearchRunState":
        return self.model_copy(update={"candidate_queue": queue})

    def with_search_plan(self, search_plan: Dict[str, Any]) -> "SearchRunState":
        return self.model_copy(update={"search_plan": dict(search_plan or {})})

    def with_query_portfolio_execution(self, execution: QueryPortfolioExecution) -> "SearchRunState":
        return self.model_copy(update={"query_portfolio": [*self.query_portfolio, execution]})


class SearchCheckpoint(BaseModel):
    """Durable, credential-free snapshot of a search run."""

    schema_version: int = 1
    sequence: int = 0
    stage: str
    question: str
    source: str
    current_query: str = ""
    total: int = 0
    iteration: int = 0
    search_intent: str = ""
    search_plan: Dict[str, Any] = Field(default_factory=dict)
    query_view_selection: List[Dict[str, Any]] = Field(default_factory=list)
    query_portfolio: List[Dict[str, Any]] = Field(default_factory=list)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    search_state: Dict[str, Any] = Field(default_factory=dict)
    records: List[Dict[str, Any]] = Field(default_factory=list)
    query_iteration_results: List[Dict[str, Any]] = Field(default_factory=list)
    citation_map: Dict[str, Any] = Field(default_factory=dict)
    ranking_steps: List[Dict[str, Any]] = Field(default_factory=list)
    ranking_scores: List[Dict[str, Any]] = Field(default_factory=list)
    completed_batch_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
