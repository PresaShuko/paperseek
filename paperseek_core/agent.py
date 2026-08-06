
import re
import json
import inspect
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from paperseek_core.llm import LLMClient, format_modelscope_quota
from paperseek_core.execution import SearchCancelled, run_cancellable
from paperseek_core.ranking import (
    RankingBatchScheduler,
    RankingOutputCodec,
)
from paperseek_core.ranking_pipeline import RankingPipeline, RankingRunRequest
from paperseek_core.ranking_scoring import RankingScorer
from paperseek_core.abstracts import AbstractFetcher
from paperseek_core.disciplines import (
    apply_arxiv_category_filter,
    apply_wos_discipline_filter,
    discipline_prompt_context,
    discipline_source_note,
    discipline_summary,
    normalize_source_filter_values,
    openalex_field_ids,
)
from paperseek_core.retrieval import (
    ProviderRetrievalCapabilities,
    RetrievalLane,
    document_key,
)
from paperseek_core.retrieval_pipeline import RetrievalPipeline
from paperseek_core.retrieval_support import RetrievalSupport
from paperseek_core.retrieval_clients import ExternalRetrievalServices
from paperseek_core.citation_pipeline import CitationExpansionPipeline
from paperseek_core.citation_support import CitationSupport
from paperseek_core.query_portfolio import QueryPortfolioPipeline
from paperseek_core.query_generation import QueryGenerationPipeline
from paperseek_core.query_contract import (
    QueryContractGuard,
    provider_error_text as _query_provider_error_text,
    queries_equivalent as _query_queries_equivalent,
    sanitize_openalex_query as _query_sanitize_openalex_query,
    sanitize_semantic_scholar_query as _query_sanitize_semantic_scholar_query,
    strict_query_output_instruction,
)
from paperseek_core.intent_analysis import IntentAnalysisPipeline
from paperseek_core.checkpoint_coordinator import CheckpointCoordinator
from paperseek_core.candidate_ledger import CandidateLedger
from paperseek_core.workflow import SearchCompletionPipeline, SearchWorkflowExecutor
from paperseek_core.harness import (
    QueryLoopDecision,
    QueryLoopSnapshot,
    SearchCheckpoint,
    SearchRunState,
    SearchLoopController,
    extract_json_object_text as _harness_extract_json_object_text,
    looks_truncated_or_malformed_query as _harness_looks_truncated_or_malformed_query,
    query_response_from_json as _harness_query_response_from_json,
    strip_llm_fence as _harness_strip_llm_fence,
)
from paperseek_core.sources.contracts import ProviderError
from paperseek_core.sources.factory import create_source_provider
from paperseek_core.planning import SearchPlan


def _extract_json_object_text(text: str) -> str:
    return _harness_extract_json_object_text(text)


def _query_response_from_json(text: str) -> Tuple[str, str]:
    return _harness_query_response_from_json(text)


def _looks_truncated_or_malformed_query(query: str) -> bool:
    return _harness_looks_truncated_or_malformed_query(query)


def _sanitize_openalex_query(query: str) -> str:
    return _query_sanitize_openalex_query(query)


def _sanitize_semantic_scholar_query(query: str) -> str:
    return _query_sanitize_semantic_scholar_query(query)


def _provider_error_text(exc: ProviderError) -> str:
    return _query_provider_error_text(exc)


def _queries_equivalent(left: str, right: str) -> bool:
    return _query_queries_equivalent(left, right)


def _strip_llm_fence(text: str) -> str:
    return _harness_strip_llm_fence(text)


def _extract_intent_summary(text: str, max_chars: int = 1600) -> str:
    raw = _strip_llm_fence(text)
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        parts = []
        for key in (
            "intent",
            "core_concepts",
            "must_have_facets",
            "optional_facets",
            "required_relation",
            "likely_synonyms",
            "boundaries",
            "adjustment_strategy",
        ):
            value = parsed.get(key)
            if isinstance(value, list):
                value = "; ".join(str(item).strip() for item in value if str(item).strip())
            value = str(value or "").strip()
            if value:
                parts.append(f"{key}: {value}")
        raw = "\n".join(parts) if parts else raw
    raw = re.sub(r"\s+\n", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    if len(raw) > max_chars:
        raw = raw[:max_chars].rstrip() + "..."
    return raw


_LOOP_INTENT_STOPWORDS = {
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
    "concept",
    "concepts",
    "core",
    "data",
    "effect",
    "effects",
    "find",
    "from",
    "how",
    "intent",
    "into",
    "keep",
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
_LOOP_INTENT_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{1,}|[\u4e00-\u9fff]{2,}")


def _extract_loop_intent_terms(*texts: str, limit: int = 20) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for text in texts:
        for match in _LOOP_INTENT_TERM_RE.findall(str(text or "")):
            clean = match.strip("-").lower()
            if len(clean) < 3 and not match.isupper():
                continue
            if clean in _LOOP_INTENT_STOPWORDS or clean in seen:
                continue
            seen.add(clean)
            terms.append(clean)
            if len(terms) >= limit:
                return terms
    return terms


def _positive_intent_summary_text(text: str) -> str:
    lines: list[str] = []
    for line in str(text or "").splitlines():
        prefix = line.split(":", 1)[0].strip().lower()
        if prefix in {"boundaries", "exclusions", "exclude", "negative_constraints"}:
            continue
        lines.append(line)
    return "\n".join(lines)


def _repair_server_error_query(query: str) -> str:
    """Rewrite fragile exact phrases into proximity expressions after WoS 5xx errors."""
    normalized = (
        query.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )

    def phrase_to_near(match):
        phrase = re.sub(r"\s+", " ", match.group(1).strip())
        if re.search(r"\b(AND|OR|NOT|NEAR|SAME)\b", phrase, re.IGNORECASE):
            return match.group(0)
        terms = [t for t in phrase.split(" ") if t]
        if len(terms) < 2:
            return match.group(0)
        return "(" + " NEAR/2 ".join(terms) + ")"

    repaired = re.sub(r'"([^"]+)"', phrase_to_near, normalized)
    repaired = re.sub(r"\s+", " ", repaired).strip()
    return repaired if repaired != query else query


def _simplify_server_error_query(query: str) -> str:
    """Fallback query for WoS 5xx errors: avoid proximity and exact-phrase operators."""
    simplified = (
        query.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )

    def phrase_to_and(match):
        phrase = re.sub(r"\s+", " ", match.group(1).strip())
        if re.search(r"\b(AND|OR|NOT|NEAR|SAME)\b", phrase, re.IGNORECASE):
            return match.group(0)
        terms = [t for t in phrase.split(" ") if t]
        if len(terms) < 2:
            return match.group(0)
        return "(" + " AND ".join(terms) + ")"

    simplified = re.sub(r'"([^"]+)"', phrase_to_and, simplified)
    simplified = re.sub(r"([\w*?-]+)\s+NEAR/\d+\s+([\w*?-]+)", r"\1 AND \2", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"([\w*?-]+)\s+NEAR\s+([\w*?-]+)", r"\1 AND \2", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"([\w*?-]+)\s+SAME\s+([\w*?-]+)", r"\1 AND \2", simplified, flags=re.IGNORECASE)
    simplified = re.sub(r"\s+", " ", simplified).strip()
    return simplified if simplified != query else query


def _make_starter_safe_query(query: str) -> str:
    """Normalize LLM output to the most stable WoS Starter API query subset."""
    safe_query = _simplify_server_error_query(query)
    # Run twice to catch nested forms that expose another proximity expression after
    # phrase simplification.
    safe_query = _simplify_server_error_query(safe_query)
    return safe_query


def _server_error_query_variants(query: str) -> list:
    variants = []
    for candidate in (
        _simplify_server_error_query(query),
        _repair_server_error_query(query),
        _simplify_server_error_query(_repair_server_error_query(query)),
    ):
        if candidate != query and candidate not in variants:
            variants.append(candidate)
    return variants


def _describe_document(doc, idx: int, abstract_limit: int = 1200) -> str:
    """Produce a compact text description of a document for the LLM ranking prompt."""
    parts = [f"{idx}. UID: {doc.uid or document_key(doc)}"]
    provider = getattr(doc, "provider", "")
    if provider:
        parts.append(f"   Provider: {provider}")
    if doc.title:
        parts.append(f"   Title: {doc.title}")
    if doc.types:
        parts.append(f"   Document types: {'; '.join(doc.types[:5])}")
    if doc.source:
        src = doc.source
        src_parts = []
        if src.source_title:
            src_parts.append(src.source_title)
        if src.publish_year:
            src_parts.append(str(src.publish_year))
        if src.volume:
            src_parts.append(f"V{src.volume}")
        if src.issue:
            src_parts.append(f"I{src.issue}")
        if src_parts:
            parts.append(f"   Source: {', '.join(src_parts)}")
    if doc.names and doc.names.authors:
        authors = [
            a.display_name or a.wos_standard or ""
            for a in doc.names.authors[:5]
        ]
        parts.append(f"   Authors: {', '.join(a for a in authors if a)}")
    if doc.keywords and doc.keywords.author_keywords:
        parts.append(f"   Keywords: {'; '.join(doc.keywords.author_keywords[:8])}")
    abstract = getattr(doc, "abstract", "")
    if abstract:
        parts.append(f"   Abstract: {abstract[:max(200, int(abstract_limit or 1200))]}")
    return "\n".join(parts)


class PaperSeekAgent:
    def __init__(self, config, llm_client: LLMClient, abstract_fetcher: Optional[AbstractFetcher] = None):
        self.config = config
        self.llm = llm_client
        self.abstract_fetcher = abstract_fetcher or AbstractFetcher()
        self.data_source = (getattr(config, "data_source", "wos") or "wos").lower()
        self.discipline_fields = normalize_source_filter_values(
            self.data_source,
            getattr(config, "discipline_fields", ()),
        )
        try:
            self.config.discipline_fields = self.discipline_fields
        except Exception:
            pass
        self.citation_support = CitationSupport(self)
        self.retrieval_support = RetrievalSupport(self)
        self.event_handler: Optional[Callable[[dict], None]] = None
        self.citation_map: dict = self._empty_citation_map(enabled=getattr(config, "expand_citations", True))
        self.search_intent: str = ""
        self.search_plan: Optional[SearchPlan] = None
        self.search_plan_diagnostics: list[dict] = []
        self.query_view_selection: list[dict] = []
        self.query_portfolio: list[dict] = []
        self.query_portfolio_lane_results: Dict[str, list] = {}
        self.query_iteration_results: list[dict] = []
        self._retrieval_primary_hits: list = []
        self.last_query_audit: str = ""
        self.retrieval_metadata_by_key: Dict[str, Dict[str, Any]] = {}
        self.ranking_steps: Dict[str, Dict[str, Any]] = {}
        self.ranking_context: Dict[str, Any] = {}
        self.external_retrieval = ExternalRetrievalServices(
            config,
            run_cancellable=self._run_cancellable,
            log=self._emit_log,
            ranking_step=self._emit_ranking_step,
            metadata_by_key=lambda: self.retrieval_metadata_by_key,
        )
        self.query_contract = QueryContractGuard(self)
        self.query_generation = QueryGenerationPipeline(
            self,
            starter_safe_query=_make_starter_safe_query,
        )
        self.intent_analysis = IntentAnalysisPipeline(self)
        self.checkpoints = CheckpointCoordinator(self)
        self.candidate_ledger = CandidateLedger(self)
        self.search_loop = SearchLoopController()
        self.search_run_state: Optional[SearchRunState] = None
        self.cancel_check: Optional[Callable[[], bool]] = None
        self.checkpoint_handler: Optional[Callable[[dict], None]] = None
        self.resume_checkpoint: Optional[SearchCheckpoint] = None
        self.checkpoint_sequence = 0
        self.run_question = ""
        self.iteration_history: list = []
        self.current_query = ""
        self.last_total = 0
        self.last_iteration = 0

        self.provider = create_source_provider(config, self.data_source, log=self._emit_log)
        self.documents_api = self.provider.documents_api if self.data_source == "wos" else None

    def search(
        self,
        question: str,
        verbose: bool = False,
        event_handler: Optional[Callable[[dict], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        checkpoint_handler: Optional[Callable[[dict], None]] = None,
        resume_checkpoint: Optional[dict] = None,
    ) -> dict:
        """Main entry: natural language question -> dict with results and metadata."""
        self.event_handler = event_handler
        self.cancel_check = cancel_check
        self.checkpoint_handler = checkpoint_handler
        self.resume_checkpoint = self._validate_resume_checkpoint(question, resume_checkpoint)
        self.checkpoint_sequence = int(self.resume_checkpoint.sequence if self.resume_checkpoint else 0)
        try:
            return self._search(question, verbose=verbose)
        finally:
            self.event_handler = None
            self.cancel_check = None
            self.checkpoint_handler = None
            self.resume_checkpoint = None

    def _validate_resume_checkpoint(self, question: str, payload: Optional[dict]) -> Optional[SearchCheckpoint]:
        return self.checkpoints.validate(question, payload)

    def _restore_checkpoint_state(self, checkpoint: SearchCheckpoint) -> None:
        self.checkpoints.restore(checkpoint)

    def _save_checkpoint(
        self,
        stage: str,
        *,
        records: Optional[list] = None,
        ranking_scores: Optional[list] = None,
        completed_batch_ids: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        self.checkpoints.save(
            stage,
            records=records,
            ranking_scores=ranking_scores,
            completed_batch_ids=completed_batch_ids,
            metadata=metadata,
        )

    def _search(self, question: str, verbose: bool = False) -> dict:
        return SearchWorkflowExecutor(
            self,
            make_starter_safe_query=_make_starter_safe_query,
            server_error_query_variants=_server_error_query_variants,
            queries_equivalent=_queries_equivalent,
        ).run(question, verbose=verbose)
    def _complete_search_pipeline(
        self,
        question: str,
        query: str,
        total: int,
        hits: list,
        history: list,
        iteration: int,
        checkpoint: Optional[SearchCheckpoint] = None,
    ) -> dict:
        return SearchCompletionPipeline(self).run(
            question, query, total, hits, history, iteration, checkpoint=checkpoint
        )

    @staticmethod
    def _ranking_scores_from_ranked(ranked: list) -> list[dict[str, Any]]:
        output = []
        for entry in ranked or []:
            document = entry.get("document") if isinstance(entry, dict) else None
            uid = str(getattr(document, "uid", "") or "")
            if not uid:
                continue
            output.append(
                {
                    "uid": uid,
                    "score": entry.get("score", 0),
                    "reasoning": str(entry.get("reasoning") or ""),
                }
            )
        return output

    def partial_result_payload(self, question: str = "") -> dict:
        """Return the latest safe run snapshot for failed or cancelled searches."""
        query = self.current_query or (self.search_run_state.current_query if self.search_run_state else "")
        return {
            "question": question or self.run_question,
            "search_intent": self.search_intent,
            "search_plan": self.search_plan.model_dump() if self.search_plan else {},
            "query_view_selection": list(self.query_view_selection),
            "query_portfolio": list(self.query_portfolio),
            "query_iteration_memory": self._query_iteration_memory_payload(),
            "final_query": query,
            "db": self.config.wos_db if self.data_source == "wos" else self.data_source.upper(),
            "source": self.data_source,
            "field": self._field_summary(),
            "total": self.last_total,
            "iterations": self.last_iteration,
            "history": list(self.iteration_history or []),
            "search_state": self._search_state_payload(),
            "citation_map": dict(self.citation_map or {}),
            "ranking_steps": list(self.ranking_steps.values()),
            "ranked": [],
        }

    def _search_state_payload(self) -> dict:
        return self.candidate_ledger.payload()

    def _query_loop_decision(
        self,
        query: str,
        hits: list,
        total: int,
        iteration: int,
        configured_iterations: int,
        adaptive_max_iterations: int,
        history: list,
    ) -> QueryLoopDecision:
        self._set_search_state_query(query)
        preview = self._preview_hits(hits)
        snapshot = QueryLoopSnapshot(
            iteration=iteration,
            configured_iterations=configured_iterations,
            adaptive_max_iterations=adaptive_max_iterations,
            total=total,
            target_min=int(getattr(self.config, "target_min", 5) or 5),
            target_max=int(getattr(self.config, "target_max", 50) or 50),
            retrieval_pool_min=self._retrieval_pool_min(),
            retrieval_pool_max=self._retrieval_pool_max(),
            history=history,
            query=query,
            hit_count=len(hits or []),
            top_titles=[str(item.get("title") or "") for item in preview if item.get("title")],
            intent_terms=_extract_loop_intent_terms(self.run_question, query, _positive_intent_summary_text(self.search_intent)),
        )
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query=query)
        self.search_run_state, decision = self.search_loop.evaluate(self.search_run_state, snapshot)
        return decision

    def _set_search_state_query(self, query: str) -> None:
        self.current_query = query or ""
        if self.search_run_state is not None:
            self.search_run_state = self.search_run_state.with_current_query(query)

    def _preflight_query(self, query: str):
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query=query)
        self.search_run_state, validation = self.search_loop.preflight(self.search_run_state, query)
        return validation

    def _harness_source_search(self, query: str):
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query=query)
        self.search_run_state, result, error = self.search_loop.source_search(
            self.search_run_state,
            query,
            self._provider_search,
        )
        return result, error

    def _recover_source_error(
        self,
        error: Exception,
        *,
        query: str = "",
        repair_attempts: int = 0,
        max_repair_attempts: int = 2,
        has_server_error_variant: bool = False,
        allow_broaden_query: bool = False,
    ):
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query=query)
        self.search_run_state, decision = self.search_loop.recover_source_error(
            self.search_run_state,
            error,
            query=query,
            repair_attempts=repair_attempts,
            max_repair_attempts=max_repair_attempts,
            has_server_error_variant=has_server_error_variant,
            allow_broaden_query=allow_broaden_query,
        )
        return decision

    def _observe_ranking_batch_error(
        self,
        error: Exception,
        *,
        step_id: str,
        batch_index: int,
        batch_count: int,
        concurrency: int,
        candidate_count: int,
        rate_limited: bool,
    ):
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query="")
        self.search_run_state, observation = self.search_loop.observe_ranking_batch_error(
            self.search_run_state,
            error,
            step_id=step_id,
            batch_index=batch_index,
            batch_count=batch_count,
            concurrency=concurrency,
            candidate_count=candidate_count,
            rate_limited=rate_limited,
        )
        return observation

    def _recover_ranking_failures(
        self,
        *,
        step_id: str,
        concurrency: int,
        next_concurrency: int,
        failed_batches: int,
        failed_candidates: int,
        rate_limited: bool,
    ):
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query="")
        self.search_run_state, decision = self.search_loop.recover_ranking_failures(
            self.search_run_state,
            step_id=step_id,
            concurrency=concurrency,
            next_concurrency=next_concurrency,
            failed_batches=failed_batches,
            failed_candidates=failed_candidates,
            rate_limited=rate_limited,
        )
        return decision

    def _plan_citation_expansion(self, *, candidate_count: int, seed_ranking_count: int, seed_count: int, depth: int):
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query="")
        self.search_run_state, decision = self.search_loop.plan_citation_expansion(
            self.search_run_state,
            candidate_count=candidate_count,
            seed_ranking_count=seed_ranking_count,
            configured_seed_count=seed_count,
            configured_depth=depth,
        )
        return decision

    def _observe_citation_traversal(
        self,
        *,
        status: str,
        seed_count: int,
        depth: int,
        per_seed: int,
        max_records: int,
        added_candidates: int = 0,
        candidate_pool: int = 0,
        frontier: Optional[Dict[str, Any]] = None,
        error: Exception | None = None,
    ):
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query="")
        self.search_run_state, observation = self.search_loop.observe_citation_traversal(
            self.search_run_state,
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
        return observation

    def _recover_citation_error(
        self,
        error: Exception,
        *,
        seed_count: int,
        depth: int,
        per_seed: int,
        max_records: int,
        retry_attempts: int,
        max_retries: int = 1,
    ):
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query="")
        self.search_run_state, decision = self.search_loop.recover_citation_error(
            self.search_run_state,
            error,
            seed_count=seed_count,
            depth=depth,
            per_seed=per_seed,
            max_records=max_records,
            retry_attempts=retry_attempts,
            max_retries=max_retries,
        )
        return decision

    def _enqueue_candidate_queue(
        self,
        documents: list,
        origin: str,
        evidence_by_key: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> list:
        return self.candidate_ledger.enqueue(documents, origin, evidence_by_key)

    @staticmethod
    def _merge_unique(existing: list, incoming: list) -> list:
        return CandidateLedger._merge_unique(existing, incoming)

    @staticmethod
    def _merge_citation_paths(existing: list, incoming: list) -> list:
        return CandidateLedger._merge_citation_paths(existing, incoming)

    @staticmethod
    def _optional_float(value: Any) -> Optional[float]:
        return CandidateLedger._optional_float(value)

    def _record_candidate_gate(self, all_candidates: list, selected_candidates: list, limit: int) -> None:
        self.candidate_ledger.record_gate(all_candidates, selected_candidates, limit)

    def _record_candidate_scores(self, ranked: list, action: str) -> None:
        self.candidate_ledger.record_scores(ranked, action)

    def _record_final_candidates(self, ranked: list) -> None:
        self.candidate_ledger.record_final(ranked)

    def _execute_query_portfolio(self, question: str, final_query: str, primary_hits: list, history: list) -> list:
        return QueryPortfolioPipeline(self).run(question, final_query, primary_hits, history)

    def _provider_search(self, query: str):
        return self._provider_search_lane(query, RetrievalLane.RELEVANCE, self._candidate_limit(), page=1)

    def _source_safe_query(self, query: str) -> str:
        return self.query_contract.source_safe_query(query)

    def _source_query_format_issue(self, query: str) -> str:
        return self.query_contract.format_issue(query)

    def _consume_query_audit(self) -> str:
        audit = self.last_query_audit
        self.last_query_audit = ""
        return audit

    def _finalize_source_query(
        self,
        question: str,
        raw: str,
        *,
        current_query: str = "",
        feedback: str = "",
        system_prompt: str = "",
        log_name: str = "",
        output_label: str = "query string",
        operation: str = "generate",
    ) -> str:
        return self.query_contract.finalize(
            question,
            raw,
            current_query=current_query,
            feedback=feedback,
            system_prompt=system_prompt,
            log_name=log_name,
            output_label=output_label,
            operation=operation,
        )

    def _retry_malformed_source_query(
        self,
        question: str,
        malformed_query: str,
        *,
        current_query: str = "",
        feedback: str = "",
        system_prompt: str = "",
        log_name: str = "",
        output_label: str = "query string",
        operation: str = "generate",
        issue: str = "",
    ) -> str:
        return self.query_contract.retry_malformed(
            question,
            malformed_query,
            current_query=current_query,
            feedback=feedback,
            system_prompt=system_prompt,
            log_name=log_name,
            output_label=output_label,
            operation=operation,
            issue=issue,
        )

    def _repair_query_after_provider_error(self, question: str, query: str, error: ProviderError) -> str:
        return self.query_contract.repair_after_provider_error(question, query, error)

    def _is_repairable_provider_error(self, error: ProviderError) -> bool:
        return self.query_contract.is_repairable_provider_error(error)

    def _repair_source_query_syntax(self, question: str, query: str, error: ProviderError) -> str:
        return self.query_contract.repair_source_syntax(question, query, error)

    def _syntax_repair_prompt(self) -> str:
        return self.query_contract.syntax_repair_prompt()

    def _provider_search_lane(self, query: str, lane: str, limit: int, page: int = 1):
        return self._run_cancellable(
            lambda: self._provider_search_lane_blocking(query, lane, limit, page=page)
        )

    def _provider_search_lane_blocking(self, query: str, lane: str, limit: int, page: int = 1):
        if self.data_source == "openalex":
            return self._call_provider_search(query=query, limit=limit, page=page, field_ids=openalex_field_ids(self.discipline_fields), lane=lane)
        if self.data_source == "crossref":
            return self._call_provider_search(query=query, limit=limit, page=page, lane=lane)
        if self.provider:
            if self.data_source == "wos" and self.documents_api is not self.provider.documents_api:
                self.provider.documents_api = self.documents_api
            return self._call_provider_search(query=query, limit=limit, page=page, lane=lane)

    def _call_provider_search(self, **kwargs):
        return self._call_provider_search_with(self.provider, **kwargs)

    @staticmethod
    def _call_provider_search_with(provider, **kwargs):
        if provider is None:
            raise ProviderError("unknown", "No source provider is configured.", query=str(kwargs.get("query") or ""))
        search = provider.search
        signature = inspect.signature(search)
        accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
        if accepts_kwargs:
            return search(**kwargs)
        supported = {name: value for name, value in kwargs.items() if name in signature.parameters}
        return search(**supported)

    def _apply_discipline_filter(self, query: str) -> str:
        if self.data_source == "wos":
            return apply_wos_discipline_filter(query, self.discipline_fields)
        if self.data_source == "arxiv":
            return apply_arxiv_category_filter(query, self.discipline_fields)
        return query

    def _discipline_context(self) -> str:
        return discipline_prompt_context(
            self.discipline_fields,
            self.data_source,
            getattr(self.config, "search_field", ""),
        )

    def _field_summary(self) -> str:
        parts = []
        if self.data_source == "openalex":
            selected = discipline_summary(self.discipline_fields)
            if selected:
                parts.append(selected)
        elif self.discipline_fields:
            parts.append(", ".join(self.discipline_fields))
        if getattr(self.config, "search_field", ""):
            parts.append(str(self.config.search_field))
        return "; ".join(parts)

    def _retrieval_pool_max(self) -> int:
        try:
            return max(1, int(getattr(self.config, "retrieval_pool_max", 3000) or 3000))
        except (TypeError, ValueError):
            return 3000

    def _retrieval_pool_min(self) -> int:
        try:
            configured = max(0, int(getattr(self.config, "retrieval_pool_min", 5) or 5))
        except (TypeError, ValueError):
            configured = 5
        try:
            target_max = max(1, int(getattr(self.config, "target_max", 50) or 50))
        except (TypeError, ValueError):
            target_max = 50
        return min(configured, target_max)

    def _adaptive_max_iterations(self, configured_iterations: int) -> int:
        configured = max(1, int(configured_iterations or 5))
        requested = getattr(self.config, "adaptive_max_iterations", None)
        try:
            if requested is not None:
                return max(configured, int(requested))
        except (TypeError, ValueError):
            pass
        return max(configured + 8, configured * 3, 10)

    def _llm_ranking_candidate_limit(self) -> int:
        try:
            configured = max(1, int(getattr(self.config, "ranking_candidate_limit", 256) or 256))
        except (TypeError, ValueError):
            configured = 256
        try:
            target_max = max(1, int(getattr(self.config, "target_max", 50) or 50))
        except (TypeError, ValueError):
            target_max = 50
        return min(max(configured, target_max), self._retrieval_pool_max())

    def _citation_seed_selection_limit(self) -> int:
        try:
            seed_count = max(1, int(getattr(self.config, "citation_seed_count", 30) or 30))
        except (TypeError, ValueError):
            seed_count = 30
        return min(self._llm_ranking_candidate_limit(), max(seed_count * 4, 64))

    def _ranked_output_floor(self) -> int:
        return 50

    def _select_ranked_output(self, ranked: list) -> list:
        if len(ranked) <= self._ranked_output_floor():
            return ranked
        high_score = [entry for entry in ranked if self._ranking_score(entry) >= 5]
        if len(high_score) > self._ranked_output_floor():
            return high_score
        return ranked[: self._ranked_output_floor()]

    def _ranking_score(self, entry: Any) -> float:
        try:
            return float((entry or {}).get("score", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _complete_after_unchanged_revision(self, history: list, iteration: int, query: str, total: int, hits: list, attempted_action: str) -> None:
        if total == 0:
            action = "empty"
            message = f"No records found and the {attempted_action} query was unchanged; stopped instead of repeating the same request."
        elif total < self.config.target_min:
            action = "accept_low"
            message = f"Accepted {total} records below the target minimum because the {attempted_action} query was unchanged."
        elif total > self._retrieval_pool_max():
            action = "accept_high"
            message = f"Accepted {total} records above the LLM pre-ranking safety pool because the {attempted_action} query was unchanged; the fused candidate pool will be truncated before LLM ranking."
        elif total > self.config.target_max:
            action = "accept_pool"
            message = f"Accepted {total} records for downstream pre-ranking because the {attempted_action} query was unchanged."
        else:
            action = "accept"
            message = f"Accepted {total} records because the {attempted_action} query was unchanged."
        row = {
            "iteration": iteration,
            "query": query,
            "total": total,
            "action": action,
            "next_query": None,
            "message": message,
        }
        history.append(row)
        self._emit_stage(
            "search",
            "complete",
            total=total,
            history=history,
            final_query=query,
            preview=self._preview_hits(hits),
        )

    def _candidate_limit(self) -> int:
        output_limit = max(1, min(int(self.config.target_max or 50), 50))
        if self.data_source == "wos":
            return output_limit
        return min(max(output_limit * 2, output_limit), 100)

    def _record_query_iteration(self, iteration: int, query: str, total: int, hits: list) -> None:
        records = self._dedupe_documents(list(hits or []))[:100]
        normalized_query = re.sub(r"\s+", " ", str(query or "")).strip().casefold()
        if not records or not normalized_query:
            return
        entry = {
            "iteration": int(iteration or 0),
            "query": str(query or ""),
            "total": int(total or 0),
            "records": records,
        }
        for index, existing in enumerate(self.query_iteration_results):
            existing_query = re.sub(
                r"\s+", " ", str((existing or {}).get("query") or "")
            ).strip().casefold()
            if existing_query == normalized_query:
                self.query_iteration_results[index] = entry
                break
        else:
            self.query_iteration_results.append(entry)
        self.query_iteration_results = self.query_iteration_results[-12:]

    def _query_iteration_memory_payload(self) -> list[dict]:
        return [
            {
                "iteration": int(item.get("iteration") or 0),
                "query": str(item.get("query") or ""),
                "total": int(item.get("total") or 0),
                "candidate_count": len(item.get("records") or []),
            }
            for item in self.query_iteration_results
            if isinstance(item, dict)
        ]

    def _query_iteration_lanes(self, final_query: str) -> Dict[str, list]:
        final_normalized = re.sub(r"\s+", " ", str(final_query or "")).strip().casefold()
        lanes: Dict[str, list] = {}
        for item in self.query_iteration_results:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "")
            normalized = re.sub(r"\s+", " ", query).strip().casefold()
            records = self._dedupe_documents(list(item.get("records") or []))
            if not records or not normalized or normalized == final_normalized:
                continue
            iteration = max(1, int(item.get("iteration") or len(lanes) + 1))
            lanes[f"query_iteration:{iteration}"] = records
        return lanes

    def _retrieval_capabilities(self) -> ProviderRetrievalCapabilities:
        if self.provider and hasattr(self.provider, "retrieval_capabilities"):
            return self.provider.retrieval_capabilities()
        if self.data_source == "wos":
            return ProviderRetrievalCapabilities(
                source="wos",
                lanes=(RetrievalLane.RELEVANCE, RetrievalLane.IMPACT, RetrievalLane.RECENT),
                max_lane_limit=100,
            )
        return ProviderRetrievalCapabilities(source=self.data_source, lanes=(RetrievalLane.RELEVANCE,))

    def _retrieve_candidates(self, question: str, query: str, primary_hits: list) -> list:
        return RetrievalPipeline(self).run(question, query, primary_hits)
    def _refuse_candidates_after_citation(self, question: str, candidates: list) -> list:
        return self.retrieval_support.refusion_after_citation(question, candidates)

    @staticmethod
    def _is_citation_candidate_origin(origin: str) -> bool:
        return RetrievalSupport.is_citation_origin(origin)

    def _refresh_candidate_retrieval_evidence(self, documents: list) -> None:
        self.retrieval_support.refresh_candidate_evidence(documents)

    def _effective_lane_limit(
        self,
        capabilities: ProviderRetrievalCapabilities,
        lane: str = RetrievalLane.RELEVANCE,
    ) -> int:
        try:
            configured = max(1, int(getattr(self.config, "retrieval_lane_limit", 500) or 500))
        except (TypeError, ValueError):
            configured = 500
        # A single lane cannot contribute more papers to LLM scoring than the
        # final ranking gate can accept. Keeping that bound here avoids paging
        # far past useful depth while still allowing all lanes to add diversity.
        ranking_limit = self._llm_ranking_candidate_limit()
        useful_depth = max(100, ranking_limit)
        if lane != RetrievalLane.RELEVANCE:
            # Diversification lanes only need a strong top slice before fusion.
            useful_depth = max(100, int(math.ceil(ranking_limit / 4.0)))
        return max(1, min(configured, capabilities.max_lane_limit, self._retrieval_pool_max(), useful_depth))

    def _retrieval_rrf_k(self) -> int:
        try:
            return max(1, int(getattr(self.config, "retrieval_rrf_k", 60) or 60))
        except (TypeError, ValueError):
            return 60

    def _collect_retrieval_lane(
        self,
        query: str,
        lane: str,
        limit: int,
        initial_hits: Optional[list] = None,
    ) -> list:
        if initial_hits is None and lane == RetrievalLane.RELEVANCE:
            initial_hits = self._retrieval_primary_hits
        collected = self._dedupe_documents(list(initial_hits or []))[:limit]
        if len(collected) >= limit:
            return collected

        default_page_size = min(100, limit)
        if collected and len(collected) < default_page_size:
            return collected
        page = 2 if collected else 1
        while len(collected) < limit:
            self._check_cancelled()
            request_limit = min(1000 if self.data_source == "semanticscholar" and lane != RetrievalLane.RELEVANCE else 100, limit - len(collected))
            if self.data_source == "wos":
                request_limit = min(request_limit, limit)
            try:
                result = self._provider_search_lane(query, lane, request_limit, page=page)
            except Exception as exc:
                if not collected:
                    raise
                self._emit_log(
                    f"Retrieval lane retained {len(collected)} candidates after page {page} failed: "
                    f"{exc.__class__.__name__}: {exc}"
                )
                break
            hits = list(getattr(result, "hits", []) or [])
            if not hits:
                break
            collected.extend(hits)
            metadata = getattr(result, "metadata", None)
            page_size = max(1, int(getattr(metadata, "limit", request_limit) or request_limit))
            total = int(getattr(metadata, "total", 0) or 0)
            if self.data_source == "wos":
                break
            if len(hits) < page_size:
                break
            if total and len(collected) >= total:
                break
            if self.data_source == "semanticscholar" and lane != RetrievalLane.RELEVANCE:
                break
            page += 1
        return self._dedupe_documents(collected)[:limit]

    def _external_embedding_scores(self, question: str, documents: list) -> Optional[List[float]]:
        return self.external_retrieval.embedding_scores(question, documents)

    @staticmethod
    def _embedding_score_map(documents: list, scores: Optional[List[float]]) -> Dict[str, float]:
        return ExternalRetrievalServices.embedding_score_map(documents, scores)

    def _apply_external_reranker(self, question: str, documents: list) -> list:
        return self.external_retrieval.rerank(question, documents)

    def _retrieval_model_candidates(self, kind: str, default_model: str, provider: str = "") -> List[str]:
        return self.external_retrieval.model_candidates(kind, default_model, provider)

    def _retrieval_api_key(self, kind: str, provider: str) -> str:
        return self.external_retrieval.api_key(kind, provider)

    def _retrieval_base_url(self, kind: str, provider: str) -> str:
        return self.external_retrieval.base_url(kind, provider)

    @staticmethod
    def _citation_seed_key(doc) -> str:
        return CitationSupport.seed_key(doc)

    def _build_citation_seed_plans(self, seed_ranked: list, candidates: list, plan) -> list:
        return self.citation_support.build_seed_plans(seed_ranked, candidates, plan)

    @staticmethod
    def _citation_seed_plan_counts(seed_plans: list) -> dict:
        return CitationSupport.seed_plan_counts(seed_plans)

    def _prepare_candidates(self, question: str, hits: list) -> list:
        return CitationExpansionPipeline(self).run(question, hits)

    def _citation_evidence_by_key(self, records: list, citation_data: dict) -> Dict[str, Dict[str, Any]]:
        return CitationSupport.evidence_by_key(records, citation_data)

    def _citation_seed_candidate_pool(self, candidates: list, limit: int) -> list:
        return self.citation_support.seed_candidate_pool(candidates, limit)

    def _empty_citation_map(self, enabled: bool = True, initial_candidates: int = 0, candidate_pool: int = 0) -> dict:
        return self.citation_support.empty_map(enabled, initial_candidates, candidate_pool)

    def _finalize_citation_map(self, ranked: list) -> None:
        self.citation_support.finalize_map(ranked)

    @staticmethod
    def _dedupe_documents(documents: list) -> list:
        return CitationSupport.dedupe_documents(documents)

    def _emit(self, event_type: str, **payload: Any) -> None:
        self._check_cancelled()
        if self.event_handler:
            self.event_handler({"type": event_type, **payload})

    def _check_cancelled(self) -> None:
        if self.cancel_check and self.cancel_check():
            raise SearchCancelled("Search cancelled by user.")

    def _run_cancellable(self, operation: Callable[[], Any]) -> Any:
        return run_cancellable(operation, self.cancel_check)

    def _emit_log(self, message: str, **payload: Any) -> None:
        self._emit("log", message=message, **payload)

    def _emit_stage(self, stage: str, status: str, **data: Any) -> None:
        if stage == "query" and self.search_plan is not None:
            data.setdefault("search_plan", self.search_plan.model_dump())
        self._emit("stage", stage=stage, status=status, data=data)

    def _emit_ranking_step(
        self,
        step_id: str,
        status: str,
        title: str,
        current: int = 0,
        total: int = 0,
        detail: str = "",
        **data: Any,
    ) -> None:
        normalized_status = (status or "processing").lower()
        safe_total = max(0, int(total or 0))
        safe_current = max(0, min(int(current or 0), safe_total or int(current or 0)))
        step = {
            "id": step_id,
            "title": title,
            "status": normalized_status,
            "current": safe_current,
            "total": safe_total,
            "detail": detail,
        }
        for key in ("candidate_count", "lane_counts", "seed_count", "added_candidates", "concurrency", "batch_size"):
            if key in data and data[key] is not None:
                step[key] = data[key]
        self.ranking_steps[step_id] = step
        payload = dict(self.ranking_context)
        payload.update(data)
        payload["ranking_steps"] = list(self.ranking_steps.values())
        if "candidate_count" not in payload and "candidate_count" in step:
            payload["candidate_count"] = step["candidate_count"]
        self._emit_stage("ranking", "processing", **payload)

    def _source_label(self) -> str:
        labels = {
            "wos": "WoS Starter",
            "openalex": "OpenAlex",
            "crossref": "Crossref",
            "arxiv": "arXiv",
            "semanticscholar": "Semantic Scholar",
            "pubmed": "PubMed",
            "googlescholar": "Google Scholar",
            "paperhub": "Computer science top conferences",
        }
        return labels.get(self.data_source, self.data_source)

    def _source_request_label(self, query: str) -> str:
        discipline_note = discipline_source_note(self.discipline_fields, self.data_source)
        suffix = f" ({discipline_note})" if discipline_note else ""
        if self.data_source == "wos":
            return f"GET /documents db={self.config.wos_db} q={query}{suffix}"
        if self.data_source == "openalex":
            return f"GET /works search={query}{suffix}"
        if self.data_source == "crossref":
            return f"GET /works query.bibliographic={query}{suffix}"
        if self.data_source == "arxiv":
            return f"GET /api/query search_query={query}{suffix}"
        if self.data_source == "semanticscholar":
            return f"GET /graph/v1/paper/search query={query}{suffix}"
        if self.data_source == "pubmed":
            return f"GET /entrez/eutils/esearch.fcgi term={query}{suffix}"
        if self.data_source == "googlescholar":
            return f"POST /scholar q={query}{suffix}"
        if self.data_source == "paperhub":
            return f"GET paper-hub shards query={query}{suffix}"
        return f"{query}{suffix}"

    def _source_response_log(self, result) -> str:
        total = result.metadata.total if result.metadata else 0
        count = len(result.hits or [])
        if self.provider:
            info = getattr(self.provider, "last_response_info", {}) or {}
            method = info.get("method", "GET")
            url = str(info.get("url", "")).split("?")[0] or self._source_label()
            status = info.get("status", "unknown")
            elapsed = info.get("elapsed_ms")
            elapsed_text = f" in {elapsed}ms" if elapsed is not None else ""
            attempts = info.get("attempts")
            attempts_text = f"; attempts={attempts}" if attempts else ""
            return f"{self._source_label()} {method} {url} -> HTTP {status} OK{elapsed_text}{attempts_text}; total={total}; returned={count}."
        return f"WoS Starter GET /documents completed; total={total}; returned={count}."

    def _llm_request_log(self, purpose: str) -> None:
        base_url = getattr(self.llm, "base_url", "")
        model = self._display_llm_model(getattr(self.llm, "model", ""))
        provider = getattr(self.config, "llm_provider", "llm")
        api_type = getattr(self.config, "llm_api_type", "")
        self._emit_log(f"LLM request started: provider={provider} api_type={api_type} model={model} purpose={purpose} endpoint={base_url}.")

    def _llm_response_log(self, purpose: str) -> None:
        info = getattr(self.llm, "last_response_info", {}) or {}
        method = info.get("method", "POST")
        url = str(info.get("url", "")).split("?")[0] or "LLM endpoint"
        status = info.get("status", "completed")
        elapsed = info.get("elapsed_ms")
        elapsed_text = f" in {elapsed}ms" if elapsed is not None else ""
        status_text = f"HTTP {status} OK" if isinstance(status, int) and status < 400 else str(status)
        self._emit_log(f"LLM {method} {url} -> {status_text}{elapsed_text}; purpose={purpose}.")
        route_label = info.get("fallback_route")
        if route_label:
            self._emit_log(f"LLM route used: {route_label}.")
        quota = info.get("quota") or {}
        quota_text = format_modelscope_quota(quota)
        if quota_text:
            self._emit(
                "quota",
                provider=getattr(self.config, "llm_provider", ""),
                model=getattr(self.llm, "model", ""),
                purpose=purpose,
                quota=quota,
            )
            self._emit_log(f"ModelScope quota updated: {quota_text}.")

    @staticmethod
    def _display_llm_model(model: str) -> str:
        return {
            "z-ai/glm-5.2": "glm-5.2",
            "minimaxai/minimax-m3": "minimax-m3",
            "moonshotai/kimi-k2.6": "kimi-k2.6",
            "nvidia/nemotron-3-ultra-550b-a55b": "nemotron-3-ultra-550b-a55b",
        }.get(model, model)

    def _preview_hits(self, hits: list, limit: int = 5) -> list:
        preview = []
        for doc in (hits or [])[:limit]:
            source = getattr(doc, "source", None)
            preview.append({
                "uid": getattr(doc, "uid", ""),
                "title": getattr(doc, "title", "") or "(no title)",
                "source": getattr(source, "source_title", "") if source else "",
                "year": getattr(source, "publish_year", None) if source else None,
                "provider": getattr(doc, "provider", self.data_source),
            })
        return preview

    def _analyze_intent(self, question: str) -> str:
        return self.intent_analysis.run(question)

    def _intent_context(self) -> str:
        if not self.search_intent:
            return ""
        question_type = str(getattr(self.search_plan, "question_type", "") or "")
        if question_type == "broad_landscape":
            query_policy = (
                "Build a high-recall candidate query around the central subject without forcing optional dimensions into AND constraints. "
            )
        else:
            query_policy = (
                "Build a balanced precision-oriented candidate query, normally with two or three mandatory concept groups: the central subject plus one or two of the most discriminating relation, object, population, method, or outcome facets. "
                "When the subject is a broad umbrella term, require two discriminating groups; when it is a stable narrow named construct, one additional group may be sufficient. "
                "Do not turn every must_have_facet into a separate AND clause. Combine closely related facets when established terminology expresses them together, and preserve remaining facets as ranking and query-portfolio evidence. "
                "Add a remaining facet in a later revision only when returned titles show that it is needed to correct topic drift. "
            )
        return (
            "\nInterpreted search intent:\n"
            f"{self.search_intent}\n"
            "Use this intent as the invariant goal when generating or revising the query. "
            "Preserve must_have_facets and required_relation, while treating optional_facets as supporting coverage rather than automatic AND constraints. "
            f"{query_policy}"
            "Avoid semantic drift across the listed boundaries. "
            "Treat boundaries as interpretation guardrails, not automatic NOT clauses; only exclusions explicitly requested by the user may become hard negative query terms.\n"
        )

    def _result_feedback(self, query: str, hits: list, total: Optional[int], adjustment: str, limit: int = 5) -> str:
        total_text = "unknown" if total is None else str(total)
        lines = [
            "\nPrevious source feedback:",
            f"- Current query: {query}",
            f"- Returned total records: {total_text}",
            f"- Adjustment needed: {adjustment}",
        ]
        preview = self._preview_hits(hits, limit=limit)
        if preview:
            lines.append(
                "- Top returned candidate titles to compare against the intent "
                "(source relevance order when available):"
            )
            for index, item in enumerate(preview, 1):
                title = re.sub(r"\s+", " ", item.get("title") or "(no title)").strip()
                source = item.get("source") or item.get("provider") or ""
                year = item.get("year")
                meta = ", ".join(str(value) for value in (source, year) if value)
                suffix = f" ({meta})" if meta else ""
                lines.append(f"  {index}. {title[:220]}{suffix}")
        else:
            lines.append("- Top returned candidate titles: none returned.")
        lines.append(
            "Before revising the query, compare these titles with the interpreted search intent. "
            "Decide whether the returned set is on-intent, off-intent, or missing a core facet. "
            "If titles are off-intent, remove or replace the drift-causing terms rather than "
            "mechanically adding more keywords. If titles are on-intent but the count is still "
            "wrong, adjust specificity or recall while preserving the invariant intent. Put the "
            "adjustment direction, title-based diagnostic, and reason in the JSON rationale field. "
            "Put only the revised source query in the JSON query field."
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _query_temperature() -> float:
        return QueryContractGuard.query_temperature()

    def _chat_query_json(self, messages: list) -> str:
        return self.query_contract.chat_json(messages)

    @staticmethod
    def _strict_query_output_instruction(output_label: str) -> str:
        return strict_query_output_instruction(output_label)

    def _generate_query(self, question: str) -> str:
        return self.query_generation._generate_query(question)

    def _broaden_query(self, question: str, current_query: str, feedback: str = "") -> str:
        return self.query_generation._broaden_query(question, current_query, feedback)

    def _narrow_query(self, question: str, current_query: str, feedback: str = "") -> str:
        return self.query_generation._narrow_query(question, current_query, feedback)

    def _generate_openalex_query(self, question: str) -> str:
        return self.query_generation._generate_openalex_query(question)

    def _generate_generic_source_query(self, question: str) -> str:
        return self.query_generation._generate_generic_source_query(question)

    def _generate_source_query(self, question: str, system_prompt: str, log_name: str, output_label: str) -> str:
        return self.query_generation._generate_source_query(question, system_prompt, log_name, output_label)

    def _revise_source_query(
        self,
        question: str,
        current_query: str,
        *,
        system_prompt: str,
        log_name: str,
        result_description: str,
        output_label: str,
        feedback: str = "",
    ) -> str:
        return self.query_generation._revise_source_query(
            question,
            current_query,
            system_prompt=system_prompt,
            log_name=log_name,
            result_description=result_description,
            output_label=output_label,
            feedback=feedback,
        )

    def _generate_crossref_query(self, question: str) -> str:
        return self.query_generation._generate_crossref_query(question)

    def _rank_results(
        self,
        question: str,
        documents: list,
        ranking_context: Optional[Dict[str, Any]] = None,
        step_id: str = "llm_reranking",
        step_title: str = "LLM reranking",
        resume_scores: Optional[list] = None,
        completed_batch_ids: Optional[list[str]] = None,
        checkpoint_records: Optional[list] = None,
        checkpoint_resume_stage: str = "pre_rank",
    ) -> list:
        request = RankingRunRequest(
            question=question,
            documents=documents,
            ranking_context=dict(ranking_context or {}),
            step_id=step_id,
            step_title=step_title,
            resume_scores=list(resume_scores or []),
            completed_batch_ids=list(completed_batch_ids or []),
            checkpoint_records=checkpoint_records,
            checkpoint_resume_stage=checkpoint_resume_stage,
        )
        return RankingPipeline(self).run(request)
    @staticmethod
    def _ranking_batch_id(step_id: str, documents: list) -> str:
        return RankingBatchScheduler.batch_id(step_id, documents, document_key)

    def _ranking_scheduler(self) -> RankingBatchScheduler:
        return RankingBatchScheduler(
            batch_size_value=getattr(self.config, "ranking_batch_size", 256),
            concurrency_value=getattr(self.config, "ranking_concurrency", 16),
        )

    def _ranking_batch_size(self, total_documents: int) -> int:
        return self._ranking_scheduler().batch_size(total_documents)

    def _ranking_concurrency(self) -> int:
        return self._ranking_scheduler().concurrency()

    def _ranking_concurrency_schedule(self, batch_count: int) -> List[int]:
        del batch_count
        return self._ranking_scheduler().concurrency_schedule()

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "429" in text or "rate_limit" in text or "too many requests" in text

    def _ranking_llm_timeout_seconds(self) -> int:
        configured = getattr(self.config, "ranking_llm_timeout_seconds", 180) or 180
        try:
            return max(10, int(configured))
        except (TypeError, ValueError):
            return 60

    def _new_ranking_llm_client(self):
        timeout_seconds = self._ranking_llm_timeout_seconds()
        if hasattr(self.llm, "fork"):
            try:
                client = self.llm.fork()
                if hasattr(client, "timeout_seconds"):
                    client.timeout_seconds = timeout_seconds
                if hasattr(client, "attempts"):
                    attempts = getattr(client, "attempts", None)
                    if isinstance(attempts, int):
                        client.attempts = 1
                return client
            except Exception:
                pass
        client_class = self.llm.__class__
        api_key = getattr(self.llm, "api_key", None)
        base_url = getattr(self.llm, "base_url", "")
        if api_key is None:
            return self.llm
        try:
            if hasattr(self.llm, "models"):
                try:
                    return client_class(api_key, list(getattr(self.llm, "models") or []), base_url, timeout_seconds=timeout_seconds)
                except TypeError:
                    return client_class(api_key, list(getattr(self.llm, "models") or []), base_url)
            model = getattr(self.llm, "model", "")
            attempts = getattr(self.llm, "attempts", None)
            if attempts is not None:
                try:
                    return client_class(api_key, model=model, base_url=base_url, attempts=attempts, timeout_seconds=timeout_seconds)
                except TypeError:
                    try:
                        return client_class(api_key, model=model, base_url=base_url, attempts=attempts)
                    except TypeError:
                        pass
            try:
                return client_class(api_key, model=model, base_url=base_url, timeout_seconds=timeout_seconds)
            except TypeError:
                try:
                    return client_class(api_key, model, base_url, timeout_seconds=timeout_seconds)
                except TypeError:
                    return client_class(api_key, model, base_url)
        except Exception:
            return self.llm

    def _ranking_scorer(self) -> RankingScorer:
        return RankingScorer(self, _describe_document)

    def _score_ranking_batch(self, question: str, documents: list, llm_client: LLMClient) -> list:
        return self._ranking_scorer().score_batch(question, documents, llm_client)

    def _score_ranking_batch_score_only(self, question: str, documents: list, llm_client: LLMClient) -> list:
        return self._ranking_scorer().score_batch(question, documents, llm_client)

    def _attach_ranking_reasons(
        self,
        question: str,
        documents: list,
        scores: list,
        llm_client: LLMClient,
    ) -> list:
        return self._ranking_scorer().attach_reasons(question, documents, scores, llm_client)

    @staticmethod
    def _should_retry_score_only_in_chunks(exc: Exception) -> bool:
        return RankingScorer.should_retry_in_chunks(exc)

    def _request_compact_ranking_scores(self, question: str, documents: list, llm_client: LLMClient) -> list:
        return self._ranking_scorer().request_compact_scores(question, documents, llm_client)

    def _request_compact_ranking_scores_in_chunks(
        self,
        question: str,
        documents: list,
        llm_client: LLMClient,
        chunk_size: int = 64,
    ) -> list:
        return self._ranking_scorer().request_scores_in_chunks(
            question,
            documents,
            llm_client,
            chunk_size=chunk_size,
        )

    def _ranking_reason_documents(self, documents: list, scores: list) -> list:
        return self._ranking_scorer().reason_documents(documents, scores)

    def _request_ranking_reasons(
        self,
        question: str,
        documents: list,
        scores: list,
        llm_client: LLMClient,
    ) -> dict[str, str]:
        return self._ranking_scorer().request_reasons(question, documents, scores, llm_client)
    @staticmethod
    def _json_object(raw: str) -> dict:
        return RankingOutputCodec.json_object(raw)

    def _ranking_output_codec(self) -> RankingOutputCodec:
        return RankingOutputCodec(self._ranking_document_identity)

    def _parse_compact_ranking_scores(self, raw: str, documents: list) -> list:
        return self._ranking_output_codec().parse_scores(raw, documents)

    def _parse_ranking_reasons(self, raw: str, identities: list[str]) -> dict[str, str]:
        return self._ranking_output_codec().parse_reasons(raw, identities)

    @staticmethod
    def _ranking_document_identity(document: Any) -> str:
        return str(getattr(document, "uid", "") or document_key(document) or "").strip()

    def _match_ranking_scores_to_documents(self, documents: list, scores: list) -> Tuple[list, list]:
        return self._ranking_output_codec().match_scores(documents, scores)

    def _ranking_plan_context(self) -> str:
        if self.search_plan is None:
            return "{}"
        plan = self.search_plan
        payload = {
            "intent": plan.intent,
            "question_type": plan.question_type,
            "core_concepts": list(plan.core_concepts),
            "must_have_facets": list(plan.must_have_facets),
            "optional_facets": list(plan.optional_facets),
            "required_relation": plan.required_relation,
            "likely_synonyms": list(plan.likely_synonyms),
            "adjacent_concepts": list(plan.adjacent_concepts),
            "boundaries": list(plan.boundaries),
            "ambiguities": list(plan.ambiguities),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _rank_from_scores(self, documents: list, scores: list) -> list:
        valid_scores, missing_documents = self._match_ranking_scores_to_documents(documents, scores)
        identity_to_doc = {
            self._ranking_document_identity(document): document
            for document in documents
            if self._ranking_document_identity(document)
        }

        ranked = []
        for entry in valid_scores:
            uid = entry.get("uid", "")
            doc = identity_to_doc.get(uid)
            if doc is None:
                continue

            ranked.append({
                "document": doc,
                "score": entry.get("score", 0),
                "reasoning": entry.get("reasoning", ""),
                **self._retrieval_entry_metadata(doc),
            })

        for doc in missing_documents:
            ranked.append({"document": doc, "score": 0, "reasoning": "", **self._retrieval_entry_metadata(doc)})

        return sorted(ranked, key=lambda item: float(item.get("score") or 0), reverse=True)

    def _retrieval_entry_metadata(self, doc) -> Dict[str, Any]:
        key = document_key(doc)
        if not key:
            return {}
        return dict(self.retrieval_metadata_by_key.get(key, {}))

    @staticmethod
    def _validated_ranking_scores(value: Any) -> list[dict[str, Any]]:
        return RankingOutputCodec.validated_scores(value)

    def _enrich_with_abstracts(self, ranked: list) -> list:
        for entry in ranked:
            doc = entry["document"]
            if not doc:
                continue
            identifiers = getattr(doc, "identifiers", None)
            if identifiers:
                doi = getattr(identifiers, "doi", None)
                if doi:
                    abstract = self.abstract_fetcher.fetch(doi)
                    if abstract:
                        entry["abstract"] = abstract
        return ranked


LiteratureSearchAgent = PaperSeekAgent
WosSearchAgent = PaperSeekAgent
