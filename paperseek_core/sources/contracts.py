from dataclasses import dataclass
from typing import List, Optional, Tuple

from paperseek_core.domain.models import PaperRecord


@dataclass
class CitationSeedPlan:
    record: PaperRecord
    role: str = "relevance"
    directions: Tuple[str, ...] = ("backward", "forward")
    depth: int = 1


@dataclass
class SearchMetadata:
    total: int = 0
    page: int = 1
    limit: int = 10


@dataclass
class ProviderSearchResult:
    metadata: SearchMetadata
    hits: List[PaperRecord]


class ProviderError(Exception):
    def __init__(
        self,
        source: str,
        message: str,
        status: Optional[int] = None,
        body: str = "",
        query: str = "",
    ):
        super().__init__(message)
        self.source = source
        self.status = status
        self.body = body
        self.query = query
