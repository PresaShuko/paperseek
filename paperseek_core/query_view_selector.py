import re

from pydantic import BaseModel, ConfigDict, Field

from paperseek_core.planning import QueryView, SearchPlan
from paperseek_core.query_compiler import compile_query_view


DIRECT_VIEW_OVERLAP_THRESHOLD = 0.30
PAIRWISE_VIEW_OVERLAP_THRESHOLD = 0.90

_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "in",
    "not",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


class QueryViewSelection(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str = ""
    view: QueryView
    original_index: int
    score: float
    lexical_overlap: float = 0.0
    max_pairwise_overlap: float = 0.0
    selected: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    compiled_query: str = ""
    compile_error: str = ""

    def audit_payload(self) -> dict:
        return {
            "source": self.source,
            "view_id": self.view.view_id,
            "view_type": self.view.view_type,
            "selected": self.selected,
            "score": round(self.score, 6),
            "lexical_overlap": round(self.lexical_overlap, 6),
            "max_pairwise_overlap": round(self.max_pairwise_overlap, 6),
            "reason_codes": list(self.reason_codes),
            "compile_error": self.compile_error,
        }


def select_query_views(
    plan: SearchPlan,
    source: str,
    primary_query: str,
    budget: int,
) -> list[QueryViewSelection]:
    """Rank complementary query views without using benchmark labels."""

    budget = max(0, int(budget or 0))
    primary_normalized = _normalize_query(primary_query)
    primary_terms = _query_terms(primary_query)
    selections: list[QueryViewSelection] = []

    for index, view in enumerate(plan.query_views):
        score = 1.0 - (index * 0.01)
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

        selections.append(
            QueryViewSelection(
                source=str(source or "").strip().lower(),
                view=view,
                original_index=index,
                score=score,
                lexical_overlap=overlap,
                reason_codes=reasons,
                compiled_query=compiled_query,
                compile_error=compile_error,
            )
        )

    eligible = [
        item
        for item in selections
        if not item.compile_error and "exact_primary_duplicate" not in item.reason_codes
    ]
    selected_indexes: set[int] = set()
    selected_terms: list[set[str]] = []
    selected_normalized: set[str] = set()
    for item in sorted(eligible, key=lambda candidate: (-candidate.score, candidate.original_index)):
        if len(selected_indexes) >= budget:
            break
        normalized = _normalize_query(item.compiled_query)
        terms = _query_terms(item.compiled_query)
        pairwise_overlap = max(
            (_jaccard(terms, existing_terms) for existing_terms in selected_terms),
            default=0.0,
        )
        reasons = list(item.reason_codes)
        if normalized in selected_normalized:
            reasons.append("exact_selected_view_duplicate")
        elif pairwise_overlap >= PAIRWISE_VIEW_OVERLAP_THRESHOLD:
            reasons.append("near_selected_view_duplicate")
        else:
            selected_indexes.add(item.original_index)
            selected_normalized.add(normalized)
            selected_terms.append(terms)
        selections[item.original_index] = item.model_copy(
            update={
                "max_pairwise_overlap": pairwise_overlap,
                "reason_codes": reasons,
            }
        )
    return [
        item.model_copy(update={"selected": item.original_index in selected_indexes})
        for item in selections
    ]


def selected_query_views(selections: list[QueryViewSelection]) -> list[QueryViewSelection]:
    return sorted(
        (item for item in selections if item.selected),
        key=lambda item: (-item.score, item.original_index),
    )


def _normalize_query(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _query_terms(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(token) > 1 and token not in _QUERY_STOPWORDS
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
