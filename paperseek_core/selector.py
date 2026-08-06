"""Backward-compatible imports for query-view selection."""

from paperseek_core.query_view_selector import (
    DIRECT_VIEW_OVERLAP_THRESHOLD,
    QueryViewSelection,
    select_query_views,
    selected_query_views,
)


__all__ = [
    "DIRECT_VIEW_OVERLAP_THRESHOLD",
    "QueryViewSelection",
    "select_query_views",
    "selected_query_views",
]
