from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable

from paperseek_core.client import ApiException
from paperseek_core.harness import (
    RECOVERY_BROADEN_QUERY,
    RECOVERY_REPAIR_QUERY,
    RECOVERY_SIMPLIFY_QUERY,
)
from paperseek_core.llm import LLMError
from paperseek_core.sources.providers import ProviderError


@dataclass
class QueryExecutionResult:
    query: str
    result: Any | None = None
    retry_iteration: bool = False


class QueryExecutionPipeline:
    """Execute one source-query iteration with bounded repair and recovery."""

    def __init__(
        self,
        host: Any,
        *,
        make_starter_safe_query: Callable[[str], str],
        server_error_query_variants: Callable[[str], list[str]],
        queries_equivalent: Callable[[str, str], bool],
    ) -> None:
        self.host = host
        self.make_starter_safe_query = make_starter_safe_query
        self.server_error_query_variants = server_error_query_variants
        self.queries_equivalent = queries_equivalent

    def run(
        self,
        *,
        question: str,
        query: str,
        iteration: int,
        history: list[dict[str, Any]],
        verbose: bool,
    ) -> QueryExecutionResult:
        query = self._sanitize(query, iteration, history)
        if verbose:
            print(f"[Iteration {iteration}] Query: {query}", file=sys.stderr)

        try:
            query, result = self._search_with_repairs(
                question=question,
                query=query,
                iteration=iteration,
                history=history,
                verbose=verbose,
            )
            return QueryExecutionResult(query=query, result=result)
        except ApiException as exc:
            return self._recover_rejected_query(
                exc,
                question=question,
                query=query,
                iteration=iteration,
                history=history,
            )

    def _sanitize(self, query: str, iteration: int, history: list[dict[str, Any]]) -> str:
        host = self.host
        if host.data_source == "wos":
            safe_query = self.make_starter_safe_query(query)
            message = "Converted the generated query to the stable WoS Starter subset before calling the API."
        else:
            safe_query = host._source_safe_query(query)
            message = f"Sanitized the generated {host._source_label()} query before calling the API."
        if safe_query == query:
            return query

        history.append(
            {
                "iteration": iteration,
                "query": query,
                "total": None,
                "action": "sanitize",
                "next_query": safe_query,
                "message": message,
            }
        )
        host._emit_stage("search", "processing", history=history, final_query=safe_query)
        host._set_search_state_query(safe_query)
        return safe_query

    def _search_with_repairs(
        self,
        *,
        question: str,
        query: str,
        iteration: int,
        history: list[dict[str, Any]],
        verbose: bool,
    ) -> tuple[str, Any]:
        host = self.host
        server_error_variants = self.server_error_query_variants(query)
        provider_repair_attempts: set[tuple[Any, ...]] = set()
        preflight_repair_attempts = 0

        while True:
            validation = host._preflight_query(query)
            if not validation.ok:
                repaired_query = ""
                if preflight_repair_attempts < 2:
                    preflight_repair_attempts += 1
                    repaired_query = host._retry_malformed_source_query(
                        question,
                        query,
                        feedback="",
                        system_prompt=host._syntax_repair_prompt(),
                        log_name=f"{host.data_source}_query_preflight",
                        output_label=f"{host._source_label()} query string",
                        operation="preflight validation",
                        issue=validation.issue,
                    )
                if repaired_query and not self.queries_equivalent(query, repaired_query):
                    history.append(
                        {
                            "iteration": iteration,
                            "query": query,
                            "total": None,
                            "action": "repair",
                            "next_query": repaired_query,
                            "message": f"{host._source_label()} query failed harness preflight; repaired before calling the source API.",
                            "rationale": host._consume_query_audit(),
                        }
                    )
                    host._emit_stage("search", "processing", history=history, final_query=repaired_query)
                    host._emit_log(f"{host._source_label()} query repaired by harness preflight; retrying validation.")
                    query = repaired_query
                    host._set_search_state_query(query)
                    continue
                raise LLMError(f"{host._source_label()} query failed harness preflight: {validation.issue}")

            try:
                host._check_cancelled()
                host._emit_stage(
                    "search",
                    "processing",
                    iteration=iteration,
                    query=query,
                    history=history,
                    final_query=query,
                )
                host._emit_log(f"{host._source_label()} request started: {host._source_request_label(query)}")
                result, search_error = host._harness_source_search(query)
                host._check_cancelled()
                if search_error is not None:
                    raise search_error
                host._emit_log(host._source_response_log(result))
                return query, result
            except ProviderError as exc:
                repair_key = (query, exc.status, str(exc)[:200])
                repair_attempts = len(provider_repair_attempts)
                if repair_key in provider_repair_attempts:
                    repair_attempts = 2
                recovery = host._recover_source_error(
                    exc,
                    query=query,
                    repair_attempts=repair_attempts,
                    max_repair_attempts=2,
                )
                if recovery.action == RECOVERY_REPAIR_QUERY and repair_key not in provider_repair_attempts:
                    provider_repair_attempts.add(repair_key)
                    repaired_query = host._repair_query_after_provider_error(question, query, exc)
                    if repaired_query and not self.queries_equivalent(query, repaired_query):
                        history.append(
                            {
                                "iteration": iteration,
                                "query": query,
                                "total": None,
                                "action": "repair",
                                "next_query": repaired_query,
                                "message": f"{host._source_label()} rejected the query; repaired the source syntax and retried.",
                            }
                        )
                        host._emit_stage("search", "processing", history=history, final_query=repaired_query)
                        host._emit_log(f"{host._source_label()} query repaired after API error; retrying request.")
                        query = repaired_query
                        host._set_search_state_query(query)
                        continue
                raise
            except ApiException as exc:
                recovery = host._recover_source_error(
                    exc,
                    query=query,
                    repair_attempts=0,
                    max_repair_attempts=1,
                    has_server_error_variant=bool(server_error_variants),
                )
                if recovery.action == RECOVERY_SIMPLIFY_QUERY and server_error_variants:
                    repaired_query = server_error_variants.pop(0)
                    if repaired_query != query:
                        action = "repair" if "NEAR/" in repaired_query.upper() else "simplify"
                        history.append(
                            {
                                "iteration": iteration,
                                "query": query,
                                "total": None,
                                "action": action,
                                "next_query": repaired_query,
                                "message": "WoS returned HTTP 512; rewrote the query into a simpler supported form and retried.",
                            }
                        )
                        host._emit_stage("search", "processing", history=history, final_query=repaired_query)
                        query = repaired_query
                        host._set_search_state_query(query)
                        if verbose:
                            print(f"[Iteration {iteration}] Rewrote query after 512: {query}", file=sys.stderr)
                        continue
                raise

    def _recover_rejected_query(
        self,
        exc: ApiException,
        *,
        question: str,
        query: str,
        iteration: int,
        history: list[dict[str, Any]],
    ) -> QueryExecutionResult:
        host = self.host
        if exc.status != 400 or "query" not in str(exc.body).lower():
            exc.query = query
            exc.iteration = iteration
            raise exc

        recovery = host._recover_source_error(
            exc,
            query=query,
            repair_attempts=0,
            max_repair_attempts=1,
            allow_broaden_query=True,
        )
        if recovery.action != RECOVERY_BROADEN_QUERY:
            exc.query = query
            exc.iteration = iteration
            raise exc

        feedback = host._result_feedback(query, [], None, "syntax rejected")
        revised_query = host._apply_discipline_filter(host._broaden_query(question, query, feedback))
        query_audit = host._consume_query_audit()
        if self.queries_equivalent(query, revised_query):
            exc.query = query
            exc.iteration = iteration
            raise exc

        history.append(
            {
                "iteration": iteration,
                "query": query,
                "total": None,
                "action": "broaden",
                "next_query": revised_query,
                "message": "WoS rejected the query syntax; generated a broader replacement query.",
                "rationale": query_audit,
            }
        )
        host._emit_stage("search", "processing", history=history, final_query=revised_query)
        host._set_search_state_query(revised_query)
        return QueryExecutionResult(query=revised_query, retry_iteration=True)
