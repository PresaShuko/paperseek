"""Structured query planning, bounded refinement, and portfolio execution."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable
from urllib.parse import urlencode

from paperseek_core import prompts
from paperseek_core.errors import QueryGenerationError, QuerySourceError
from paperseek_core.execution import NEVER_CANCELLED
from paperseek_core.models import (
    CheckpointDraft,
    ConceptGroup,
    CoreProgressEvent,
    PaperRecord,
    QueryHistoryEntry,
    QueryIterationMemory,
    QueryLoopBudget,
    QueryLoopDecision,
    QueryLoopRequest,
    QueryLoopResult,
    QueryLoopResumeState,
    QueryLoopSnapshot,
    QueryPortfolioExecution,
    QueryValidation,
    QueryView,
    QueryViewSelection,
    RetrievalRequest,
    SearchPlan,
    SourceQueryProposal,
)
from paperseek_core.ports import CancellationToken, LLMPort, SourcePort, WorkflowObserver
from paperseek_core.retrieval import dedupe_documents, document_key
from paperseek_core.sources.contracts import SourceError, SourceSearchRequest


QUERY_FIELD_ALIASES = (
    "query",
    "search_query",
    "query_string",
    "source_query",
    "term",
    "wos_query",
)
RATIONALE_FIELD_ALIASES = (
    "rationale",
    "adjustment",
    "adjustment_direction",
    "reason",
    "diagnostic_note",
)
SUPPORTED_QUERY_SOURCES = {
    "openalex",
    "arxiv",
    "crossref",
    "semanticscholar",
    "pubmed",
    "googlescholar",
    "paperhub",
    "wos",
}
PLAIN_TEXT_QUERY_SOURCES = {"crossref", "semanticscholar"}
MINIMAL_BOOLEAN_QUERY_SOURCES = {"googlescholar", "paperhub"}
OPENALEX_MAX_ENCODED_SEARCH_BYTES = 3200
DIRECT_VIEW_OVERLAP_THRESHOLD = 0.30
PAIRWISE_VIEW_OVERLAP_THRESHOLD = 0.90


_PROMPT_BY_SOURCE = {
    "arxiv": {
        "generate": prompts.SYSTEM_ARXIV_QUERY_GENERATION,
        "broaden": prompts.SYSTEM_ARXIV_QUERY_BROADEN,
        "narrow": prompts.SYSTEM_ARXIV_QUERY_NARROW,
    },
    "crossref": {
        "generate": prompts.SYSTEM_CROSSREF_QUERY_GENERATION,
        "broaden": prompts.SYSTEM_CROSSREF_QUERY_BROADEN,
        "narrow": prompts.SYSTEM_CROSSREF_QUERY_NARROW,
    },
    "googlescholar": {
        "generate": prompts.SYSTEM_GOOGLE_SCHOLAR_QUERY_GENERATION,
        "broaden": prompts.SYSTEM_GOOGLE_SCHOLAR_QUERY_BROADEN,
        "narrow": prompts.SYSTEM_GOOGLE_SCHOLAR_QUERY_NARROW,
    },
    "openalex": {
        "generate": prompts.SYSTEM_OPENALEX_QUERY_GENERATION,
        "broaden": prompts.SYSTEM_OPENALEX_QUERY_BROADEN,
        "narrow": prompts.SYSTEM_OPENALEX_QUERY_NARROW,
    },
    "paperhub": {
        "generate": prompts.SYSTEM_PAPERHUB_QUERY_GENERATION,
        "broaden": prompts.SYSTEM_PAPERHUB_QUERY_BROADEN,
        "narrow": prompts.SYSTEM_PAPERHUB_QUERY_NARROW,
    },
    "pubmed": {
        "generate": prompts.SYSTEM_PUBMED_QUERY_GENERATION,
        "broaden": prompts.SYSTEM_PUBMED_QUERY_BROADEN,
        "narrow": prompts.SYSTEM_PUBMED_QUERY_NARROW,
    },
    "semanticscholar": {
        "generate": prompts.SYSTEM_SEMANTIC_SCHOLAR_QUERY_GENERATION,
        "broaden": prompts.SYSTEM_SEMANTIC_SCHOLAR_QUERY_BROADEN,
        "narrow": prompts.SYSTEM_SEMANTIC_SCHOLAR_QUERY_NARROW,
    },
    "wos": {
        "generate": prompts.SYSTEM_QUERY_GENERATION,
        "broaden": prompts.SYSTEM_QUERY_BROADEN,
        "narrow": prompts.SYSTEM_QUERY_NARROW,
    },
}

_SOURCE_LABELS = {
    "arxiv": "arXiv search_query string",
    "crossref": "Crossref bibliographic query string",
    "googlescholar": "Google Scholar q string",
    "openalex": "OpenAlex search query string",
    "paperhub": "PaperHub search query string",
    "pubmed": "PubMed ESearch term string",
    "semanticscholar": "Semantic Scholar query string",
    "wos": "WoS query string",
}


def _strip_llm_fence(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def _extract_json_object_text(text: str) -> str:
    raw = _strip_llm_fence(text)
    if not raw:
        return ""
    if raw.startswith("{") and raw.endswith("}"):
        return raw
    start = raw.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(raw[start:], start):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start : index + 1]
    return ""


def _normalize_question_type(value: Any, question: str) -> str:
    normalized = str(value or "").strip().lower()
    allowed = {
        "broad_landscape",
        "specific_relation",
        "method_application",
        "mechanism",
        "comparison",
        "seminal_work",
        "recent_progress",
        "systematic_search",
    }
    if normalized in allowed:
        return normalized
    question_lower = str(question or "").lower()
    if any(marker in question_lower for marker in ("field of", "works related", "papers about", "research on", "literature on")):
        return "broad_landscape"
    if any(marker in question_lower for marker in ("latest", "recent", "state of the art")):
        return "recent_progress"
    if any(marker in question_lower for marker in ("compare", "comparison", "versus", " vs ")):
        return "comparison"
    if any(marker in question_lower for marker in ("method", "use of", "application", "applied")):
        return "method_application"
    return "specific_relation"


def _explicit_user_exclusion(question: str, exclusion: str) -> bool:
    question_text = re.sub(r"\s+", " ", str(question or "")).strip().casefold()
    exclusion_text = re.sub(r"\s+", " ", str(exclusion or "")).strip(" \t\r\n,;.").casefold()
    if not question_text or not exclusion_text:
        return False
    negative_segments = re.findall(
        r"(?:\bexclude(?:d|s|ing)?\b|\bwithout\b|\bexcept(?: for)?\b|\bnot\b|不要|排除|不包括|不含)"
        r"\s*(?:about\s+|including\s+|include\s+)?([^?.;；。！？]+)",
        question_text,
    )
    return any(exclusion_text in segment for segment in negative_segments)


def parse_search_plan(text: str, question: str) -> SearchPlan | None:
    object_text = _extract_json_object_text(text)
    if not object_text:
        return None
    try:
        payload = json.loads(object_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    allowed_plan = set(SearchPlan.model_fields)
    normalized = {key: value for key, value in payload.items() if key in allowed_plan}
    normalized["intent"] = str(normalized.get("intent") or question or "Literature search").strip()
    normalized["question_type"] = _normalize_question_type(normalized.get("question_type"), question)
    raw_views = normalized.get("query_views")
    views = []
    if isinstance(raw_views, list):
        for index, item in enumerate(raw_views):
            if not isinstance(item, dict):
                continue
            view = dict(item)
            view["view_id"] = view.get("view_id") or view.get("id") or view.get("name") or f"view_{index + 1}"
            view["concept_groups"] = view.get("concept_groups") or view.get("groups") or []
            exclusions = view.get("exclusions")
            if isinstance(exclusions, str):
                exclusions = [exclusions]
            view["exclusions"] = [
                str(value)
                for value in exclusions or []
                if _explicit_user_exclusion(question, str(value))
            ]
            allowed_view = set(QueryView.model_fields) | {"id", "name", "groups"}
            view = {key: value for key, value in view.items() if key in allowed_view}
            groups = []
            for group in view.get("concept_groups") or []:
                if isinstance(group, dict):
                    groups.append(
                        {
                            key: value
                            for key, value in group.items()
                            if key in ConceptGroup.model_fields
                        }
                    )
            view["concept_groups"] = groups
            views.append(view)
    normalized["query_views"] = views
    try:
        return SearchPlan.model_validate(normalized)
    except (TypeError, ValueError):
        return None


def fallback_search_plan(question: str, reason: str = "") -> SearchPlan:
    intent = re.sub(r"\s+", " ", str(question or "Literature search")).strip()
    strategy = "Preserve the user's original concepts while varying terminology."
    if reason:
        strategy += f" Structured planning fallback: {reason}."
    return SearchPlan(
        intent=intent,
        question_type=_normalize_question_type("", question),
        core_concepts=[intent],
        must_have_facets=[intent],
        adjustment_strategy=strategy,
    )


def _parse_query_proposal(text: str) -> tuple[str, str]:
    object_text = _extract_json_object_text(text)
    if not object_text:
        return "", ""
    try:
        payload = json.loads(object_text)
    except json.JSONDecodeError:
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    query = ""
    for key in QUERY_FIELD_ALIASES:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            query = value.strip()
            break
        if isinstance(value, dict):
            nested = value.get("value") or value.get("query")
            if isinstance(nested, str) and nested.strip():
                query = nested.strip()
                break
    rationale_parts = []
    for key in RATIONALE_FIELD_ALIASES:
        value = payload.get(key)
        if isinstance(value, list):
            value = "; ".join(str(item).strip() for item in value if str(item).strip())
        value = str(value or "").strip()
        if value:
            rationale_parts.append(value)
    return query, "\n".join(rationale_parts).strip()


def _parentheses_balanced(query: str) -> bool:
    depth = 0
    for char in query or "":
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _looks_malformed(query: str) -> bool:
    value = (query or "").strip()
    return bool(
        not value
        or value.count('"') % 2
        or not _parentheses_balanced(value)
        or re.search(r"\b(?:AND|OR|NOT)\s*$", value, flags=re.IGNORECASE)
        or re.search(r"\(\s*$", value)
    )


def _top_level_boolean_matches(query: str) -> list[tuple[int, int, str]]:
    matches = []
    depth = 0
    in_quote = False
    escape = False
    index = 0
    while index < len(query):
        char = query[index]
        if escape:
            escape = False
            index += 1
            continue
        if char == "\\" and in_quote:
            escape = True
            index += 1
            continue
        if char == '"':
            in_quote = not in_quote
            index += 1
            continue
        if in_quote:
            index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0 and char.isalpha():
            end = index + 1
            while end < len(query) and query[end].isalpha():
                end += 1
            word = query[index:end].upper()
            if word in {"AND", "OR", "NOT"}:
                matches.append((index, end, word))
            index = end
            continue
        index += 1
    return matches


def validate_source_query(source: str, query: str) -> QueryValidation:
    source_id = (source or "").strip().lower()
    value = (query or "").strip()
    if not value:
        return QueryValidation(source=source_id, query=value, ok=False, issue="missing query field in JSON response")
    if source_id not in SUPPORTED_QUERY_SOURCES:
        return QueryValidation(source=source_id, query=value, ok=False, issue=f"unsupported data source: {source_id or '(missing)'}")
    if source_id not in PLAIN_TEXT_QUERY_SOURCES and _looks_malformed(value):
        return QueryValidation(
            source=source_id,
            query=value,
            ok=False,
            issue="unbalanced quotation marks, parentheses, or trailing Boolean operator",
        )
    if re.search(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]", value):
        return QueryValidation(source=source_id, query=value, ok=False, issue="query contains control characters or multiple lines")
    api_parameter = re.search(
        r"(?:^|[?&\s])(?:query(?:\.[a-z_]+)?|search(?:\.[a-z_]+)?|filter|page|limit)=",
        value,
        flags=re.IGNORECASE,
    )
    if api_parameter or re.search(r"https?://", value, flags=re.IGNORECASE):
        return QueryValidation(source=source_id, query=value, ok=False, issue="query must contain only the source query value, not a URL or API parameter")
    foreign_field = re.search(
        r"(?:^|[\s(])(?:TS|TI|AB|AU)\s*=|(?:^|[\s(])(?:all|ti|abs|cat|title|abstract|topic):|\[[A-Za-z][^\]]*\]",
        value,
        flags=re.IGNORECASE,
    )
    if source_id in PLAIN_TEXT_QUERY_SOURCES:
        if re.search(r"\s+(?:AND|OR|NOT|ANDNOT)\s+", value, flags=re.IGNORECASE):
            return QueryValidation(source=source_id, query=value, ok=False, issue=f"{source_id} relevance search requires plain text, not Boolean operators")
        if foreign_field:
            return QueryValidation(source=source_id, query=value, ok=False, issue=f"{source_id} relevance search does not accept database field syntax")
    if source_id in MINIMAL_BOOLEAN_QUERY_SOURCES:
        if re.search(r"\s+(?:AND|NOT|ANDNOT)\s+", value, flags=re.IGNORECASE):
            return QueryValidation(source=source_id, query=value, ok=False, issue=f"{source_id} uses implicit AND with OR groups and minus exclusions")
        if foreign_field:
            return QueryValidation(source=source_id, query=value, ok=False, issue=f"{source_id} does not accept database field syntax")
    if source_id == "openalex":
        if len(urlencode({"search": value}).encode("ascii")) > OPENALEX_MAX_ENCODED_SEARCH_BYTES:
            return QueryValidation(source=source_id, query=value, ok=False, issue="OpenAlex search query is too long for a safe request URL; use fewer established terms or split the search into query views")
        operators = {operator for _, _, operator in _top_level_boolean_matches(value)}
        if "AND" in operators and "OR" in operators:
            return QueryValidation(source=source_id, query=value, ok=False, issue="OpenAlex mixed top-level AND/OR requires each OR synonym group to be parenthesized")
        if re.search(r"[*?]", value):
            return QueryValidation(source=source_id, query=value, ok=False, issue="OpenAlex search= does not accept wildcard syntax; use complete terms")
    if source_id == "arxiv" and re.search(r"(?:^|[\s(])(?:title|abstract|author|topic):", value, flags=re.IGNORECASE):
        return QueryValidation(source=source_id, query=value, ok=False, issue="arXiv field prefixes must use all:, ti:, abs:, au:, cat:, id:, jr:, co:, or rn:")
    if source_id == "pubmed" and re.search(r"(?:^|[\s(])(?:all|ti|abs|cat):", value, flags=re.IGNORECASE):
        return QueryValidation(source=source_id, query=value, ok=False, issue="PubMed fields must use bracketed tags such as [Title/Abstract]")
    return QueryValidation(source=source_id, query=value, ok=True)


def _dedupe_top_level_and(query: str) -> str:
    matches = _top_level_boolean_matches(query)
    if not matches or any(operator != "AND" for _, _, operator in matches):
        return query
    clauses = []
    start = 0
    for match_start, match_end, _ in matches:
        clauses.append(query[start:match_start].strip())
        start = match_end
    clauses.append(query[start:].strip())
    if any(not clause for clause in clauses):
        return query
    output = []
    seen = set()
    for clause in clauses:
        normalized = re.sub(r"\s+", " ", clause).strip().casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        output.append(clause)
    return " AND ".join(output)


def _source_safe_query(source: str, query: str) -> str:
    value = str(query or "").strip()
    if source == "semanticscholar":
        return re.sub(r"\s+", " ", re.sub(r"(?<=\w)[\-‐-―](?=\w)", " ", value)).strip()
    if source != "openalex":
        return value
    original = value
    cleaned = original.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    cleaned = re.sub(r"^\s*(?:search|q)\s*=\s*", "", cleaned, flags=re.IGNORECASE).strip().strip("`")
    cleaned = re.sub(r"\b(?:filter|per-page|page|sort|select|fields)\s*=[^\s]+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"([A-Za-z0-9])[*?]+\b", r"\1", cleaned).replace("*", "").replace("?", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([)])", r"\1", cleaned)
    cleaned = re.sub(r"([(])\s+", r"\1", cleaned)
    cleaned = re.sub(r"^\s*(?:AND|OR|NOT)\b\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+\b(?:AND|OR|NOT)\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\(\s*(?:AND|OR)\s+", "(", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(?:AND|OR)\s*\)", ")", cleaned, flags=re.IGNORECASE)
    return _dedupe_top_level_and(cleaned.strip()) or original


def strict_query_output_instruction(output_label: str) -> str:
    normalized_label = str(output_label or "").casefold()
    atomic = ""
    if "broadened" in normalized_label:
        atomic = (
            "- Make exactly one atomic broadening edit to the current query. Change one concept group only: "
            "remove one non-essential restrictive group, replace one group's wording with broader alternatives, "
            "or broaden the alternatives inside that one group. Copy every other concept group and filter unchanged. "
            "Do not remove one group and broaden another in the same response.\n"
            "- In rationale, name the one changed concept group and describe its before/after meaning.\n"
        )
    elif "narrowed" in normalized_label:
        atomic = (
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
        f"{atomic}"
        "- The rationale field may briefly explain the adjustment, direction, or title-intent diagnostic for audit.\n"
        "- Do not put the rationale, labels, markdown, bullets, or comments inside the query field.\n"
        "- If you compare returned titles with the intent, put the on-intent/off-intent conclusion in rationale and keep query clean.\n"
        "- If you cannot improve the query, repeat the current valid query in query and explain why in rationale.\n"
    )


class QueryPlanner:
    def __init__(self, llm: LLMPort) -> None:
        self.llm = llm

    async def plan(self, question: str, *, portfolio_required: bool) -> SearchPlan:
        messages = [
            {"role": "system", "content": prompts.SYSTEM_SEARCH_INTENT_ANALYSIS},
            {"role": "user", "content": f"Research question: {question}\n\nOutput ONLY the compact JSON intent object."},
        ]
        raw = await self.llm.chat_json(messages, temperature=0.0, max_tokens=4096)
        first = parse_search_plan(raw, question)
        gaps = first.coverage_gaps() if first is not None and portfolio_required else ([] if first is not None else ["a valid SearchPlan JSON object"])
        if not gaps:
            return first
        if first is None:
            retry_messages = [
                {"role": "system", "content": prompts.SYSTEM_SEARCH_INTENT_ANALYSIS},
                {
                    "role": "user",
                    "content": (
                        f"Research question: {question}\n\n"
                        "The previous response was invalid or truncated. Start over without repeating it. "
                        "Return one compact SearchPlan JSON object under 1800 tokens. Use exactly 3 query_views, "
                        "ordered by expected unique recall contribution, with at most 3 concept_groups per view "
                        "and at most 5 short terms per group. Every view must contain valid concept_groups. Output only JSON."
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
                        f"{'; '.join(gaps)}. Return a complete replacement SearchPlan JSON object. Preserve useful existing views, "
                        "add the missing distinct views, and output only JSON. Every query view must contain valid concept_groups."
                    ),
                },
            ]
        retry_raw = await self.llm.chat_json(retry_messages, temperature=0.0, max_tokens=4096)
        retry = parse_search_plan(retry_raw, question)
        if retry is not None and (not portfolio_required or not retry.coverage_gaps()):
            return retry
        if first is not None:
            return first
        if retry is not None:
            return retry
        return fallback_search_plan(question, "invalid structured output")

    async def propose(
        self,
        source: str,
        question: str,
        plan: SearchPlan,
        *,
        operation: str,
        current_query: str = "",
        feedback: str = "",
    ) -> SourceQueryProposal:
        source_id = str(source or "").strip().lower()
        prompt_operation = operation if operation in {"generate", "broaden", "narrow"} else "generate"
        system_prompt = _PROMPT_BY_SOURCE[source_id][prompt_operation]
        label = _SOURCE_LABELS[source_id]
        output_label = label if operation == "generate" else f"{operation}ed {label}"
        if operation == "repair":
            output_label = f"corrected {label}"
        user_parts = [f"Research question: {question}", plan.audit_summary()]
        if current_query:
            user_parts.append(f"Current query: {current_query}")
        if feedback:
            user_parts.append(feedback)
        user_parts.append(strict_query_output_instruction(output_label))
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(user_parts)},
        ]
        raw = await self.llm.chat_json(messages, temperature=0.0, max_tokens=2048)
        query, rationale = _parse_query_proposal(raw)
        query = _source_safe_query(source_id, query)
        validation = validate_source_query(source_id, query)
        if validation.ok:
            return SourceQueryProposal(query=query, rationale=rationale)

        repair_messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Research question: {question}\n"
                    f"{plan.audit_summary()}\n"
                    f"Previous valid query: {current_query or '(none)'}\n"
                    f"Rejected malformed {operation} output: {query or '(empty)'}\n"
                    f"Format problem: {validation.issue}.\n\n"
                    f"Generate a complete replacement {output_label}. Do not return a fragment. "
                    "Keep quotation marks and parentheses balanced."
                    f"{strict_query_output_instruction(output_label)}"
                ),
            },
        ]
        retry_raw = await self.llm.chat_json(repair_messages, temperature=0.0, max_tokens=2048)
        repaired, repaired_rationale = _parse_query_proposal(retry_raw)
        repaired = _source_safe_query(source_id, repaired)
        if validate_source_query(source_id, repaired).ok:
            return SourceQueryProposal(
                query=repaired,
                rationale=repaired_rationale,
                warnings=["query_output_repaired"],
            )
        if current_query:
            return SourceQueryProposal(
                query=current_query,
                warnings=["query_revision_invalid_previous_query_retained"],
            )
        raise QueryGenerationError(
            f"{source_id} query generation failed: LLM did not return valid JSON with a query field."
        )


@dataclass(frozen=True)
class CompiledQuery:
    source: str
    view_id: str
    query: str
    purpose: str = ""


def _selected_groups(view: QueryView) -> list[ConceptGroup]:
    required = [group for group in view.concept_groups if group.required]
    return required or list(view.concept_groups[:1])


def _clean_term(value: str, *, strip_wildcards: bool = True) -> str:
    term = re.sub(r"\s+", " ", str(value or "")).strip().replace("\\", " ").replace('"', " ")
    if strip_wildcards:
        term = term.replace("*", "").replace("?", "")
    return re.sub(r"\s+", " ", term).strip(" ()[]{}")


def _quoted_term(value: str) -> str:
    term = _clean_term(value)
    return f'"{term}"' if term and re.search(r"\s", term) else term


def _unique_terms(groups: list[ConceptGroup], *, per_group: int = 4, total: int = 12) -> list[str]:
    output = []
    seen = set()
    for group in groups:
        for value in group.terms[:per_group]:
            term = _clean_term(value)
            key = term.casefold()
            if not term or key in seen:
                continue
            seen.add(key)
            output.append(term)
            if len(output) >= total:
                return output
    return output


def compile_query_view(source: str, view: QueryView) -> CompiledQuery:
    source_id = str(source or "").strip().lower()
    if source_id not in SUPPORTED_QUERY_SOURCES:
        raise ValueError(f"No structured query compiler is available for source={source_id}")
    groups = _selected_groups(view)
    if source_id in {"crossref", "semanticscholar"}:
        terms = _unique_terms(groups, per_group=3 if source_id == "semanticscholar" else 4, total=10 if source_id == "semanticscholar" else 12)
        query = " ".join(terms)
        if source_id == "semanticscholar":
            query = re.sub(r"\s+", " ", re.sub(r"(?<=\w)[\-‐-―](?=\w)", " ", query)).strip()
    elif source_id == "arxiv":
        required = []
        optional = []
        fields = {"all": "all", "title": "ti", "abstract": "abs"}
        for group in view.concept_groups:
            terms = []
            for value in group.terms:
                term = re.sub(r"\s+", " ", str(value or "")).strip().replace("\\", " ").replace('"', " ").strip(" ()")
                if term:
                    terms.append(f'{fields.get(group.field_hint, "all")}:"{term}"' if re.search(r"\s", term) else f'{fields.get(group.field_hint, "all")}:{term}')
            clause = terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})" if terms else ""
            if clause:
                (required if group.required else optional).append(clause)
        clauses = required or ([optional[0] if len(optional) == 1 else f"({' OR '.join(optional)})"] if optional else [])
        query = " AND ".join(clauses)
        for exclusion in view.exclusions:
            term = re.sub(r"\s+", " ", exclusion).strip().replace('"', "").strip(" ()")
            if term:
                query += f' ANDNOT all:"{term}"' if re.search(r"\s", term) else f" ANDNOT all:{term}"
    elif source_id == "openalex":
        required = []
        optional = []
        for group in view.concept_groups:
            terms = [_quoted_term(value) for value in group.terms]
            terms = [term for term in terms if term]
            clause = terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})" if terms else ""
            if clause:
                (required if group.required else optional).append(clause)
        clauses = required or ([optional[0] if len(optional) == 1 else f"({' OR '.join(optional)})"] if optional else [])
        query = " AND ".join(clauses)
        for exclusion in view.exclusions:
            term = _quoted_term(exclusion)
            if term:
                query += f" NOT {term}"
    elif source_id == "pubmed":
        fields = {"all": "Title/Abstract", "title": "Title", "abstract": "Title/Abstract"}
        clauses = []
        for group in groups:
            terms = [f"{_quoted_term(value)}[{fields.get(group.field_hint, 'Title/Abstract')}]" for value in group.terms if _quoted_term(value)]
            if terms:
                clauses.append(terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})")
        query = " AND ".join(clauses)
        exclusions = [f"{_quoted_term(value)}[Title/Abstract]" for value in view.exclusions if _quoted_term(value)]
        if exclusions:
            query += f" NOT {exclusions[0] if len(exclusions) == 1 else f'({' OR '.join(exclusions)})'}"
    elif source_id in {"googlescholar", "paperhub"}:
        clauses = []
        for group in groups:
            terms = [_quoted_term(value) for value in group.terms]
            terms = [term for term in terms if term]
            if terms:
                if source_id == "googlescholar":
                    clauses.append(terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})")
                else:
                    clauses.append(" OR ".join(terms))
        query = " ".join(clauses)
        for exclusion in view.exclusions:
            term = _quoted_term(exclusion)
            if term:
                query += f" -{term}"
    else:
        clauses = []
        for group in groups:
            terms = [_quoted_term(value) for value in group.terms]
            terms = [term for term in terms if term]
            if terms:
                clauses.append(terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})")
        topic = " AND ".join(clauses)
        for exclusion in view.exclusions:
            term = _quoted_term(exclusion)
            if term:
                topic += f" NOT {term}"
        query = f"TS=({topic})"
    if not query:
        raise ValueError(f"{source_id} query view did not contain compilable terms")
    validation = validate_source_query(source_id, query)
    if not validation.ok:
        raise ValueError(validation.issue)
    return CompiledQuery(source=source_id, view_id=view.view_id, query=query, purpose=view.purpose)


_QUERY_STOPWORDS = {"a", "an", "and", "by", "for", "in", "not", "of", "on", "or", "the", "to", "with"}


def _normalize_query(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _query_terms(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold()) if len(token) > 1 and token not in _QUERY_STOPWORDS}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


@dataclass
class _Selection:
    source: str
    view: QueryView
    original_index: int
    score: float
    lexical_overlap: float
    max_pairwise_overlap: float
    selected: bool
    reason_codes: list[str]
    compiled_query: str
    compile_error: str


def _select_query_views(plan: SearchPlan, source: str, primary_query: str, budget: int) -> list[_Selection]:
    budget = max(0, int(budget or 0))
    primary_normalized = _normalize_query(primary_query)
    primary_terms = _query_terms(primary_query)
    selections = []
    for index, view in enumerate(plan.query_views):
        score = 1.0 - index * 0.01
        reasons = ["search_plan_expected_gain_order"]
        compiled_query = ""
        compile_error = ""
        overlap = 0.0
        try:
            compiled_query = compile_query_view(source, view).query
            overlap = _jaccard(primary_terms, _query_terms(compiled_query))
        except Exception as exc:
            compile_error = f"{exc.__class__.__name__}: {exc}"
            score = -10.0
            reasons.append("compile_error")
        normalized = _normalize_query(compiled_query)
        if normalized and normalized == primary_normalized:
            score = -9.0
            reasons.append("exact_primary_duplicate")
        elif view.view_type == "direct_terminology" and overlap >= DIRECT_VIEW_OVERLAP_THRESHOLD:
            reasons.append("high_primary_overlap_observed")
        else:
            reasons.append("complementary_view")
        selections.append(_Selection(source, view, index, score, overlap, 0.0, False, reasons, compiled_query, compile_error))
    eligible = [item for item in selections if not item.compile_error and "exact_primary_duplicate" not in item.reason_codes]
    selected_indexes = set()
    selected_terms = []
    selected_normalized = set()
    for item in sorted(eligible, key=lambda candidate: (-candidate.score, candidate.original_index)):
        if len(selected_indexes) >= budget:
            break
        normalized = _normalize_query(item.compiled_query)
        terms = _query_terms(item.compiled_query)
        pairwise = max((_jaccard(terms, existing) for existing in selected_terms), default=0.0)
        item.max_pairwise_overlap = pairwise
        if normalized in selected_normalized:
            item.reason_codes.append("exact_selected_view_duplicate")
        elif pairwise >= PAIRWISE_VIEW_OVERLAP_THRESHOLD:
            item.reason_codes.append("near_selected_view_duplicate")
        else:
            selected_indexes.add(item.original_index)
            selected_normalized.add(normalized)
            selected_terms.append(terms)
    for item in selections:
        item.selected = item.original_index in selected_indexes
    return selections


_TITLE_DRIFT_STOPWORDS = {
    "about", "across", "after", "against", "analysis", "and", "are", "based", "between", "boundaries",
    "case", "concept", "concepts", "core", "data", "effect", "effects", "from", "how", "intent", "into",
    "likely", "literature", "method", "methods", "model", "models", "not", "only", "paper", "papers",
    "query", "research", "result", "results", "search", "study", "studies", "synonyms", "that", "the",
    "their", "this", "through", "using", "what", "when", "where", "with",
}
_TITLE_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{1,}|[\u4e00-\u9fff]{2,}")


def _title_signal_terms(terms: list[str], limit: int = 16) -> list[str]:
    output = []
    seen = set()
    for term in terms:
        for match in _TITLE_TERM_RE.findall(str(term or "")):
            clean = match.strip("-").lower()
            if (len(clean) < 3 and not match.isupper()) or clean in _TITLE_DRIFT_STOPWORDS or clean in seen:
                continue
            seen.add(clean)
            output.append(clean)
            if len(output) >= limit:
                return output
    return output


def _title_drift(snapshot: QueryLoopSnapshot) -> tuple[bool, str, str]:
    titles = [str(title or "").strip() for title in snapshot.top_titles[:5] if str(title or "").strip()]
    if len(titles) < 3:
        return False, "", ""
    signal_terms = _title_signal_terms(list(snapshot.intent_terms or []) or [snapshot.query])
    if len(signal_terms) < 3:
        return False, "", ""
    title_text = " ".join(titles).lower()
    covered = [term for term in signal_terms if term in title_text]
    coverage = len(covered) / max(1, len(signal_terms))
    drifted = len(covered) == 0 or (len(signal_terms) >= 6 and len(covered) < 2 and coverage < 0.20)
    if not drifted:
        return False, "", ""
    missing = [term for term in signal_terms if term not in covered][:6]
    return (
        True,
        "top returned titles appear off-intent; preserve the core intent and redirect the query toward missing facets: " + ", ".join(missing),
        f"Title-intent coverage was low before accepting the count ({len(covered)}/{len(signal_terms)} signal terms matched in the top titles).",
    )


def _contiguous_narrow_totals(snapshot: QueryLoopSnapshot, pool_max: int) -> list[int]:
    totals = []
    for row in reversed(snapshot.history):
        action = str(row.get("action") or "").strip().lower()
        if action in {"repair", "sanitize"}:
            continue
        if action != "narrow":
            break
        try:
            total = int(row.get("total"))
        except (TypeError, ValueError):
            break
        if total <= pool_max:
            break
        totals.append(total)
    totals.reverse()
    return totals


class QueryLoopController:
    def decide(self, snapshot: QueryLoopSnapshot) -> QueryLoopDecision:
        total = max(0, int(snapshot.total or 0))
        iteration = max(1, int(snapshot.iteration or 1))
        configured = max(1, int(snapshot.configured_iterations or 1))
        adaptive = max(configured, int(snapshot.adaptive_max_iterations or configured))
        target_min = max(0, int(snapshot.target_min or 0))
        target_max = max(1, int(snapshot.target_max or 1))
        pool_min = max(0, int(snapshot.retrieval_pool_min or 0))
        pool_max = max(1, int(snapshot.retrieval_pool_max or target_max))
        if total == 0:
            if snapshot.consecutive_zero_results >= 3 or iteration >= adaptive:
                return QueryLoopDecision(action="empty", terminal=True, message="No records found before the iteration limit was reached.", adjustment="zero records", reason="Stop only after repeated zero-result searches or the adaptive hard iteration budget.")
            return QueryLoopDecision(action="broaden", message="No records found; generated a broader query.", adjustment="too few or zero records", reason="Zero-result searches should broaden beyond the configured soft iteration count until the adaptive budget is exhausted.")
        drifted, adjustment, reason = _title_drift(snapshot)
        if drifted and iteration < configured:
            return QueryLoopDecision(action="narrow", message=f"{total} records found, but the top returned titles appear off-intent; generated a redirected query.", adjustment=adjustment, reason=reason)
        if target_min <= total <= target_max:
            return QueryLoopDecision(action="accept", terminal=True, message=f"Accepted {total} records within the target range.", reason="The source count is inside the user-facing target range.")
        if total < target_min:
            if total < pool_min and iteration < adaptive:
                return QueryLoopDecision(action="broaden", message=f"Only {total} records found, below the target minimum of {target_min}; generated a broader query.", adjustment=f"below target minimum {target_min}", reason="The candidate pool is too small for robust downstream ranking.")
            return QueryLoopDecision(action="accept_low", terminal=True, message=f"Accepted {total} records at the iteration limit, below the target minimum of {target_min}.", adjustment=f"below target minimum {target_min}", reason="A small non-empty candidate pool can still be ranked after the adaptive budget is exhausted.")
        if total > pool_max:
            previous = _contiguous_narrow_totals(snapshot, pool_max)
            sequence = [*previous[-2:], total]
            stalled = len(sequence) >= 3 and all((before - after) / max(1, before) < 0.10 for before, after in zip(sequence, sequence[1:]))
            if iteration < adaptive and not (iteration >= configured and stalled):
                trend = f" The preceding broad query returned {previous[-1]} records; use the title feedback to choose a different, intent-preserving constraint." if previous else ""
                return QueryLoopDecision(
                    action="narrow",
                    message=f"{total} records exceed the bounded retrieval pool of {pool_max}; generated a narrower query before candidate materialization.",
                    adjustment=f"reduce the source result count toward {pool_max} or fewer by tightening one central facet supported by the interpreted intent and returned titles; preserve the core intent.{trend}",
                    reason="A database-wide count above the retrieval pool should be narrowed before bounded retrieval; relevant top titles alone are not sufficient evidence to accept the long tail.",
                )
            stop_reason = "successive narrowing rounds no longer reduced the broad source count meaningfully" if stalled else f"the adaptive hard limit of {adaptive} iterations was reached"
            return QueryLoopDecision(action="accept_high", terminal=True, message=f"Accepted a broad source result set of {total} records after {stop_reason}; bounded retrieval lanes will cap the materialized candidate pool at {pool_max} before LLM ranking.", adjustment=f"above LLM pre-ranking safety pool {pool_max}", reason="Further query revision is unlikely to improve the source count within the remaining loop budget, while downstream retrieval remains bounded.")
        if total > target_max:
            return QueryLoopDecision(action="accept_pool", terminal=True, message=f"Accepted {total} records for downstream pre-ranking; final displayed results are selected after retrieval fusion and LLM ranking.", adjustment=f"above target maximum {target_max}", reason="The count is above the display target but inside the safe retrieval pool, so downstream fusion should handle it.")
        return QueryLoopDecision(action="accept", terminal=True, message=f"Accepted {total} records within the target range.", reason="Fallback accept for a valid non-empty candidate pool.")


class QueryLoopPipeline:
    """Run the frozen query loop through explicit LLM, source, and observer ports."""

    def __init__(
        self,
        llm: LLMPort,
        source: SourcePort,
        observer: WorkflowObserver,
        *,
        cancellation: CancellationToken = NEVER_CANCELLED,
    ) -> None:
        self.llm = llm
        self.source = source
        self.observer = observer
        self.cancellation = cancellation
        self.planner = QueryPlanner(llm)
        self.controller = QueryLoopController()

    async def run(self, request: QueryLoopRequest) -> QueryLoopResult:
        self.cancellation.raise_if_cancelled()
        budget = request.budget
        self._event(
            "query.started",
            {
                "source": self.source.name,
                "target_min": budget.target_min,
                "target_max": budget.target_max,
                "retrieval_pool_max": budget.retrieval_pool_max,
                "max_iterations": budget.max_iterations,
            },
        )
        if request.resume is not None:
            state = self._validate_resume(request)
            self._event(
                "query.resumed",
                {
                    "phase": state.phase,
                    "iteration": state.iteration,
                    "portfolio_count": len(state.query_portfolio),
                },
            )
        else:
            plan = await self.planner.plan(
                request.question,
                portfolio_required=budget.query_portfolio_enabled,
            )
            self.cancellation.raise_if_cancelled()
            proposal = await self.planner.propose(
                self.source.name,
                request.question,
                plan,
                operation="generate",
            )
            self.cancellation.raise_if_cancelled()
            state = QueryLoopResumeState(
                phase="query_ready",
                question=request.question,
                source=self.source.name,
                search_plan=plan,
                current_query=proposal.query,
                warnings=proposal.warnings,
            )
            self._event(
                "query.planned",
                {
                    "source": self.source.name,
                    "query_view_count": len(plan.query_views),
                    "warning_count": len(proposal.warnings),
                },
            )
            state = self._checkpoint(state, "query_ready", "query.plan")

        if state.phase not in {"query_primary_complete", "query_portfolio", "query_complete"}:
            state = await self._run_primary_loop(state, budget)
        if state.phase != "query_complete":
            state = await self._run_portfolio(state, budget)
            state = self._checkpoint(state, "query_complete", "query.complete")

        result = self._result(state, budget)
        self._event(
            "query.completed",
            {
                "source": self.source.name,
                "iteration": result.iterations,
                "total": result.total,
                "primary_count": len(result.primary_hits),
                "candidate_count": len(result.records),
                "portfolio_count": len(result.query_portfolio),
                "warning_count": len(result.warnings),
            },
        )
        return result

    def _validate_resume(self, request: QueryLoopRequest) -> QueryLoopResumeState:
        assert request.resume is not None
        resume = request.resume
        if resume.question.strip() != request.question.strip():
            raise QuerySourceError("query checkpoint question does not match the resumed request")
        if resume.source != self.source.name:
            raise QuerySourceError("query checkpoint source does not match the resumed request")
        return resume

    async def _run_primary_loop(
        self,
        state: QueryLoopResumeState,
        budget: QueryLoopBudget,
    ) -> QueryLoopResumeState:
        configured = max(1, int(budget.max_iterations))
        adaptive = (
            max(configured, int(budget.adaptive_max_iterations))
            if budget.adaptive_max_iterations is not None
            else max(configured + 8, configured * 3, 10)
        )
        pool_min = min(max(0, int(budget.retrieval_pool_min)), budget.target_max)
        while state.iteration < adaptive:
            self.cancellation.raise_if_cancelled()
            iteration = state.iteration + 1
            query = state.current_query
            validation = validate_source_query(self.source.name, query)
            if not validation.ok:
                raise QueryGenerationError(
                    f"{self.source.name} query failed preflight: {validation.issue}"
                )
            self._event(
                "query.request_started",
                {
                    "source": self.source.name,
                    "iteration": iteration,
                    "lane": "relevance",
                    "limit": self._primary_limit(budget),
                },
            )
            response = await self._primary_search_with_repair(
                state,
                query,
                iteration,
                budget,
            )
            query = response[0]
            source_result = response[1]
            hits = list(source_result.hits or [])
            total = int(source_result.metadata.total or 0)
            memory = self._record_iteration(
                list(state.query_iteration_memory),
                iteration,
                query,
                total,
                hits,
            )
            fallback_query = state.fallback_query
            fallback_total = state.fallback_total
            fallback_hits = list(state.fallback_hits)
            if total and hits:
                if (
                    not fallback_hits
                    or total <= budget.retrieval_pool_max
                    or fallback_total > budget.retrieval_pool_max
                ):
                    fallback_query = query
                    fallback_total = total
                    fallback_hits = list(hits)
            snapshot = QueryLoopSnapshot(
                iteration=iteration,
                configured_iterations=configured,
                adaptive_max_iterations=adaptive,
                total=total,
                target_min=budget.target_min,
                target_max=budget.target_max,
                retrieval_pool_min=pool_min,
                retrieval_pool_max=budget.retrieval_pool_max,
                history=[item.model_dump(mode="json") for item in state.history],
                query=query,
                hit_count=len(hits),
                top_titles=[record.title for record in hits[:5] if record.title],
                intent_terms=self._intent_terms(state.search_plan),
            )
            decision = self.controller.decide(snapshot)
            updated = state.model_copy(
                update={
                    "current_query": query,
                    "iteration": iteration,
                    "total": total,
                    "primary_hits": hits,
                    "query_iteration_memory": memory,
                    "fallback_query": fallback_query,
                    "fallback_total": fallback_total,
                    "fallback_hits": fallback_hits,
                }
            )
            self._event(
                "query.progress",
                {
                    "iteration": iteration,
                    "total": total,
                    "hit_count": len(hits),
                    "decision": decision.action,
                },
            )
            if decision.action in {"broaden", "narrow"}:
                proposal = await self.planner.propose(
                    self.source.name,
                    state.question,
                    state.search_plan,
                    operation=decision.action,
                    current_query=query,
                    feedback=decision.adjustment,
                )
                warnings = self._merge_unique(updated.warnings, proposal.warnings)
                if _normalize_query(proposal.query) == _normalize_query(query):
                    terminal = self._unchanged_history(
                        iteration,
                        query,
                        total,
                        decision.action,
                        budget,
                    )
                    updated = updated.model_copy(
                        update={
                            "history": [*updated.history, terminal],
                            "warnings": warnings,
                            "terminal_status": terminal.action,
                        }
                    )
                    return self._checkpoint(
                        self._restore_visible_fallback(updated),
                        "query_primary_complete",
                        "query.primary",
                    )
                history = QueryHistoryEntry(
                    iteration=iteration,
                    query=query,
                    total=total,
                    action=decision.action,
                    next_query=proposal.query,
                    message=decision.message,
                    rationale=proposal.rationale,
                    controller_reason=decision.reason,
                )
                updated = updated.model_copy(
                    update={
                        "current_query": proposal.query,
                        "history": [*updated.history, history],
                        "warnings": warnings,
                    }
                )
                state = self._checkpoint(updated, "next_query", "query.iteration")
                continue
            history = QueryHistoryEntry(
                iteration=iteration,
                query=query,
                total=total,
                action=decision.action,
                next_query=None,
                message=decision.message,
                controller_reason=decision.reason,
            )
            updated = updated.model_copy(
                update={
                    "history": [*updated.history, history],
                    "terminal_status": decision.action,
                }
            )
            return self._checkpoint(
                self._restore_visible_fallback(updated),
                "query_primary_complete",
                "query.primary",
            )
        return self._checkpoint(
            self._restore_visible_fallback(state),
            "query_primary_complete",
            "query.primary",
        )

    async def _primary_search_with_repair(
        self,
        state: QueryLoopResumeState,
        query: str,
        iteration: int,
        budget: QueryLoopBudget,
    ) -> tuple[str, Any]:
        current = query
        repair_attempts = 0
        while True:
            request = SourceSearchRequest(
                query=current,
                limit=self._primary_limit(budget),
                page=1,
                lane="relevance",
                field_ids=budget.field_ids,
            )
            try:
                result = await self.source.search(request)
                self.cancellation.raise_if_cancelled()
                return current, result
            except SourceError as exc:
                if exc.status not in {400, 422} or repair_attempts >= 2:
                    self._primary_failed(iteration, exc)
                repair_attempts += 1
                proposal = await self.planner.propose(
                    self.source.name,
                    state.question,
                    state.search_plan,
                    operation="repair",
                    current_query=current,
                    feedback="The source rejected the query syntax; preserve intent and correct only source syntax.",
                )
                if _normalize_query(proposal.query) == _normalize_query(current):
                    self._primary_failed(iteration, exc)
                current = proposal.query
            except Exception as exc:
                self._primary_failed(iteration, exc)

    def _primary_failed(self, iteration: int, exc: Exception) -> None:
        self._event(
            "query.failed",
            {
                "code": "query_primary_source_failed",
                "source": self.source.name,
                "iteration": iteration,
                "error_type": type(exc).__name__,
            },
        )
        raise QuerySourceError("The primary query failed without a recoverable source result.") from exc

    async def _run_portfolio(
        self,
        state: QueryLoopResumeState,
        budget: QueryLoopBudget,
    ) -> QueryLoopResumeState:
        if (
            not budget.query_portfolio_enabled
            or not state.search_plan.query_views
            or self.source.name not in SUPPORTED_QUERY_SOURCES
        ):
            return state.model_copy(update={"phase": "query_portfolio"})
        selections = _select_query_views(
            state.search_plan,
            self.source.name,
            state.current_query,
            budget.query_portfolio_max,
        )
        public_selections = [
            QueryViewSelection(
                source=item.source,
                view_id=item.view.view_id,
                view_type=item.view.view_type,
                selected=item.selected,
                score=round(item.score, 6),
                lexical_overlap=round(item.lexical_overlap, 6),
                max_pairwise_overlap=round(item.max_pairwise_overlap, 6),
                reason_codes=item.reason_codes,
                compile_error=item.compile_error,
                compiled_query=item.compiled_query,
                original_index=item.original_index,
            )
            for item in selections
        ]
        completed_ids = {item.view_id for item in state.query_portfolio}
        requests_started = sum(item.status == "completed" for item in state.query_portfolio)
        seen_queries = {
            _normalize_query(value)
            for value in [
                state.current_query,
                *[item.query for item in state.history],
                *[item.next_query for item in state.history],
            ]
            if value
        }
        combined = dedupe_documents(
            [
                *state.primary_hits,
                *[
                    record
                    for records in state.portfolio_lane_results.values()
                    for record in records
                ],
            ]
        )
        seen_keys = {document_key(record) for record in combined if document_key(record)}
        current = state.model_copy(update={"query_view_selection": public_selections})
        for selection in sorted(selections, key=lambda item: (-item.score, item.original_index)):
            self.cancellation.raise_if_cancelled()
            view = selection.view
            if view.view_id in completed_ids:
                continue
            execution: QueryPortfolioExecution
            if selection.compile_error:
                execution = self._portfolio_execution(selection, status="failed", error="query_view_compile_failed")
            elif "exact_primary_duplicate" in selection.reason_codes:
                execution = self._portfolio_execution(selection, status="skipped_duplicate")
            elif requests_started >= budget.query_portfolio_max:
                execution = self._portfolio_execution(
                    selection,
                    status="skipped_budget",
                    reasons=self._merge_unique(selection.reason_codes, ["query_view_request_budget"]),
                )
            else:
                query = selection.compiled_query
                normalized = _normalize_query(query)
                if not normalized or normalized in seen_queries:
                    execution = self._portfolio_execution(selection, status="skipped_duplicate")
                else:
                    seen_queries.add(normalized)
                    requests_started += 1
                    try:
                        validation = validate_source_query(self.source.name, query)
                        if not validation.ok:
                            raise ValueError(validation.issue)
                        self._event(
                            "query.portfolio_request_started",
                            {
                                "view_id": view.view_id,
                                "limit": budget.query_portfolio_limit,
                            },
                        )
                        response = await self.source.search(
                            SourceSearchRequest(
                                query=query,
                                limit=budget.query_portfolio_limit,
                                page=1,
                                lane="relevance",
                                field_ids=budget.field_ids,
                            )
                        )
                        self.cancellation.raise_if_cancelled()
                        view_hits = list(response.hits or [])
                        added = 0
                        for record in view_hits:
                            key = document_key(record)
                            if not key or key in seen_keys:
                                continue
                            seen_keys.add(key)
                            combined.append(record)
                            added += 1
                        lane_results = dict(current.portfolio_lane_results)
                        lane_results[view.view_id] = view_hits
                        current = current.model_copy(update={"portfolio_lane_results": lane_results})
                        execution = self._portfolio_execution(
                            selection,
                            total=int(response.metadata.total or 0),
                            hit_count=len(view_hits),
                            added_unique=added,
                        )
                    except Exception as exc:
                        warning = f"query_portfolio_failed:{view.view_id}"
                        current = current.model_copy(
                            update={
                                "warnings": self._merge_unique(current.warnings, [warning])
                            }
                        )
                        execution = self._portfolio_execution(
                            selection,
                            status="failed",
                            error=type(exc).__name__,
                        )
                        self._event(
                            "query.portfolio_degraded",
                            {
                                "code": "query_portfolio_failed",
                                "view_id": view.view_id,
                                "error_type": type(exc).__name__,
                            },
                        )
            history = QueryHistoryEntry(
                iteration=current.iteration,
                query=execution.query,
                total=execution.total if execution.status == "completed" else None,
                action="portfolio",
                next_query=None,
                message=(
                    f"Query view {execution.view_id} {execution.status}; returned "
                    f"{execution.hit_count} and added {execution.added_unique} unique candidates."
                ),
                view_id=execution.view_id,
                view_type=execution.view_type,
                purpose=execution.purpose,
                status=execution.status,
                selector_score=execution.selector_score,
                selector_overlap=execution.selector_overlap,
                selector_reasons=execution.selector_reasons,
            )
            current = current.model_copy(
                update={
                    "history": [*current.history, history],
                    "query_portfolio": [*current.query_portfolio, execution],
                }
            )
            completed_ids.add(view.view_id)
            current = self._checkpoint(current, "query_portfolio", "query.portfolio")
        return current.model_copy(update={"phase": "query_portfolio"})

    @staticmethod
    def _portfolio_execution(
        selection: _Selection,
        *,
        status: str = "completed",
        error: str = "",
        reasons: list[str] | None = None,
        total: int = 0,
        hit_count: int = 0,
        added_unique: int = 0,
    ) -> QueryPortfolioExecution:
        return QueryPortfolioExecution(
            view_id=selection.view.view_id,
            view_type=selection.view.view_type,
            purpose=selection.view.purpose,
            query=selection.compiled_query,
            total=total,
            hit_count=hit_count,
            added_unique=added_unique,
            status=status,
            error=error,
            selector_score=selection.score,
            selector_overlap=selection.lexical_overlap,
            selector_reasons=reasons if reasons is not None else selection.reason_codes,
        )

    def _result(
        self,
        state: QueryLoopResumeState,
        budget: QueryLoopBudget,
    ) -> QueryLoopResult:
        supplemental = {}
        final_normalized = _normalize_query(state.current_query)
        for item in state.query_iteration_memory:
            if item.records and _normalize_query(item.query) != final_normalized:
                supplemental[f"query_iteration:{max(1, item.iteration)}"] = list(item.records)
        for view_id, records in state.portfolio_lane_results.items():
            if records:
                supplemental[f"query_view:{view_id}"] = list(records)
        records = dedupe_documents(
            [
                *state.primary_hits,
                *[record for values in state.portfolio_lane_results.values() for record in values],
            ]
        )
        retrieval = RetrievalRequest(
            question=state.question,
            query=state.current_query,
            primary_hits=state.primary_hits,
            supplemental_lanes=supplemental,
            lane_limit=budget.retrieval_lane_limit,
            ranking_candidate_limit=budget.ranking_candidate_limit,
            pool_max=budget.retrieval_pool_max,
            field_ids=budget.field_ids,
        )
        return QueryLoopResult(
            question=state.question,
            source=state.source,
            search_plan=state.search_plan,
            final_query=state.current_query,
            total=state.total,
            primary_hits=state.primary_hits,
            records=records,
            iterations=state.iteration,
            history=state.history,
            query_iteration_memory=state.query_iteration_memory,
            query_view_selection=state.query_view_selection,
            query_portfolio=state.query_portfolio,
            terminal_status=state.terminal_status,
            warnings=state.warnings,
            retrieval_request=retrieval,
        )

    def _checkpoint(
        self,
        state: QueryLoopResumeState,
        phase: str,
        step_key: str,
    ) -> QueryLoopResumeState:
        self.cancellation.raise_if_cancelled()
        current = state.model_copy(update={"phase": phase})
        payload = {
            "source": current.source,
            "question": current.question,
            "phase": phase,
            "iteration": current.iteration,
            "query": current.current_query,
            "portfolio": [item.view_id for item in current.query_portfolio],
        }
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.observer.on_checkpoint(
            CheckpointDraft(
                step_key=step_key,
                idempotency_key=f"query:{phase}:{digest}",
                state=current.model_dump(mode="json"),
                workflow_version="m2.query-loop.v1",
            )
        )
        return current

    def _restore_visible_fallback(
        self,
        state: QueryLoopResumeState,
    ) -> QueryLoopResumeState:
        if state.total != 0 or state.primary_hits or not state.fallback_hits:
            return state
        history = QueryHistoryEntry(
            iteration=state.iteration,
            query=state.current_query,
            total=0,
            action="fallback",
            next_query=state.fallback_query,
            message=(
                "The latest query returned 0 records; fell back to the most recent non-empty "
                "candidate pool for downstream retrieval and ranking."
            ),
        )
        return state.model_copy(
            update={
                "current_query": state.fallback_query,
                "total": state.fallback_total,
                "primary_hits": state.fallback_hits,
                "history": [*state.history, history],
                "warnings": self._merge_unique(
                    state.warnings,
                    ["query_terminal_zero_last_nonempty_retained"],
                ),
            }
        )

    @staticmethod
    def _record_iteration(
        memory: list[QueryIterationMemory],
        iteration: int,
        query: str,
        total: int,
        records: list[PaperRecord],
    ) -> list[QueryIterationMemory]:
        records = dedupe_documents(records)[:100]
        normalized = _normalize_query(query)
        if not records or not normalized:
            return memory
        entry = QueryIterationMemory(
            iteration=iteration,
            query=query,
            total=total,
            records=records,
        )
        output = list(memory)
        for index, existing in enumerate(output):
            if _normalize_query(existing.query) == normalized:
                output[index] = entry
                break
        else:
            output.append(entry)
        return output[-12:]

    @staticmethod
    def _unchanged_history(
        iteration: int,
        query: str,
        total: int,
        attempted_action: str,
        budget: QueryLoopBudget,
    ) -> QueryHistoryEntry:
        attempted = "broader" if attempted_action == "broaden" else "narrower"
        if total == 0:
            action = "empty"
            message = f"No records found and the {attempted} query was unchanged; stopped instead of repeating the same request."
        elif total < budget.target_min:
            action = "accept_low"
            message = f"Accepted {total} records below the target minimum because the {attempted} query was unchanged."
        elif total > budget.retrieval_pool_max:
            action = "accept_high"
            message = f"Accepted {total} records above the LLM pre-ranking safety pool because the {attempted} query was unchanged; the fused candidate pool will be truncated before LLM ranking."
        elif total > budget.target_max:
            action = "accept_pool"
            message = f"Accepted {total} records for downstream pre-ranking because the {attempted} query was unchanged."
        else:
            action = "accept"
            message = f"Accepted {total} records because the {attempted} query was unchanged."
        return QueryHistoryEntry(
            iteration=iteration,
            query=query,
            total=total,
            action=action,
            next_query=None,
            message=message,
        )

    def _primary_limit(self, budget: QueryLoopBudget) -> int:
        output_limit = max(1, min(int(budget.target_max or 50), 50))
        if self.source.name == "wos":
            return output_limit
        return min(max(output_limit * 2, output_limit), 100)

    @staticmethod
    def _intent_terms(plan: SearchPlan) -> list[str]:
        return [
            *plan.core_concepts,
            *plan.must_have_facets,
            *plan.likely_synonyms,
            plan.required_relation,
        ]

    @staticmethod
    def _merge_unique(values: Iterable[str], additions: Iterable[str]) -> list[str]:
        return list(dict.fromkeys([*values, *additions]))

    def _event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.cancellation.raise_if_cancelled()
        self.observer.on_event(
            CoreProgressEvent(event_type=event_type, stage="query", payload=payload)
        )


__all__ = [
    "CompiledQuery",
    "QueryLoopController",
    "QueryLoopPipeline",
    "QueryPlanner",
    "compile_query_view",
    "fallback_search_plan",
    "parse_search_plan",
    "strict_query_output_instruction",
    "validate_source_query",
]
