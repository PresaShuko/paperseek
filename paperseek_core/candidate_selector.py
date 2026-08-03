import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Iterable

from paperseek_core.harness.query_contract import extract_json_object_text
from paperseek_core.harness.schemas import SelectorBatch, SelectorDecision
from paperseek_core.llm import LLMClient
from paperseek_core.planning import SearchPlan
from paperseek_core.retrieval import document_key


SYSTEM_CANDIDATE_SELECTION = """You are the paper-level Candidate Selector in a literature-search system.
Judge every candidate against the stable SearchPlan, not against the wording of the latest database query. Treat must_have_facets and required_relation as the relevance invariants; optional_facets can strengthen a match but their absence is not a reason to exclude.

Use these labels:
- include: the available title/abstract/metadata provides positive evidence that the paper satisfies the research intent.
- exclude: the available evidence clearly contradicts a required concept, object, relation, method, or explicit boundary.
- uncertain: evidence is incomplete, mixed, or only indirectly related. Missing abstracts must not be excluded solely for being missing.

Optimize for high recall. The absence of a named term or explicit relationship is incomplete evidence, not a contradiction: label it uncertain. Exclude only when candidate text positively establishes an explicit mismatch or boundary violation, and cite that mismatch in evidence. Do not invent facts.
For each candidate, estimate coverage of the SearchPlan must-have facets and core concepts from 0.0 to 1.0, list missing required concepts or relations, and recommend only useful next actions from: read, enrich, expand_backward, expand_forward, none.

Use one or more of these reason codes:
- include/uncertain: direct_match, partial_match, indirect_relation, missing_evidence, missing_abstract, ambiguous_relation.
- exclude only: explicit_scope_mismatch, explicit_boundary_violation, explicit_object_mismatch, explicit_relation_mismatch, explicit_method_mismatch, explicit_time_mismatch, explicit_document_type_mismatch.

Return one JSON object with exactly this top-level shape:
{"decisions":[{"candidate_id":"exact supplied id","label":"include|exclude|uncertain","relevance_score":0.0,"concept_coverage":{"concept":0.0},"missing_concepts":[],"evidence":[],"recommended_actions":["none"],"reason_codes":[]}]}
Return one decision for every supplied candidate ID and no other IDs. Output JSON only."""


SYSTEM_CANDIDATE_SELECTION_RETRY = """The previous Candidate Selector response was incomplete or invalid.
Return a complete replacement JSON object for only the candidates supplied below. Copy every candidate_id exactly. Use the required decisions array and no prose or markdown."""

_ALLOWED_ACTIONS = {"read", "enrich", "expand_backward", "expand_forward", "none"}
_EXPLICIT_EXCLUSION_REASONS = {
    "explicit_scope_mismatch",
    "explicit_boundary_violation",
    "explicit_object_mismatch",
    "explicit_relation_mismatch",
    "explicit_method_mismatch",
    "explicit_time_mismatch",
    "explicit_document_type_mismatch",
}
_ABSENCE_ONLY_EVIDENCE = re.compile(
    r"(?:\b(?:does\s+not|doesn't|did\s+not|not)\s+(?:explicitly\s+)?"
    r"(?:mention|name|state|identify|cite|reference)\b|\bno\s+(?:explicit\s+)?"
    r"(?:mention|reference|citation)\b|未(?:明确)?提及|没有(?:明确)?提及|未(?:明确)?说明)",
    flags=re.IGNORECASE,
)
CANDIDATE_SELECTOR_PROMPT_VERSION = "3"


class CandidateSelector:
    """Independent, recall-preserving paper relevance selector.

    The selector owns its prompt, schema validation, call budget, cache, and
    failure policy. A failed or incomplete batch degrades to ``uncertain`` so
    retrieval evidence is never discarded because an LLM endpoint failed.
    """

    def __init__(
        self,
        llm: LLMClient,
        *,
        batch_size: int = 12,
        concurrency: int = 2,
        max_llm_calls: int = 24,
        max_attempts: int = 2,
        exclude_score_max: float = 0.25,
        cache: dict[str, SelectorDecision] | None = None,
    ):
        self.llm = llm
        self.batch_size = max(1, int(batch_size or 1))
        self.concurrency = max(1, int(concurrency or 1))
        self.max_llm_calls = max(0, int(max_llm_calls or 0))
        self.max_attempts = max(1, int(max_attempts or 1))
        self.exclude_score_max = min(1.0, max(0.0, float(exclude_score_max)))
        self.cache = cache if cache is not None else {}
        self.llm_calls = 0
        self._call_lock = Lock()

    def select(
        self,
        question: str,
        plan: SearchPlan,
        candidates: Iterable[Any],
    ) -> SelectorBatch:
        documents = self._unique_candidates(candidates)
        decisions: dict[str, SelectorDecision] = {}
        cache_hits = 0
        fallback_count = 0
        errors: list[str] = []
        with self._call_lock:
            calls_before = self.llm_calls
        pending: list[Any] = []

        for document in documents:
            candidate_id = document_key(document)
            cache_key = self.cache_key(question, plan, document)
            cached = self.cache.get(cache_key)
            if cached is not None:
                decisions[candidate_id] = cached
                cache_hits += 1
            else:
                pending.append(document)

        batches = list(_chunks(pending, self.batch_size))
        if len(batches) > 1 and self.concurrency > 1:
            with ThreadPoolExecutor(max_workers=min(self.concurrency, len(batches))) as executor:
                batch_results = list(
                    executor.map(
                        lambda batch: self._select_batch(question, plan, batch),
                        batches,
                    )
                )
        else:
            batch_results = [self._select_batch(question, plan, batch) for batch in batches]

        for batch, (selected, batch_errors) in zip(batches, batch_results):
            errors.extend(batch_errors)
            for document in batch:
                candidate_id = document_key(document)
                decision = selected.get(candidate_id)
                if decision is None:
                    decision = self._fallback_decision(document, "selector_missing_or_failed")
                    fallback_count += 1
                decision = self._apply_recall_guards(document, decision)
                decisions[candidate_id] = decision
                self.cache[self.cache_key(question, plan, document)] = decision

        ordered = [decisions[document_key(document)] for document in documents]
        with self._call_lock:
            calls_used = self.llm_calls - calls_before
        return SelectorBatch(
            decisions=ordered,
            llm_calls=calls_used,
            cache_hits=cache_hits,
            fallback_count=fallback_count,
            errors=errors,
        )

    def _select_batch(
        self,
        question: str,
        plan: SearchPlan,
        documents: list[Any],
    ) -> tuple[dict[str, SelectorDecision], list[str]]:
        expected = {document_key(document): document for document in documents}
        resolved: dict[str, SelectorDecision] = {}
        errors: list[str] = []

        for attempt in range(self.max_attempts):
            missing_ids = [candidate_id for candidate_id in expected if candidate_id not in resolved]
            if not missing_ids:
                break
            if not self._reserve_llm_call():
                errors.append("selector_llm_budget_exhausted")
                break

            remaining = [expected[candidate_id] for candidate_id in missing_ids]
            messages = self._messages(question, plan, remaining, retry=attempt > 0)
            try:
                raw = self.llm.chat_json(messages, temperature=0.0, max_tokens=4096)
                parsed = self._parse_response(raw, set(missing_ids))
            except Exception as exc:
                errors.append(f"{exc.__class__.__name__}: {exc}")
                continue

            if not parsed:
                errors.append("selector_response_contained_no_valid_decisions")
                continue
            resolved.update(parsed)
            if len(parsed) < len(missing_ids):
                errors.append(
                    f"selector_response_incomplete:{len(parsed)}/{len(missing_ids)}"
                )

        return resolved, errors

    def _reserve_llm_call(self) -> bool:
        with self._call_lock:
            if self.llm_calls >= self.max_llm_calls:
                return False
            self.llm_calls += 1
            return True

    @staticmethod
    def _messages(
        question: str,
        plan: SearchPlan,
        documents: list[Any],
        *,
        retry: bool,
    ) -> list[dict[str, str]]:
        plan_payload = {
            "intent": plan.intent,
            "question_type": plan.question_type,
            "core_concepts": plan.core_concepts,
            "must_have_facets": plan.must_have_facets,
            "optional_facets": plan.optional_facets,
            "required_relation": plan.required_relation,
            "likely_synonyms": plan.likely_synonyms,
            "adjacent_concepts": plan.adjacent_concepts,
            "boundaries": plan.boundaries,
            "ambiguities": plan.ambiguities,
        }
        candidates = [_candidate_payload(document) for document in documents]
        user_payload = {
            "research_question": question,
            "search_plan": plan_payload,
            "candidates": candidates,
        }
        systems = [SYSTEM_CANDIDATE_SELECTION]
        if retry:
            systems.append(SYSTEM_CANDIDATE_SELECTION_RETRY)
        return [
            {"role": "system", "content": "\n\n".join(systems)},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]

    @staticmethod
    def _parse_response(raw: str, expected_ids: set[str]) -> dict[str, SelectorDecision]:
        object_text = extract_json_object_text(str(raw or ""))
        if not object_text:
            return {}
        try:
            payload = json.loads(object_text)
        except json.JSONDecodeError:
            return {}
        values = payload.get("decisions") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            return {}

        output: dict[str, SelectorDecision] = {}
        for value in values:
            try:
                decision = SelectorDecision.model_validate(value)
            except (TypeError, ValueError):
                continue
            if decision.candidate_id not in expected_ids or decision.candidate_id in output:
                continue
            output[decision.candidate_id] = decision
        return output

    def _apply_recall_guards(self, document: Any, decision: SelectorDecision) -> SelectorDecision:
        abstract = str(getattr(document, "abstract", "") or "").strip()
        reasons = _unique_strings(decision.reason_codes)
        actions = [action for action in _unique_strings(decision.recommended_actions) if action in _ALLOWED_ACTIONS]
        evidence = _unique_strings(decision.evidence)
        missing = _unique_strings(decision.missing_concepts)
        label = decision.label

        if label == "exclude" and not abstract:
            label = "uncertain"
            reasons.append("missing_abstract_guard")
            if "enrich" not in actions:
                actions.insert(0, "enrich")
        elif (
            label == "exclude"
            and "explicit_boundary_violation" not in reasons
            and any(_ABSENCE_ONLY_EVIDENCE.search(item) for item in evidence)
        ):
            label = "uncertain"
            reasons.append("absence_is_not_contradiction_guard")
        elif label == "exclude" and (decision.relevance_score > self.exclude_score_max or not evidence):
            label = "uncertain"
            reasons.append("weak_exclusion_evidence_guard")
        elif label == "exclude" and not _EXPLICIT_EXCLUSION_REASONS.intersection(reasons):
            label = "uncertain"
            reasons.append("unsupported_exclusion_guard")

        if not actions:
            actions = ["none"]
        return decision.model_copy(
            update={
                "label": label,
                "missing_concepts": missing,
                "evidence": evidence,
                "recommended_actions": actions,
                "reason_codes": _unique_strings(reasons),
            }
        )

    @staticmethod
    def _fallback_decision(document: Any, reason: str) -> SelectorDecision:
        actions = ["enrich"] if not str(getattr(document, "abstract", "") or "").strip() else ["none"]
        return SelectorDecision(
            candidate_id=document_key(document),
            label="uncertain",
            relevance_score=0.5,
            recommended_actions=actions,
            reason_codes=[reason],
        )

    @staticmethod
    def cache_key(question: str, plan: SearchPlan, document: Any) -> str:
        payload = {
            "prompt_version": CANDIDATE_SELECTOR_PROMPT_VERSION,
            "question": str(question or "").strip(),
            "plan": plan.model_dump(mode="json"),
            "candidate": _candidate_payload(document),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _unique_candidates(candidates: Iterable[Any]) -> list[Any]:
        output: list[Any] = []
        seen: set[str] = set()
        for document in candidates or []:
            key = document_key(document)
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(document)
        return output


def _candidate_payload(document: Any) -> dict[str, Any]:
    source = getattr(document, "source", None)
    source_title = str(getattr(source, "source_title", "") or "") if source else ""
    publish_year = getattr(source, "publish_year", None) if source else None
    keywords = getattr(getattr(document, "keywords", None), "author_keywords", None) or []
    return {
        "candidate_id": document_key(document),
        "title": _clean_text(getattr(document, "title", ""), 500),
        "abstract": _clean_text(getattr(document, "abstract", ""), 2400),
        "venue": _clean_text(source_title, 300),
        "year": publish_year,
        "document_types": [str(value) for value in (getattr(document, "types", None) or [])[:5]],
        "keywords": [str(value) for value in keywords[:10]],
    }


def _clean_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _unique_strings(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        cleaned = _clean_text(value, 500)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def _chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


__all__ = [
    "CandidateSelector",
    "CANDIDATE_SELECTOR_PROMPT_VERSION",
    "SYSTEM_CANDIDATE_SELECTION",
    "SYSTEM_CANDIDATE_SELECTION_RETRY",
]
