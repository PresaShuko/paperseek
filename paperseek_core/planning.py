import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paperseek_core.harness.query_contract import extract_json_object_text


QuestionType = Literal[
    "broad_landscape",
    "specific_relation",
    "method_application",
    "mechanism",
    "comparison",
    "seminal_work",
    "recent_progress",
    "systematic_search",
]
FieldHint = Literal["all", "title", "abstract"]
ViewType = Literal[
    "direct_terminology",
    "successor_paradigm",
    "mechanism_method",
    "application_benchmark",
    "evidence_synthesis",
    "relation_variant",
    "domain_variant",
    "other",
]


def _clean_list(values) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;")
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


class ConceptGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = ""
    terms: list[str] = Field(default_factory=list)
    required: bool = True
    field_hint: FieldHint = "all"

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @field_validator("terms", mode="before")
    @classmethod
    def clean_terms(cls, value) -> list[str]:
        if isinstance(value, str):
            value = [value]
        return _clean_list(value)

    @model_validator(mode="after")
    def require_terms(self):
        if not self.terms and self.label:
            self.terms = [self.label]
        if not self.terms:
            raise ValueError("concept group must contain at least one term")
        if not self.label:
            self.label = self.terms[0]
        return self


class QueryView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    view_id: str = Field(min_length=1)
    view_type: ViewType = "other"
    purpose: str = ""
    concept_groups: list[ConceptGroup] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)

    @field_validator("view_id")
    @classmethod
    def clean_view_id(cls, value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9_-]+", "_", str(value or "").strip().lower()).strip("_")
        return cleaned or "query_view"

    @field_validator("purpose")
    @classmethod
    def clean_purpose(cls, value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @field_validator("exclusions", mode="before")
    @classmethod
    def clean_exclusions(cls, value) -> list[str]:
        if isinstance(value, str):
            value = [value]
        return _clean_list(value)

    @model_validator(mode="after")
    def require_groups(self):
        if not self.concept_groups:
            raise ValueError("query view must contain at least one concept group")
        if self.view_type == "other":
            haystack = " ".join(
                [
                    self.view_id,
                    self.purpose,
                    *[group.label for group in self.concept_groups],
                    *[term for group in self.concept_groups for term in group.terms],
                ]
            ).casefold()
            if any(marker in haystack for marker in ("successor", "terminology evolution", "cross-modal", "cross modal", "image-text", "vision-language", "modern paradigm")):
                self.view_type = "successor_paradigm"
            elif any(marker in haystack for marker in ("direct", "terminology", "lexical", "field name")):
                self.view_type = "direct_terminology"
            elif any(marker in haystack for marker in ("survey", "review", "overview", "synthesis")):
                self.view_type = "evidence_synthesis"
            elif any(marker in haystack for marker in ("application", "benchmark", "dataset", "use case")):
                self.view_type = "application_benchmark"
            elif any(marker in haystack for marker in ("method", "mechanism", "feature", "technique", "model")):
                self.view_type = "mechanism_method"
        return self


class SearchPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: str = Field(min_length=1)
    question_type: QuestionType = "specific_relation"
    core_concepts: list[str] = Field(default_factory=list)
    must_have_facets: list[str] = Field(default_factory=list)
    optional_facets: list[str] = Field(default_factory=list)
    required_relation: str = ""
    likely_synonyms: list[str] = Field(default_factory=list)
    adjacent_concepts: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    adjustment_strategy: str = ""
    ambiguities: list[str] = Field(default_factory=list)
    query_views: list[QueryView] = Field(default_factory=list)

    @field_validator("intent", "required_relation", "adjustment_strategy")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @field_validator(
        "core_concepts",
        "must_have_facets",
        "optional_facets",
        "likely_synonyms",
        "adjacent_concepts",
        "boundaries",
        "ambiguities",
        mode="before",
    )
    @classmethod
    def clean_terms(cls, value) -> list[str]:
        if isinstance(value, str):
            value = [value]
        return _clean_list(value)

    @model_validator(mode="after")
    def normalize_views(self):
        if not self.core_concepts:
            self.core_concepts = [self.intent]
        if not self.must_have_facets:
            self.must_have_facets = list(self.core_concepts)
        required_keys = {value.casefold() for value in self.must_have_facets}
        self.optional_facets = [
            value for value in self.optional_facets if value.casefold() not in required_keys
        ]
        seen: set[str] = set()
        unique: list[QueryView] = []
        for view in self.query_views:
            if view.view_id in seen:
                continue
            seen.add(view.view_id)
            if self.question_type == "broad_landscape":
                view = view.model_copy(
                    update={
                        "concept_groups": [
                            group.model_copy(update={"field_hint": "all"})
                            for group in view.concept_groups
                        ]
                    }
                )
            unique.append(view)
        self.query_views = unique[:6]
        return self

    def audit_summary(self) -> str:
        parts = [f"intent: {self.intent}", f"question_type: {self.question_type}"]
        for label, values in (
            ("core_concepts", self.core_concepts),
            ("must_have_facets", self.must_have_facets),
            ("optional_facets", self.optional_facets),
            ("likely_synonyms", self.likely_synonyms),
            ("adjacent_concepts", self.adjacent_concepts),
            ("boundaries", self.boundaries),
            ("ambiguities", self.ambiguities),
        ):
            if values:
                parts.append(f"{label}: {'; '.join(values)}")
        if self.required_relation:
            parts.append(f"required_relation: {self.required_relation}")
        if self.adjustment_strategy:
            parts.append(f"adjustment_strategy: {self.adjustment_strategy}")
        if self.query_views:
            parts.append("query_views: " + "; ".join(f"{view.view_id} [{view.view_type}] ({view.purpose})" for view in self.query_views))
        return "\n".join(parts)

    def coverage_gaps(self) -> list[str]:
        gaps = []
        if len(self.query_views) < 3:
            gaps.append(
                "at least three valid complementary query views; the current plan would silently fall back to a single-query search"
            )
        if self.question_type != "broad_landscape":
            return gaps
        view_types = {view.view_type for view in self.query_views}
        if "successor_paradigm" not in view_types:
            gaps.append(
                "a successor_paradigm query view covering established newer terminology or methods that solve the task without repeating the exact field name"
            )
        return gaps


def parse_search_plan(text: str, question: str) -> SearchPlan | None:
    object_text = extract_json_object_text(text)
    if not object_text:
        return None
    try:
        payload = json.loads(object_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    normalized = dict(payload)
    normalized["intent"] = str(normalized.get("intent") or question or "Literature search").strip()
    normalized["question_type"] = _normalize_question_type(normalized.get("question_type"), question)
    normalized["query_views"] = _normalize_query_views(normalized.get("query_views"))
    for view in normalized["query_views"]:
        exclusions = view.get("exclusions")
        if isinstance(exclusions, str):
            exclusions = [exclusions]
        view["exclusions"] = [
            str(value)
            for value in (exclusions or [])
            if _is_explicit_user_exclusion(question, str(value))
        ]
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


def _normalize_question_type(value, question: str) -> QuestionType:
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
        return normalized  # type: ignore[return-value]
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


def _normalize_query_views(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    output = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        normalized["view_id"] = normalized.get("view_id") or normalized.get("id") or normalized.get("name") or f"view_{index + 1}"
        normalized["concept_groups"] = normalized.get("concept_groups") or normalized.get("groups") or []
        output.append(normalized)
    return output


def _is_explicit_user_exclusion(question: str, exclusion: str) -> bool:
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
