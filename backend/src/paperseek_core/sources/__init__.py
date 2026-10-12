"""Source adapter contracts owned by the research core."""

from paperseek_core.sources.contracts import (
    SourceCapabilities,
    SourceError,
    SourceFailureKind,
    SourceSearchMetadata,
    SourceSearchRequest,
    SourceSearchResult,
)
from paperseek_core.sources.http import AsyncHttpTransport

__all__ = [
    "SourceCapabilities",
    "SourceError",
    "SourceFailureKind",
    "SourceSearchMetadata",
    "SourceSearchRequest",
    "SourceSearchResult",
    "AsyncHttpTransport",
]
