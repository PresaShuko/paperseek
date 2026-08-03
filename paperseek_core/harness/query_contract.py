
import json
import re
from typing import Any, Dict, Iterable, Tuple
from urllib.parse import urlencode

from pydantic import ValidationError

from paperseek_core.harness.schemas import QueryProposal, QueryValidation


QUERY_FIELD_ALIASES = ("query", "search_query", "query_string", "source_query", "term", "wos_query")
RATIONALE_FIELD_ALIASES = ("rationale", "adjustment", "adjustment_direction", "reason", "diagnostic_note")
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


def strip_llm_fence(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def extract_json_object_text(text: str) -> str:
    raw = strip_llm_fence(text)
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


def parse_query_proposal(text: str) -> QueryProposal | None:
    obj_text = extract_json_object_text(text)
    if not obj_text:
        return None
    try:
        parsed = json.loads(obj_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    payload = _normalize_query_payload(parsed)
    try:
        return QueryProposal(**payload)
    except ValidationError:
        return None


def query_response_from_json(text: str) -> Tuple[str, str]:
    proposal = parse_query_proposal(text)
    if proposal is None:
        return "", ""
    return proposal.query, proposal.rationale


def looks_truncated_or_malformed_query(query: str) -> bool:
    value = (query or "").strip()
    if not value:
        return True
    if value.count('"') % 2:
        return True
    if not parentheses_are_balanced(value):
        return True
    if re.search(r"\b(?:AND|OR|NOT)\s*$", value, flags=re.IGNORECASE):
        return True
    if re.search(r"\(\s*$", value):
        return True
    return False


def validate_source_query(source: str, query: str) -> QueryValidation:
    source_id = (source or "").strip().lower()
    value = (query or "").strip()
    if not value:
        return QueryValidation(source=source_id, query=value, ok=False, issue="missing query field in JSON response")
    if source_id not in SUPPORTED_QUERY_SOURCES:
        return QueryValidation(source=source_id, query=value, ok=False, issue=f"unsupported data source: {source_id or '(missing)'}")
    if source_id not in PLAIN_TEXT_QUERY_SOURCES and looks_truncated_or_malformed_query(value):
        return QueryValidation(
            source=source_id,
            query=value,
            ok=False,
            issue="unbalanced quotation marks, parentheses, or trailing Boolean operator",
        )
    issue = _source_specific_query_issue(source_id, value)
    if issue:
        return QueryValidation(source=source_id, query=value, ok=False, issue=issue)
    return QueryValidation(source=source_id, query=value, ok=True)


def dedupe_repeated_top_level_conjunctions(query: str) -> str:
    """Remove exact duplicate top-level AND clauses without changing query meaning."""

    value = str(query or "").strip()
    matches = _top_level_boolean_matches(value)
    if not matches or any(operator != "AND" for _, _, operator in matches):
        return value

    clauses = []
    start = 0
    for match_start, match_end, _ in matches:
        clauses.append(value[start:match_start].strip())
        start = match_end
    clauses.append(value[start:].strip())
    if any(not clause for clause in clauses):
        return value

    deduped = []
    seen = set()
    for clause in clauses:
        normalized = re.sub(r"\s+", " ", clause).strip().casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(clause)
    return " AND ".join(deduped)


def _source_specific_query_issue(source: str, query: str) -> str:
    if re.search(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]", query):
        return "query contains control characters or multiple lines"

    api_parameter = re.search(
        r"(?:^|[?&\s])(?:query(?:\.[a-z_]+)?|search(?:\.[a-z_]+)?|filter|page|limit)=",
        query,
        flags=re.IGNORECASE,
    )
    if api_parameter or re.search(r"https?://", query, flags=re.IGNORECASE):
        return "query must contain only the source query value, not a URL or API parameter"

    foreign_field = re.search(
        r"(?:^|[\s(])(?:TS|TI|AB|AU)\s*=|(?:^|[\s(])(?:all|ti|abs|cat|title|abstract|topic):|\[[A-Za-z][^\]]*\]",
        query,
        flags=re.IGNORECASE,
    )

    if source in PLAIN_TEXT_QUERY_SOURCES:
        if re.search(r"\s+(?:AND|OR|NOT|ANDNOT)\s+", query, flags=re.IGNORECASE):
            return f"{source} relevance search requires plain text, not Boolean operators"
        if foreign_field:
            return f"{source} relevance search does not accept database field syntax"

    if source in MINIMAL_BOOLEAN_QUERY_SOURCES:
        if re.search(r"\s+(?:AND|NOT|ANDNOT)\s+", query, flags=re.IGNORECASE):
            return f"{source} uses implicit AND with OR groups and minus exclusions"
        if foreign_field:
            return f"{source} does not accept database field syntax"

    if source == "openalex":
        encoded_length = len(urlencode({"search": query}).encode("ascii"))
        if encoded_length > OPENALEX_MAX_ENCODED_SEARCH_BYTES:
            return (
                "OpenAlex search query is too long for a safe request URL; "
                "use fewer established terms or split the search into query views"
            )
        top_level_operators = {operator for _, _, operator in _top_level_boolean_matches(query)}
        if "AND" in top_level_operators and "OR" in top_level_operators:
            return "OpenAlex mixed top-level AND/OR requires each OR synonym group to be parenthesized"
        if re.search(r"[*?]", query):
            return "OpenAlex search= does not accept wildcard syntax; use complete terms"

    if source == "arxiv" and re.search(
        r"(?:^|[\s(])(?:title|abstract|author|topic):",
        query,
        flags=re.IGNORECASE,
    ):
        return "arXiv field prefixes must use all:, ti:, abs:, au:, cat:, id:, jr:, co:, or rn:"

    if source == "pubmed" and re.search(r"(?:^|[\s(])(?:all|ti|abs|cat):", query, flags=re.IGNORECASE):
        return "PubMed fields must use bracketed tags such as [Title/Abstract]"

    return ""


def parentheses_are_balanced(query: str) -> bool:
    depth = 0
    for char in query or "":
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _top_level_boolean_matches(query: str) -> list[tuple[int, int, str]]:
    matches: list[tuple[int, int, str]] = []
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


def _normalize_query_payload(parsed: Dict[str, Any]) -> Dict[str, str]:
    query = _first_query_value(parsed, QUERY_FIELD_ALIASES)
    rationale = _join_rationale_values(parsed, RATIONALE_FIELD_ALIASES)
    return {"query": query, "rationale": rationale}


def _first_query_value(parsed: Dict[str, Any], aliases: Iterable[str]) -> str:
    for key in aliases:
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("value") or value.get("query")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def _join_rationale_values(parsed: Dict[str, Any], aliases: Iterable[str]) -> str:
    parts = []
    for key in aliases:
        value = parsed.get(key)
        if isinstance(value, list):
            value = "; ".join(str(item).strip() for item in value if str(item).strip())
        value = str(value or "").strip()
        if value:
            parts.append(value)
    return "\n".join(parts).strip()
