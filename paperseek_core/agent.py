
import re
import json
import hashlib
import inspect
import math
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from itertools import count
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple
import requests

from paperseek_core.client import Configuration, ApiClient, DocumentsApi
from paperseek_core.client import ApiException
from paperseek_core.llm import LLMClient, LLMError, format_modelscope_quota
from paperseek_core.prompts import (
    SYSTEM_SEARCH_INTENT_ANALYSIS,
    SYSTEM_ARXIV_QUERY_GENERATION,
    SYSTEM_ARXIV_QUERY_BROADEN,
    SYSTEM_ARXIV_QUERY_NARROW,
    SYSTEM_PAPERHUB_QUERY_GENERATION,
    SYSTEM_PAPERHUB_QUERY_BROADEN,
    SYSTEM_PAPERHUB_QUERY_NARROW,
    SYSTEM_PUBMED_QUERY_GENERATION,
    SYSTEM_PUBMED_QUERY_BROADEN,
    SYSTEM_PUBMED_QUERY_NARROW,
    SYSTEM_GOOGLE_SCHOLAR_QUERY_GENERATION,
    SYSTEM_GOOGLE_SCHOLAR_QUERY_BROADEN,
    SYSTEM_GOOGLE_SCHOLAR_QUERY_NARROW,
    SYSTEM_QUERY_GENERATION,
    SYSTEM_QUERY_BROADEN,
    SYSTEM_QUERY_NARROW,
    SYSTEM_OPENALEX_QUERY_GENERATION,
    SYSTEM_OPENALEX_QUERY_BROADEN,
    SYSTEM_OPENALEX_QUERY_NARROW,
    SYSTEM_CROSSREF_QUERY_GENERATION,
    SYSTEM_CROSSREF_QUERY_BROADEN,
    SYSTEM_CROSSREF_QUERY_NARROW,
    SYSTEM_GENERIC_SOURCE_QUERY_GENERATION,
    SYSTEM_GENERIC_SOURCE_QUERY_BROADEN,
    SYSTEM_GENERIC_SOURCE_QUERY_NARROW,
    SYSTEM_RESULT_RANKING,
    SYSTEM_SEMANTIC_SCHOLAR_QUERY_GENERATION,
    SYSTEM_SEMANTIC_SCHOLAR_QUERY_BROADEN,
    SYSTEM_SEMANTIC_SCHOLAR_QUERY_NARROW,
)
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
    document_alias_keys,
    document_key,
    document_text,
    fuse_candidates_rrf,
)
from paperseek_core.harness import (
    ACTION_BROADEN,
    ACTION_NARROW,
    CITATION_RETRY_REDUCED,
    RECOVERY_BROADEN_QUERY,
    RECOVERY_REPAIR_QUERY,
    RECOVERY_SIMPLIFY_QUERY,
    RANKING_RETRY_LOWER_CONCURRENCY,
    RANKING_RETRY_SAME_TIER,
    CandidateCitationPath,
    CandidateEvidence,
    CandidateLifecycleEvent,
    FrontierBudget,
    FrontierOutcome,
    QueryLoopDecision,
    QueryLoopSnapshot,
    QueryPortfolioExecution,
    SearchCheckpoint,
    SearchRunState,
    SearchLoopController,
    SelectorBatch,
    SelectorDecision,
    RankingScoreEntry,
    dedupe_repeated_top_level_conjunctions,
    extract_json_object_text as _harness_extract_json_object_text,
    looks_truncated_or_malformed_query as _harness_looks_truncated_or_malformed_query,
    query_response_from_json as _harness_query_response_from_json,
    strip_llm_fence as _harness_strip_llm_fence,
    validate_source_query,
)
from paperseek_core.candidate_selector import CandidateSelector
from paperseek_core.crawler import CrawlerController
from paperseek_core.frontier import FrontierScheduler
from paperseek_core.tool_executor import ToolExecution, ToolExecutor
from paperseek_core.harness.pydantic_ai_adapter import (
    PydanticAIAdapterUnavailable,
    pydantic_ai_query_retry_enabled,
    run_query_proposal_agent,
)
from paperseek_core.sources.providers import (
    ArxivProvider,
    CitationSeedPlan,
    CrossrefProvider,
    GoogleScholarSerperProvider,
    OpenAlexProvider,
    PaperAuthor,
    PaperCitation,
    PaperHubProvider,
    PaperIdentifiers,
    PaperKeywords,
    PaperLinks,
    PaperNames,
    PaperRecord,
    PaperSource,
    ProviderError,
    ProviderSearchResult,
    PubMedProvider,
    SearchMetadata,
    SemanticScholarProvider,
)
from paperseek_core.sources.metadata import supported_source_ids
from paperseek_core.planning import SearchPlan, fallback_search_plan, parse_search_plan
from paperseek_core.query_compiler import supports_query_portfolio
from paperseek_core.query_view_selector import select_query_views
from paperseek_core.checkpoints import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointError,
    paper_records_from_checkpoint,
    paper_records_to_checkpoint,
    scrub_checkpoint_value,
)


_EXTERNAL_API_KEY_COUNTER_LOCK = Lock()
_EXTERNAL_API_KEY_COUNTERS = {}
_SERIALIZED_CANDIDATE_LEDGER_LIMIT = 512


class EmptyRankingBatchError(RuntimeError):
    """Raised when an LLM ranking batch returns no usable scores."""


class SearchCancelled(RuntimeError):
    """Raised when a caller requests cooperative cancellation of a search run."""


def _split_external_api_keys(api_key: str) -> List[str]:
    keys = [item.strip() for item in re.split(r"[\s,;]+", api_key or "") if item.strip()]
    return list(dict.fromkeys(keys))


def _next_external_api_key(keys: List[str]) -> str:
    if not keys:
        return ""
    if len(keys) == 1:
        return keys[0]
    pool_key = "\0".join(keys)
    with _EXTERNAL_API_KEY_COUNTER_LOCK:
        counter = _EXTERNAL_API_KEY_COUNTERS.setdefault(pool_key, count())
        index = next(counter)
    return keys[index % len(keys)]


def _external_api_key_attempts(api_key: str, max_attempts: int = 3) -> List[str]:
    keys = _split_external_api_keys(api_key)
    if not keys:
        return [""]
    attempts = min(max(1, int(max_attempts or 1)), len(keys))
    return [_next_external_api_key(keys) for _ in range(attempts)]


def _retryable_external_status(status_code: int) -> bool:
    return status_code in (401, 403, 408, 409, 425, 429) or status_code >= 500


def _extract_json_object_text(text: str) -> str:
    return _harness_extract_json_object_text(text)


def _query_response_from_json(text: str) -> Tuple[str, str]:
    return _harness_query_response_from_json(text)


def _trim_boolean_edges(query: str) -> str:
    query = re.sub(r"^\s*(?:AND|OR|NOT)\b\s*", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+\b(?:AND|OR|NOT)\s*$", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\(\s*(?:AND|OR)\s+", "(", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+(?:AND|OR)\s*\)", ")", query, flags=re.IGNORECASE)
    return query.strip()


def _looks_truncated_or_malformed_query(query: str) -> bool:
    return _harness_looks_truncated_or_malformed_query(query)


def _sanitize_openalex_query(query: str) -> str:
    """Keep OpenAlex search= queries inside the syntax accepted by default search."""
    original = (query or "").strip()
    if not original:
        return ""
    cleaned = (
        original.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )
    cleaned = re.sub(r"^\s*(?:search|q)\s*=\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip().strip("`")
    cleaned = re.sub(r"\b(?:filter|per-page|page|sort|select|fields)\s*=[^\s]+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"([A-Za-z0-9])[*?]+\b", r"\1", cleaned)
    cleaned = cleaned.replace("*", "").replace("?", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([)])", r"\1", cleaned)
    cleaned = re.sub(r"([(])\s+", r"\1", cleaned)
    cleaned = _trim_boolean_edges(cleaned)
    cleaned = dedupe_repeated_top_level_conjunctions(cleaned)
    return cleaned or original


def _sanitize_semantic_scholar_query(query: str) -> str:
    """Normalize terms for /paper/search, which does not match hyphenated queries reliably."""

    cleaned = str(query or "").strip()
    cleaned = re.sub(r"(?<=\w)[\-\u2010-\u2015](?=\w)", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _provider_error_text(exc: ProviderError) -> str:
    parts = [str(exc)]
    if exc.status:
        parts.append(f"HTTP {exc.status}")
    if exc.body:
        parts.append(str(exc.body))
    return " ".join(parts)


def _queries_equivalent(left: str, right: str) -> bool:
    return re.sub(r"\s+", " ", (left or "").strip()).lower() == re.sub(r"\s+", " ", (right or "").strip()).lower()


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


def _is_source_availability_error(value: object) -> bool:
    text = str(value or "").casefold()
    return any(
        marker in text
        for marker in (
            "http 401",
            "http 403",
            "http 408",
            "http 425",
            "http 429",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "network error",
            "timed out",
            "timeout",
            "unavailable",
            "connectionerror",
        )
    )


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


def _citation_count(doc) -> int:
    total = 0
    for citation in getattr(doc, "citations", []) or []:
        total += getattr(citation, "count", 0) or 0
    return total


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
        return ""
    if isinstance(value, dict):
        for key in ("value", "name", "displayName", "display_name", "title"):
            text = _first_text(value.get(key))
            if text:
                return text
        return ""
    return str(value or "").strip()


def _wos_author(item: Any) -> PaperAuthor:
    if isinstance(item, dict):
        return PaperAuthor(
            display_name=_first_text(item.get("displayName") or item.get("display_name") or item.get("name")),
            wos_standard=_first_text(item.get("wosStandard") or item.get("wos_standard")),
            researcher_id=_first_text(item.get("researcherId") or item.get("researcher_id")),
        )
    return PaperAuthor(display_name=_first_text(item))


def _wos_record_from_json(item: dict[str, Any]) -> PaperRecord:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    names = item.get("names") if isinstance(item.get("names"), dict) else {}
    identifiers = item.get("identifiers") if isinstance(item.get("identifiers"), dict) else {}
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    keywords = item.get("keywords") if isinstance(item.get("keywords"), dict) else {}
    citations = []
    for citation in _as_list(item.get("citations")):
        if isinstance(citation, dict):
            citations.append(PaperCitation(db=_first_text(citation.get("db")), count=_to_int(citation.get("count")) or 0))

    return PaperRecord(
        uid=_first_text(item.get("uid") or item.get("id") or identifiers.get("wosuid") or item.get("title")),
        title=_first_text(item.get("title")),
        types=[_first_text(value) for value in _as_list(item.get("types")) if _first_text(value)],
        source_types=[_first_text(value) for value in _as_list(item.get("sourceTypes")) if _first_text(value)],
        source=PaperSource(
            source_title=_first_text(source.get("sourceTitle") or source.get("source_title")),
            publish_year=_to_int(source.get("publishYear") or source.get("publish_year")),
            publish_month=_first_text(source.get("publishMonth") or source.get("publish_month")),
            volume=_first_text(source.get("volume")),
            issue=_first_text(source.get("issue")),
        ),
        names=PaperNames(authors=[_wos_author(author) for author in _as_list(names.get("authors"))]),
        links=PaperLinks(
            record=_first_text(links.get("record")),
            citing_articles=_first_text(links.get("citingArticles") or links.get("citing_articles")),
            references=_first_text(links.get("references")),
            related=_first_text(links.get("related")),
            landing_page=_first_text(links.get("record") or links.get("landingPage") or links.get("landing_page")),
        ),
        citations=citations,
        identifiers=PaperIdentifiers(
            doi=_first_text(identifiers.get("doi")),
            issn=_first_text(identifiers.get("issn")),
            eissn=_first_text(identifiers.get("eissn")),
            isbn=_first_text(identifiers.get("isbn")),
            eisbn=_first_text(identifiers.get("eisbn")),
            pmid=_first_text(identifiers.get("pmid")),
        ),
        keywords=PaperKeywords(author_keywords=[_first_text(value) for value in _as_list(keywords.get("authorKeywords") or keywords.get("author_keywords")) if _first_text(value)]),
        provider="wos",
        raw=item,
    )


def _wos_result_from_json(payload: dict[str, Any], limit: int) -> ProviderSearchResult:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    hits = payload.get("hits") if isinstance(payload.get("hits"), list) else []
    return ProviderSearchResult(
        metadata=SearchMetadata(
            total=_to_int(metadata.get("total")) or 0,
            page=_to_int(metadata.get("page")) or 1,
            limit=_to_int(metadata.get("limit")) or limit,
        ),
        hits=[_wos_record_from_json(item) for item in hits if isinstance(item, dict)],
    )


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
        self.search_loop = SearchLoopController.from_config(config)
        self.search_loop_metadata = self.search_loop.summary()
        self.search_run_state: Optional[SearchRunState] = None
        self._candidate_selector_instance: Optional[CandidateSelector] = None
        self.last_query_selector_feedback: dict[str, Any] = {}
        self.last_query_selector_batch = SelectorBatch()
        self.cancel_check: Optional[Callable[[], bool]] = None
        self.checkpoint_handler: Optional[Callable[[dict], None]] = None
        self.resume_checkpoint: Optional[SearchCheckpoint] = None
        self.checkpoint_sequence = 0
        self.run_question = ""
        self.iteration_history: list = []
        self.current_query = ""
        self.last_total = 0
        self.last_iteration = 0

        self.documents_api = None
        self.provider = None
        if self.data_source == "openalex":
            self.provider = OpenAlexProvider(
                api_key=getattr(config, "openalex_api_key", ""),
                email=getattr(config, "openalex_email", ""),
            )
        elif self.data_source == "crossref":
            self.provider = CrossrefProvider(email=getattr(config, "crossref_email", ""))
        elif self.data_source == "arxiv":
            self.provider = ArxivProvider()
        elif self.data_source == "semanticscholar":
            self.provider = SemanticScholarProvider(api_key=getattr(config, "semantic_scholar_api_key", ""))
        elif self.data_source == "pubmed":
            self.provider = PubMedProvider(
                api_key=getattr(config, "pubmed_api_key", ""),
                email=getattr(config, "pubmed_email", ""),
                tool=getattr(config, "pubmed_tool", "paperseek"),
            )
        elif self.data_source == "googlescholar":
            self.provider = GoogleScholarSerperProvider(api_key=getattr(config, "serper_api_key", ""))
        elif self.data_source == "paperhub":
            self.provider = PaperHubProvider()
        else:
            wos_cfg = Configuration(api_key={"ClarivateApiKeyAuth": config.wos_api_key})
            self.documents_api = DocumentsApi(ApiClient(configuration=wos_cfg))
        self._source_providers: Dict[str, Any] = {}
        if self.provider is not None:
            self._source_providers[self.data_source] = self.provider

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
        if not payload:
            return None
        try:
            checkpoint = SearchCheckpoint.model_validate(payload)
        except Exception as exc:
            raise CheckpointError(f"checkpoint_corrupt: {exc}") from exc
        if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointError(
                f"checkpoint_corrupt: unsupported schema version {checkpoint.schema_version}"
            )
        if checkpoint.question.strip() != question.strip():
            raise CheckpointError("checkpoint_corrupt: research question does not match the resumed request")
        if checkpoint.source != self.data_source:
            raise CheckpointError("checkpoint_corrupt: data source does not match the resumed request")
        return checkpoint

    def _restore_checkpoint_state(self, checkpoint: SearchCheckpoint) -> None:
        self._candidate_selector_instance = None
        self.last_query_selector_feedback = {}
        self.last_query_selector_batch = SelectorBatch()
        self.search_intent = checkpoint.search_intent
        self.search_plan = SearchPlan.model_validate(checkpoint.search_plan) if checkpoint.search_plan else None
        self.query_view_selection = list(checkpoint.query_view_selection)
        self.query_portfolio = list(checkpoint.query_portfolio)
        self.query_iteration_results = []
        for item in checkpoint.query_iteration_results:
            if not isinstance(item, dict):
                continue
            try:
                records = paper_records_from_checkpoint(item.get("records") or [])
            except Exception:
                continue
            self.query_iteration_results.append(
                {
                    "iteration": int(item.get("iteration") or 0),
                    "query": str(item.get("query") or ""),
                    "total": int(item.get("total") or 0),
                    "records": records,
                }
            )
        self.search_run_state = (
            SearchRunState.model_validate(checkpoint.search_state)
            if checkpoint.search_state
            else SearchRunState(
                question=checkpoint.question,
                source=checkpoint.source,
                current_query=checkpoint.current_query,
                search_plan=checkpoint.search_plan,
            )
        )
        self.current_query = checkpoint.current_query
        self.last_total = int(checkpoint.total or 0)
        self.last_iteration = int(checkpoint.iteration or 0)
        self.iteration_history = list(checkpoint.history)
        self.citation_map = dict(checkpoint.citation_map or self._empty_citation_map())
        self.ranking_steps = {
            str(step.get("id") or step.get("step_id") or index): dict(step)
            for index, step in enumerate(checkpoint.ranking_steps)
            if isinstance(step, dict)
        }

    def _save_checkpoint(
        self,
        stage: str,
        *,
        records: Optional[list] = None,
        ranking_scores: Optional[list] = None,
        completed_batch_ids: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        if not self.checkpoint_handler:
            return
        self.checkpoint_sequence += 1
        checkpoint = SearchCheckpoint(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            sequence=self.checkpoint_sequence,
            stage=stage,
            question=self.run_question,
            source=self.data_source,
            current_query=self.current_query,
            total=int(self.last_total or 0),
            iteration=int(self.last_iteration or 0),
            search_intent=self.search_intent,
            search_plan=self.search_plan.model_dump() if self.search_plan else {},
            query_view_selection=list(self.query_view_selection),
            query_portfolio=list(self.query_portfolio),
            history=list(self.iteration_history or []),
            search_state=self._search_state_payload(),
            records=paper_records_to_checkpoint(records or []),
            query_iteration_results=[
                {
                    "iteration": int(item.get("iteration") or 0),
                    "query": str(item.get("query") or ""),
                    "total": int(item.get("total") or 0),
                    "records": paper_records_to_checkpoint(item.get("records") or []),
                }
                for item in self.query_iteration_results
                if isinstance(item, dict) and item.get("records")
            ],
            citation_map=dict(self.citation_map or {}),
            ranking_steps=list(self.ranking_steps.values()),
            ranking_scores=list(ranking_scores or []),
            completed_batch_ids=list(completed_batch_ids or []),
            metadata=dict(metadata or {}),
        )
        try:
            self.checkpoint_handler(scrub_checkpoint_value(checkpoint.model_dump()))
        except SearchCancelled:
            raise
        except Exception as exc:
            self._emit_log(f"Checkpoint persistence failed; search will continue without this snapshot: {exc}")
        self._check_cancelled()

    def _search(self, question: str, verbose: bool = False) -> dict:
        self.run_question = question
        self.query_portfolio_lane_results = {}
        self.query_iteration_results = []
        checkpoint = self.resume_checkpoint
        if checkpoint:
            self._restore_checkpoint_state(checkpoint)
            history = list(checkpoint.history)
            self.iteration_history = history
            query = checkpoint.current_query
            iteration = int(checkpoint.iteration or 0)
            total = int(checkpoint.total or 0)
            restored_records = paper_records_from_checkpoint(checkpoint.records)
            phase = str((checkpoint.metadata or {}).get("phase") or "")

            if checkpoint.stage in {"candidate_merge", "citation_layer", "pre_rank", "ranking_batch", "ranking_complete"}:
                return self._complete_search_pipeline(
                    question,
                    query,
                    total,
                    restored_records,
                    history,
                    iteration,
                    checkpoint=checkpoint,
                )
            if checkpoint.stage == "query_execution" and phase in {"query_primary_complete", "query_portfolio"}:
                hits = restored_records
                if phase == "query_portfolio":
                    self.query_portfolio_lane_results["checkpoint"] = list(hits)
                hits = self._execute_query_portfolio(question, query, hits, history)
                self._save_checkpoint(
                    "query_execution",
                    records=hits,
                    metadata={"phase": "query_complete", "resume_from_stage": "query_execution"},
                )
                return self._complete_search_pipeline(question, query, total, hits, history, iteration)
            if checkpoint.stage == "query_execution" and phase == "query_complete":
                return self._complete_search_pipeline(
                    question,
                    query,
                    total,
                    restored_records,
                    history,
                    iteration,
                )

            hits = []
            fallback_query = str((checkpoint.metadata or {}).get("fallback_query") or "")
            fallback_total = int((checkpoint.metadata or {}).get("fallback_total") or 0)
            fallback_hits = restored_records
            self._emit_log(
                f"Resuming query loop from durable checkpoint: stage={checkpoint.stage}; "
                f"phase={phase or 'query_ready'}; next_iteration={iteration + 1}."
            )
        else:
            self._candidate_selector_instance = None
            self.last_query_selector_feedback = {}
            self.last_query_selector_batch = SelectorBatch()
            self.iteration_history = []
            self.current_query = ""
            self.last_total = 0
            self.last_iteration = 0
            self.search_plan = None
            self.query_view_selection = []
            self.query_portfolio = []
            self.search_intent = self._analyze_intent(question)
            if self.search_intent:
                self._emit_stage("query", "processing", source=self.data_source, intent=self.search_intent)
            query = self._source_safe_query(self._apply_discipline_filter(self._generate_query(question)))
            self.search_run_state = SearchRunState(
                question=question,
                source=self.data_source,
                current_query=query,
                search_plan=self.search_plan.model_dump() if self.search_plan else {},
            )
            self.current_query = query
            history = []
            self.iteration_history = history
            iteration = 0
            total = 0
            hits = []
            fallback_query = ""
            fallback_total = 0
            fallback_hits: list = []
            self._save_checkpoint(
                "search_plan",
                metadata={"phase": "query_ready", "resume_from_stage": "search_plan"},
            )

        configured_iterations = max(1, int(getattr(self.config, "max_iterations", 5) or 5))
        adaptive_max_iterations = self._adaptive_max_iterations(configured_iterations)
        while iteration < adaptive_max_iterations:
            self._check_cancelled()
            iteration += 1
            self.last_iteration = iteration
            if self.data_source == "wos":
                safe_query = _make_starter_safe_query(query)
                sanitize_message = "Converted the generated query to the stable WoS Starter subset before calling the API."
            else:
                safe_query = self._source_safe_query(query)
                sanitize_message = f"Sanitized the generated {self._source_label()} query before calling the API."
            if safe_query != query:
                row = {
                    "iteration": iteration,
                    "query": query,
                    "total": None,
                    "action": "sanitize",
                    "next_query": safe_query,
                    "message": sanitize_message,
                }
                history.append(row)
                self._emit_stage("search", "processing", history=history, final_query=safe_query)
                query = safe_query
                self._set_search_state_query(query)

            if verbose:
                print(f"[Iteration {iteration}] Query: {query}", file=sys.stderr)

            server_error_variants = _server_error_query_variants(query)
            provider_repair_attempts = set()
            preflight_repair_attempts = 0
            try:
                while True:
                    validation = self._preflight_query(query)
                    if not validation.ok:
                        if preflight_repair_attempts < 2:
                            preflight_repair_attempts += 1
                            repaired_query = self._retry_malformed_source_query(
                                question,
                                query,
                                feedback="",
                                system_prompt=self._syntax_repair_prompt(),
                                log_name=f"{self.data_source}_query_preflight",
                                output_label=f"{self._source_label()} query string",
                                operation="preflight validation",
                                issue=validation.issue,
                            )
                            if repaired_query and not _queries_equivalent(query, repaired_query):
                                row = {
                                    "iteration": iteration,
                                    "query": query,
                                    "total": None,
                                    "action": "repair",
                                    "next_query": repaired_query,
                                    "message": f"{self._source_label()} query failed harness preflight; repaired before calling the source API.",
                                    "rationale": self._consume_query_audit(),
                                }
                                history.append(row)
                                self._emit_stage("search", "processing", history=history, final_query=repaired_query)
                                self._emit_log(f"{self._source_label()} query repaired by harness preflight; retrying validation.")
                                query = repaired_query
                                self._set_search_state_query(query)
                                continue
                        raise LLMError(f"{self._source_label()} query failed harness preflight: {validation.issue}")
                    try:
                        self._check_cancelled()
                        self._emit_stage(
                            "search",
                            "processing",
                            iteration=iteration,
                            query=query,
                            history=history,
                            final_query=query,
                        )
                        self._emit_log(f"{self._source_label()} request started: {self._source_request_label(query)}")
                        result, search_error = self._harness_source_search(query)
                        self._check_cancelled()
                        if search_error is not None:
                            raise search_error
                        self._emit_log(self._source_response_log(result))
                        break
                    except ProviderError as e:
                        repair_key = (query, e.status, str(e)[:200])
                        repair_attempts = len(provider_repair_attempts)
                        if repair_key in provider_repair_attempts:
                            repair_attempts = 2
                        recovery = self._recover_source_error(
                            e,
                            query=query,
                            repair_attempts=repair_attempts,
                            max_repair_attempts=2,
                        )
                        if recovery.action == RECOVERY_REPAIR_QUERY and repair_key not in provider_repair_attempts:
                            provider_repair_attempts.add(repair_key)
                            repaired_query = self._repair_query_after_provider_error(question, query, e)
                            if repaired_query and not _queries_equivalent(query, repaired_query):
                                row = {
                                    "iteration": iteration,
                                    "query": query,
                                    "total": None,
                                    "action": "repair",
                                    "next_query": repaired_query,
                                    "message": f"{self._source_label()} rejected the query; repaired the source syntax and retried.",
                                }
                                history.append(row)
                                self._emit_stage("search", "processing", history=history, final_query=repaired_query)
                                self._emit_log(f"{self._source_label()} query repaired after API error; retrying request.")
                                query = repaired_query
                                self._set_search_state_query(query)
                                continue
                        raise
                    except ApiException as e:
                        recovery = self._recover_source_error(
                            e,
                            query=query,
                            repair_attempts=0,
                            max_repair_attempts=1,
                            has_server_error_variant=bool(server_error_variants),
                        )
                        if recovery.action == RECOVERY_SIMPLIFY_QUERY and server_error_variants:
                            repaired_query = server_error_variants.pop(0)
                            if repaired_query != query:
                                action = "repair" if "NEAR/" in repaired_query.upper() else "simplify"
                                row = {
                                    "iteration": iteration,
                                    "query": query,
                                    "total": None,
                                    "action": action,
                                    "next_query": repaired_query,
                                    "message": "WoS returned HTTP 512; rewrote the query into a simpler supported form and retried.",
                                }
                                history.append(row)
                                self._emit_stage("search", "processing", history=history, final_query=repaired_query)
                                query = repaired_query
                                self._set_search_state_query(query)
                                if verbose:
                                    print(f"[Iteration {iteration}] Rewrote query after 512: {query}", file=sys.stderr)
                                continue
                        raise
            except ApiException as e:
                if e.status == 400 and "query" in str(e.body).lower():
                    recovery = self._recover_source_error(
                        e,
                        query=query,
                        repair_attempts=0,
                        max_repair_attempts=1,
                        allow_broaden_query=True,
                    )
                    if recovery.action != RECOVERY_BROADEN_QUERY:
                        e.query = query
                        e.iteration = iteration
                        raise
                    current_query = query
                    feedback = self._result_feedback(query, [], None, "syntax rejected")
                    revised_query = self._apply_discipline_filter(self._broaden_query(question, query, feedback))
                    query_audit = self._consume_query_audit()
                    if _queries_equivalent(current_query, revised_query):
                        e.query = query
                        e.iteration = iteration
                        raise
                    query = revised_query
                    row = {
                        "iteration": iteration,
                        "query": current_query,
                        "total": None,
                        "action": "broaden",
                        "next_query": query,
                        "message": "WoS rejected the query syntax; generated a broader replacement query.",
                        "rationale": query_audit,
                    }
                    history.append(row)
                    self._emit_stage("search", "processing", history=history, final_query=query)
                    self._set_search_state_query(query)
                    continue
                e.query = query
                e.iteration = iteration
                raise

            total = result.metadata.total if result.metadata and result.metadata.total is not None else 0
            hits = result.hits or []
            self._record_query_iteration(iteration, query, total, hits)
            self.last_total = int(total or 0)
            if total and hits:
                pool_max = self._retrieval_pool_max()
                if not fallback_hits or int(total or 0) <= pool_max or int(fallback_total or 0) > pool_max:
                    fallback_query = query
                    fallback_total = int(total or 0)
                    fallback_hits = list(hits or [])

            if verbose:
                print(f"[Iteration {iteration}] Total results: {total}", file=sys.stderr)

            selector_batch = self._query_iteration_selector_feedback(question, query, hits, iteration)
            decision = self._query_loop_decision(
                query,
                hits,
                total,
                iteration,
                configured_iterations,
                adaptive_max_iterations,
                history,
            )

            if decision.action == ACTION_BROADEN:
                current_query = query
                feedback = self._result_feedback(query, hits, total, decision.adjustment or "too few or zero records")
                revised_query = self._apply_discipline_filter(self._broaden_query(question, query, feedback))
                query_audit = self._consume_query_audit()
                if _queries_equivalent(current_query, revised_query):
                    self._complete_after_unchanged_revision(history, iteration, current_query, total, hits, "broader")
                    self._save_checkpoint(
                        "query_execution",
                        records=hits,
                        metadata={"phase": "query_primary_complete"},
                    )
                    break
                query = revised_query
                row = {
                    "iteration": iteration,
                    "query": current_query,
                    "total": total,
                    "action": "broaden",
                    "next_query": query,
                    "message": decision.message,
                    "rationale": query_audit,
                    "controller_reason": decision.reason,
                }
                history.append(row)
                self._set_search_state_query(query)
                self._emit_stage("search", "processing", total=total, history=history, final_query=query, preview=self._preview_hits(hits))
                self._save_checkpoint(
                    "query_execution",
                    records=fallback_hits,
                    metadata={
                        "phase": "next_query",
                        "fallback_query": fallback_query,
                        "fallback_total": fallback_total,
                    },
                )
                continue
            elif decision.action == ACTION_NARROW:
                current_query = query
                feedback = self._result_feedback(query, hits, total, decision.adjustment)
                revised_query = self._apply_discipline_filter(self._narrow_query(question, query, feedback))
                query_audit = self._consume_query_audit()
                if _queries_equivalent(current_query, revised_query):
                    if total > self._retrieval_pool_max() and iteration < adaptive_max_iterations:
                        retry_feedback = (
                            f"{feedback}\n"
                            "The previous narrowing response did not change the query. "
                            "Return a different valid query that adds a missing central facet, stricter phrase, method, domain, population, or publication-type term from the interpreted intent. "
                            "Do not remove existing core intent terms."
                        )
                        revised_query = self._apply_discipline_filter(self._narrow_query(question, current_query, retry_feedback))
                        query_audit = self._consume_query_audit()
                    if _queries_equivalent(current_query, revised_query):
                        self._complete_after_unchanged_revision(history, iteration, current_query, total, hits, "narrower")
                        self._save_checkpoint(
                            "query_execution",
                            records=hits,
                            metadata={"phase": "query_primary_complete"},
                        )
                        break
                query = revised_query
                row = {
                    "iteration": iteration,
                    "query": current_query,
                    "total": total,
                    "action": "narrow",
                    "next_query": query,
                    "message": decision.message,
                    "rationale": query_audit,
                    "controller_reason": decision.reason,
                }
                history.append(row)
                self._set_search_state_query(query)
                self._emit_stage("search", "processing", total=total, history=history, final_query=query, preview=self._preview_hits(hits))
                self._save_checkpoint(
                    "query_execution",
                    records=fallback_hits,
                    metadata={
                        "phase": "next_query",
                        "fallback_query": fallback_query,
                        "fallback_total": fallback_total,
                    },
                )
                continue
            else:
                row = {
                    "iteration": iteration,
                    "query": query,
                    "total": total,
                    "action": decision.action,
                    "next_query": None,
                    "message": decision.message,
                    "controller_reason": decision.reason,
                }
                history.append(row)
                self._save_checkpoint(
                    "query_execution",
                    records=hits,
                    metadata={"phase": "query_primary_complete"},
                )
                self._emit_stage(
                    "search",
                    "complete",
                    total=total,
                    history=history,
                    final_query=query,
                    preview=self._preview_hits(hits),
                )
                break

        if iteration > configured_iterations or (not hits and total == 0):
            if verbose:
                print(f"[Done] {total} total results after {iteration} iterations.", file=sys.stderr)

        if total == 0 and not hits and fallback_hits:
            zero_query = query
            query = fallback_query
            total = fallback_total
            hits = fallback_hits
            self.last_total = int(total or 0)
            self._set_search_state_query(query)
            row = {
                "iteration": iteration,
                "query": zero_query,
                "total": 0,
                "action": "fallback",
                "next_query": query,
                "message": (
                    "The latest query returned 0 records; fell back to the most recent non-empty "
                    "candidate pool for downstream retrieval and ranking."
                ),
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

        hits = self._execute_query_portfolio(question, query, hits, history)
        if total == 0 and hits:
            total = len(hits)
            self.last_total = total
        self._set_search_state_query(query)
        self._save_checkpoint(
            "query_execution",
            records=hits,
            metadata={"phase": "query_complete", "resume_from_stage": "query_execution"},
        )

        return self._complete_search_pipeline(question, query, total, hits, history, iteration)

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
        checkpoint_records = paper_records_from_checkpoint(checkpoint.records) if checkpoint else []
        checkpoint_stage = checkpoint.stage if checkpoint else ""
        resume_stage = str((checkpoint.metadata or {}).get("resume_from_stage") or checkpoint_stage) if checkpoint else ""
        checkpoint_step = str((checkpoint.metadata or {}).get("step_id") or "") if checkpoint else ""
        if checkpoint_stage == "ranking_batch" and checkpoint_step == "llm_reranking":
            resume_stage = "ranking_batch"

        if checkpoint:
            self._emit_log(
                f"Resuming search from durable checkpoint: stage={checkpoint_stage}; "
                f"resume_stage={resume_stage}; sequence={checkpoint.sequence}."
            )

        self.ranking_steps = dict(self.ranking_steps or {})
        ranking_context = {
            "source": self.data_source,
            "total": total,
            "history": history,
            "final_query": query,
            "preview": self._preview_hits(hits),
        }
        self.ranking_context = dict(ranking_context)
        self._check_cancelled()
        self._emit_stage("ranking", "processing", candidate_count=len(hits or []), **ranking_context)
        if resume_stage in {"candidate_merge", "candidate_feedback", "citation_layer", "pre_rank", "ranking_batch", "ranking_complete"}:
            retrieved = checkpoint_records
        elif total == 0 and not hits:
            retrieved = []
        else:
            retrieved = self._retrieve_candidates(question, query, hits)
            self._save_checkpoint(
                "candidate_merge",
                records=retrieved,
                metadata={"resume_from_stage": "candidate_merge"},
            )
        self._check_cancelled()
        if resume_stage in {"citation_layer", "pre_rank", "ranking_batch", "ranking_complete"}:
            candidates = checkpoint_records
        elif resume_stage == "candidate_feedback":
            self._emit_log("Resuming the candidate feedback frontier from its durable action state.")
            candidates = self._prepare_candidates(question, retrieved)
            self._save_checkpoint(
                "citation_layer",
                records=candidates,
                metadata={"resume_from_stage": "citation_layer"},
            )
        else:
            self._emit_ranking_step(
                "candidate_preparation",
                "processing",
                "Preparing LLM candidate list",
                current=0,
                total=max(1, len(retrieved or [])),
                detail=f"{len(retrieved or [])} fused candidates before citation expansion.",
            )
            candidates = self._prepare_candidates(question, retrieved)
            self._emit_ranking_step(
                "candidate_preparation",
                "complete",
                "Preparing LLM candidate list",
                current=len(candidates),
                total=max(1, len(candidates)),
                detail=f"{len(candidates)} candidates ready before LLM ranking.",
                candidate_count=len(candidates),
            )
            self._save_checkpoint(
                "citation_layer",
                records=candidates,
                metadata={"resume_from_stage": "citation_layer"},
            )

        ranking_candidate_limit = self._llm_ranking_candidate_limit()
        if resume_stage in {"pre_rank", "ranking_batch", "ranking_complete"}:
            all_candidates = list(candidates)
        else:
            candidates = self._prioritize_selector_includes(candidates)
            all_candidates = list(candidates)
            if len(candidates) > ranking_candidate_limit:
                self._emit_log(
                    f"LLM ranking candidate list truncated: candidates={len(candidates)}; "
                    f"ranking_candidate_limit={ranking_candidate_limit}."
                )
                candidates = candidates[:ranking_candidate_limit]
            self._record_candidate_gate(all_candidates, candidates, ranking_candidate_limit)
            self._save_checkpoint(
                "pre_rank",
                records=candidates,
                metadata={"resume_from_stage": "pre_rank", "all_candidate_count": len(all_candidates)},
            )
        if len(candidates) != len(hits or []):
            self._emit_stage("ranking", "processing", candidate_count=len(candidates), **ranking_context)
        self._check_cancelled()
        if resume_stage == "ranking_complete":
            ranked_all = self._rank_from_scores(candidates, checkpoint.ranking_scores)
        else:
            ranked_all = self._rank_results(
                question,
                candidates,
                ranking_context=ranking_context,
                resume_scores=(checkpoint.ranking_scores if resume_stage == "ranking_batch" else None),
                completed_batch_ids=(checkpoint.completed_batch_ids if resume_stage == "ranking_batch" else None),
                checkpoint_records=candidates,
                checkpoint_resume_stage="pre_rank",
            )
            self._save_checkpoint(
                "ranking_complete",
                records=candidates,
                ranking_scores=self._ranking_scores_from_ranked(ranked_all),
                metadata={"resume_from_stage": "ranking_complete"},
            )
        self._record_candidate_scores(ranked_all, "llm_scored")
        ranked = self._select_ranked_output(ranked_all)
        self._record_final_candidates(ranked)
        self._finalize_citation_map(ranked)

        if self.config.fetch_abstracts:
            self._check_cancelled()
            self._emit_log("External abstract enrichment started.")
            self._emit_ranking_step(
                "abstract_enrichment",
                "processing",
                "Abstract enrichment",
                current=0,
                total=max(1, len(ranked)),
                detail="Fetching missing abstracts when available.",
            )
            ranked = self._enrich_with_abstracts(ranked)
            self._emit_log("External abstract enrichment completed.")
            self._emit_ranking_step(
                "abstract_enrichment",
                "complete",
                "Abstract enrichment",
                current=len(ranked),
                total=max(1, len(ranked)),
                detail="Abstract enrichment completed.",
            )

        self._emit_stage(
            "ranking",
            "complete",
            ranked_count=len(ranked),
            ranking_steps=list(self.ranking_steps.values()),
            **ranking_context,
        )

        self._emit_stage("results", "complete", ranked_count=len(ranked), total=total)

        return {
            "question": question,
            "search_intent": self.search_intent,
            "search_plan": self.search_plan.model_dump() if self.search_plan else {},
            "query_view_selection": list(self.query_view_selection),
            "query_portfolio": list(self.query_portfolio),
            "query_iteration_memory": self._query_iteration_memory_payload(),
            "final_query": query,
            "db": self.config.wos_db if self.data_source == "wos" else self.data_source.upper(),
            "source": self.data_source,
            "field": self._field_summary(),
            "total": total,
            "iterations": iteration,
            "history": history,
            "search_loop": self.search_loop_metadata,
            "search_state": self._search_state_payload(),
            "citation_map": self.citation_map,
            "ranking_steps": list(self.ranking_steps.values()),
            "ranked": ranked,
        }

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
            "search_loop": dict(self.search_loop_metadata or {}),
            "search_state": self._search_state_payload(),
            "citation_map": dict(self.citation_map or {}),
            "ranking_steps": list(self.ranking_steps.values()),
            "ranked": [],
        }

    def _search_state_payload(self) -> dict:
        if self.search_run_state is None:
            return {}

        payload = self.search_run_state.model_dump()
        queue_payload = payload.get("candidate_queue") or {}
        ledger = self.search_run_state.candidate_queue.ledger
        selector_counts: Dict[str, int] = {}
        ranking_gate_counts: Dict[str, int] = {}
        lifecycle_candidate_counts: Dict[str, int] = {}
        citation_candidate_count = 0
        ranked_ledger_keys = []

        for insertion_order, (key, evidence) in enumerate(ledger.items()):
            label = str(evidence.selector_label or "unseen")
            selector_counts[label] = selector_counts.get(label, 0) + 1
            gate_label = str(evidence.ranking_gate_label or "unseen")
            ranking_gate_counts[gate_label] = ranking_gate_counts.get(gate_label, 0) + 1
            actions = {str(event.action or "") for event in evidence.lifecycle if event.action}
            for action in actions:
                lifecycle_candidate_counts[action] = lifecycle_candidate_counts.get(action, 0) + 1
            if evidence.citation_paths:
                citation_candidate_count += 1

            priority = 4
            if "final_output" in actions:
                priority = 0
            elif "llm_scored" in actions:
                priority = 1
            elif "selected_for_llm" in actions or label == "include":
                priority = 2
            elif evidence.citation_paths:
                priority = 3
            ranked_ledger_keys.append((priority, insertion_order, key))

        retained_keys = {
            key
            for _, _, key in sorted(ranked_ledger_keys)[:_SERIALIZED_CANDIDATE_LEDGER_LIMIT]
        }
        serialized_ledger = {
            key: value
            for key, value in dict(queue_payload.get("ledger") or {}).items()
            if key in retained_keys
        }
        queue_payload["ledger"] = serialized_ledger
        queue_payload["ledger_summary"] = {
            "total_candidates": len(ledger),
            "serialized_candidates": len(serialized_ledger),
            "omitted_candidates": max(0, len(ledger) - len(serialized_ledger)),
            "selector_counts": selector_counts,
            "ranking_gate_counts": ranking_gate_counts,
            "lifecycle_candidate_counts": lifecycle_candidate_counts,
            "citation_candidate_count": citation_candidate_count,
        }
        payload["candidate_queue"] = queue_payload
        return payload

    def _query_loop_decision(
        self,
        query: str,
        hits: list,
        total: int,
        iteration: int,
        configured_iterations: int,
        adaptive_max_iterations: int,
        history: list,
        selector_batch: Optional[SelectorBatch] = None,
    ) -> QueryLoopDecision:
        self._set_search_state_query(query)
        preview = self._preview_hits(hits)
        selector_batch = selector_batch or self.last_query_selector_batch
        selector_counts = selector_batch.label_counts()
        missing_concepts = self._merge_unique(
            [],
            [
                concept
                for decision in selector_batch.decisions
                if decision.label != "exclude"
                for concept in decision.missing_concepts
            ],
        )
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
            selector_observed_count=len(selector_batch.decisions),
            selector_include_count=selector_counts.get("include", 0),
            selector_uncertain_count=selector_counts.get("uncertain", 0),
            selector_exclude_count=selector_counts.get("exclude", 0),
            selector_missing_concepts=missing_concepts,
        )
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query=query)
        self.search_run_state, decision = self.search_loop.evaluate(self.search_run_state, snapshot)
        return decision

    def _query_iteration_selector_feedback(
        self,
        question: str,
        query: str,
        hits: list,
        iteration: int,
    ) -> SelectorBatch:
        self.last_query_selector_feedback = {}
        self.last_query_selector_batch = SelectorBatch()
        if not (
            bool(getattr(self.config, "crawler_enabled", False))
            and self._intermediate_selector_feedback_active()
            and hits
        ):
            return SelectorBatch()
        sample = self._crawler_selector_sample(hits)
        before_selected = {
            key
            for key, evidence in self.search_run_state.candidate_queue.ledger.items()
            if evidence.selector_label in {"include", "exclude", "uncertain"}
        }
        batch = self._select_candidate_batch(
            question,
            sample,
            f"query_iteration:{iteration}",
        )
        new_decisions = [
            decision
            for decision in batch.decisions
            if decision.candidate_id not in before_selected
        ]
        if new_decisions:
            scheduler = FrontierScheduler(
                self.search_run_state.action_frontier,
                low_yield_round_limit=max(1, int(getattr(self.config, "crawler_low_yield_round_limit", 2) or 2)),
            )
            controller = CrawlerController(
                self.search_plan,
                self.data_source,
                scheduler,
                state=self.search_run_state.crawler_state,
                supported_actions=(),
            )
            controller.observe_selector(
                batch.model_copy(update={"decisions": new_decisions}),
                allow_follow_up_actions=False,
            )
            self.search_run_state = self.search_run_state.with_action_frontier(
                controller.scheduler.snapshot()
            ).with_crawler_state(controller.state)

        counts = batch.label_counts()
        missing = self._merge_unique(
            [],
            [
                concept
                for decision in batch.decisions
                if decision.label != "exclude"
                for concept in decision.missing_concepts
            ],
        )
        self.last_query_selector_feedback = {
            "query": query,
            "iteration": iteration,
            "observed": len(batch.decisions),
            "include": counts.get("include", 0),
            "uncertain": counts.get("uncertain", 0),
            "exclude": counts.get("exclude", 0),
            "missing_concepts": missing[:8],
        }
        self.last_query_selector_batch = batch
        self._emit_log(
            "Query-loop Candidate Selector feedback: "
            f"iteration={iteration}; inspected={len(batch.decisions)}; "
            f"include={counts.get('include', 0)}; uncertain={counts.get('uncertain', 0)}; "
            f"exclude={counts.get('exclude', 0)}; missing={','.join(missing[:5]) or 'none'}."
        )
        return batch

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
        docs = list(documents or [])
        keys = [document_key(document) for document in docs]
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(question="", source=self.data_source, current_query="")
        before = set(self.search_run_state.candidate_queue.keys)
        self.search_run_state, _ = self.search_loop.update_candidate_queue(
            self.search_run_state,
            candidate_keys=keys,
            origin=origin,
        )
        queue = self.search_run_state.candidate_queue
        records = list(queue.records)
        ledger = dict(queue.ledger)
        recorded_keys = {str(record.get("key") or "") for record in records}
        for document, key in zip(docs, keys):
            if not key:
                continue
            identifiers = getattr(document, "identifiers", None)
            if key not in recorded_keys:
                records.append(
                    {
                        "key": key,
                        "id": key,
                        "title": str(getattr(document, "title", "") or ""),
                        "doi": str(getattr(identifiers, "doi", "") or ""),
                        "arxiv": str(getattr(identifiers, "arxiv", "") or ""),
                        "pmid": str(getattr(identifiers, "pmid", "") or ""),
                    }
                )
                recorded_keys.add(key)

            metadata = dict(self.retrieval_metadata_by_key.get(key, {}) or {})
            extra = dict((evidence_by_key or {}).get(key, {}) or {})
            existing = ledger.get(key)
            source = getattr(document, "source", None)
            provider = str(getattr(document, "provider", "") or self.data_source or "")
            retrieval_lanes = [str(value) for value in metadata.get("retrieval_lanes", []) if value]
            query_views = [
                lane.split(":", 1)[1]
                for lane in retrieval_lanes
                if lane.startswith("query_view:") and ":" in lane
            ]
            source_ranks = {
                str(lane): int(rank)
                for lane, rank in dict(metadata.get("retrieval_source_ranks", {}) or {}).items()
                if rank is not None
            }
            event = CandidateLifecycleEvent(
                stage=origin,
                action="duplicate" if key in before else "added",
                origin=origin,
                detail=str(extra.get("detail") or ""),
            )
            citation_paths = [
                item if isinstance(item, CandidateCitationPath) else CandidateCitationPath.model_validate(item)
                for item in (extra.get("citation_paths") or [])
            ]
            if existing is None:
                evidence = CandidateEvidence(
                    candidate_id=key,
                    title=str(getattr(document, "title", "") or ""),
                    doi=str(getattr(identifiers, "doi", "") or ""),
                    arxiv=str(getattr(identifiers, "arxiv", "") or ""),
                    pmid=str(getattr(identifiers, "pmid", "") or ""),
                    openalex=str(getattr(identifiers, "openalex", "") or ""),
                    semanticscholar=str(getattr(identifiers, "semanticscholar", "") or ""),
                    year=getattr(source, "publish_year", None) if source else None,
                    citations=_citation_count(document),
                    sources=[provider] if provider else [],
                    origins=[origin] if origin else [],
                    query_views=query_views,
                    retrieval_lanes=retrieval_lanes,
                    source_ranks=source_ranks,
                    citation_paths=citation_paths,
                    concept_coverage={
                        name: float(metadata.get(field, 0.0) or 0.0)
                        for name, field in (
                            ("embedding", "retrieval_embedding_score"),
                            ("bm25", "retrieval_bm25_score"),
                            ("term", "retrieval_term_coverage"),
                            ("rrf", "retrieval_rrf_score"),
                            ("rrf_normalized", "retrieval_rrf_normalized"),
                            ("primary_prior", "retrieval_primary_prior"),
                        )
                    },
                    retrieval_score=self._optional_float(metadata.get("retrieval_score")),
                    rerank_score=self._optional_float(metadata.get("rerank_score")),
                    lifecycle=[event],
                )
            else:
                evidence = existing.model_copy(
                    update={
                        "sources": self._merge_unique(existing.sources, [provider]),
                        "origins": self._merge_unique(existing.origins, [origin]),
                        "query_views": self._merge_unique(existing.query_views, query_views),
                        "retrieval_lanes": self._merge_unique(existing.retrieval_lanes, retrieval_lanes),
                        "source_ranks": {**existing.source_ranks, **source_ranks},
                        "citation_paths": self._merge_citation_paths(existing.citation_paths, citation_paths),
                        "concept_coverage": {
                            **existing.concept_coverage,
                            **{
                                name: float(metadata.get(field, 0.0) or 0.0)
                                for name, field in (
                                    ("embedding", "retrieval_embedding_score"),
                                    ("bm25", "retrieval_bm25_score"),
                                    ("term", "retrieval_term_coverage"),
                                    ("rrf", "retrieval_rrf_score"),
                                    ("rrf_normalized", "retrieval_rrf_normalized"),
                                    ("primary_prior", "retrieval_primary_prior"),
                                )
                                if field in metadata
                            },
                        },
                        "retrieval_score": self._optional_float(metadata.get("retrieval_score"))
                        if "retrieval_score" in metadata
                        else existing.retrieval_score,
                        "rerank_score": self._optional_float(metadata.get("rerank_score"))
                        if "rerank_score" in metadata
                        else existing.rerank_score,
                        "lifecycle": [*existing.lifecycle, event],
                    }
                )
            ledger[key] = evidence

        if len(records) != len(queue.records) or ledger != queue.ledger:
            self.search_run_state = self.search_run_state.with_candidate_queue(
                queue.model_copy(update={"records": records, "ledger": ledger})
            )
        added = []
        added_keys = set()
        for document, key in zip(docs, keys):
            if not key or key in before or key in added_keys:
                continue
            added_keys.add(key)
            added.append(document)
        return added

    @staticmethod
    def _merge_unique(existing: list, incoming: list) -> list:
        output = list(existing or [])
        seen = {str(value) for value in output}
        for value in incoming or []:
            text = str(value or "").strip()
            if text and text not in seen:
                output.append(text)
                seen.add(text)
        return output

    def _candidate_selector_active(self) -> bool:
        return bool(getattr(self.config, "candidate_selector_enabled", False)) and self.search_plan is not None

    def _intermediate_selector_feedback_active(self) -> bool:
        return self._candidate_selector_active() and bool(
            getattr(self.config, "crawler_intermediate_selector_enabled", False)
        )

    def _candidate_selector_for_run(self) -> CandidateSelector:
        if self._candidate_selector_instance is not None:
            return self._candidate_selector_instance
        cache: dict[str, SelectorDecision] = {}
        if self.search_run_state is not None:
            for evidence in self.search_run_state.candidate_queue.ledger.values():
                if not evidence.selector_input_hash or evidence.selector_label not in {"include", "exclude", "uncertain"}:
                    continue
                cache[evidence.selector_input_hash] = SelectorDecision(
                    candidate_id=evidence.candidate_id,
                    label=evidence.selector_label,
                    relevance_score=evidence.selector_relevance_score
                    if evidence.selector_relevance_score is not None
                    else 0.5,
                    concept_coverage=dict(evidence.selector_concept_coverage),
                    missing_concepts=list(evidence.selector_missing_concepts),
                    evidence=list(evidence.selector_evidence),
                    recommended_actions=list(evidence.selector_recommended_actions) or ["none"],
                    reason_codes=list(evidence.selector_reason_codes),
                )
        self._candidate_selector_instance = CandidateSelector(
            self.llm,
            batch_size=max(1, int(getattr(self.config, "candidate_selector_batch_size", 12) or 12)),
            concurrency=max(1, int(getattr(self.config, "candidate_selector_concurrency", 2) or 2)),
            max_llm_calls=max(0, int(getattr(self.config, "candidate_selector_max_llm_calls", 24) or 0)),
            max_attempts=max(1, int(getattr(self.config, "candidate_selector_max_attempts", 2) or 2)),
            exclude_score_max=float(getattr(self.config, "candidate_selector_exclude_score_max", 0.25) or 0.25),
            cache=cache,
        )
        return self._candidate_selector_instance

    def _crawler_selector_sample(self, documents: list) -> list:
        try:
            sample_size = max(
                1,
                min(int(getattr(self.config, "crawler_selector_sample_size", 24) or 24), 100),
            )
        except (TypeError, ValueError):
            sample_size = 24
        return self._dedupe_documents(documents or [])[:sample_size]

    def _select_candidate_batch(self, question: str, documents: list, origin: str) -> SelectorBatch:
        unique_documents = self._dedupe_documents(documents or [])
        if not unique_documents:
            return SelectorBatch()
        self._enqueue_candidate_queue(unique_documents, origin)
        if self._candidate_selector_active():
            selector = self._candidate_selector_for_run()
            try:
                batch = selector.select(question, self.search_plan, unique_documents)
            except Exception as exc:
                self._emit_log(
                    f"Candidate Selector failed unexpectedly; preserving {len(unique_documents)} candidates as uncertain: "
                    f"{exc.__class__.__name__}: {exc}"
                )
                batch = SelectorBatch(
                    decisions=[
                        SelectorDecision(
                            candidate_id=document_key(document),
                            label="uncertain",
                            relevance_score=0.5,
                            recommended_actions=["enrich"]
                            if not str(getattr(document, "abstract", "") or "").strip()
                            else ["none"],
                            reason_codes=["selector_unexpected_failure"],
                        )
                        for document in unique_documents
                        if document_key(document)
                    ],
                    fallback_count=len(unique_documents),
                    errors=[f"{exc.__class__.__name__}: {exc}"],
                )
        else:
            batch = SelectorBatch(
                decisions=[
                    SelectorDecision(
                        candidate_id=document_key(document),
                        label="uncertain",
                        relevance_score=0.5,
                        recommended_actions=["none"],
                        reason_codes=["candidate_selector_disabled"],
                    )
                    for document in unique_documents
                    if document_key(document)
                ]
            )
        self._record_selector_batch(question, unique_documents, batch, origin)
        counts = batch.label_counts()
        self._emit_log(
            "Candidate Selector completed: "
            f"origin={origin}; include={counts.get('include', 0)}; uncertain={counts.get('uncertain', 0)}; "
            f"exclude={counts.get('exclude', 0)}; llm_calls={batch.llm_calls}; cache_hits={batch.cache_hits}; "
            f"fallbacks={batch.fallback_count}."
        )
        return batch

    def _record_selector_batch(
        self,
        question: str,
        documents: list,
        batch: SelectorBatch,
        origin: str,
    ) -> None:
        if self.search_run_state is None:
            return
        queue = self.search_run_state.candidate_queue
        ledger = dict(queue.ledger)
        documents_by_key = {
            document_key(document): document
            for document in documents or []
            if document_key(document)
        }
        selector = self._candidate_selector_instance
        for decision in batch.decisions:
            document = documents_by_key.get(decision.candidate_id)
            evidence = ledger.get(decision.candidate_id)
            if document is None or evidence is None:
                continue
            input_hash = (
                selector.cache_key(question, self.search_plan, document)
                if selector is not None and self.search_plan is not None
                else ""
            )
            ledger[decision.candidate_id] = evidence.model_copy(
                update={
                    "selector_label": decision.label,
                    "selector_relevance_score": decision.relevance_score,
                    "selector_concept_coverage": dict(decision.concept_coverage),
                    "selector_missing_concepts": list(decision.missing_concepts),
                    "selector_evidence": list(decision.evidence),
                    "selector_recommended_actions": list(decision.recommended_actions),
                    "selector_reason_codes": self._merge_unique(
                        evidence.selector_reason_codes,
                        decision.reason_codes,
                    ),
                    "selector_input_hash": input_hash,
                    "lifecycle": [
                        *evidence.lifecycle,
                        CandidateLifecycleEvent(
                            stage="candidate_selector",
                            action=decision.label,
                            origin=origin,
                            detail=(
                                f"relevance={decision.relevance_score:.3f}; "
                                f"missing={','.join(decision.missing_concepts[:5])}"
                            ),
                        ),
                    ],
                }
            )
        self.search_run_state = self.search_run_state.with_candidate_queue(
            queue.model_copy(update={"ledger": ledger})
        )

    def _selector_filtered_candidates(self, documents: list) -> list:
        if self.search_run_state is None or not self._candidate_selector_active():
            return list(documents or [])
        ledger = self.search_run_state.candidate_queue.ledger
        keep_uncertain = bool(getattr(self.config, "candidate_selector_keep_uncertain", True))

        def should_keep(document) -> bool:
            evidence = ledger.get(document_key(document))
            if evidence is None:
                return True
            if evidence.selector_label == "exclude":
                return False
            if evidence.selector_label == "uncertain":
                return keep_uncertain
            # An unsampled candidate remains unseen in the ledger. Selection is
            # a prioritization signal, so lack of a decision must not reduce recall.
            return True

        return [document for document in documents or [] if should_keep(document)]

    def _prioritize_selector_includes(self, documents: list) -> list:
        values = list(documents or [])
        if self.search_run_state is None or not self._candidate_selector_active():
            return values
        ledger = self.search_run_state.candidate_queue.ledger
        included = []
        remaining = []
        for index, document in enumerate(values):
            evidence = ledger.get(document_key(document))
            if evidence is not None and evidence.selector_label == "include":
                score = evidence.selector_relevance_score
                included.append((-(float(score) if score is not None else 0.0), index, document))
            else:
                remaining.append(document)
        included.sort(key=lambda item: (item[0], item[1]))
        return [document for _, _, document in included] + remaining

    @staticmethod
    def _merge_citation_paths(existing: list, incoming: list) -> list:
        output = list(existing or [])
        seen = {
            (item.seed_id, item.parent_id, item.direction, item.depth)
            for item in output
        }
        for item in incoming or []:
            key = (item.seed_id, item.parent_id, item.direction, item.depth)
            if key not in seen:
                output.append(item)
                seen.add(key)
        return output

    @staticmethod
    def _optional_float(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _record_candidate_gate(self, all_candidates: list, selected_candidates: list, limit: int) -> None:
        if self.search_run_state is None:
            return
        selected_keys = {
            document_key(document)
            for document in selected_candidates or []
            if document_key(document)
        }
        queue = self.search_run_state.candidate_queue
        ledger = dict(queue.ledger)
        for document in all_candidates or []:
            key = document_key(document)
            evidence = ledger.get(key)
            if not key or evidence is None:
                continue
            selected = key in selected_keys
            action = "selected_for_llm" if selected else "truncated_before_llm"
            reason = "within_ranking_candidate_limit" if selected else "ranking_candidate_limit"
            reason_codes = [reason]
            origin = "local_fused_rank"
            if selected and evidence.selector_label == "include":
                reason_codes.append("selector_include_priority")
                origin = "candidate_selector"
            ledger[key] = evidence.model_copy(
                update={
                    "ranking_gate_label": "selected" if selected else "truncated",
                    "ranking_gate_reason_codes": self._merge_unique(evidence.ranking_gate_reason_codes, reason_codes),
                    "lifecycle": [
                        *evidence.lifecycle,
                        CandidateLifecycleEvent(
                            stage="ranking_gate",
                            action=action,
                            origin=origin,
                            detail=f"ranking_candidate_limit={limit}",
                        ),
                    ],
                }
            )
        self.search_run_state = self.search_run_state.with_candidate_queue(
            queue.model_copy(update={"ledger": ledger})
        )

    def _record_candidate_scores(self, ranked: list, action: str) -> None:
        if self.search_run_state is None:
            return
        queue = self.search_run_state.candidate_queue
        ledger = dict(queue.ledger)
        for entry in ranked or []:
            document = (entry or {}).get("document") if isinstance(entry, dict) else None
            key = document_key(document) if document is not None else ""
            evidence = ledger.get(key)
            if not key or evidence is None:
                continue
            ledger[key] = evidence.model_copy(
                update={
                    "llm_score": self._optional_float((entry or {}).get("score")),
                    "lifecycle": [
                        *evidence.lifecycle,
                        CandidateLifecycleEvent(stage="ranking", action=action, origin="llm_ranking"),
                    ],
                }
            )
        self.search_run_state = self.search_run_state.with_candidate_queue(
            queue.model_copy(update={"ledger": ledger})
        )

    def _record_final_candidates(self, ranked: list) -> None:
        if self.search_run_state is None:
            return
        queue = self.search_run_state.candidate_queue
        ledger = dict(queue.ledger)
        for entry in ranked or []:
            document = (entry or {}).get("document") if isinstance(entry, dict) else None
            key = document_key(document) if document is not None else ""
            evidence = ledger.get(key)
            if not key or evidence is None:
                continue
            ledger[key] = evidence.model_copy(
                update={
                    "lifecycle": [
                        *evidence.lifecycle,
                        CandidateLifecycleEvent(stage="results", action="final_output", origin="ranked_output"),
                    ]
                }
            )
        self.search_run_state = self.search_run_state.with_candidate_queue(
            queue.model_copy(update={"ledger": ledger})
        )

    def _execute_query_portfolio(self, question: str, final_query: str, primary_hits: list, history: list) -> list:
        if not bool(getattr(self.config, "crawler_enabled", False)):
            return self._execute_query_portfolio_legacy(question, final_query, primary_hits, history)
        return self._execute_query_portfolio_frontier(question, final_query, primary_hits, history)

    def _execute_query_portfolio_frontier(
        self,
        question: str,
        final_query: str,
        primary_hits: list,
        history: list,
    ) -> list:
        if not supports_query_portfolio(self.data_source):
            return list(primary_hits or [])
        if not bool(getattr(self.config, "query_portfolio_enabled", True)):
            return list(primary_hits or [])
        if not self.search_plan or not self.search_plan.query_views:
            return list(primary_hits or [])

        try:
            max_views = max(1, min(int(getattr(self.config, "query_portfolio_max", 3) or 3), 6))
        except (TypeError, ValueError):
            max_views = 3
        try:
            per_view_limit = max(1, min(int(getattr(self.config, "query_portfolio_limit", 100) or 100), 100))
        except (TypeError, ValueError):
            per_view_limit = 100

        crawler_sources = self._crawler_source_order()
        selections_by_source = {
            source: select_query_views(
                self.search_plan,
                source,
                final_query if source == self.data_source else "",
                max_views,
            )
            for source in crawler_sources
        }
        selections = [
            selection
            for source in crawler_sources
            for selection in selections_by_source[source]
        ]
        self.query_view_selection = [item.audit_payload() for item in selections]
        selection_by_key = {
            (item.source, item.view.view_id): item
            for item in selections
        }
        combined = self._dedupe_documents(list(primary_hits or []))
        seen_keys = {document_key(document) for document in combined if document_key(document)}
        seen_queries = {
            (
                self.data_source,
                re.sub(r"\s+", " ", str(value or "")).strip().casefold(),
            )
            for value in [final_query, *[row.get("query") for row in history], *[row.get("next_query") for row in history]]
            if value
        }
        if self.search_run_state is None:
            self.search_run_state = SearchRunState(
                question=question,
                source=self.data_source,
                current_query=final_query,
                search_plan=self.search_plan.model_dump(),
            )

        frontier_state = self.search_run_state.action_frontier
        if not frontier_state.actions:
            max_reader_requests = max(0, int(getattr(self.config, "crawler_max_reader_requests", 8) or 0))
            max_citation_requests = max(0, int(getattr(self.config, "crawler_max_citation_requests", 8) or 0))
            frontier_state = frontier_state.model_copy(
                update={
                    "budget": FrontierBudget(
                        max_source_requests=max_views,
                        max_reader_requests=max_reader_requests,
                        max_citation_requests=max_citation_requests,
                        max_tool_requests=max_views + max_reader_requests + max_citation_requests,
                        max_candidates=max(1, int(getattr(self.config, "retrieval_pool_max", 3000) or 3000)),
                        max_wall_seconds=max(1.0, float(getattr(self.config, "crawler_max_wall_seconds", 300.0) or 300.0)),
                        candidate_count=len(seen_keys),
                    )
                }
            )
        scheduler = FrontierScheduler(
            frontier_state,
            low_yield_round_limit=max(1, int(getattr(self.config, "crawler_low_yield_round_limit", 2) or 2)),
        )
        controller = CrawlerController(
            self.search_plan,
            self.data_source,
            scheduler,
            state=self.search_run_state.crawler_state,
        )
        for source in crawler_sources:
            controller.seed_query_views(selections_by_source[source], source=source)

        completed_execution_ids = {
            (
                str(item.get("source") or self.data_source).strip().lower(),
                str(item.get("view_id") or ""),
            )
            for item in self.query_portfolio
            if isinstance(item, dict) and item.get("view_id")
        }

        def sync_controller_state() -> None:
            self.search_run_state = self.search_run_state.with_action_frontier(
                controller.scheduler.snapshot()
            ).with_crawler_state(controller.state)

        def record_execution(execution: QueryPortfolioExecution) -> None:
            execution_id = (execution.source or self.data_source, execution.view_id)
            if execution_id in completed_execution_ids:
                return
            payload = execution.model_dump()
            self.query_portfolio.append(payload)
            self.search_run_state = self.search_run_state.with_query_portfolio_execution(execution)
            history.append(
                {
                    "iteration": self.last_iteration,
                    "query": execution.query,
                    "total": execution.total if execution.status == "completed" else None,
                    "action": "portfolio",
                    "next_query": None,
                    "message": (
                        f"Query view {execution.source}:{execution.view_id} {execution.status}; "
                        f"returned {execution.hit_count} and added {execution.added_unique} unique candidates."
                    ),
                    "view_id": execution.view_id,
                    "source": execution.source,
                    "view_type": execution.view_type,
                    "purpose": execution.purpose,
                    "status": execution.status,
                    "selector_score": execution.selector_score,
                    "selector_overlap": execution.selector_overlap,
                    "selector_reasons": execution.selector_reasons,
                }
            )
            completed_execution_ids.add(execution_id)
            self._emit_stage(
                "search",
                "processing",
                total=self.last_total,
                history=history,
                final_query=final_query,
                query_view_selection=list(self.query_view_selection),
                query_portfolio=list(self.query_portfolio),
                preview=self._preview_hits(combined),
            )
            self._save_checkpoint(
                "query_execution",
                records=combined,
                metadata={
                    "phase": "query_portfolio",
                    "completed_execution_ids": [
                        f"{source}:{view_id}"
                        for source, view_id in sorted(completed_execution_ids)
                    ],
                },
            )

        for selection in selections:
            view = selection.view
            if (selection.source, view.view_id) in completed_execution_ids:
                continue
            if selection.compile_error:
                record_execution(
                    QueryPortfolioExecution(
                        view_id=view.view_id,
                        source=selection.source,
                        view_type=view.view_type,
                        purpose=view.purpose,
                        query=selection.compiled_query,
                        status="failed",
                        error=selection.compile_error,
                        selector_score=selection.score,
                        selector_overlap=selection.lexical_overlap,
                        selector_reasons=selection.reason_codes,
                    )
                )
            elif "exact_primary_duplicate" in selection.reason_codes:
                record_execution(
                    QueryPortfolioExecution(
                        view_id=view.view_id,
                        source=selection.source,
                        view_type=view.view_type,
                        purpose=view.purpose,
                        query=selection.compiled_query,
                        status="skipped_duplicate",
                        selector_score=selection.score,
                        selector_overlap=selection.lexical_overlap,
                        selector_reasons=selection.reason_codes,
                    )
                )

        intermediate_feedback = self._intermediate_selector_feedback_active()
        if intermediate_feedback and not controller.scheduler.state.outcomes and combined:
            primary_batch = self.last_query_selector_batch
            if not primary_batch.decisions:
                primary_batch = self._select_candidate_batch(
                    question,
                    self._crawler_selector_sample(combined),
                    "primary_query",
                )
            controller.observe_selector(primary_batch, allow_follow_up_actions=False)
            sync_controller_state()

        def search_handler(action) -> ProviderSearchResult:
            source = controller.query_source(action)
            portfolio_query = self._apply_discipline_filter(action.query) if source == self.data_source else action.query
            normalized_query = re.sub(r"\s+", " ", portfolio_query).strip().casefold()
            query_identity = (source, normalized_query)
            if not normalized_query or query_identity in seen_queries:
                raise ValueError("duplicate or empty frontier query")
            seen_queries.add(query_identity)
            source_state = self.search_run_state.model_copy(
                update={"source": source, "current_query": portfolio_query}
            )
            source_state, validation = self.search_loop.preflight(source_state, portfolio_query)
            self.search_run_state = self.search_run_state.model_copy(
                update={"validations": source_state.validations}
            )
            if not validation.ok:
                raise ValueError(validation.issue)
            self._emit_log(
                f"Crawler search action started: action={action.action_id}; source={source}; query={portfolio_query}"
            )
            source_state, result, search_error = self.search_loop.source_search(
                source_state,
                portfolio_query,
                lambda query: self._provider_search_lane_for_source(
                    source,
                    query,
                    RetrievalLane.RELEVANCE,
                    per_view_limit,
                    page=1,
                ),
            )
            self.search_run_state = self.search_run_state.model_copy(
                update={
                    "validations": source_state.validations,
                    "errors": source_state.errors,
                }
            )
            if search_error is not None:
                raise search_error
            return result

        executor = ToolExecutor({"search": search_handler}, passthrough_exceptions=(SearchCancelled,))
        self._emit_log(
            f"Crawler frontier started: sources={','.join(crawler_sources)}; actions={len(controller.scheduler.state.actions)}; "
            f"source_request_budget={max_views}; per_view_limit={per_view_limit}."
        )
        cycle_executions: Dict[str, QueryPortfolioExecution] = {}

        def execute_query_action(action):
            source = controller.query_source(action)
            view_id = controller.query_view_id(action)
            selection = selection_by_key.get((source, view_id))
            if selection is None:
                return ToolExecution(
                    action=action,
                    status="failed",
                    error=f"unknown_query_view:{view_id or action.action_id}",
                )
            return executor.execute(action)

        def select_query_action(action, execution_result) -> FrontierOutcome:
            source = controller.query_source(action)
            view_id = controller.query_view_id(action)
            selection = selection_by_key.get((source, view_id))
            if execution_result.status == "done":
                view_hits = list(execution_result.records)
                added_documents = []
                for document in view_hits:
                    key = document_key(document)
                    if key and key in seen_keys:
                        continue
                    if key:
                        seen_keys.add(key)
                    combined.append(document)
                    added_documents.append(document)
                lane_key = f"{source}:{view_id}"
                self.query_portfolio_lane_results[lane_key] = view_hits
                if intermediate_feedback:
                    gaps_before = set(controller.concept_gaps())
                    selector_batch = self._select_candidate_batch(
                        question,
                        self._crawler_selector_sample(added_documents),
                        f"query_view:{source}:{view_id}",
                    )
                    controller.observe_selector(selector_batch, allow_follow_up_actions=False)
                    gaps_after = set(controller.concept_gaps())
                    counts = selector_batch.label_counts()
                else:
                    gaps_before = set()
                    gaps_after = set()
                    counts = {"include": 0, "uncertain": 0, "exclude": 0}
                outcome = FrontierOutcome(
                    action_id=action.action_id,
                    status="done",
                    candidates_seen=len(view_hits),
                    added_unique=len(added_documents),
                    include_count=counts.get("include", 0),
                    uncertain_count=counts.get("uncertain", 0),
                    exclude_count=counts.get("exclude", 0),
                    newly_relevant_count=counts.get("include", 0),
                    concept_gap_reduction=len(gaps_before - gaps_after),
                    elapsed_ms=execution_result.elapsed_ms,
                )
                execution = QueryPortfolioExecution(
                    view_id=view_id,
                    source=source,
                    view_type=selection.view.view_type,
                    purpose=selection.view.purpose,
                    query=action.query,
                    total=execution_result.total,
                    hit_count=len(view_hits),
                    added_unique=len(added_documents),
                    selector_score=selection.score,
                    selector_overlap=selection.lexical_overlap,
                    selector_reasons=[*selection.reason_codes, "frontier_scheduled"],
                )
            else:
                outcome = FrontierOutcome(
                    action_id=action.action_id,
                    status="failed" if execution_result.status == "failed" else "skipped",
                    elapsed_ms=execution_result.elapsed_ms,
                    error=execution_result.error,
                )
                execution = QueryPortfolioExecution(
                    view_id=view_id or action.action_id,
                    source=source,
                    view_type=selection.view.view_type if selection else "",
                    purpose=selection.view.purpose if selection else "",
                    query=action.query,
                    status="failed" if execution_result.status == "failed" else "skipped_selector",
                    error=execution_result.error,
                    selector_score=selection.score if selection else 0.0,
                    selector_overlap=selection.lexical_overlap if selection else 0.0,
                    selector_reasons=[*(selection.reason_codes if selection else []), "frontier_scheduled"],
                )
            cycle_executions[action.action_id] = execution
            return outcome

        while True:
            self._check_cancelled()
            cycle = self.search_loop.run_frontier_cycle(
                controller,
                execute_query_action,
                select_query_action,
                passthrough_exceptions=(SearchCancelled,),
            )
            if not cycle.scheduled or cycle.action is None:
                break
            sync_controller_state()
            execution = cycle_executions.pop(cycle.action.action_id, None)
            if execution is None:
                source = controller.query_source(cycle.action)
                view_id = controller.query_view_id(cycle.action)
                selection = selection_by_key.get((source, view_id))
                execution = QueryPortfolioExecution(
                    view_id=view_id or cycle.action.action_id,
                    source=source,
                    view_type=selection.view.view_type if selection else "",
                    purpose=selection.view.purpose if selection else "",
                    query=cycle.action.query,
                    status="failed",
                    error=cycle.outcome.error if cycle.outcome else "frontier_cycle_failed",
                    selector_score=selection.score if selection else 0.0,
                    selector_overlap=selection.lexical_overlap if selection else 0.0,
                    selector_reasons=[*(selection.reason_codes if selection else []), cycle.backend_used],
                )
            record_execution(execution)
            failed_source = controller.query_source(cycle.action)
            if (
                execution.status == "failed"
                and failed_source != self.data_source
                and _is_source_availability_error(execution.error)
            ):
                source_pending = [
                    action
                    for action in controller.scheduler.state.actions
                    if action.status == "pending"
                    and controller.query_source(action) == failed_source
                ]
                if source_pending:
                    controller.scheduler.replace_pending(
                        [
                            action.model_copy(
                                update={
                                    "status": "skipped",
                                    "reason_codes": self._merge_unique(
                                        action.reason_codes,
                                        ["source_circuit_open"],
                                    ),
                                }
                            )
                            for action in source_pending
                        ]
                    )
                    sync_controller_state()
                    self._emit_log(
                        f"Crawler source circuit opened after an availability error: source={failed_source}; "
                        f"skipped_actions={len(source_pending)}; preserving remaining source budget for fallback."
                    )
                    for pending_action in source_pending:
                        pending_view_id = controller.query_view_id(pending_action)
                        pending_selection = selection_by_key.get((failed_source, pending_view_id))
                        if pending_selection is None:
                            continue
                        record_execution(
                            QueryPortfolioExecution(
                                view_id=pending_view_id,
                                source=failed_source,
                                view_type=pending_selection.view.view_type,
                                purpose=pending_selection.view.purpose,
                                query=pending_action.query,
                                status="skipped_source_unavailable",
                                error=execution.error,
                                selector_score=pending_selection.score,
                                selector_overlap=pending_selection.lexical_overlap,
                                selector_reasons=self._merge_unique(
                                    pending_selection.reason_codes,
                                    ["source_circuit_open"],
                                ),
                            )
                        )

        pending = [
            action
            for action in controller.scheduler.state.actions
            if action.status == "pending"
            and (
                controller.query_source(action),
                controller.query_view_id(action),
            ) not in completed_execution_ids
        ]
        if pending:
            stop_reason = controller.scheduler.state.stop_reason or "frontier_not_selected"
            controller.scheduler.replace_pending(
                [
                    action.model_copy(
                        update={
                            "status": "skipped",
                            "reason_codes": self._merge_unique(action.reason_codes, [stop_reason]),
                        }
                    )
                    for action in pending
                ]
            )
            sync_controller_state()
            for action in pending:
                source = controller.query_source(action)
                view_id = controller.query_view_id(action)
                selection = selection_by_key.get((source, view_id))
                if selection is None:
                    continue
                record_execution(
                    QueryPortfolioExecution(
                        view_id=view_id,
                        source=source,
                        view_type=selection.view.view_type,
                        purpose=selection.view.purpose,
                        query=action.query,
                        status="skipped_selector",
                        selector_score=selection.score,
                        selector_overlap=selection.lexical_overlap,
                        selector_reasons=self._merge_unique(selection.reason_codes, [stop_reason]),
                    )
                )

        self._emit_log(
            f"Crawler frontier completed: actions={controller.state.completed_actions}; "
            f"stop={controller.scheduler.state.stop_reason or 'frontier_empty'}; "
            f"unique_loaded_candidates={len(combined)}."
        )
        self._emit_stage(
            "search",
            "complete",
            total=self.last_total,
            history=history,
            final_query=final_query,
            query_view_selection=list(self.query_view_selection),
            query_portfolio=list(self.query_portfolio),
            preview=self._preview_hits(combined),
        )
        return self._dedupe_documents(combined)

    def _execute_query_portfolio_legacy(self, question: str, final_query: str, primary_hits: list, history: list) -> list:
        if not supports_query_portfolio(self.data_source):
            return list(primary_hits or [])
        if not bool(getattr(self.config, "query_portfolio_enabled", True)):
            return list(primary_hits or [])
        if not self.search_plan or not self.search_plan.query_views:
            return list(primary_hits or [])

        try:
            max_views = max(1, min(int(getattr(self.config, "query_portfolio_max", 3) or 3), 6))
        except (TypeError, ValueError):
            max_views = 3
        try:
            per_view_limit = max(1, min(int(getattr(self.config, "query_portfolio_limit", 100) or 100), 100))
        except (TypeError, ValueError):
            per_view_limit = 100

        selections = select_query_views(
            self.search_plan,
            self.data_source,
            final_query,
            max_views,
        )
        self.query_view_selection = [item.audit_payload() for item in selections]
        ranked_selections = sorted(
            selections,
            key=lambda item: (-item.score, item.original_index),
        )
        self._emit_log(
            "Query view selector completed: "
            + "; ".join(
                f"{item.view.view_id}={'selected' if item.selected else 'reserve'}"
                f" score={item.score:.3f} overlap={item.lexical_overlap:.3f}"
                for item in ranked_selections
            )
        )

        combined = list(primary_hits or [])
        seen_keys = {document_key(document) for document in combined if document_key(document)}
        seen_queries = {
            re.sub(r"\s+", " ", str(value or "")).strip().casefold()
            for value in [final_query, *[row.get("query") for row in history], *[row.get("next_query") for row in history]]
            if value
        }
        self._emit_log(
            f"Query portfolio started: source={self.data_source}; candidate_views={len(self.search_plan.query_views)}; "
            f"request_budget={max_views}; per_view_limit={per_view_limit}."
        )

        completed_view_ids = {
            str(item.get("view_id") or "")
            for item in self.query_portfolio
            if isinstance(item, dict) and item.get("view_id")
        }
        requests_started = sum(
            1
            for item in self.query_portfolio
            if isinstance(item, dict) and item.get("status") == "completed"
        )
        for selection in ranked_selections:
            view = selection.view
            if view.view_id in completed_view_ids:
                continue
            self._check_cancelled()
            execution = None
            compiled_query = selection.compiled_query
            if selection.compile_error:
                execution = QueryPortfolioExecution(
                    view_id=view.view_id,
                    view_type=view.view_type,
                    purpose=view.purpose,
                    query=compiled_query,
                    status="failed",
                    error=selection.compile_error,
                    selector_score=selection.score,
                    selector_overlap=selection.lexical_overlap,
                    selector_reasons=selection.reason_codes,
                )
            elif "exact_primary_duplicate" in selection.reason_codes:
                execution = QueryPortfolioExecution(
                    view_id=view.view_id,
                    view_type=view.view_type,
                    purpose=view.purpose,
                    query=compiled_query,
                    status="skipped_duplicate",
                    selector_score=selection.score,
                    selector_overlap=selection.lexical_overlap,
                    selector_reasons=selection.reason_codes,
                )
            elif requests_started >= max_views:
                execution = QueryPortfolioExecution(
                    view_id=view.view_id,
                    view_type=view.view_type,
                    purpose=view.purpose,
                    query=compiled_query,
                    status="skipped_budget",
                    selector_score=selection.score,
                    selector_overlap=selection.lexical_overlap,
                    selector_reasons=self._merge_unique(selection.reason_codes, ["query_view_request_budget"]),
                )
            else:
                try:
                    portfolio_query = self._apply_discipline_filter(compiled_query)
                    normalized_query = re.sub(r"\s+", " ", portfolio_query).strip().casefold()
                    if not normalized_query or normalized_query in seen_queries:
                        execution = QueryPortfolioExecution(
                            view_id=view.view_id,
                            view_type=view.view_type,
                            purpose=view.purpose,
                            query=portfolio_query,
                            status="skipped_duplicate",
                            selector_score=selection.score,
                            selector_overlap=selection.lexical_overlap,
                            selector_reasons=selection.reason_codes,
                        )
                    else:
                        seen_queries.add(normalized_query)
                        if self.search_run_state is None:
                            self.search_run_state = SearchRunState(question=question, source=self.data_source, current_query=final_query)
                        self.search_run_state, validation = self.search_loop.preflight(self.search_run_state, portfolio_query)
                        if not validation.ok:
                            raise ValueError(validation.issue)
                        self._emit_log(
                            f"Query portfolio request started: view={view.view_id}; purpose={view.purpose or 'complementary recall'}; "
                            f"query={portfolio_query}"
                        )
                        requests_started += 1
                        self.search_run_state, result, search_error = self.search_loop.source_search(
                            self.search_run_state,
                            portfolio_query,
                            lambda query: self._provider_search_lane(
                                query,
                                RetrievalLane.RELEVANCE,
                                per_view_limit,
                                page=1,
                            ),
                        )
                        if search_error is not None:
                            raise search_error
                        view_hits = list(getattr(result, "hits", []) or [])
                        total = int(getattr(getattr(result, "metadata", None), "total", 0) or 0)
                        added = 0
                        for document in view_hits:
                            key = document_key(document)
                            if key and key in seen_keys:
                                continue
                            if key:
                                seen_keys.add(key)
                            combined.append(document)
                            added += 1
                        self.query_portfolio_lane_results[view.view_id] = view_hits
                        execution = QueryPortfolioExecution(
                            view_id=view.view_id,
                            view_type=view.view_type,
                            purpose=view.purpose,
                            query=portfolio_query,
                            total=total,
                            hit_count=len(view_hits),
                            added_unique=added,
                            selector_score=selection.score,
                            selector_overlap=selection.lexical_overlap,
                            selector_reasons=selection.reason_codes,
                        )
                        self._emit_log(
                            f"Query portfolio view completed: view={view.view_id}; total={total}; "
                            f"returned={len(view_hits)}; added_unique={added}."
                        )
                except Exception as exc:
                    execution = QueryPortfolioExecution(
                        view_id=view.view_id,
                        view_type=view.view_type,
                        purpose=view.purpose,
                        query=compiled_query,
                        status="failed",
                        error=f"{exc.__class__.__name__}: {exc}",
                        selector_score=selection.score,
                        selector_overlap=selection.lexical_overlap,
                        selector_reasons=selection.reason_codes,
                    )
                    self._emit_log(
                        f"Query portfolio view skipped after error: view={view.view_id}; {exc.__class__.__name__}: {exc}"
                    )

            execution_payload = execution.model_dump()
            self.query_portfolio.append(execution_payload)
            if self.search_run_state is not None:
                self.search_run_state = self.search_run_state.with_query_portfolio_execution(execution)
            history.append(
                {
                    "iteration": self.last_iteration,
                    "query": execution.query,
                    "total": execution.total if execution.status == "completed" else None,
                    "action": "portfolio",
                    "next_query": None,
                    "message": (
                        f"Query view {execution.view_id} {execution.status}; "
                        f"returned {execution.hit_count} and added {execution.added_unique} unique candidates."
                    ),
                    "view_id": execution.view_id,
                    "view_type": execution.view_type,
                    "purpose": execution.purpose,
                    "status": execution.status,
                    "selector_score": execution.selector_score,
                    "selector_overlap": execution.selector_overlap,
                    "selector_reasons": execution.selector_reasons,
                }
            )
            self._emit_stage(
                "search",
                "processing",
                total=self.last_total,
                history=history,
                final_query=final_query,
                query_view_selection=list(self.query_view_selection),
                query_portfolio=list(self.query_portfolio),
                preview=self._preview_hits(combined),
            )
            self._save_checkpoint(
                "query_execution",
                records=combined,
                metadata={"phase": "query_portfolio", "completed_view_ids": sorted(completed_view_ids | {view.view_id})},
            )
            completed_view_ids.add(view.view_id)

        self._emit_log(
            f"Query portfolio completed: views={len(self.query_portfolio)}; unique_loaded_candidates={len(combined)}."
        )
        self._emit_stage(
            "search",
            "complete",
            total=self.last_total,
            history=history,
            final_query=final_query,
            query_view_selection=list(self.query_view_selection),
            query_portfolio=list(self.query_portfolio),
            preview=self._preview_hits(combined),
        )
        return self._dedupe_documents(combined)

    def _provider_search(self, query: str):
        return self._provider_search_lane(query, RetrievalLane.RELEVANCE, self._candidate_limit(), page=1)

    def _source_safe_query(self, query: str) -> str:
        if self.data_source == "openalex":
            return _sanitize_openalex_query(query)
        if self.data_source == "semanticscholar":
            return _sanitize_semantic_scholar_query(query)
        return (query or "").strip()

    def _source_query_format_issue(self, query: str) -> str:
        validation = validate_source_query(self.data_source, query)
        return "" if validation.ok else validation.issue

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
        query, rationale = _query_response_from_json(raw)
        query = self._source_safe_query(self._apply_discipline_filter(query))
        self.last_query_audit = rationale
        issue = self._source_query_format_issue(query)
        if not issue:
            return query
        self._emit_log(f"{self._source_label()} query output looked malformed or truncated ({issue}); requesting a replacement.")
        repaired = self._retry_malformed_source_query(
            question,
            query,
            current_query=current_query,
            feedback=feedback,
            system_prompt=system_prompt,
            log_name=log_name,
            output_label=output_label,
            operation=operation,
            issue=issue,
        )
        if repaired:
            return repaired
        self.last_query_audit = ""
        if current_query:
            return current_query
        raise LLMError(f"{self._source_label()} query generation failed: LLM did not return valid JSON with a query field.")

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
        if not system_prompt:
            system_prompt = self._syntax_repair_prompt()
        retry_log = f"{log_name}_format_retry" if log_name else f"{self.data_source}_query_format_retry"
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Research question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Previous valid query: {current_query or '(none)'}\n"
                    f"Rejected malformed {operation} output: {malformed_query or '(empty)'}\n"
                    f"Format problem: {issue or 'malformed or truncated output'}.\n\n"
                    f"Generate a complete replacement {output_label}. "
                    "Do not return a fragment. Keep quotation marks and parentheses balanced."
                    f"{self._strict_query_output_instruction(output_label)}"
                ),
            },
        ]
        self._llm_request_log(retry_log)
        try:
            proposal = None
            if pydantic_ai_query_retry_enabled():
                try:
                    proposal = run_query_proposal_agent(
                        self.llm,
                        messages,
                        temperature=self._query_temperature(),
                        retries=1,
                        model_name=f"paperseek-{self.data_source}-query-retry",
                    )
                except PydanticAIAdapterUnavailable as exc:
                    self._emit_log(f"PydanticAI query retry unavailable; using native JSON retry: {exc}")
            if proposal is not None:
                raw = ""
                query, rationale = proposal.query, proposal.rationale
            else:
                raw = self._chat_query_json(messages)
                query, rationale = _query_response_from_json(raw)
            self._llm_response_log(retry_log)
        except Exception as exc:
            self._emit_log(f"{self._source_label()} query format retry skipped after LLM error: {exc}")
            return ""
        query = self._source_safe_query(self._apply_discipline_filter(query))
        self.last_query_audit = rationale
        if query and not self._source_query_format_issue(query):
            return query
        self._emit_log(f"{self._source_label()} query format retry returned another malformed query; keeping the previous valid query.")
        self.last_query_audit = ""
        return ""

    def _repair_query_after_provider_error(self, question: str, query: str, error: ProviderError) -> str:
        if self.data_source == "openalex":
            sanitized = _sanitize_openalex_query(query)
            if sanitized and not self._source_query_format_issue(sanitized) and not _queries_equivalent(query, sanitized):
                return sanitized
        if not self._is_repairable_provider_error(error):
            return ""
        return self._repair_source_query_syntax(question, query, error)

    def _is_repairable_provider_error(self, error: ProviderError) -> bool:
        text = _provider_error_text(error).lower()
        if error.status in (400, 422):
            return True
        markers = (
            "invalid query",
            "invalid query parameters",
            "syntax",
            "wildcard",
            "parse",
            "unbalanced",
            "unsupported",
            "malformed",
            "bad query",
        )
        return any(marker in text for marker in markers)

    def _repair_source_query_syntax(self, question: str, query: str, error: ProviderError) -> str:
        source_label = self._source_label()
        error_text = _provider_error_text(error)
        messages = [
            {
                "role": "system",
                "content": self._syntax_repair_prompt(),
            },
            {
                "role": "user",
                "content": (
                    f"Source: {source_label}\n"
                    f"Research question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"Rejected query:\n{query}\n\n"
                    f"API error:\n{error_text[:1200]}\n\n"
                    "Return exactly one corrected query string that preserves the research intent "
                    "and follows the source API rules."
                    f"{self._strict_query_output_instruction('corrected source query string')}"
                ),
            },
        ]
        self._llm_request_log(f"{self.data_source}_query_syntax_repair")
        try:
            raw = self._chat_query_json(messages)
            self._llm_response_log(f"{self.data_source}_query_syntax_repair")
        except Exception as exc:
            self._emit_log(f"{source_label} query syntax repair skipped after LLM error: {exc}")
            return ""
        repaired, rationale = _query_response_from_json(raw)
        repaired = self._source_safe_query(self._apply_discipline_filter(repaired))
        self.last_query_audit = rationale
        if not repaired or self._source_query_format_issue(repaired):
            self.last_query_audit = ""
            return ""
        return repaired

    def _syntax_repair_prompt(self) -> str:
        if self.data_source == "openalex":
            return (
                SYSTEM_OPENALEX_QUERY_GENERATION
                + "\nRepair task: correct only syntax that the OpenAlex /works search parameter rejected. "
                "Keep the output as a single search= query value. Do not use search.exact, filters, wildcards, URLs, or API parameters."
            )
        if self.data_source == "crossref":
            return (
                SYSTEM_CROSSREF_QUERY_GENERATION
                + "\nRepair task: convert the rejected text into a valid Crossref query.bibliographic value. "
                "Keep plain bibliographic terms only."
            )
        if self.data_source == "arxiv":
            return SYSTEM_ARXIV_QUERY_GENERATION + "\nRepair task: return a valid arXiv search_query value only."
        if self.data_source == "semanticscholar":
            return SYSTEM_SEMANTIC_SCHOLAR_QUERY_GENERATION + "\nRepair task: return a valid Semantic Scholar query value only."
        if self.data_source == "pubmed":
            return SYSTEM_PUBMED_QUERY_GENERATION + "\nRepair task: return a valid PubMed ESearch term value only."
        if self.data_source == "googlescholar":
            return SYSTEM_GOOGLE_SCHOLAR_QUERY_GENERATION + "\nRepair task: return a valid Google Scholar q value only."
        if self.data_source == "paperhub":
            return SYSTEM_PAPERHUB_QUERY_GENERATION + "\nRepair task: return valid plain PaperHub search text only."
        return SYSTEM_QUERY_GENERATION + "\nRepair task: return a valid Web of Science Starter API q value only."

    def _crawler_source_order(self) -> tuple[str, ...]:
        configured = getattr(self.config, "crawler_sources", ()) or ()
        if isinstance(configured, str):
            configured = re.split(r"[,;\s]+", configured)
        supported = set(supported_source_ids())
        ordered: list[str] = []
        for value in (self.data_source, *configured):
            source = str(value or "").strip().lower()
            if not source or source in ordered or source not in supported:
                continue
            if not supports_query_portfolio(source):
                continue
            if source == "wos" and source != self.data_source:
                continue
            ordered.append(source)
        return tuple(ordered or [self.data_source])

    def _provider_for_source(self, source: str):
        source = str(source or "").strip().lower()
        if source == self.data_source:
            return self.provider
        if source in self._source_providers:
            return self._source_providers[source]
        provider = None
        if source == "openalex":
            provider = OpenAlexProvider(
                api_key=getattr(self.config, "openalex_api_key", ""),
                email=getattr(self.config, "openalex_email", ""),
            )
        elif source == "crossref":
            provider = CrossrefProvider(email=getattr(self.config, "crossref_email", ""))
        elif source == "arxiv":
            provider = ArxivProvider()
        elif source == "semanticscholar":
            provider = SemanticScholarProvider(
                api_key=getattr(self.config, "semantic_scholar_api_key", "")
            )
        elif source == "pubmed":
            provider = PubMedProvider(
                api_key=getattr(self.config, "pubmed_api_key", ""),
                email=getattr(self.config, "pubmed_email", ""),
                tool=getattr(self.config, "pubmed_tool", "paperseek"),
            )
        elif source == "googlescholar":
            provider = GoogleScholarSerperProvider(
                api_key=getattr(self.config, "serper_api_key", "")
            )
        elif source == "paperhub":
            provider = PaperHubProvider()
        if provider is not None:
            self._source_providers[source] = provider
        return provider

    def _provider_search_lane_for_source(
        self,
        source: str,
        query: str,
        lane: str,
        limit: int,
        page: int = 1,
    ):
        source = str(source or "").strip().lower()
        if source == self.data_source:
            return self._provider_search_lane(query, lane, limit, page=page)
        provider = self._provider_for_source(source)
        if provider is None:
            raise ProviderError(source, f"No crawler provider is available for source={source}.", query=query)
        kwargs = {"query": query, "limit": limit, "page": page, "lane": lane}
        return self._call_provider_search_with(provider, **kwargs)

    def _provider_search_lane(self, query: str, lane: str, limit: int, page: int = 1):
        if self.data_source == "openalex":
            return self._call_provider_search(query=query, limit=limit, page=page, field_ids=openalex_field_ids(self.discipline_fields), lane=lane)
        if self.data_source == "crossref":
            return self._call_provider_search(query=query, limit=limit, page=page, lane=lane)
        if self.provider:
            return self._call_provider_search(query=query, limit=limit, page=page, lane=lane)
        sort_field = self._wos_sort_field_for_lane(lane)
        try:
            return self.documents_api.documents_get(
                q=query,
                db=self.config.wos_db,
                limit=limit,
                sort_field=sort_field,
            )
        except ApiException as exc:
            if exc.status == 429:
                self._emit_log("WoS Starter rate limit reached; waiting briefly before one retry.")
                time.sleep(2.0)
                return self.documents_api.documents_get(
                    q=query,
                    db=self.config.wos_db,
                    limit=limit,
                    sort_field=sort_field,
                )
            raise
        except Exception as exc:
            self._emit_log(f"WoS client parsing failed; retrying with the fallback JSON parser: {exc.__class__.__name__}.")
            return self._wos_raw_search(query, limit=limit, sort_field=sort_field)

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

    @staticmethod
    def _wos_sort_field_for_lane(lane: str) -> str:
        if lane == RetrievalLane.IMPACT:
            return "TC+D"
        if lane == RetrievalLane.RECENT:
            return "PY+D"
        return "RS+D"

    def _wos_raw_search(self, query: str, limit: Optional[int] = None, sort_field: str = "RS+D") -> ProviderSearchResult:
        limit = limit or self._candidate_limit()
        response = requests.get(
            "https://api.clarivate.com/apis/wos-starter/v1/documents",
            params={"q": query, "db": self.config.wos_db, "limit": limit, "sortField": sort_field},
            headers={"Accept": "application/json", "X-ApiKey": self.config.wos_api_key},
            timeout=45,
        )
        if response.status_code == 429:
            self._emit_log("WoS Starter raw request rate limited; waiting briefly before one retry.")
            time.sleep(2.0)
            response = requests.get(
                "https://api.clarivate.com/apis/wos-starter/v1/documents",
                params={"q": query, "db": self.config.wos_db, "limit": limit, "sortField": sort_field},
                headers={"Accept": "application/json", "X-ApiKey": self.config.wos_api_key},
                timeout=45,
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ApiException(status=response.status_code, reason=response.reason, body=response.text)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiException(status=response.status_code, reason="Invalid JSON response", body=response.text) from exc
        return _wos_result_from_json(payload, limit)

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
        capabilities = self._retrieval_capabilities()
        lane_limits = {
            lane: self._effective_lane_limit(capabilities, lane)
            for lane in capabilities.lanes
        }
        lane_results: Dict[str, list] = {}
        lane_total = max(1, len(capabilities.lanes))
        try:
            lane_concurrency = max(
                1,
                min(
                    len(capabilities.lanes),
                    int(getattr(capabilities, "lane_concurrency", 1) or 1),
                ),
            )
        except (TypeError, ValueError):
            lane_concurrency = 1
        self._emit_ranking_step(
            "multi_lane_retrieval",
            "processing",
            "Multi-lane retrieval",
            current=0,
            total=lane_total,
            detail=(
                f"Starting {', '.join(capabilities.lanes)} lanes; lane limits {lane_limits}; "
                f"concurrency {lane_concurrency}."
            ),
        )
        self._emit_log(
            "Lightweight multi-lane retrieval started: "
            f"source={self.data_source}; lanes={','.join(capabilities.lanes)}; lane_limits={lane_limits}; "
            f"lane_concurrency={lane_concurrency}; pool_max={self._retrieval_pool_max()}."
        )
        completed_lanes = 0
        self._retrieval_primary_hits = list(primary_hits or [])

        def collect_lane(lane: str) -> list:
            lane_query = question if lane == RetrievalLane.SEMANTIC else query
            return self._collect_retrieval_lane(lane_query, lane, lane_limits[lane])

        def record_lane_result(lane: str, documents: Optional[list] = None, error: Optional[Exception] = None) -> None:
            nonlocal completed_lanes
            if error is None:
                lane_results[lane] = list(documents or [])
                self._emit_log(f"Retrieval lane completed: {lane}; candidates={len(lane_results[lane])}.")
            else:
                self._emit_log(f"Retrieval lane skipped after error: {lane}; {error.__class__.__name__}: {error}")
            completed_lanes += 1
            self._emit_ranking_step(
                "multi_lane_retrieval",
                "processing",
                "Multi-lane retrieval",
                current=completed_lanes,
                total=lane_total,
                detail=f"{lane} lane finished; collected {sum(len(values) for values in lane_results.values())} lane candidates.",
                lane_counts={key: len(value) for key, value in lane_results.items()},
            )

        try:
            if lane_concurrency == 1:
                for lane in capabilities.lanes:
                    try:
                        record_lane_result(lane, collect_lane(lane))
                    except SearchCancelled:
                        raise
                    except Exception as exc:
                        record_lane_result(lane, error=exc)
            else:
                executor = ThreadPoolExecutor(max_workers=lane_concurrency)
                try:
                    future_to_lane = {
                        executor.submit(collect_lane, lane): lane
                        for lane in capabilities.lanes
                    }
                    pending = set(future_to_lane)
                    while pending:
                        done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                        self._check_cancelled()
                        for future in done:
                            lane = future_to_lane[future]
                            try:
                                record_lane_result(lane, future.result())
                            except SearchCancelled:
                                raise
                            except Exception as exc:
                                record_lane_result(lane, error=exc)
                except SearchCancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    executor = None
                    raise
                finally:
                    if executor is not None:
                        executor.shutdown(wait=True)
        finally:
            self._retrieval_primary_hits = []

        # Preserve capability order so equal-score fusion ties are stable even
        # when network requests complete in a different order.
        lane_results = {
            lane: lane_results[lane]
            for lane in capabilities.lanes
            if lane in lane_results
        }
        for view_id, documents in self.query_portfolio_lane_results.items():
            if documents:
                lane_results[f"query_view:{view_id}"] = self._dedupe_documents(documents)
        iteration_lanes = self._query_iteration_lanes(query)
        lane_results.update(iteration_lanes)
        if iteration_lanes:
            self._emit_log(
                "Query iteration memory added to candidate fusion: "
                f"lanes={len(iteration_lanes)}; candidates="
                f"{sum(len(documents) for documents in iteration_lanes.values())}."
            )
        if not lane_results and primary_hits:
            lane_results[RetrievalLane.RELEVANCE] = list(primary_hits or [])
        if not lane_results:
            self._emit_ranking_step(
                "multi_lane_retrieval",
                "complete",
                "Multi-lane retrieval",
                current=lane_total,
                total=lane_total,
                detail="No retrieval lanes returned candidates; using the primary source response.",
            )
            return list(primary_hits or [])

        ordered_docs = []
        for lane_docs in lane_results.values():
            ordered_docs.extend(lane_docs)
        unique_docs = self._dedupe_documents(ordered_docs)
        self._emit_ranking_step(
            "embedding_similarity",
            "processing",
            "Embedding similarity",
            current=0,
            total=max(1, len(unique_docs)),
            detail=f"Computing semantic similarity for {len(unique_docs)} unique candidates.",
        )
        embedding_scores = self._external_embedding_scores(question, unique_docs)
        self._emit_ranking_step(
            "embedding_similarity",
            "complete",
            "Embedding similarity",
            current=len(unique_docs),
            total=max(1, len(unique_docs)),
            detail="External embedding completed." if embedding_scores else "Using local sparse hashing similarity.",
        )
        self._emit_ranking_step(
            "rrf_fusion",
            "processing",
            "RRF fusion",
            current=0,
            total=max(1, len(unique_docs)),
            detail=f"Fusing lane rank, BM25/term coverage, and embedding signals for {len(unique_docs)} candidates.",
        )
        fused = fuse_candidates_rrf(
            question,
            lane_results,
            pool_max=self._retrieval_pool_max(),
            rrf_k=self._retrieval_rrf_k(),
            embedding_scores_by_key=self._embedding_score_map(unique_docs, embedding_scores),
        )
        self.retrieval_metadata_by_key = fused.metadata_by_key
        self._emit_ranking_step(
            "rrf_fusion",
            "complete",
            "RRF fusion",
            current=len(fused.documents),
            total=max(1, fused.total_candidates),
            detail=f"Fused {fused.total_candidates} unique candidates into a pool of {len(fused.documents)}.",
            lane_counts=fused.lane_counts,
            candidate_count=len(fused.documents),
        )
        fused_documents = self._maybe_crossref_enrich_candidates(fused.documents)
        fused_documents = self._apply_external_reranker(question, fused_documents)
        self._emit_log(
            "Lightweight multi-lane retrieval completed: "
            f"unique_candidates={fused.total_candidates}; fused_candidates={len(fused_documents)}; "
            f"lane_counts={fused.lane_counts}."
        )
        self._emit_ranking_step(
            "multi_lane_retrieval",
            "complete",
            "Multi-lane retrieval",
            current=lane_total,
            total=lane_total,
            detail=f"Retrieval completed with {len(fused_documents)} fused candidates.",
            lane_counts=fused.lane_counts,
            candidate_count=len(fused_documents),
        )
        return fused_documents

    def _refuse_candidates_after_citation(self, question: str, candidates: list) -> list:
        """Re-run local fusion so citation neighbors compete in the final ranking gate."""

        unique_candidates = self._dedupe_documents(list(candidates or []))
        if not unique_candidates or self.search_run_state is None:
            return unique_candidates

        ledger = self.search_run_state.candidate_queue.ledger
        citation_keys = {
            key
            for key, evidence in ledger.items()
            if any(self._is_citation_candidate_origin(origin) for origin in evidence.origins)
        }
        citation_documents = [
            document
            for document in unique_candidates
            if document_key(document) in citation_keys
        ]
        if not citation_documents:
            return unique_candidates

        documents_by_key = {
            document_key(document): document
            for document in unique_candidates
            if document_key(document)
        }
        ranked_lanes: Dict[str, list] = {}
        for key, document in documents_by_key.items():
            metadata = dict(self.retrieval_metadata_by_key.get(key, {}) or {})
            for lane, rank in dict(metadata.get("retrieval_source_ranks", {}) or {}).items():
                try:
                    lane_rank = int(rank)
                except (TypeError, ValueError):
                    continue
                ranked_lanes.setdefault(str(lane), []).append((lane_rank, key, document))

        lane_results: Dict[str, list] = {
            lane: [document for _, _, document in sorted(values, key=lambda item: (item[0], item[1]))]
            for lane, values in ranked_lanes.items()
            if values
        }
        pre_citation_documents = []
        for document in unique_candidates:
            key = document_key(document)
            evidence = ledger.get(key)
            origins = list(evidence.origins) if evidence is not None else []
            if not origins or any(not self._is_citation_candidate_origin(origin) for origin in origins):
                pre_citation_documents.append(document)
        if pre_citation_documents:
            lane_results[RetrievalLane.LOCAL_QUALITY] = pre_citation_documents
        lane_results[RetrievalLane.CITATION] = citation_documents

        self._emit_ranking_step(
            "citation_refusion",
            "processing",
            "Citation-aware candidate fusion",
            current=0,
            total=max(1, len(unique_candidates)),
            detail=(
                "Re-ranking the complete candidate pool after citation expansion with local BM25, "
                "sparse hashing similarity, and RRF."
            ),
            candidate_count=len(unique_candidates),
        )
        fused = fuse_candidates_rrf(
            question,
            lane_results,
            pool_max=self._retrieval_pool_max(),
            rrf_k=self._retrieval_rrf_k(),
        )
        prior_metadata = self.retrieval_metadata_by_key
        merged_metadata: Dict[str, Dict[str, Any]] = {}
        for key, metadata in fused.metadata_by_key.items():
            merged = {**dict(prior_metadata.get(key, {}) or {}), **dict(metadata or {})}
            if "rerank_score" in prior_metadata.get(key, {}):
                merged["rerank_score"] = prior_metadata[key]["rerank_score"]
            merged_metadata[key] = merged
        self.retrieval_metadata_by_key = merged_metadata
        self._refresh_candidate_retrieval_evidence(fused.documents)
        self._emit_log(
            "Citation-aware local fusion completed: "
            f"candidates={fused.total_candidates}; citation_candidates={len(citation_documents)}; "
            f"fused_candidates={len(fused.documents)}."
        )
        self._emit_ranking_step(
            "citation_refusion",
            "complete",
            "Citation-aware candidate fusion",
            current=len(fused.documents),
            total=max(1, fused.total_candidates),
            detail=(
                f"Re-fused {fused.total_candidates} candidates after citation expansion; "
                f"citation candidates={len(citation_documents)}."
            ),
            candidate_count=len(fused.documents),
            lane_counts=fused.lane_counts,
        )
        return fused.documents

    @staticmethod
    def _is_citation_candidate_origin(origin: str) -> bool:
        value = str(origin or "")
        return value == "citation_expansion" or value.startswith("citation_frontier:")

    def _refresh_candidate_retrieval_evidence(self, documents: list) -> None:
        if self.search_run_state is None:
            return
        queue = self.search_run_state.candidate_queue
        ledger = dict(queue.ledger)
        for document in documents or []:
            key = document_key(document)
            evidence = ledger.get(key)
            metadata = dict(self.retrieval_metadata_by_key.get(key, {}) or {})
            if not key or evidence is None or not metadata:
                continue
            retrieval_lanes = [str(value) for value in metadata.get("retrieval_lanes", []) if value]
            query_views = [
                lane.split(":", 1)[1]
                for lane in retrieval_lanes
                if lane.startswith("query_view:") and ":" in lane
            ]
            source_ranks = {
                str(lane): int(rank)
                for lane, rank in dict(metadata.get("retrieval_source_ranks", {}) or {}).items()
                if rank is not None
            }
            concept_coverage = {
                name: float(metadata.get(field, 0.0) or 0.0)
                for name, field in (
                    ("embedding", "retrieval_embedding_score"),
                    ("bm25", "retrieval_bm25_score"),
                    ("term", "retrieval_term_coverage"),
                    ("rrf", "retrieval_rrf_score"),
                    ("rrf_normalized", "retrieval_rrf_normalized"),
                    ("primary_prior", "retrieval_primary_prior"),
                )
            }
            ledger[key] = evidence.model_copy(
                update={
                    "query_views": self._merge_unique(evidence.query_views, query_views),
                    "retrieval_lanes": retrieval_lanes,
                    "source_ranks": source_ranks,
                    "concept_coverage": {**evidence.concept_coverage, **concept_coverage},
                    "retrieval_score": self._optional_float(metadata.get("retrieval_score")),
                    "rerank_score": (
                        self._optional_float(metadata.get("rerank_score"))
                        if "rerank_score" in metadata
                        else evidence.rerank_score
                    ),
                }
            )
        self.search_run_state = self.search_run_state.with_candidate_queue(
            queue.model_copy(update={"ledger": ledger})
        )

    def _maybe_crossref_enrich_candidates(self, documents: list) -> list:
        if not getattr(self.config, "retrieval_crossref_enrichment", False):
            return documents
        enriched = 0
        headers = {"Accept": "application/json", "User-Agent": "paperseek/1.0"}
        for document in documents[:100]:
            identifiers = getattr(document, "identifiers", None)
            doi = getattr(identifiers, "doi", "") if identifiers is not None else ""
            if not doi:
                continue
            try:
                response = requests.get(f"https://api.crossref.org/works/{doi}", headers=headers, timeout=20)
                if response.status_code < 200 or response.status_code >= 300:
                    continue
                message = (response.json().get("message") or {})
                cited = int(message.get("is-referenced-by-count") or 0)
                if cited and not getattr(document, "citations", None):
                    document.citations = [PaperCitation(db="Crossref", count=cited)]
                if getattr(document, "source", None) is not None and not getattr(document.source, "publish_year", None):
                    year = self._crossref_year(message)
                    if year:
                        document.source.publish_year = year
                enriched += 1
            except Exception:
                continue
        self._emit_log(f"Optional Crossref candidate enrichment completed: enriched={enriched}.")
        return documents

    @staticmethod
    def _crossref_year(message: dict) -> Optional[int]:
        for key in ("published-print", "published-online", "published", "issued"):
            parts = ((message.get(key) or {}).get("date-parts") or [])
            if parts and parts[0]:
                try:
                    return int(parts[0][0])
                except (TypeError, ValueError):
                    continue
        return None

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
        provider = (getattr(self.config, "retrieval_embedding_provider", "local") or "local").strip().lower()
        if provider in ("", "local", "python"):
            return None
        if not documents:
            return []
        api_key = self._retrieval_api_key("embedding", provider)
        base_url = self._retrieval_base_url("embedding", provider)
        if not api_key or not base_url:
            self._emit_log("External embedding skipped: provider configured but API key or base URL is missing; using local hashing embeddings.")
            return None
        texts = [question] + [document_text(document)[:1800] for document in documents]
        for model in self._retrieval_model_candidates("embedding", "qwen3-embedding:8b", provider):
            try:
                vectors = self._embedding_vectors(base_url, api_key, model, texts, provider=provider)
            except Exception as exc:
                self._emit_log(f"External embedding failed for model={model}; trying fallback if available: {exc}")
                continue
            if len(vectors) != len(texts):
                self._emit_log(f"External embedding returned an unexpected vector count for model={model}; trying fallback if available.")
                continue
            query_vector = vectors[0]
            self._emit_log(f"External embedding completed: provider={provider}; model={model}; documents={len(documents)}.")
            return [self._dense_cosine(query_vector, vector) for vector in vectors[1:]]
        self._emit_log("External embedding failed for all configured models; using local hashing embeddings.")
        return None

    @staticmethod
    def _embedding_score_map(documents: list, scores: Optional[List[float]]) -> Dict[str, float]:
        if not scores or len(scores) != len(documents):
            return {}
        output = {}
        for document, score in zip(documents, scores):
            key = document_key(document)
            if key:
                output[key] = score
        return output

    def _post_external_api(
        self,
        url: str,
        api_key: str,
        headers_factory: Callable[[str], Dict[str, str]],
        payload: Dict[str, Any],
        *,
        timeout: int = 60,
        label: str = "External API",
    ):
        attempts = _external_api_key_attempts(api_key)
        last_error = None
        for attempt_index, key in enumerate(attempts, 1):
            try:
                response = requests.post(url, headers=headers_factory(key), json=payload, timeout=timeout)
            except requests.RequestException as exc:
                last_error = exc
                if attempt_index < len(attempts):
                    self._emit_log(f"{label} request failed; retrying with another key ({attempt_index}/{len(attempts)}): {exc}")
                    continue
                raise
            if (
                response.status_code < 200 or response.status_code >= 300
            ) and attempt_index < len(attempts) and _retryable_external_status(response.status_code):
                self._emit_log(
                    f"{label} request returned HTTP {response.status_code}; "
                    f"retrying with another key ({attempt_index}/{len(attempts)})."
                )
                last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
                continue
            return response
        if last_error:
            raise last_error
        return requests.post(url, headers=headers_factory(""), json=payload, timeout=timeout)

    def _embedding_vectors(self, base_url: str, api_key: str, model: str, texts: list, provider: str = "") -> List[List[float]]:
        if (provider or "").strip().lower() == "nvidia":
            return self._nvidia_embedding_vectors(base_url, api_key, model, texts)
        vectors: List[List[float]] = []
        url = f"{base_url.rstrip('/')}/embeddings"
        batch_size = 64
        for offset in range(0, len(texts), batch_size):
            batch = texts[offset:offset + batch_size]
            response = self._post_external_api(
                url,
                api_key,
                lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                {"model": model, "input": batch, "encoding_format": "float"},
                timeout=60,
                label="External embedding",
            )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            payload = response.json()
            data = payload.get("data") or []
            data = sorted(data, key=lambda item: int(item.get("index", 0))) if all(isinstance(item, dict) for item in data) else data
            for item in data:
                embedding = item.get("embedding") if isinstance(item, dict) else None
                if not isinstance(embedding, list):
                    raise RuntimeError("embedding response item has no embedding vector")
                vectors.append([float(value) for value in embedding])
        return vectors

    def _nvidia_embedding_vectors(self, base_url: str, api_key: str, model: str, texts: list) -> List[List[float]]:
        url = f"{base_url.rstrip('/')}/embeddings"

        def request_vectors(batch: list, input_type: str) -> List[List[float]]:
            response = self._post_external_api(
                url,
                api_key,
                lambda key: {"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"},
                {"model": model, "input": batch, "input_type": input_type, "encoding_format": "float"},
                timeout=60,
                label="NVIDIA embedding",
            )
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            payload = response.json()
            data = payload.get("data") or []
            data = sorted(data, key=lambda item: int(item.get("index", 0))) if all(isinstance(item, dict) for item in data) else data
            vectors = []
            for item in data:
                embedding = item.get("embedding") if isinstance(item, dict) else None
                if not isinstance(embedding, list):
                    raise RuntimeError("embedding response item has no embedding vector")
                vectors.append([float(value) for value in embedding])
            return vectors

        vectors: List[List[float]] = []
        if texts:
            vectors.extend(request_vectors(texts[:1], "query"))
        batch_size = 64
        for offset in range(1, len(texts), batch_size):
            vectors.extend(request_vectors(texts[offset:offset + batch_size], "passage"))
        return vectors

    def _apply_external_reranker(self, question: str, documents: list) -> list:
        provider = (getattr(self.config, "retrieval_reranker_provider", "") or "").strip().lower()
        if provider in ("", "none", "off") or not documents:
            return documents
        self._emit_ranking_step(
            "external_reranker",
            "processing",
            "External reranker",
            current=0,
            total=max(1, min(200, len(documents))),
            detail=f"Calling {provider} reranker for the top {min(200, len(documents))} candidates.",
        )
        if provider == "modelscope":
            self._emit_log("External reranker skipped: ModelScope API-Inference does not support rerank.")
            self._emit_ranking_step(
                "external_reranker",
                "skipped",
                "External reranker",
                current=0,
                total=max(1, min(200, len(documents))),
                detail="ModelScope API-Inference does not support rerank; keeping RRF order.",
            )
            return documents
        api_key = self._retrieval_api_key("reranker", provider)
        base_url = self._retrieval_base_url("reranker", provider)
        if not api_key or not base_url:
            self._emit_log("External reranker skipped: provider configured but API key or base URL is missing.")
            self._emit_ranking_step(
                "external_reranker",
                "skipped",
                "External reranker",
                current=0,
                total=max(1, min(200, len(documents))),
                detail="Reranker API key or base URL is missing; keeping RRF order.",
            )
            return documents
        rerank_count = min(200, len(documents))
        texts = [document_text(document)[:1800] for document in documents[:rerank_count]]
        for model in self._retrieval_model_candidates("reranker", "qwen3-reranker:8b", provider):
            try:
                if provider == "nvidia":
                    endpoint = base_url.rstrip("/")
                    if not (endpoint.endswith("/reranking") or endpoint.endswith("/ranking")):
                        endpoint = f"{endpoint}/reranking"
                    response = self._post_external_api(
                        endpoint,
                        api_key,
                        lambda key: {"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"},
                        {"model": model, "query": {"text": question}, "passages": [{"text": text} for text in texts]},
                        timeout=60,
                        label="External reranker",
                    )
                else:
                    response = self._post_external_api(
                        f"{base_url.rstrip('/')}/rerank",
                        api_key,
                        lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        {"model": model, "query": question, "documents": texts, "top_n": rerank_count},
                        timeout=60,
                        label="External reranker",
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
                payload = response.json()
                results = (payload.get("rankings") or []) if provider == "nvidia" else (payload.get("results") or payload.get("data") or [])
                ranked = []
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    index = item.get("index")
                    score = item.get("logit", item.get("relevance_score", item.get("score", 0)))
                    if isinstance(index, int) and 0 <= index < rerank_count:
                        ranked.append((float(score or 0), index))
                if not ranked:
                    raise RuntimeError("reranker response contained no indexed scores")
                ranked.sort(reverse=True)
                used = {index for _, index in ranked}
                for score, index in ranked:
                    key = document_key(documents[index])
                    if key:
                        self.retrieval_metadata_by_key.setdefault(key, {})["rerank_score"] = float(score)
                reranked_docs = [documents[index] for _, index in ranked]
                reranked_docs.extend(documents[index] for index in range(rerank_count) if index not in used)
                reranked_docs.extend(documents[rerank_count:])
                self._emit_log(f"External reranker completed: provider={provider}; model={model}; reranked={rerank_count}.")
                self._emit_ranking_step(
                    "external_reranker",
                    "complete",
                    "External reranker",
                    current=rerank_count,
                    total=max(1, rerank_count),
                    detail=f"{provider} reranker completed with model={model}.",
                    candidate_count=len(reranked_docs),
                )
                return reranked_docs
            except Exception as exc:
                self._emit_log(f"External reranker failed for model={model}; trying fallback if available: {exc}")
        self._emit_log("External reranker failed for all configured models; keeping RRF order.")
        self._emit_ranking_step(
            "external_reranker",
            "error",
            "External reranker",
            current=0,
            total=max(1, rerank_count),
            detail="All configured reranker models failed; keeping RRF order.",
        )
        return documents

    def _retrieval_model_candidates(self, kind: str, default_model: str, provider: str = "") -> List[str]:
        raw = getattr(self.config, f"retrieval_{kind}_model", "") or default_model
        provider = (provider or "").strip().lower()
        if kind == "embedding" and provider == "modelscope":
            modelscope_models = "Qwen/Qwen3-Embedding-8B,Qwen/Qwen3-Embedding-4B"
            if raw in ("", default_model, "qwen3-embedding:8b,bge-large-zh:latest", "BAAI/bge-large-zh-v1.5"):
                raw = modelscope_models
        if kind == "embedding" and provider == "nvidia":
            if raw in ("", default_model, "qwen3-embedding:8b", "qwen3-embedding:8b,bge-large-zh:latest"):
                raw = "nvidia/nv-embedqa-e5-v5"
            elif raw == "nv-embed-v1":
                raw = "nvidia/nv-embed-v1"
        if kind == "embedding" and provider == "openrouter":
            if raw in ("", default_model, "qwen3-embedding:8b", "qwen3-embedding:8b,bge-large-zh:latest"):
                raw = "openai/text-embedding-3-small"
        if kind == "reranker" and provider == "nvidia":
            if raw in ("", default_model, "qwen3-reranker:8b", "BAAI/bge-reranker-v2-m3"):
                raw = "nv-rerank-qa-mistral-4b:1"
        if kind == "reranker" and provider == "openrouter":
            if raw in ("", default_model, "qwen3-reranker:8b", "BAAI/bge-reranker-v2-m3"):
                raw = "jinaai/jina-reranker-v2-base-multilingual"
        candidates = []
        for part in str(raw).replace(";", ",").split(","):
            value = part.strip()
            if value and value not in candidates:
                candidates.append(value)
        return candidates or [default_model]

    def _retrieval_api_key(self, kind: str, provider: str) -> str:
        attr = f"retrieval_{kind}_api_key"
        value = getattr(self.config, attr, "") or ""
        if value:
            return value
        if provider in (
            "cstcloud",
            "openai",
            "dashscope",
            "siliconflow",
            "openrouter",
            "huggingface",
            "nvidia",
            "zhipu",
            "volcengine",
            "modelscope",
            "custom",
        ):
            return getattr(self.config, "llm_api_key", "") or ""
        return ""

    def _retrieval_base_url(self, kind: str, provider: str) -> str:
        attr = f"retrieval_{kind}_base_url"
        value = getattr(self.config, attr, "") or ""
        if value:
            return value
        if kind == "reranker" and provider == "modelscope":
            return ""
        provider_urls = {
            "cstcloud": "https://uni-api.cstcloud.cn/v1",
            "openai": "https://api.openai.com/v1",
            "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "siliconflow": "https://api.siliconflow.cn/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "huggingface": "https://router.huggingface.co/v1",
            "nvidia": "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking" if kind == "reranker" else "https://integrate.api.nvidia.com/v1",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4",
            "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
            "modelscope": "https://api-inference.modelscope.cn/v1",
        }
        if provider in provider_urls:
            return provider_urls[provider]
        if provider == "custom":
            return getattr(self.config, "llm_base_url", "") or ""
        return ""

    @staticmethod
    def _dense_cosine(left: list, right: list) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
        right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return max(0.0, min(1.0, dot / (left_norm * right_norm)))

    @staticmethod
    def _citation_seed_key(doc) -> str:
        if not doc:
            return ""
        identifiers = getattr(doc, "identifiers", None)
        for value in (
            getattr(identifiers, "openalex", "") if identifiers else "",
            getattr(identifiers, "doi", "") if identifiers else "",
            getattr(doc, "uid", ""),
            getattr(doc, "title", ""),
        ):
            normalized = str(value or "").strip().lower()
            if normalized:
                return normalized
        return ""

    def _build_citation_seed_plans(self, seed_ranked: list, candidates: list, plan) -> list:
        seed_limit = max(1, int(getattr(plan, "seed_limit", 1) or 1))
        depth = max(1, min(int(getattr(plan, "depth", 1) or 1), 3))
        relevance_quota = max(1, int(getattr(plan, "relevance_quota", seed_limit // 2) or 1))
        impact_quota = max(0, int(getattr(plan, "impact_quota", 0) or 0))
        recent_quota = max(0, int(getattr(plan, "recent_quota", max(0, seed_limit - relevance_quota - impact_quota)) or 0))
        plans: List[CitationSeedPlan] = []
        index_by_key: Dict[str, CitationSeedPlan] = {}

        def add_plan(doc, role: str, directions: Tuple[str, ...]):
            if not doc or len(plans) >= seed_limit and self._citation_seed_key(doc) not in index_by_key:
                return
            key = self._citation_seed_key(doc)
            if not key:
                return
            existing = index_by_key.get(key)
            if existing:
                merged = []
                for direction in tuple(existing.directions) + tuple(directions):
                    if direction not in merged:
                        merged.append(direction)
                existing.directions = tuple(merged)
                if role not in existing.role.split("+"):
                    existing.role = f"{existing.role}+{role}"
                existing.depth = max(existing.depth, depth)
                return
            if len(plans) >= seed_limit:
                return
            plan = CitationSeedPlan(record=doc, role=role, directions=directions, depth=depth)
            index_by_key[key] = plan
            plans.append(plan)

        relevance_docs = [
            entry.get("document")
            for entry in seed_ranked
            if entry.get("document") is not None and float(entry.get("score") or 0) >= 7
        ]
        if len(relevance_docs) < relevance_quota:
            for entry in seed_ranked:
                doc = entry.get("document")
                if doc is not None and doc not in relevance_docs:
                    relevance_docs.append(doc)
                if len(relevance_docs) >= relevance_quota:
                    break
        for doc in relevance_docs[:relevance_quota]:
            add_plan(doc, "relevance", ("backward", "forward"))

        impact_docs = sorted(
            candidates or [],
            key=lambda doc: (_citation_count(doc), getattr(getattr(doc, "source", None), "publish_year", 0) or 0),
            reverse=True,
        )
        for doc in impact_docs[:impact_quota]:
            add_plan(doc, "impact", ("backward",))

        recent_docs = sorted(
            candidates or [],
            key=lambda doc: (getattr(getattr(doc, "source", None), "publish_year", 0) or 0, _citation_count(doc)),
            reverse=True,
        )
        for doc in recent_docs[:recent_quota]:
            add_plan(doc, "recent", ("forward",))

        if len(plans) < seed_limit:
            for entry in seed_ranked:
                add_plan(entry.get("document"), "relevance", ("backward", "forward"))
                if len(plans) >= seed_limit:
                    break

        buckets: Dict[str, List[CitationSeedPlan]] = {"relevance": [], "impact": [], "recent": []}
        for seed_plan in plans:
            roles = set(str(seed_plan.role or "relevance").split("+"))
            bucket = "recent" if "recent" in roles else "impact" if "impact" in roles else "relevance"
            buckets[bucket].append(seed_plan)
        interleaved: List[CitationSeedPlan] = []
        while any(buckets.values()):
            for role in ("relevance", "impact", "recent"):
                if buckets[role]:
                    interleaved.append(buckets[role].pop(0))
        return interleaved

    @staticmethod
    def _citation_seed_plan_counts(seed_plans: list) -> dict:
        counts: Dict[str, int] = {"relevance": 0, "impact": 0, "recent": 0}
        for plan in seed_plans or []:
            for role in str(getattr(plan, "role", "") or "").split("+"):
                if role in counts:
                    counts[role] += 1
        return counts

    def _prepare_candidates(self, question: str, hits: list) -> list:
        dynamic_citations = (
            bool(getattr(self.config, "crawler_enabled", False))
            and self._candidate_selector_active()
            and bool(getattr(self.config, "citation_feedback_enabled", False))
        )
        if dynamic_citations:
            return self._prepare_candidates_frontier(question, hits)
        candidates = self._prepare_candidates_legacy(question, hits)
        if not self._candidate_selector_active():
            return candidates
        self._select_candidate_batch(
            question,
            self._crawler_selector_sample(candidates),
            "candidate_preparation",
        )
        selected = self._selector_filtered_candidates(candidates)
        excluded = len(candidates) - len(selected)
        if excluded:
            self._emit_log(
                f"Candidate Selector excluded {excluded} candidates before final LLM ranking; "
                f"retained={len(selected)}."
            )
        return selected

    def _prepare_candidates_frontier(self, question: str, hits: list) -> list:
        candidates = self._dedupe_documents(hits or [])
        if not self.search_run_state.action_frontier.outcomes:
            self.citation_map = self._empty_citation_map(
                enabled=getattr(self.config, "expand_citations", True),
                initial_candidates=len(candidates),
                candidate_pool=len(candidates),
            )
        self._enqueue_candidate_queue(candidates, "candidate_retrieval")
        initial_batch = self._select_candidate_batch(
            question,
            self._crawler_selector_sample(candidates),
            "candidate_retrieval",
        )
        documents_by_key = {
            document_key(document): document
            for document in candidates
            if document_key(document)
        }
        candidate_depths = {key: 0 for key in documents_by_key}

        supported_actions = {"read", "enrich"}
        if self.data_source == "openalex" and getattr(self.config, "expand_citations", True):
            supported_actions.update({"expand_backward", "expand_forward"})
        frontier_state = self.search_run_state.action_frontier
        scheduler = FrontierScheduler(
            frontier_state,
            low_yield_round_limit=max(1, int(getattr(self.config, "crawler_low_yield_round_limit", 2) or 2)),
        )
        controller = CrawlerController(
            self.search_plan,
            self.data_source,
            scheduler,
            state=self.search_run_state.crawler_state,
            supported_actions=supported_actions,
            max_citation_depth=max(0, min(int(getattr(self.config, "citation_depth", 2) or 2), 3)),
        )
        controller.observe_selector(
            initial_batch,
            allow_follow_up_actions=True,
            candidate_depths=candidate_depths,
        )

        if "expand_backward" in supported_actions:
            roles = self._frontier_citation_seed_roles(candidates, initial_batch)
            controller.seed_citation_actions(
                initial_batch,
                roles_by_candidate=roles,
                candidate_depths=candidate_depths,
                max_actions=max(1, int(getattr(self.config, "crawler_max_citation_requests", 8) or 8)),
            )

        citation_nodes: dict[str, dict] = {}
        citation_edges: list[dict] = []
        citation_edge_keys: set[tuple] = set()

        def sync_controller_state() -> None:
            self.search_run_state = self.search_run_state.with_action_frontier(
                controller.scheduler.snapshot()
            ).with_crawler_state(controller.state)

        def reader_handler(action) -> ToolExecution:
            document = documents_by_key.get(action.candidate_id)
            if document is None:
                return ToolExecution(action=action, status="skipped", error="candidate_not_found")
            if str(getattr(document, "abstract", "") or "").strip():
                return ToolExecution(
                    action=action,
                    status="done",
                    records=[document],
                    total=1,
                    metadata={"changed": False, "reason": "abstract_already_available"},
                )
            identifiers = getattr(document, "identifiers", None)
            doi = str(getattr(identifiers, "doi", "") or "") if identifiers else ""
            if not doi:
                return ToolExecution(action=action, status="skipped", error="no_doi_for_abstract_enrichment")
            abstract = self.abstract_fetcher.fetch(doi)
            if not abstract:
                return ToolExecution(action=action, status="done", records=[document], total=1, metadata={"changed": False})
            document.abstract = abstract
            return ToolExecution(action=action, status="done", records=[document], total=1, metadata={"changed": True})

        def citation_handler(action) -> ToolExecution:
            document = documents_by_key.get(action.candidate_id)
            if document is None:
                return ToolExecution(action=action, status="skipped", error="citation_seed_not_found")
            direction = "backward" if action.action_type == "expand_backward" else "forward"
            per_seed = max(1, min(int(getattr(self.config, "citation_per_seed", 4) or 4), 10))
            plan = CitationSeedPlan(
                record=document,
                role="selector",
                directions=(direction,),
                depth=1,
            )
            data = self.provider.citation_neighbors_with_graph(
                [document],
                per_seed=per_seed,
                max_records=per_seed,
                field_ids=openalex_field_ids(self.discipline_fields),
                seed_plans=[plan],
                depth=1,
                cancel_check=self._check_cancelled,
                request_attempts=1,
                request_timeout=10,
            )
            return ToolExecution(
                action=action,
                status="done",
                records=list(data.get("records") or []),
                total=len(data.get("records") or []),
                metadata={key: value for key, value in data.items() if key != "records"},
            )

        handlers = {"read": reader_handler, "enrich": reader_handler}
        if "expand_backward" in supported_actions:
            handlers.update({"expand_backward": citation_handler, "expand_forward": citation_handler})
        executor = ToolExecutor(handlers, passthrough_exceptions=(SearchCancelled,))

        self._emit_log(
            f"Candidate feedback frontier started: pending_actions="
            f"{sum(1 for action in controller.scheduler.state.actions if action.status == 'pending')}; "
            f"supported={','.join(sorted(supported_actions))}."
        )
        self._emit_ranking_step(
            "candidate_feedback",
            "processing",
            "Candidate feedback loop",
            current=0,
            total=max(1, len(controller.scheduler.state.actions)),
            detail="Selecting, enriching, and expanding high-value candidates under a shared frontier budget.",
        )
        feedback_results: Dict[str, dict] = {}

        def select_feedback_action(action, result) -> FrontierOutcome:
            selector_batch = SelectorBatch()
            added_documents: list = []
            gaps_before = set(controller.concept_gaps())
            ledger_before = self.search_run_state.candidate_queue.ledger if self.search_run_state else {}
            labels_before = {
                document_key(document): ledger_before[document_key(document)].selector_label
                for document in result.records
                if document_key(document) in ledger_before
            }
            if result.status == "done" and action.action_type in {"read", "enrich"}:
                selector_batch = self._select_candidate_batch(
                    question,
                    result.records,
                    f"frontier:{action.action_type}",
                )
            elif result.status == "done" and action.action_type.startswith("expand_"):
                evidence_by_key = self._citation_evidence_by_key(
                    result.records,
                    {
                        "edges": result.metadata.get("edges") or [],
                        "nodes": result.metadata.get("nodes") or [],
                    },
                )
                for evidence in evidence_by_key.values():
                    for path in evidence.get("citation_paths") or []:
                        path["depth"] = action.depth
                newly_queued = self._enqueue_candidate_queue(
                    result.records,
                    f"citation_frontier:{action.action_type}",
                    evidence_by_key=evidence_by_key,
                )
                for document in newly_queued:
                    key = document_key(document)
                    if not key or key in documents_by_key:
                        continue
                    documents_by_key[key] = document
                    candidate_depths[key] = action.depth
                    candidates.append(document)
                    added_documents.append(document)
                selector_batch = self._select_candidate_batch(
                    question,
                    added_documents,
                    f"citation_frontier:{action.action_type}",
                )
                for node in result.metadata.get("nodes") or []:
                    node_id = str(node.get("id") or "") if isinstance(node, dict) else ""
                    if node_id:
                        citation_nodes[node_id] = dict(node)
                for edge in result.metadata.get("edges") or []:
                    if not isinstance(edge, dict):
                        continue
                    edge_key = (
                        edge.get("source"),
                        edge.get("target"),
                        edge.get("direction"),
                    )
                    if edge_key not in citation_edge_keys:
                        citation_edge_keys.add(edge_key)
                        citation_edges.append(dict(edge))

            if selector_batch.decisions:
                controller.observe_selector(
                    selector_batch,
                    allow_follow_up_actions=True,
                    candidate_depths=candidate_depths,
                )
                if added_documents and "expand_backward" in supported_actions:
                    remaining_citation_actions = max(
                        0,
                        controller.scheduler.state.budget.max_citation_requests
                        - controller.scheduler.state.budget.citation_requests,
                    )
                    controller.seed_citation_actions(
                        selector_batch,
                        roles_by_candidate=self._frontier_citation_seed_roles(
                            added_documents,
                            selector_batch,
                        ),
                        candidate_depths=candidate_depths,
                        max_actions=remaining_citation_actions,
                    )
            gaps_after = set(controller.concept_gaps())
            counts = selector_batch.label_counts()
            newly_relevant = sum(
                1
                for decision in selector_batch.decisions
                if decision.label == "include" and labels_before.get(decision.candidate_id) != "include"
            )
            feedback_results[action.action_id] = {
                "counts": counts,
                "added_documents": added_documents,
            }
            return FrontierOutcome(
                action_id=action.action_id,
                status="done" if result.status == "done" else ("skipped" if result.status == "skipped" else "failed"),
                candidates_seen=len(result.records),
                added_unique=len(added_documents),
                include_count=counts.get("include", 0),
                uncertain_count=counts.get("uncertain", 0),
                exclude_count=counts.get("exclude", 0),
                newly_relevant_count=newly_relevant,
                concept_gap_reduction=len(gaps_before - gaps_after),
                elapsed_ms=result.elapsed_ms,
                error=result.error,
            )

        processed = 0
        while True:
            self._check_cancelled()
            cycle = self.search_loop.run_frontier_cycle(
                controller,
                executor.execute,
                select_feedback_action,
                passthrough_exceptions=(SearchCancelled,),
            )
            if not cycle.scheduled or cycle.action is None:
                break
            action = cycle.action
            feedback = feedback_results.pop(action.action_id, {})
            counts = feedback.get("counts") or {"include": 0, "uncertain": 0, "exclude": 0}
            added_documents = feedback.get("added_documents") or []
            sync_controller_state()
            processed += 1
            self._emit_ranking_step(
                "candidate_feedback",
                "processing",
                "Candidate feedback loop",
                current=processed,
                total=max(processed, len(controller.scheduler.state.actions)),
                detail=(
                    f"Completed {action.action_type}; added={len(added_documents)}; "
                    f"include={counts.get('include', 0)}; uncertain={counts.get('uncertain', 0)}."
                ),
            )
            self._save_checkpoint(
                "citation_layer",
                records=self._selector_filtered_candidates(candidates),
                metadata={
                    "resume_from_stage": "candidate_feedback",
                    "action_id": action.action_id,
                    "frontier_round": controller.scheduler.state.round_index,
                },
            )

        selected = self._selector_filtered_candidates(self._dedupe_documents(candidates))
        citation_outcomes = [
            outcome
            for outcome in controller.scheduler.state.outcomes
            if next(
                (
                    action.action_type.startswith("expand_")
                    for action in controller.scheduler.state.actions
                    if action.action_id == outcome.action_id
                ),
                False,
            )
        ]
        if any(outcome.added_unique for outcome in citation_outcomes):
            selected = self._refuse_candidates_after_citation(question, selected)
        self.citation_map.update(
            {
                "supported": self.data_source == "openalex",
                "status": "complete" if citation_outcomes else "skipped",
                "added_candidates": sum(outcome.added_unique for outcome in citation_outcomes),
                "candidate_pool": len(selected),
                "nodes": list(citation_nodes.values()),
                "edges": citation_edges,
                "frontier": controller.scheduler.state.model_dump(mode="json"),
            }
        )
        self._emit_log(
            f"Candidate feedback frontier completed: actions={processed}; retained={len(selected)}; "
            f"excluded={len(candidates) - len(selected)}; stop={controller.scheduler.state.stop_reason or 'frontier_empty'}."
        )
        self._emit_ranking_step(
            "candidate_feedback",
            "complete",
            "Candidate feedback loop",
            current=processed,
            total=max(1, processed),
            detail=f"Retained {len(selected)} include/uncertain candidates for final ranking.",
            candidate_count=len(selected),
        )
        return selected

    def _frontier_citation_seed_roles(self, documents: list, batch: SelectorBatch) -> dict[str, list[str]]:
        decisions = {decision.candidate_id: decision for decision in batch.decisions if decision.label != "exclude"}
        if not decisions:
            return {}
        try:
            seed_limit = max(1, int(getattr(self.config, "citation_seed_count", 30) or 30))
        except (TypeError, ValueError):
            seed_limit = 30
        eligible = [document for document in documents if document_key(document) in decisions]
        relevance = sorted(
            eligible,
            key=lambda document: (-decisions[document_key(document)].relevance_score, document_key(document)),
        )[:seed_limit]
        impact = sorted(
            eligible,
            key=lambda document: (-_citation_count(document), document_key(document)),
        )[:max(1, seed_limit // 3)]
        recent = sorted(
            eligible,
            key=lambda document: (
                -(getattr(getattr(document, "source", None), "publish_year", 0) or 0),
                document_key(document),
            ),
        )[:max(1, seed_limit // 3)]
        roles: dict[str, list[str]] = {}
        for role, values in (("relevance", relevance), ("impact", impact), ("recent", recent)):
            for document in values:
                key = document_key(document)
                roles[key] = self._merge_unique(roles.get(key, []), [role])
        return roles

    def _prepare_candidates_legacy(self, question: str, hits: list) -> list:
        candidates = self._dedupe_documents(list(hits or []))
        # Queue insertion returns only records that are new to the ledger. A
        # paper discovered during an earlier query iteration is still part of
        # the fused retrieval pool and must continue to citation/ranking.
        self._enqueue_candidate_queue(candidates, "retrieval")
        self.citation_map = self._empty_citation_map(
            enabled=getattr(self.config, "expand_citations", True),
            initial_candidates=len(candidates),
            candidate_pool=len(candidates),
        )
        if not candidates:
            return candidates
        if not getattr(self.config, "expand_citations", True):
            return candidates
        if self.data_source != "openalex" or not isinstance(self.provider, OpenAlexProvider):
            self._emit_log("Citation expansion skipped: this data source does not support OpenAlex citation traversal yet.")
            self.citation_map.update({"supported": False, "status": "unsupported"})
            return candidates
        last_source_status = str((getattr(self.provider, "last_response_info", {}) or {}).get("status") or "")
        if last_source_status == "429":
            self._emit_log("Citation expansion skipped because OpenAlex is rate limiting this run; keeping the current candidate pool.")
            self.citation_map.update({"supported": True, "status": "rate_limited"})
            self._emit_ranking_step(
                "citation_expansion",
                "skipped",
                "Citation expansion",
                current=0,
                total=1,
                detail="OpenAlex returned 429 during retrieval; citation traversal was skipped to avoid blocking the run.",
            )
            return candidates

        self._check_cancelled()
        seed_selection_limit = self._citation_seed_selection_limit()
        seed_candidates = self._citation_seed_candidate_pool(candidates, seed_selection_limit)
        if len(candidates) > len(seed_candidates):
            self._emit_log(
                "Citation seed selection pool truncated: "
                f"candidates={len(candidates)}; seed_selection_limit={seed_selection_limit}."
            )
        self._emit_log(
            "Citation expansion started: selecting seed papers from the fused retrieval order "
            "before traversing references and citing works."
        )
        self._emit_ranking_step(
            "citation_seed_ranking",
            "processing",
            "Citation seed selection",
            current=0,
            total=max(1, len(seed_candidates)),
            detail="Selecting a bounded, query-view-diversified seed pool from the existing fused retrieval order.",
        )
        seed_ranked = [
            {
                "document": document,
                "score": 10,
                "reasoning": "Selected from the fused retrieval order.",
                **self._retrieval_entry_metadata(document),
            }
            for document in seed_candidates
        ]
        self._check_cancelled()
        self._emit_ranking_step(
            "citation_seed_ranking",
            "complete",
            "Citation seed selection",
            current=len(seed_candidates),
            total=max(1, len(seed_candidates)),
            detail="Seed selection completed without an additional LLM scoring pass.",
        )
        seed_limit = max(1, int(getattr(self.config, "citation_seed_count", 30) or 30))
        citation_depth = max(1, min(int(getattr(self.config, "citation_depth", 2) or 2), 3))
        citation_plan = self._plan_citation_expansion(
            candidate_count=len(candidates),
            seed_ranking_count=len(seed_candidates),
            seed_count=seed_limit,
            depth=citation_depth,
        )
        seed_plans = self._build_citation_seed_plans(seed_ranked, candidates, citation_plan)
        seeds = [plan.record for plan in seed_plans]
        if not seed_plans:
            self._emit_log("Citation expansion skipped: no seed papers available.")
            self.citation_map.update({"status": "no_seeds"})
            self._emit_ranking_step(
                "citation_expansion",
                "skipped",
                "Citation expansion",
                current=0,
                total=max(1, seed_limit),
                detail="No seed papers were available for citation traversal.",
            )
            return candidates

        self._emit_ranking_step(
            "citation_expansion",
            "processing",
            "Citation expansion",
            current=0,
            total=max(1, len(seed_plans)),
            detail=f"Traversing citation neighborhoods for {len(seed_plans)} seed papers across relevance, impact, and recency plans.",
            seed_count=len(seeds),
            citation_depth=citation_depth,
        )
        try:
            traversal_per_seed = max(1, int(getattr(self.config, "citation_per_seed", 4) or 4))
        except (TypeError, ValueError):
            traversal_per_seed = 4
        try:
            traversal_max_records = max(1, int(getattr(self.config, "citation_max_records", 160) or 160))
        except (TypeError, ValueError):
            traversal_max_records = 160
        traversal_depth = citation_depth
        citation_data = None
        retry_attempts = 0
        citation_progress_state = {"last_emit": 0.0, "last_current": -1}

        def emit_citation_progress(progress: dict) -> None:
            self._check_cancelled()
            event = str(progress.get("event") or "")
            total = max(1, int(progress.get("total") or len(seed_plans) or 1))
            current = max(0, min(total, int(progress.get("current") or 0)))
            records = max(0, int(progress.get("records") or 0))
            now = time.perf_counter()
            step = max(1, total // 10)
            should_emit = (
                event == "start"
                or current >= total
                or current % step == 0
                or (current != citation_progress_state["last_current"] and now - citation_progress_state["last_emit"] >= 5.0)
            )
            if not should_emit:
                return
            citation_progress_state["last_emit"] = now
            citation_progress_state["last_current"] = current
            self._emit_log(f"Citation expansion progress: {current}/{total} seed plans processed; added={records}.")
            self._emit_ranking_step(
                "citation_expansion",
                "processing",
                "Citation expansion",
                current=current,
                total=total,
                detail=f"Traversing OpenAlex citation neighborhoods; added {records} candidates so far.",
                seed_count=len(seeds),
                citation_depth=traversal_depth,
                added_candidates=records,
            )

        while citation_data is None:
            self._check_cancelled()
            try:
                try:
                    citation_data = self.provider.citation_neighbors_with_graph(
                        seeds,
                        per_seed=traversal_per_seed,
                        max_records=traversal_max_records,
                        field_ids=openalex_field_ids(self.discipline_fields),
                        seed_plans=seed_plans,
                        depth=traversal_depth,
                        cancel_check=self._check_cancelled,
                        progress_callback=emit_citation_progress,
                        request_attempts=1,
                        request_timeout=10,
                    )
                except TypeError as exc:
                    if "unexpected keyword argument" not in str(exc):
                        raise
                    citation_data = self.provider.citation_neighbors_with_graph(
                        seeds,
                        per_seed=traversal_per_seed,
                        max_records=traversal_max_records,
                        field_ids=openalex_field_ids(self.discipline_fields),
                        seed_plans=seed_plans,
                        depth=traversal_depth,
                    )
            except ProviderError as exc:
                self._observe_citation_traversal(
                    status="error",
                    seed_count=len(seeds),
                    depth=traversal_depth,
                    per_seed=traversal_per_seed,
                    max_records=traversal_max_records,
                    candidate_pool=len(candidates),
                    error=exc,
                )
                decision = self._recover_citation_error(
                    exc,
                    seed_count=len(seeds),
                    depth=traversal_depth,
                    per_seed=traversal_per_seed,
                    max_records=traversal_max_records,
                    retry_attempts=retry_attempts,
                    max_retries=1,
                )
                if decision.action == CITATION_RETRY_REDUCED:
                    retry_attempts += 1
                    traversal_per_seed = decision.per_seed
                    traversal_max_records = decision.max_records
                    traversal_depth = decision.depth
                    self._emit_log(
                        "Citation expansion retrying with a reduced traversal budget: "
                        f"per_seed={traversal_per_seed}; max_records={traversal_max_records}; depth={traversal_depth}."
                    )
                    self._emit_ranking_step(
                        "citation_expansion",
                        "processing",
                        "Citation expansion",
                        current=0,
                        total=max(1, len(seeds)),
                        detail="Citation traversal failed once; retrying with a reduced traversal budget.",
                        seed_count=len(seeds),
                        citation_depth=traversal_depth,
                    )
                    continue
                self._check_cancelled()
                self._emit_log(f"Citation expansion skipped after OpenAlex error: {exc}")
                self.citation_map.update({"status": "error", "error": str(exc)})
                self._emit_ranking_step(
                    "citation_expansion",
                    "error",
                    "Citation expansion",
                    current=0,
                    total=max(1, len(seeds)),
                    detail=f"Citation traversal failed: {exc}",
                    seed_count=len(seeds),
                )
                return candidates

        self._check_cancelled()
        related = citation_data.get("records", [])
        citation_frontier = dict(citation_data.get("frontier") or {})
        citation_evidence = self._citation_evidence_by_key(related, citation_data)
        added_related = self._enqueue_candidate_queue(
            related,
            "citation_expansion",
            evidence_by_key=citation_evidence,
        )
        candidates = candidates + added_related
        added = len(added_related)
        self._observe_citation_traversal(
            status="complete",
            seed_count=len(seeds),
            depth=traversal_depth,
            per_seed=traversal_per_seed,
            max_records=traversal_max_records,
            added_candidates=added,
            candidate_pool=len(candidates),
            frontier=citation_frontier,
        )
        self.citation_map.update({
            "enabled": True,
            "supported": True,
            "status": "complete",
            "initial_candidates": len(hits or []),
            "seed_count": len(seeds),
            "seed_plan_counts": self._citation_seed_plan_counts(seed_plans),
            "citation_depth": traversal_depth,
            "frontier": citation_frontier,
            "added_candidates": added,
            "candidate_pool": len(candidates),
            "nodes": citation_data.get("nodes", []),
            "edges": citation_data.get("edges", []),
        })
        frontier_stop = str(citation_frontier.get("stop_reason") or "completed")
        frontier_requests = int(citation_frontier.get("request_count") or 0)
        self._emit_log(
            f"Citation expansion completed: added {added} citation-neighbor candidates; "
            f"candidate pool={len(candidates)}; frontier_stop={frontier_stop}; requests={frontier_requests}."
        )
        self._emit_ranking_step(
            "citation_expansion",
            "complete",
            "Citation expansion",
            current=len(seeds),
            total=max(1, len(seeds)),
            detail=(
                f"Added {added} citation-neighbor candidates; candidate pool={len(candidates)}; "
                f"frontier stop={frontier_stop}; requests={frontier_requests}."
            ),
            seed_count=len(seeds),
            candidate_count=len(candidates),
            added_candidates=added,
            citation_depth=traversal_depth,
        )
        candidates = self._refuse_candidates_after_citation(question, candidates)
        self.citation_map["candidate_pool"] = len(candidates)
        return candidates

    def _citation_evidence_by_key(self, records: list, citation_data: dict) -> Dict[str, Dict[str, Any]]:
        edges = [edge for edge in (citation_data.get("edges") or []) if isinstance(edge, dict)]
        output: Dict[str, Dict[str, Any]] = {}
        for document in records or []:
            key = document_key(document)
            identifiers = getattr(document, "identifiers", None)
            node_id = str(
                getattr(document, "uid", "")
                or (getattr(identifiers, "openalex", "") if identifiers else "")
                or getattr(document, "title", "")
                or ""
            )
            if not key or not node_id:
                continue
            paths = []
            for edge in edges:
                edge_source = str(edge.get("source") or "")
                edge_target = str(edge.get("target") or "")
                edge_type = str(edge.get("type") or "")
                if edge_source == node_id and edge_type == "cites":
                    direction = "forward"
                    parent_id = edge_target
                elif edge_target == node_id and edge_type == "references":
                    direction = "backward"
                    parent_id = edge_source
                else:
                    continue
                try:
                    depth = max(0, int(edge.get("layer") or 0))
                except (TypeError, ValueError):
                    depth = 0
                paths.append(
                    CandidateCitationPath(
                        seed_id=str(edge.get("seed") or ""),
                        parent_id=parent_id,
                        direction=direction,
                        depth=depth,
                    )
                )
            output[key] = {
                "citation_paths": paths,
                "detail": f"citation_paths={len(paths)}",
            }
        return output

    def _citation_seed_candidate_pool(self, candidates: list, limit: int) -> list:
        limit = max(1, int(limit or 1))
        candidate_by_key = {
            document_key(document): document
            for document in candidates or []
            if document_key(document)
        }
        selected = []
        selected_keys = set()

        def add_documents(documents, quota: int) -> None:
            added = 0
            for document in documents or []:
                key = document_key(document)
                if not key or key not in candidate_by_key or key in selected_keys:
                    continue
                selected.append(candidate_by_key[key])
                selected_keys.add(key)
                added += 1
                if len(selected) >= limit or added >= quota:
                    break

        view_types = {
            view.view_id: view.view_type
            for view in (self.search_plan.query_views if self.search_plan else [])
        }
        successor_ids = [
            view_id
            for view_id, view_type in view_types.items()
            if view_type == "successor_paradigm" and view_id in self.query_portfolio_lane_results
        ]
        successor_quota = max(1, limit // 2)
        for view_id in successor_ids:
            add_documents(self.query_portfolio_lane_results.get(view_id, []), successor_quota)
            if len(selected) >= limit:
                return selected

        other_ids = [
            view_id
            for view_id in self.query_portfolio_lane_results
            if view_id not in successor_ids
        ]
        remaining_for_views = max(0, (limit * 3 // 4) - len(selected))
        per_view_quota = max(1, remaining_for_views // max(1, len(other_ids)))
        for view_id in other_ids:
            add_documents(self.query_portfolio_lane_results.get(view_id, []), per_view_quota)
            if len(selected) >= limit:
                return selected

        add_documents(candidates, limit - len(selected))
        return selected

    def _empty_citation_map(self, enabled: bool = True, initial_candidates: int = 0, candidate_pool: int = 0) -> dict:
        return {
            "enabled": bool(enabled),
            "supported": self.data_source == "openalex",
            "status": "waiting",
            "initial_candidates": initial_candidates,
            "seed_count": 0,
            "added_candidates": 0,
            "candidate_pool": candidate_pool,
            "nodes": [],
            "edges": [],
        }

    def _finalize_citation_map(self, ranked: list) -> None:
        if not self.citation_map:
            return
        nodes = {node.get("id"): node for node in self.citation_map.get("nodes", []) if node.get("id")}
        for index, entry in enumerate(ranked or [], 1):
            doc = entry.get("document")
            if not doc:
                continue
            node_id = getattr(doc, "uid", "") or getattr(getattr(doc, "identifiers", None), "openalex", "") or getattr(doc, "title", "")
            if not node_id:
                continue
            source = getattr(doc, "source", None)
            citations = _citation_count(doc)
            node = nodes.get(node_id)
            if not node:
                node = {
                    "id": node_id,
                    "title": getattr(doc, "title", "") or "(no title)",
                    "year": getattr(source, "publish_year", None) if source else None,
                    "source": getattr(source, "source_title", "") if source else "",
                    "citations": citations,
                    "roles": [],
                    "seed_uids": [],
                }
                nodes[node_id] = node
            if "result" not in node["roles"]:
                node["roles"].append("result")
            node["rank"] = index
            node["score"] = entry.get("score", 0)
            node["reasoning"] = entry.get("reasoning", "")
        self.citation_map["nodes"] = list(nodes.values())

    @staticmethod
    def _dedupe_documents(documents: list) -> list:
        deduped = []
        seen_aliases = set()
        for doc in documents or []:
            aliases = document_alias_keys(doc)
            if not aliases or any(alias in seen_aliases for alias in aliases):
                continue
            seen_aliases.update(aliases)
            deduped.append(doc)
        return deduped

    def _emit(self, event_type: str, **payload: Any) -> None:
        self._check_cancelled()
        if self.event_handler:
            self.event_handler({"type": event_type, **payload})

    def _check_cancelled(self) -> None:
        if self.cancel_check and self.cancel_check():
            raise SearchCancelled("Search cancelled by user.")

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
            "kimi-for-coding": "kimi-k2.6",
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
        messages = [
            {"role": "system", "content": SYSTEM_SEARCH_INTENT_ANALYSIS},
            {"role": "user", "content": f"Research question: {question}\n\nOutput ONLY the compact JSON intent object."},
        ]
        self._emit_log("Search intent analysis started.")
        self._llm_request_log("intent_analysis")
        try:
            chat_json = getattr(self.llm, "chat_json", None)
            raw = (
                chat_json(messages, temperature=0.0, max_tokens=4096)
                if callable(chat_json)
                else self.llm.chat(messages, temperature=0.0)
            )
            self._llm_response_log("intent_analysis")
        except Exception as exc:
            self._emit_log(f"Search intent analysis skipped after LLM error: {exc}")
            self.search_plan = fallback_search_plan(question, f"LLM error: {exc.__class__.__name__}")
            return self.search_plan.audit_summary()
        self.search_plan = parse_search_plan(raw, question)
        response_info = getattr(self.llm, "last_response_info", {}) or {}
        self.search_plan_diagnostics.append(
            {
                "attempt": 1,
                "output_characters": len(raw or ""),
                "finish_reason": response_info.get("finish_reason"),
                "completion_tokens": response_info.get("completion_tokens"),
                "parsed": self.search_plan is not None,
                "coverage_gaps": self.search_plan.coverage_gaps() if self.search_plan is not None else ["invalid_search_plan_json"],
            }
        )
        portfolio_required = bool(getattr(self.config, "query_portfolio_enabled", False)) and supports_query_portfolio(
            self.data_source
        )
        plan_gaps = (
            self.search_plan.coverage_gaps()
            if self.search_plan is not None and portfolio_required
            else ([] if self.search_plan is not None else ["a valid SearchPlan JSON object"])
        )
        if plan_gaps:
            gaps = "; ".join(plan_gaps)
            self._emit_log(f"Search intent plan missed required structured coverage: {gaps}; requesting one corrected plan.")
            if self.search_plan is None:
                retry_messages = [
                    {"role": "system", "content": SYSTEM_SEARCH_INTENT_ANALYSIS},
                    {
                        "role": "user",
                        "content": (
                            f"Research question: {question}\n\n"
                            "The previous response was invalid or truncated. Start over without repeating it. "
                            "Return one compact SearchPlan JSON object under 1800 tokens. Use exactly 3 query_views, "
                            "ordered by expected unique recall contribution, with at most 3 concept_groups per view "
                            "and at most 5 short terms per group. "
                            "Every view must contain valid concept_groups. Output only JSON."
                        ),
                    },
                ]
            else:
                retry_messages = [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "The plan is structurally valid but has this coverage gap: "
                            f"{gaps}. Return a complete replacement SearchPlan JSON object. Preserve useful existing views, "
                            "add the missing distinct views, and output only JSON. Every query view must contain valid concept_groups."
                        ),
                    },
                ]
            self._llm_request_log("intent_analysis_coverage_retry")
            try:
                retry_raw = (
                    chat_json(retry_messages, temperature=0.0, max_tokens=4096)
                    if callable(chat_json)
                    else self.llm.chat(retry_messages, temperature=0.0)
                )
                self._llm_response_log("intent_analysis_coverage_retry")
                retry_plan = parse_search_plan(retry_raw, question)
                response_info = getattr(self.llm, "last_response_info", {}) or {}
                self.search_plan_diagnostics.append(
                    {
                        "attempt": 2,
                        "output_characters": len(retry_raw or ""),
                        "finish_reason": response_info.get("finish_reason"),
                        "completion_tokens": response_info.get("completion_tokens"),
                        "parsed": retry_plan is not None,
                        "coverage_gaps": retry_plan.coverage_gaps() if retry_plan is not None else ["invalid_search_plan_json"],
                    }
                )
                if retry_plan is not None and not retry_plan.coverage_gaps():
                    self.search_plan = retry_plan
                elif self.search_plan is None and retry_plan is not None:
                    self.search_plan = retry_plan
                    self._emit_log("Search intent repair remained incomplete but produced a valid plan; continuing with its usable views.")
                else:
                    self._emit_log("Search intent repair remained incomplete; keeping the first valid plan when available.")
            except Exception as exc:
                self._emit_log(f"Search intent repair failed; keeping the first valid plan when available: {exc}")
        if self.search_plan is not None:
            self._emit_log("Search intent analysis completed.")
        else:
            self._emit_log(
                "Search intent analysis returned no usable structured plan after one repair; "
                "continuing with the deterministic fallback plan."
            )
            self.search_plan = fallback_search_plan(question, "invalid structured output")
        return self.search_plan.audit_summary()

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
                "Build a precise candidate query. Every must_have_facet must remain a mandatory concept group, and required_relation must remain mandatory when present. "
                "Use OR only for direct alternatives within one required concept; join distinct required concepts and the required relation with AND. "
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
        selector_feedback = self.last_query_selector_feedback
        if selector_feedback and _queries_equivalent(query, str(selector_feedback.get("query") or "")):
            lines.append(
                "- CandidateSelector audit: "
                f"inspected={selector_feedback.get('observed', 0)}; "
                f"include={selector_feedback.get('include', 0)}; "
                f"uncertain={selector_feedback.get('uncertain', 0)}; "
                f"exclude={selector_feedback.get('exclude', 0)}."
            )
            missing = [str(value) for value in selector_feedback.get("missing_concepts") or [] if str(value).strip()]
            if missing:
                lines.append(f"- SearchPlan concept gaps reported by CandidateSelector: {', '.join(missing)}")
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
        return 0.0

    def _chat_query_json(self, messages: list) -> str:
        chat_json = getattr(self.llm, "chat_json", None)
        if callable(chat_json):
            return chat_json(messages, temperature=self._query_temperature(), max_tokens=2048)
        return self.llm.chat(messages, temperature=self._query_temperature())

    @staticmethod
    def _strict_query_output_instruction(output_label: str) -> str:
        normalized_label = str(output_label or "").casefold()
        atomic_edit_contract = ""
        if "broadened" in normalized_label:
            atomic_edit_contract = (
                "- Make exactly one atomic broadening edit to the current query. Change one concept group only: "
                "remove one non-essential restrictive group, replace one group's wording with broader alternatives, "
                "or broaden the alternatives inside that one group. Copy every other concept group and filter unchanged. "
                "Do not remove one group and broaden another in the same response.\n"
                "- In rationale, name the one changed concept group and describe its before/after meaning.\n"
            )
        elif "narrowed" in normalized_label:
            atomic_edit_contract = (
                "- Make exactly one atomic narrowing edit to the current query. Change one concept group only: "
                "add one missing must-have group, replace one drift-causing alternative, or tighten the alternatives "
                "inside one existing group. Copy every other concept group and filter unchanged. Do not add two missing "
                "facets or tighten multiple groups in the same response.\n"
                "- In rationale, name the one changed concept group and describe its before/after meaning.\n"
            )
        return (
            "\nStructured output contract:\n"
            "- Return exactly one valid JSON object and no text outside JSON.\n"
            "- Use this schema: {\"query\":\"...\", \"rationale\":\"...\"}.\n"
            f"- The query field must contain exactly one complete {output_label}; it is the only value PaperSeek will send to the source API.\n"
            f"{atomic_edit_contract}"
            "- The rationale field may briefly explain the adjustment, direction, or title-intent diagnostic for audit.\n"
            "- Do not put the rationale, labels, markdown, bullets, or comments inside the query field.\n"
            "- If you compare returned titles with the intent, put the on-intent/off-intent conclusion in rationale and keep query clean.\n"
            "- If you cannot improve the query, repeat the current valid query in query and explain why in rationale.\n"
        )

    def _generate_query(self, question: str) -> str:
        if self.data_source == "openalex":
            return self._generate_openalex_query(question)
        if self.data_source == "crossref":
            return self._generate_crossref_query(question)
        if self.data_source == "arxiv":
            return self._generate_source_query(
                question,
                SYSTEM_ARXIV_QUERY_GENERATION,
                "arxiv_query_generation",
                "arXiv search_query string",
            )
        if self.data_source == "semanticscholar":
            return self._generate_source_query(
                question,
                SYSTEM_SEMANTIC_SCHOLAR_QUERY_GENERATION,
                "semanticscholar_query_generation",
                "Semantic Scholar query string",
            )
        if self.data_source == "pubmed":
            return self._generate_source_query(
                question,
                SYSTEM_PUBMED_QUERY_GENERATION,
                "pubmed_query_generation",
                "PubMed ESearch term string",
            )
        if self.data_source == "googlescholar":
            return self._generate_source_query(
                question,
                SYSTEM_GOOGLE_SCHOLAR_QUERY_GENERATION,
                "googlescholar_query_generation",
                "Google Scholar q string",
            )
        if self.data_source == "paperhub":
            return self._generate_source_query(
                question,
                SYSTEM_PAPERHUB_QUERY_GENERATION,
                "paperhub_query_generation",
                "PaperHub search query string",
            )
        if self.provider:
            return self._generate_generic_source_query(question)

        context = self._intent_context()
        field_hint = ""
        if self.config.search_field:
            field_hint = f"\nDiscipline/field constraint: {self.config.search_field}\nIncorporate this into the query via relevant SO= journals or TS= field-specific keywords."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_QUERY_GENERATION},
            {"role": "user", "content": f"Research question: {question}{context}{field_hint}{self._strict_query_output_instruction('WoS query string')}"},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log("wos_query_generation")
        raw = self._chat_query_json(messages)
        self._llm_response_log("wos_query_generation")
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=SYSTEM_QUERY_GENERATION,
            log_name="wos_query_generation",
            output_label="WoS query string",
            operation="generated query",
        )
        query = _make_starter_safe_query(query)
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _broaden_query(self, question: str, current_query: str, feedback: str = "") -> str:
        if self.data_source == "openalex":
            messages = [
                {"role": "system", "content": SYSTEM_OPENALEX_QUERY_BROADEN},
                {"role": "user", "content": (
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too few results: {current_query}\n"
                    f"{self._strict_query_output_instruction('broadened OpenAlex search query string')}"
                )},
            ]
            self._llm_request_log("openalex_query_broaden")
            raw = self._chat_query_json(messages)
            self._llm_response_log("openalex_query_broaden")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_OPENALEX_QUERY_BROADEN,
                log_name="openalex_query_broaden",
                output_label="broadened OpenAlex search query string",
                operation="broadened query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query
        if self.data_source == "crossref":
            messages = [
                {"role": "system", "content": SYSTEM_CROSSREF_QUERY_BROADEN},
                {"role": "user", "content": (
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too few results: {current_query}\n"
                    f"{self._strict_query_output_instruction('broadened Crossref bibliographic query string')}"
                )},
            ]
            self._llm_request_log("crossref_query_broaden")
            raw = self._chat_query_json(messages)
            self._llm_response_log("crossref_query_broaden")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_CROSSREF_QUERY_BROADEN,
                log_name="crossref_query_broaden",
                output_label="broadened Crossref bibliographic query string",
                operation="broadened query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query
        if self.data_source == "arxiv":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_ARXIV_QUERY_BROADEN,
                "arxiv_query_broaden",
                "too few or zero records",
                "broadened arXiv search_query string",
                feedback,
            )
        if self.data_source == "semanticscholar":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_SEMANTIC_SCHOLAR_QUERY_BROADEN,
                "semanticscholar_query_broaden",
                "too few or zero records",
                "broadened Semantic Scholar query string",
                feedback,
            )
        if self.data_source == "pubmed":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_PUBMED_QUERY_BROADEN,
                "pubmed_query_broaden",
                "too few or zero records",
                "broadened PubMed ESearch term string",
                feedback,
            )
        if self.data_source == "googlescholar":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_GOOGLE_SCHOLAR_QUERY_BROADEN,
                "googlescholar_query_broaden",
                "too few or zero records",
                "broadened Google Scholar q string",
                feedback,
            )
        if self.data_source == "paperhub":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_PAPERHUB_QUERY_BROADEN,
                "paperhub_query_broaden",
                "too few or zero records",
                "broadened PaperHub search query string",
                feedback,
            )
        if self.provider:
            messages = [
                {"role": "system", "content": SYSTEM_GENERIC_SOURCE_QUERY_BROADEN},
                {"role": "user", "content": (
                    f"Source: {self._source_label()}\n"
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too few results: {current_query}\n"
                    f"{self._strict_query_output_instruction('broadened plain search query string')}"
                )},
            ]
            self._llm_request_log(f"{self.data_source}_query_broaden")
            raw = self._chat_query_json(messages)
            self._llm_response_log(f"{self.data_source}_query_broaden")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_GENERIC_SOURCE_QUERY_BROADEN,
                log_name=f"{self.data_source}_query_broaden",
                output_label="broadened plain search query string",
                operation="broadened query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query

        messages = [
            {"role": "system", "content": SYSTEM_QUERY_BROADEN},
            {"role": "user", "content": (
                f"Question: {question}\n"
                f"{self._intent_context()}"
                f"{self._discipline_context()}\n"
                f"{feedback}"
                f"Current query returned too few or zero results: {current_query}\n"
                f"{self._strict_query_output_instruction('broadened WoS query string')}"
            )},
        ]
        self._llm_request_log("wos_query_broaden")
        raw = self._chat_query_json(messages)
        self._llm_response_log("wos_query_broaden")
        query = self._finalize_source_query(
            question,
            raw,
            current_query=current_query,
            feedback=feedback,
            system_prompt=SYSTEM_QUERY_BROADEN,
            log_name="wos_query_broaden",
            output_label="broadened WoS query string",
            operation="broadened query",
        )
        query = _make_starter_safe_query(query)
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _narrow_query(self, question: str, current_query: str, feedback: str = "") -> str:
        if self.data_source == "openalex":
            messages = [
                {"role": "system", "content": SYSTEM_OPENALEX_QUERY_NARROW},
                {"role": "user", "content": (
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too many results: {current_query}\n"
                    f"{self._strict_query_output_instruction('narrowed OpenAlex search query string')}"
                )},
            ]
            self._llm_request_log("openalex_query_narrow")
            raw = self._chat_query_json(messages)
            self._llm_response_log("openalex_query_narrow")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_OPENALEX_QUERY_NARROW,
                log_name="openalex_query_narrow",
                output_label="narrowed OpenAlex search query string",
                operation="narrowed query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query
        if self.data_source == "crossref":
            messages = [
                {"role": "system", "content": SYSTEM_CROSSREF_QUERY_NARROW},
                {"role": "user", "content": (
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too many results: {current_query}\n"
                    f"{self._strict_query_output_instruction('narrowed Crossref bibliographic query string')}"
                )},
            ]
            self._llm_request_log("crossref_query_narrow")
            raw = self._chat_query_json(messages)
            self._llm_response_log("crossref_query_narrow")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_CROSSREF_QUERY_NARROW,
                log_name="crossref_query_narrow",
                output_label="narrowed Crossref bibliographic query string",
                operation="narrowed query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query
        if self.data_source == "arxiv":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_ARXIV_QUERY_NARROW,
                "arxiv_query_narrow",
                "too many records",
                "narrowed arXiv search_query string",
                feedback,
            )
        if self.data_source == "semanticscholar":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_SEMANTIC_SCHOLAR_QUERY_NARROW,
                "semanticscholar_query_narrow",
                "too many records",
                "narrowed Semantic Scholar query string",
                feedback,
            )
        if self.data_source == "pubmed":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_PUBMED_QUERY_NARROW,
                "pubmed_query_narrow",
                "too many records",
                "narrowed PubMed ESearch term string",
                feedback,
            )
        if self.data_source == "googlescholar":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_GOOGLE_SCHOLAR_QUERY_NARROW,
                "googlescholar_query_narrow",
                "too many records",
                "narrowed Google Scholar q string",
                feedback,
            )
        if self.data_source == "paperhub":
            return self._revise_source_query(
                question,
                current_query,
                SYSTEM_PAPERHUB_QUERY_NARROW,
                "paperhub_query_narrow",
                "too many records",
                "narrowed PaperHub search query string",
                feedback,
            )
        if self.provider:
            messages = [
                {"role": "system", "content": SYSTEM_GENERIC_SOURCE_QUERY_NARROW},
                {"role": "user", "content": (
                    f"Source: {self._source_label()}\n"
                    f"Question: {question}\n"
                    f"{self._intent_context()}"
                    f"{self._discipline_context()}\n"
                    f"{feedback}"
                    f"Current query returned too many results: {current_query}\n"
                    f"{self._strict_query_output_instruction('narrowed plain search query string')}"
                )},
            ]
            self._llm_request_log(f"{self.data_source}_query_narrow")
            raw = self._chat_query_json(messages)
            self._llm_response_log(f"{self.data_source}_query_narrow")
            query = self._finalize_source_query(
                question,
                raw,
                current_query=current_query,
                feedback=feedback,
                system_prompt=SYSTEM_GENERIC_SOURCE_QUERY_NARROW,
                log_name=f"{self.data_source}_query_narrow",
                output_label="narrowed plain search query string",
                operation="narrowed query",
            )
            self._emit_stage("query", "complete", source=self.data_source, query=query)
            return query

        field_hint = ""
        if self.config.search_field:
            field_hint = f" Consider adding SO= for key journals in {self.config.search_field}."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_QUERY_NARROW},
            {"role": "user", "content": (
                f"Question: {question}\n"
                f"{self._intent_context()}"
                f"Current query returned too many results: {current_query}\n"
                f"{feedback}"
                f"{field_hint}\n"
                f"{self._strict_query_output_instruction('narrowed WoS query string')}"
            )},
        ]
        self._llm_request_log("wos_query_narrow")
        raw = self._chat_query_json(messages)
        self._llm_response_log("wos_query_narrow")
        query = self._finalize_source_query(
            question,
            raw,
            current_query=current_query,
            feedback=feedback,
            system_prompt=SYSTEM_QUERY_NARROW,
            log_name="wos_query_narrow",
            output_label="narrowed WoS query string",
            operation="narrowed query",
        )
        query = _make_starter_safe_query(query)
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _generate_openalex_query(self, question: str) -> str:
        context = self._intent_context()
        field_hint = ""
        if self.config.search_field:
            field_hint = f"\nDiscipline/field constraint: {self.config.search_field}\nTranslate this into standard English field or topic terms if useful."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_OPENALEX_QUERY_GENERATION},
            {"role": "user", "content": f"Research question: {question}{context}{field_hint}{self._strict_query_output_instruction('OpenAlex search query string')}"},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log("openalex_query_generation")
        raw = self._chat_query_json(messages)
        self._llm_response_log("openalex_query_generation")
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=SYSTEM_OPENALEX_QUERY_GENERATION,
            log_name="openalex_query_generation",
            output_label="OpenAlex search query string",
            operation="generated query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _generate_generic_source_query(self, question: str) -> str:
        context = self._intent_context()
        field_hint = ""
        if self.config.search_field:
            field_hint = f"\nDiscipline/field constraint: {self.config.search_field}\nTranslate this into standard English academic terms if useful."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_GENERIC_SOURCE_QUERY_GENERATION},
            {"role": "user", "content": (
                f"Source: {self._source_label()}\n"
                f"Research question: {question}{context}{field_hint}\n\n"
                f"{self._strict_query_output_instruction('source search query string')}"
            )},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log(f"{self.data_source}_query_generation")
        raw = self._chat_query_json(messages)
        self._llm_response_log(f"{self.data_source}_query_generation")
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=SYSTEM_GENERIC_SOURCE_QUERY_GENERATION,
            log_name=f"{self.data_source}_query_generation",
            output_label="source search query string",
            operation="generated query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _generate_source_query(self, question: str, system_prompt: str, log_name: str, output_label: str) -> str:
        context = self._intent_context()
        field_context = self._discipline_context()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Research question: {question}{context}{field_context}{self._strict_query_output_instruction(output_label)}"},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log(log_name)
        raw = self._chat_query_json(messages)
        self._llm_response_log(log_name)
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=system_prompt,
            log_name=log_name,
            output_label=output_label,
            operation="generated query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _revise_source_query(
        self,
        question: str,
        current_query: str,
        system_prompt: str,
        log_name: str,
        result_description: str,
        output_label: str,
        feedback: str = "",
    ) -> str:
        context = self._intent_context()
        field_context = self._discipline_context()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Source: {self._source_label()}\n"
                f"Question: {question}\n"
                f"{context}"
                f"{field_context}\n"
                f"{feedback}"
                f"Current query returned {result_description}: {current_query}\n"
                f"{self._strict_query_output_instruction(output_label)}"
            )},
        ]
        self._llm_request_log(log_name)
        raw = self._chat_query_json(messages)
        self._llm_response_log(log_name)
        query = self._finalize_source_query(
            question,
            raw,
            current_query=current_query,
            feedback=feedback,
            system_prompt=system_prompt,
            log_name=log_name,
            output_label=output_label,
            operation="revised query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

    def _generate_crossref_query(self, question: str) -> str:
        context = self._intent_context()
        field_hint = ""
        if self.config.search_field:
            field_hint = f"\nDiscipline/field constraint: {self.config.search_field}\nTranslate this into standard English bibliographic terms if useful."
        field_hint += self._discipline_context()

        messages = [
            {"role": "system", "content": SYSTEM_CROSSREF_QUERY_GENERATION},
            {"role": "user", "content": f"Research question: {question}{context}{field_hint}{self._strict_query_output_instruction('Crossref bibliographic query string')}"},
        ]
        self._emit_stage("query", "processing", source=self.data_source)
        self._llm_request_log("crossref_query_generation")
        raw = self._chat_query_json(messages)
        self._llm_response_log("crossref_query_generation")
        query = self._finalize_source_query(
            question,
            raw,
            system_prompt=SYSTEM_CROSSREF_QUERY_GENERATION,
            log_name="crossref_query_generation",
            output_label="Crossref bibliographic query string",
            operation="generated query",
        )
        self._emit_stage("query", "complete", source=self.data_source, query=query)
        return query

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
        if not documents:
            return []
        self._check_cancelled()

        batch_size = self._ranking_batch_size(len(documents))
        batches = [documents[index:index + batch_size] for index in range(0, len(documents), batch_size)]
        batch_ids = {
            index: self._ranking_batch_id(step_id, batch)
            for index, batch in enumerate(batches, 1)
        }
        completed_id_set = set(completed_batch_ids or [])
        scores = list(resume_scores or [])
        checkpoint_records = list(checkpoint_records or documents)
        ranking_context = ranking_context or {}
        if ranking_context:
            self.ranking_context = dict(ranking_context)
        if len(batches) <= 1:
            batch_id = batch_ids[1]
            if batch_id in completed_id_set:
                self._emit_log("Resumed completed result-ranking batch 1/1 from checkpoint.")
                return self._rank_from_scores(documents, scores)
            self._emit_ranking_step(
                step_id,
                "processing",
                step_title,
                current=0,
                total=1,
                detail=f"Scoring {len(documents)} candidates in one LLM batch.",
            )
            try:
                self._check_cancelled()
                self._llm_request_log("result_ranking")
                scores = self._score_ranking_batch(question, documents, self._new_ranking_llm_client())
                self._check_cancelled()
                if documents and not scores:
                    raise EmptyRankingBatchError("LLM ranking batch returned no valid score entries.")
                self._llm_response_log("result_ranking")
            except SearchCancelled:
                raise
            except Exception as exc:
                self._observe_ranking_batch_error(
                    exc,
                    step_id=step_id,
                    batch_index=1,
                    batch_count=1,
                    concurrency=1,
                    candidate_count=len(documents),
                    rate_limited=self._is_rate_limit_error(exc),
                )
                self._recover_ranking_failures(
                    step_id=step_id,
                    concurrency=1,
                    next_concurrency=0,
                    failed_batches=1,
                    failed_candidates=len(documents),
                    rate_limited=self._is_rate_limit_error(exc),
                )
                self._emit_log(f"Result ranking batch failed; keeping local pre-ranking order: {exc}")
                self._emit_ranking_step(
                    step_id,
                    "skipped",
                    step_title,
                    current=0,
                    total=1,
                    detail="LLM ranking failed or timed out; keeping the local pre-ranking order.",
                    candidate_count=len(documents),
                )
                return self._rank_from_scores(documents, [])
            completed_id_set.add(batch_id)
            self._save_checkpoint(
                "ranking_batch",
                records=checkpoint_records,
                ranking_scores=scores,
                completed_batch_ids=sorted(completed_id_set),
                metadata={"step_id": step_id, "resume_from_stage": checkpoint_resume_stage},
            )
            self._emit_ranking_step(
                step_id,
                "complete",
                step_title,
                current=1,
                total=1,
                detail=f"Scored {len(documents)} candidates.",
                candidate_count=len(documents),
            )
            return self._rank_from_scores(documents, scores)

        initial_workers = self._ranking_concurrency()
        self._emit_ranking_step(
            step_id,
            "processing",
            step_title,
            current=0,
            total=len(batches),
            detail=f"Scoring {len(documents)} candidates in {len(batches)} LLM batches; concurrency={initial_workers}.",
            concurrency=initial_workers,
            batch_size=batch_size,
            candidate_count=len(documents),
        )
        self._emit_log(
            f"Result ranking started in {len(batches)} batches; "
            f"candidates={len(documents)}; batch_size={batch_size}; concurrency={initial_workers}."
        )
        remaining_batches = [
            (index, batch)
            for index, batch in enumerate(batches, 1)
            if batch_ids[index] not in completed_id_set
        ]
        completed_batches = len(batches) - len(remaining_batches)
        if completed_batches:
            self._emit_log(
                f"Resumed {completed_batches}/{len(batches)} completed result-ranking batches from checkpoint."
            )
        schedule = self._ranking_concurrency_schedule(len(batches))
        for tier_index, workers in enumerate(schedule):
            self._check_cancelled()
            if not remaining_batches:
                break
            run_workers = workers
            if tier_index > 0:
                self._emit_log(f"Retrying {len(remaining_batches)} failed result-ranking batch(es) with concurrency={run_workers}.")
            lower_tier_available = tier_index < len(schedule) - 1
            same_tier_retry_used = False
            while True:
                failed_batches = []
                empty_output_batches = []
                backoff_to_lower_tier = False
                worklist = list(remaining_batches)
                for start in range(0, len(worklist), run_workers):
                    self._check_cancelled()
                    chunk = worklist[start:start + run_workers]
                    executor = ThreadPoolExecutor(max_workers=run_workers)
                    try:
                        future_to_batch = {
                            executor.submit(self._score_ranking_batch, question, batch, self._new_ranking_llm_client()): (index, batch)
                            for index, batch in chunk
                        }
                        pending = set(future_to_batch)
                        while pending:
                            done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                            self._check_cancelled()
                            if not done:
                                continue
                            for future in done:
                                self._check_cancelled()
                                index, batch = future_to_batch[future]
                                try:
                                    batch_scores = future.result()
                                    self._check_cancelled()
                                    if batch and not batch_scores:
                                        raise EmptyRankingBatchError("LLM ranking batch returned no valid score entries.")
                                except SearchCancelled:
                                    raise
                                except Exception as exc:
                                    rate_limited = self._is_rate_limit_error(exc)
                                    empty_output = isinstance(exc, EmptyRankingBatchError)
                                    self._observe_ranking_batch_error(
                                        exc,
                                        step_id=step_id,
                                        batch_index=index,
                                        batch_count=len(batches),
                                        concurrency=run_workers,
                                        candidate_count=len(batch),
                                        rate_limited=rate_limited,
                                    )
                                    self._emit_log(
                                        f"Result ranking batch {index}/{len(batches)} failed at concurrency={run_workers}; "
                                        f"will retry if a lower concurrency tier is available: {exc}"
                                    )
                                    failed_batches.append((index, batch))
                                    if empty_output:
                                        empty_output_batches.append((index, batch))
                                    if lower_tier_available and rate_limited:
                                        backoff_to_lower_tier = True
                                    self._emit_ranking_step(
                                        step_id,
                                        "processing",
                                        step_title,
                                        current=completed_batches,
                                        total=len(batches),
                                        detail=(
                                            f"Batch {index}/{len(batches)} returned no valid scores at concurrency={run_workers}; retrying once at the same concurrency."
                                            if empty_output
                                            else f"Batch {index}/{len(batches)} failed at concurrency={run_workers}; retrying failed batches with lower concurrency."
                                        ),
                                        concurrency=run_workers,
                                        batch_size=batch_size,
                                        candidate_count=len(documents),
                                    )
                                    continue
                                scores.extend(batch_scores)
                                completed_id_set.add(batch_ids[index])
                                completed_batches += 1
                                self._emit_log(f"Result ranking batch {index}/{len(batches)} completed; candidates={len(batch)}; scored={len(batch_scores)}.")
                                self._emit_ranking_step(
                                    step_id,
                                    "processing",
                                    step_title,
                                    current=completed_batches,
                                    total=len(batches),
                                    detail=f"Completed batch {index}/{len(batches)} at concurrency={run_workers}.",
                                    concurrency=run_workers,
                                    batch_size=batch_size,
                                    candidate_count=len(documents),
                                )
                                self._save_checkpoint(
                                    "ranking_batch",
                                    records=checkpoint_records,
                                    ranking_scores=scores,
                                    completed_batch_ids=sorted(completed_id_set),
                                    metadata={"step_id": step_id, "resume_from_stage": checkpoint_resume_stage},
                                )
                    except SearchCancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        executor = None
                        raise
                    finally:
                        if executor is not None:
                            executor.shutdown(wait=True)
                    if backoff_to_lower_tier:
                        unsubmitted = worklist[start + len(chunk):]
                        failed_batches.extend(unsubmitted)
                        next_workers = schedule[tier_index + 1] if lower_tier_available else 0
                        failed_docs_for_tier = sum(len(batch) for _, batch in failed_batches)
                        decision = self._recover_ranking_failures(
                            step_id=step_id,
                            concurrency=run_workers,
                            next_concurrency=next_workers,
                            failed_batches=len(failed_batches),
                            failed_candidates=failed_docs_for_tier,
                            rate_limited=True,
                        )
                        self._emit_log(
                            f"Rate limit detected at concurrency={run_workers}; "
                            f"moving {len(failed_batches)} failed or unsubmitted batch(es) to the next lower concurrency tier."
                        )
                        if decision.action != RANKING_RETRY_LOWER_CONCURRENCY:
                            break
                        break
                if (
                    failed_batches
                    and empty_output_batches
                    and not backoff_to_lower_tier
                    and not same_tier_retry_used
                    and len(empty_output_batches) == len(failed_batches)
                ):
                    failed_docs_for_tier = sum(len(batch) for _, batch in failed_batches)
                    decision = self._recover_ranking_failures(
                        step_id=step_id,
                        concurrency=run_workers,
                        next_concurrency=run_workers,
                        failed_batches=len(failed_batches),
                        failed_candidates=failed_docs_for_tier,
                        rate_limited=False,
                    )
                    if decision.action == RANKING_RETRY_SAME_TIER:
                        same_tier_retry_used = True
                        remaining_batches = failed_batches
                        self._emit_log(
                            f"Retrying {len(remaining_batches)} empty result-ranking batch(es) once more at concurrency={run_workers}."
                        )
                        continue
                break
            if failed_batches and lower_tier_available and not backoff_to_lower_tier:
                next_workers = schedule[tier_index + 1]
                failed_docs_for_tier = sum(len(batch) for _, batch in failed_batches)
                self._recover_ranking_failures(
                    step_id=step_id,
                    concurrency=run_workers,
                    next_concurrency=next_workers,
                    failed_batches=len(failed_batches),
                    failed_candidates=failed_docs_for_tier,
                    rate_limited=False,
                )
            remaining_batches = failed_batches

        if remaining_batches:
            failed_docs = sum(len(batch) for _, batch in remaining_batches)
            self._recover_ranking_failures(
                step_id=step_id,
                concurrency=schedule[-1] if schedule else initial_workers,
                next_concurrency=0,
                failed_batches=len(remaining_batches),
                failed_candidates=failed_docs,
                rate_limited=False,
            )
            self._emit_log(
                f"{len(remaining_batches)} result ranking batch(es) still failed at minimum concurrency=4; "
                "returning those candidates in source order with zero scores."
            )
            self._emit_ranking_step(
                step_id,
                "skipped" if not scores else "complete",
                step_title,
                current=completed_batches,
                total=len(batches),
                detail=(
                    f"{len(remaining_batches)} batch(es), {failed_docs} candidates, failed even at concurrency=4; "
                    "keeping local pre-ranking order for those candidates."
                ),
                concurrency=4,
                batch_size=batch_size,
                candidate_count=len(documents),
            )

        if not scores:
            if not remaining_batches:
                self._recover_ranking_failures(
                    step_id=step_id,
                    concurrency=initial_workers,
                    next_concurrency=0,
                    failed_batches=len(batches),
                    failed_candidates=len(documents),
                    rate_limited=False,
                )
            self._emit_log("All result ranking batches failed; returning candidates in source order with zero scores.")
            self._emit_ranking_step(
                step_id,
                "skipped",
                step_title,
                current=completed_batches,
                total=len(batches),
                detail="All LLM ranking batches failed or timed out; keeping the local pre-ranking order.",
                concurrency=4,
                batch_size=batch_size,
                candidate_count=len(documents),
            )
        elif not remaining_batches:
            self._emit_ranking_step(
                step_id,
                "complete",
                step_title,
                current=len(batches),
                total=len(batches),
                detail=f"LLM scoring completed for {completed_batches}/{len(batches)} batches.",
                concurrency=initial_workers,
                batch_size=batch_size,
                candidate_count=len(documents),
            )
        return self._rank_from_scores(documents, scores)

    @staticmethod
    def _ranking_batch_id(step_id: str, documents: list) -> str:
        candidate_ids = [str(getattr(document, "uid", "") or document_key(document)) for document in documents]
        digest = hashlib.sha256("\0".join(candidate_ids).encode("utf-8")).hexdigest()[:20]
        return f"{step_id}:{digest}"

    def _ranking_batch_size(self, total_documents: int) -> int:
        configured = getattr(self.config, "ranking_batch_size", 256) or 256
        try:
            batch_size = max(1, int(configured))
        except (TypeError, ValueError):
            batch_size = 256
        return min(max(1, batch_size), max(1, total_documents))

    def _ranking_concurrency(self) -> int:
        configured = getattr(self.config, "ranking_concurrency", 16) or 16
        try:
            return min(32, max(4, int(configured)))
        except (TypeError, ValueError):
            return 16

    def _ranking_concurrency_schedule(self, batch_count: int) -> List[int]:
        configured = max(4, self._ranking_concurrency())
        tiers = [32, 16, 8, 4]
        schedule = []
        for tier in tiers:
            if tier <= configured and tier not in schedule:
                schedule.append(tier)
        if configured not in schedule:
            schedule.insert(0, configured)
        if 4 not in schedule:
            schedule.append(4)
        return schedule

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

    def _score_ranking_batch(self, question: str, documents: list, llm_client: LLMClient) -> list:
        try:
            scores = self._request_ranking_scores(question, documents, llm_client)
        except Exception as exc:
            if not self._should_use_compact_ranking_fallback(exc):
                raise
            self._emit_log(
                "Full global scoring failed; switching to compact score-only global ranking: "
                f"{type(exc).__name__}: {exc}"
            )
            return self._score_ranking_batch_two_stage(question, documents, llm_client)
        matched, missing = self._match_ranking_scores_to_documents(documents, scores)
        if missing:
            self._emit_log(
                f"Full global scoring omitted {len(missing)}/{len(documents)} candidate(s); "
                "switching to compact score-only global ranking."
            )
            return self._score_ranking_batch_two_stage(question, documents, llm_client)
        return matched

    @staticmethod
    def _should_use_compact_ranking_fallback(exc: Exception) -> bool:
        text = str(exc or "").casefold()
        if PaperSeekAgent._is_rate_limit_error(exc):
            return False
        return any(
            marker in text
            for marker in (
                "context length",
                "context_length",
                "maximum context",
                "max token",
                "too many tokens",
                "truncat",
                "json",
                "message content",
                "did not contain",
                "empty response",
                "timed out",
                "timeout",
            )
        )

    def _score_ranking_batch_two_stage(self, question: str, documents: list, llm_client: LLMClient) -> list:
        scores = self._request_compact_ranking_scores(question, documents, llm_client)
        matched, missing = self._match_ranking_scores_to_documents(documents, scores)
        if missing:
            raise EmptyRankingBatchError(
                f"Compact global scoring omitted {len(missing)}/{len(documents)} candidate(s)."
            )

        reason_documents = self._ranking_reason_documents(documents, matched)
        reason_by_uid = {}
        for start in range(0, len(reason_documents), 64):
            batch = reason_documents[start:start + 64]
            try:
                reason_by_uid.update(
                    self._request_ranking_reasons(question, batch, matched, llm_client)
                )
            except Exception as exc:
                self._emit_log(
                    "Ranking reason generation failed for retained candidates; keeping global scores: "
                    f"{type(exc).__name__}: {exc}"
                )

        for entry in matched:
            entry["reasoning"] = reason_by_uid.get(str(entry.get("uid") or ""), "")
        return matched

    def _request_ranking_scores(self, question: str, documents: list, llm_client: LLMClient) -> list:
        abstract_limit = max(500, min(1200, 12000 // max(1, len(documents))))
        descriptions = []
        for i, doc in enumerate(documents, 1):
            descriptions.append(_describe_document(doc, i, abstract_limit=abstract_limit))

        papers_text = "\n\n".join(descriptions)

        messages = [
            {"role": "system", "content": SYSTEM_RESULT_RANKING},
            {"role": "user", "content": (
                f"Research question: {question}\n\n"
                f"Stable SearchPlan (intent context, not paper evidence):\n"
                f"{self._ranking_plan_context()}\n\n"
                f"Papers to evaluate:\n\n{papers_text}\n\n"
                f'Output ONLY one JSON object with the top-level key "scores".'
            )},
        ]

        chat_json = getattr(llm_client, "chat_json", None)
        max_tokens = min(32768, max(4096, len(documents) * 128))
        raw = (
            chat_json(messages, temperature=0.0, max_tokens=max_tokens)
            if callable(chat_json)
            else llm_client.chat(messages, temperature=0.3)
        )
        return self._parse_ranking_response(raw)

    def _request_compact_ranking_scores(self, question: str, documents: list, llm_client: LLMClient) -> list:
        descriptions = []
        for index, document in enumerate(documents, 1):
            description = _describe_document(document, index, abstract_limit=500)
            descriptions.append(re.sub(rf"^{index}\. UID:.*$", f"{index}.", description, count=1, flags=re.MULTILINE))
        papers_text = "\n\n".join(descriptions)
        messages = [
            {
                "role": "system",
                "content": (
                    "Score every supplied paper against the stable SearchPlan on the same absolute 0-10 relevance rubric. "
                    "Use only the supplied evidence. Return every integer index exactly once and do not generate reasons. "
                    'Output only JSON shaped as {"scores":[[1,9],[2,6]]}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Research question: {question}\n\n"
                    f"Stable SearchPlan:\n{self._ranking_plan_context()}\n\n"
                    f"Papers:\n\n{papers_text}\n\n"
                    'Return only {"scores":[[index,score],...]} with one pair for every index.'
                ),
            },
        ]
        chat_json = getattr(llm_client, "chat_json", None)
        raw = (
            chat_json(messages, temperature=0.0, max_tokens=4096)
            if callable(chat_json)
            else llm_client.chat(messages, temperature=0.0)
        )
        return self._parse_compact_ranking_scores(raw, documents)

    def _ranking_reason_documents(self, documents: list, scores: list) -> list:
        score_by_uid = {
            str(entry.get("uid") or ""): float(entry.get("score") or 0)
            for entry in scores
        }
        ordered = sorted(
            documents,
            key=lambda document: score_by_uid.get(self._ranking_document_identity(document), 0),
            reverse=True,
        )
        if len(ordered) < 50:
            return ordered
        high_scores = [
            document
            for document in ordered
            if score_by_uid.get(self._ranking_document_identity(document), 0) >= 5
        ]
        return high_scores if len(high_scores) > 50 else ordered[:50]

    def _request_ranking_reasons(
        self,
        question: str,
        documents: list,
        scores: list,
        llm_client: LLMClient,
    ) -> dict[str, str]:
        score_by_uid = {
            str(entry.get("uid") or ""): entry.get("score", 0)
            for entry in scores
        }
        descriptions = []
        identities = []
        for index, document in enumerate(documents, 1):
            identity = self._ranking_document_identity(document)
            identities.append(identity)
            description = _describe_document(document, index, abstract_limit=700)
            description = re.sub(rf"^{index}\. UID:.*$", f"{index}. Score: {score_by_uid.get(identity, 0)}", description, count=1, flags=re.MULTILINE)
            descriptions.append(description)
        retained_text = "\n\n".join(descriptions)
        messages = [
            {
                "role": "system",
                "content": (
                    "Explain the supplied relevance scores using only the paper metadata and stable SearchPlan. "
                    "Give one concise evidence-based sentence in the user's language for every integer index. "
                    'Output only JSON shaped as {"reasons":[[1,"reason"],[2,"reason"]]}.'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Research question: {question}\n\n"
                    f"Stable SearchPlan:\n{self._ranking_plan_context()}\n\n"
                    f"Retained papers:\n\n{retained_text}\n\n"
                    'Return only {"reasons":[[index,"reason"],...]}.'
                ),
            },
        ]
        chat_json = getattr(llm_client, "chat_json", None)
        max_tokens = min(8192, max(2048, len(documents) * 96))
        raw = (
            chat_json(messages, temperature=0.0, max_tokens=max_tokens)
            if callable(chat_json)
            else llm_client.chat(messages, temperature=0.0)
        )
        return self._parse_ranking_reasons(raw, identities)

    @staticmethod
    def _json_object(raw: str) -> dict:
        text = str(raw or "").strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return {}
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                return {}

    def _parse_compact_ranking_scores(self, raw: str, documents: list) -> list:
        pairs = self._json_object(raw).get("scores")
        if not isinstance(pairs, list):
            return []
        output = []
        seen = set()
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                index = int(pair[0])
                score = float(pair[1])
            except (TypeError, ValueError):
                continue
            if index < 1 or index > len(documents) or index in seen or not math.isfinite(score):
                continue
            seen.add(index)
            output.append({
                "uid": self._ranking_document_identity(documents[index - 1]),
                "score": score,
                "reasoning": "",
            })
        return output

    def _parse_ranking_reasons(self, raw: str, identities: list[str]) -> dict[str, str]:
        pairs = self._json_object(raw).get("reasons")
        if not isinstance(pairs, list):
            return {}
        output = {}
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                index = int(pair[0])
            except (TypeError, ValueError):
                continue
            reason = re.sub(r"\s+", " ", str(pair[1] or "")).strip()
            if 1 <= index <= len(identities) and reason:
                output[identities[index - 1]] = reason
        return output

    @staticmethod
    def _ranking_document_identity(document: Any) -> str:
        return str(getattr(document, "uid", "") or document_key(document) or "").strip()

    def _match_ranking_scores_to_documents(self, documents: list, scores: list) -> Tuple[list, list]:
        identities = [self._ranking_document_identity(document) for document in documents]
        exact = {identity.casefold(): index for index, identity in enumerate(identities) if identity}
        matched_indexes = set()
        matched_scores = []
        for entry in self._validated_ranking_scores(scores):
            uid = str(entry.get("uid") or "").strip()
            if not uid:
                continue
            index = exact.get(uid.casefold())
            if index is None:
                candidates = [
                    candidate_index
                    for candidate_index, identity in enumerate(identities)
                    if identity and (uid.casefold() in identity.casefold() or identity.casefold() in uid.casefold())
                ]
                if len(candidates) == 1:
                    index = candidates[0]
            if index is None or index in matched_indexes:
                continue
            normalized = dict(entry)
            normalized["uid"] = identities[index]
            matched_scores.append(normalized)
            matched_indexes.add(index)
        missing = [
            document
            for index, document in enumerate(documents)
            if index not in matched_indexes
        ]
        return matched_scores, missing

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

    def _parse_ranking_response(self, raw: str) -> list:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                payload = payload.get("scores")
            return self._validated_ranking_scores(payload)
        except json.JSONDecodeError:
            pass

        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                return self._validated_ranking_scores(json.loads(m.group(0)))
            except json.JSONDecodeError:
                pass

        return []

    @staticmethod
    def _validated_ranking_scores(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        output = []
        for item in value:
            try:
                output.append(RankingScoreEntry.model_validate(item).model_dump())
            except (TypeError, ValueError):
                continue
        return output

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
