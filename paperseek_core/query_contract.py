"""Validation and bounded repair for source-specific query output."""

from __future__ import annotations

import re
from typing import Any

from paperseek_core.harness import (
    dedupe_repeated_top_level_conjunctions,
    query_response_from_json,
    validate_source_query,
)
from paperseek_core.harness.pydantic_ai_adapter import (
    PydanticAIAdapterUnavailable,
    pydantic_ai_query_retry_enabled,
    run_query_proposal_agent,
)
from paperseek_core.llm import LLMError
from paperseek_core.prompts import (
    SYSTEM_ARXIV_QUERY_GENERATION,
    SYSTEM_CROSSREF_QUERY_GENERATION,
    SYSTEM_GOOGLE_SCHOLAR_QUERY_GENERATION,
    SYSTEM_OPENALEX_QUERY_GENERATION,
    SYSTEM_PAPERHUB_QUERY_GENERATION,
    SYSTEM_PUBMED_QUERY_GENERATION,
    SYSTEM_QUERY_GENERATION,
    SYSTEM_SEMANTIC_SCHOLAR_QUERY_GENERATION,
)
from paperseek_core.sources.providers import ProviderError


def _trim_boolean_edges(query: str) -> str:
    query = re.sub(r"^\s*(?:AND|OR|NOT)\b\s*", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+\b(?:AND|OR|NOT)\s*$", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\(\s*(?:AND|OR)\s+", "(", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+(?:AND|OR)\s*\)", ")", query, flags=re.IGNORECASE)
    return query.strip()


def sanitize_openalex_query(query: str) -> str:
    """Keep OpenAlex search= queries inside the accepted default-search syntax."""

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
    cleaned = re.sub(
        r"\b(?:filter|per-page|page|sort|select|fields)\s*=[^\s]+",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"([A-Za-z0-9])[*?]+\b", r"\1", cleaned)
    cleaned = cleaned.replace("*", "").replace("?", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([)])", r"\1", cleaned)
    cleaned = re.sub(r"([(])\s+", r"\1", cleaned)
    cleaned = _trim_boolean_edges(cleaned)
    cleaned = dedupe_repeated_top_level_conjunctions(cleaned)
    return cleaned or original


def sanitize_semantic_scholar_query(query: str) -> str:
    """Normalize terms that Semantic Scholar does not match reliably."""

    cleaned = str(query or "").strip()
    cleaned = re.sub(r"(?<=\w)[\-\u2010-\u2015](?=\w)", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def provider_error_text(exc: ProviderError) -> str:
    parts = [str(exc)]
    if exc.status:
        parts.append(f"HTTP {exc.status}")
    if exc.body:
        parts.append(str(exc.body))
    return " ".join(parts)


def queries_equivalent(left: str, right: str) -> bool:
    normalize = lambda value: re.sub(r"\s+", " ", (value or "").strip()).lower()
    return normalize(left) == normalize(right)


def strict_query_output_instruction(output_label: str) -> str:
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


class QueryContractGuard:
    """Own query parsing, validation, and bounded corrective requests."""

    def __init__(self, host: Any) -> None:
        self.host = host

    @staticmethod
    def query_temperature() -> float:
        return 0.0

    def chat_json(self, messages: list) -> str:
        chat_json = getattr(self.host.llm, "chat_json", None)
        if callable(chat_json):
            return self.host._run_cancellable(
                lambda: chat_json(messages, temperature=self.query_temperature(), max_tokens=2048)
            )
        return self.host._run_cancellable(
            lambda: self.host.llm.chat(messages, temperature=self.query_temperature())
        )

    def source_safe_query(self, query: str) -> str:
        if self.host.data_source == "openalex":
            return sanitize_openalex_query(query)
        if self.host.data_source == "semanticscholar":
            return sanitize_semantic_scholar_query(query)
        return (query or "").strip()

    def format_issue(self, query: str) -> str:
        validation = validate_source_query(self.host.data_source, query)
        return "" if validation.ok else validation.issue

    def finalize(
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
        query, rationale = query_response_from_json(raw)
        query = self.source_safe_query(self.host._apply_discipline_filter(query))
        self.host.last_query_audit = rationale
        issue = self.format_issue(query)
        if not issue:
            return query
        self.host._emit_log(
            f"{self.host._source_label()} query output looked malformed or truncated ({issue}); requesting a replacement."
        )
        repaired = self.retry_malformed(
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
        self.host.last_query_audit = ""
        if current_query:
            return current_query
        raise LLMError(
            f"{self.host._source_label()} query generation failed: LLM did not return valid JSON with a query field."
        )

    def retry_malformed(
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
        host = self.host
        if not system_prompt:
            system_prompt = self.syntax_repair_prompt()
        retry_log = f"{log_name}_format_retry" if log_name else f"{host.data_source}_query_format_retry"
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Research question: {question}\n"
                    f"{host._intent_context()}"
                    f"{host._discipline_context()}\n"
                    f"{feedback}"
                    f"Previous valid query: {current_query or '(none)'}\n"
                    f"Rejected malformed {operation} output: {malformed_query or '(empty)'}\n"
                    f"Format problem: {issue or 'malformed or truncated output'}.\n\n"
                    f"Generate a complete replacement {output_label}. "
                    "Do not return a fragment. Keep quotation marks and parentheses balanced."
                    f"{strict_query_output_instruction(output_label)}"
                ),
            },
        ]
        host._llm_request_log(retry_log)
        try:
            proposal = None
            if pydantic_ai_query_retry_enabled():
                try:
                    proposal = host._run_cancellable(
                        lambda: run_query_proposal_agent(
                            host.llm,
                            messages,
                            temperature=self.query_temperature(),
                            retries=1,
                            model_name=f"paperseek-{host.data_source}-query-retry",
                        )
                    )
                except PydanticAIAdapterUnavailable as exc:
                    host._emit_log(f"PydanticAI query retry unavailable; using native JSON retry: {exc}")
            if proposal is not None:
                query, rationale = proposal.query, proposal.rationale
            else:
                query, rationale = query_response_from_json(self.chat_json(messages))
            host._llm_response_log(retry_log)
        except Exception as exc:
            host._emit_log(f"{host._source_label()} query format retry skipped after LLM error: {exc}")
            return ""
        query = self.source_safe_query(host._apply_discipline_filter(query))
        host.last_query_audit = rationale
        if query and not self.format_issue(query):
            return query
        host._emit_log(
            f"{host._source_label()} query format retry returned another malformed query; keeping the previous valid query."
        )
        host.last_query_audit = ""
        return ""

    def repair_after_provider_error(self, question: str, query: str, error: ProviderError) -> str:
        if self.host.data_source == "openalex":
            sanitized = sanitize_openalex_query(query)
            if sanitized and not self.format_issue(sanitized) and not queries_equivalent(query, sanitized):
                return sanitized
        if not self.is_repairable_provider_error(error):
            return ""
        return self.repair_source_syntax(question, query, error)

    @staticmethod
    def is_repairable_provider_error(error: ProviderError) -> bool:
        text = provider_error_text(error).lower()
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

    def repair_source_syntax(self, question: str, query: str, error: ProviderError) -> str:
        host = self.host
        source_label = host._source_label()
        messages = [
            {"role": "system", "content": self.syntax_repair_prompt()},
            {
                "role": "user",
                "content": (
                    f"Source: {source_label}\n"
                    f"Research question: {question}\n"
                    f"{host._intent_context()}"
                    f"{host._discipline_context()}\n"
                    f"Rejected query:\n{query}\n\n"
                    f"API error:\n{provider_error_text(error)[:1200]}\n\n"
                    "Return exactly one corrected query string that preserves the research intent "
                    "and follows the source API rules."
                    f"{strict_query_output_instruction('corrected source query string')}"
                ),
            },
        ]
        host._llm_request_log(f"{host.data_source}_query_syntax_repair")
        try:
            raw = self.chat_json(messages)
            host._llm_response_log(f"{host.data_source}_query_syntax_repair")
        except Exception as exc:
            host._emit_log(f"{source_label} query syntax repair skipped after LLM error: {exc}")
            return ""
        repaired, rationale = query_response_from_json(raw)
        repaired = self.source_safe_query(host._apply_discipline_filter(repaired))
        host.last_query_audit = rationale
        if not repaired or self.format_issue(repaired):
            host.last_query_audit = ""
            return ""
        return repaired

    def syntax_repair_prompt(self) -> str:
        source = self.host.data_source
        if source == "openalex":
            return (
                SYSTEM_OPENALEX_QUERY_GENERATION
                + "\nRepair task: correct only syntax that the OpenAlex /works search parameter rejected. "
                "Keep the output as a single search= query value. Do not use search.exact, filters, wildcards, URLs, or API parameters."
            )
        if source == "crossref":
            return (
                SYSTEM_CROSSREF_QUERY_GENERATION
                + "\nRepair task: convert the rejected text into a valid Crossref query.bibliographic value. "
                "Keep plain bibliographic terms only."
            )
        if source == "arxiv":
            return SYSTEM_ARXIV_QUERY_GENERATION + "\nRepair task: return a valid arXiv search_query value only."
        if source == "semanticscholar":
            return SYSTEM_SEMANTIC_SCHOLAR_QUERY_GENERATION + "\nRepair task: return a valid Semantic Scholar query value only."
        if source == "pubmed":
            return SYSTEM_PUBMED_QUERY_GENERATION + "\nRepair task: return a valid PubMed ESearch term value only."
        if source == "googlescholar":
            return SYSTEM_GOOGLE_SCHOLAR_QUERY_GENERATION + "\nRepair task: return a valid Google Scholar q value only."
        if source == "paperhub":
            return SYSTEM_PAPERHUB_QUERY_GENERATION + "\nRepair task: return valid plain PaperHub search text only."
        return SYSTEM_QUERY_GENERATION + "\nRepair task: return a valid Web of Science Starter API q value only."
