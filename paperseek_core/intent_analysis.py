"""Structured search-intent analysis."""

from __future__ import annotations

from paperseek_core.planning import fallback_search_plan, parse_search_plan
from paperseek_core.prompts import SYSTEM_SEARCH_INTENT_ANALYSIS
from paperseek_core.query_compiler import supports_query_portfolio


class IntentAnalysisPipeline:
    def __init__(self, host) -> None:
        self._host = host

    def run(self, question: str) -> str:
        host = self._host
        messages = [
            {"role": "system", "content": SYSTEM_SEARCH_INTENT_ANALYSIS},
            {"role": "user", "content": f"Research question: {question}\n\nOutput ONLY the compact JSON intent object."},
        ]
        host._emit_log("Search intent analysis started.")
        host._llm_request_log("intent_analysis")
        try:
            chat_json = getattr(host.llm, "chat_json", None)
            raw = host._run_cancellable(
                lambda: (
                    chat_json(messages, temperature=0.0, max_tokens=4096)
                    if callable(chat_json)
                    else host.llm.chat(messages, temperature=0.0)
                )
            )
            host._llm_response_log("intent_analysis")
        except Exception as exc:
            host._emit_log(f"Search intent analysis skipped after LLM error: {exc}")
            host.search_plan = fallback_search_plan(question, f"LLM error: {exc.__class__.__name__}")
            return host.search_plan.audit_summary()
        host.search_plan = parse_search_plan(raw, question)
        response_info = getattr(host.llm, "last_response_info", {}) or {}
        host.search_plan_diagnostics.append(
            {
                "attempt": 1,
                "output_characters": len(raw or ""),
                "finish_reason": response_info.get("finish_reason"),
                "completion_tokens": response_info.get("completion_tokens"),
                "parsed": host.search_plan is not None,
                "coverage_gaps": host.search_plan.coverage_gaps() if host.search_plan is not None else ["invalid_search_plan_json"],
            }
        )
        portfolio_required = bool(getattr(host.config, "query_portfolio_enabled", False)) and supports_query_portfolio(
            host.data_source
        )
        plan_gaps = (
            host.search_plan.coverage_gaps()
            if host.search_plan is not None and portfolio_required
            else ([] if host.search_plan is not None else ["a valid SearchPlan JSON object"])
        )
        if plan_gaps:
            gaps = "; ".join(plan_gaps)
            host._emit_log(f"Search intent plan missed required structured coverage: {gaps}; requesting one corrected plan.")
            if host.search_plan is None:
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
            host._llm_request_log("intent_analysis_coverage_retry")
            try:
                retry_raw = host._run_cancellable(
                    lambda: (
                        chat_json(retry_messages, temperature=0.0, max_tokens=4096)
                        if callable(chat_json)
                        else host.llm.chat(retry_messages, temperature=0.0)
                    )
                )
                host._llm_response_log("intent_analysis_coverage_retry")
                retry_plan = parse_search_plan(retry_raw, question)
                response_info = getattr(host.llm, "last_response_info", {}) or {}
                host.search_plan_diagnostics.append(
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
                    host.search_plan = retry_plan
                elif host.search_plan is None and retry_plan is not None:
                    host.search_plan = retry_plan
                    host._emit_log("Search intent repair remained incomplete but produced a valid plan; continuing with its usable views.")
                else:
                    host._emit_log("Search intent repair remained incomplete; keeping the first valid plan when available.")
            except Exception as exc:
                host._emit_log(f"Search intent repair failed; keeping the first valid plan when available: {exc}")
        if host.search_plan is not None:
            host._emit_log("Search intent analysis completed.")
        else:
            host._emit_log(
                "Search intent analysis returned no usable structured plan after one repair; "
                "continuing with the deterministic fallback plan."
            )
            host.search_plan = fallback_search_plan(question, "invalid structured output")
        return host.search_plan.audit_summary()
