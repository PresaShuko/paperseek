from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from paperseek_core.models import CoreModel, PaperRecord


class SourceSearchRequest(CoreModel):
    query: str
    limit: int = 50
    page: int = 1
    lane: str = "relevance"
    field_ids: tuple[str, ...] = ()


class SourceSearchMetadata(CoreModel):
    total: int = 0
    page: int = 1
    limit: int = 10


class SourceSearchResult(CoreModel):
    metadata: SourceSearchMetadata
    hits: list[PaperRecord] = Field(default_factory=list)


class SourceCapabilities(CoreModel):
    source: str
    lanes: tuple[str, ...] = ("relevance",)
    metadata_fields: tuple[str, ...] = ()
    supports_abstracts: bool = False
    supports_citations: bool = False
    supports_citation_expansion: bool = False
    supports_pdf_links: bool = False
    supports_hard_field_filter: bool = False
    api_key: Literal["required", "optional", "recommended", "not_required"] = "not_required"
    max_page_size: int = 1000
    max_lane_limit: int = 1000
    page_size_by_lane: dict[str, int] = Field(default_factory=dict)
    single_page_lanes: tuple[str, ...] = ()
    lane_concurrency: int = 1
    backoff_policy: str = ""

    def supports(self, lane: str) -> bool:
        return lane in self.lanes

    def page_size(self, lane: str) -> int:
        return max(1, int(self.page_size_by_lane.get(lane, self.max_page_size) or 1))

    def is_single_page(self, lane: str) -> bool:
        return lane in self.single_page_lanes


class SourceFailureKind(str, Enum):
    CONNECT_TIMEOUT = "connect_timeout"
    SEND_TIMEOUT = "send_timeout"
    FIRST_BYTE_TIMEOUT = "first_byte_timeout"
    READ_IDLE_TIMEOUT = "read_idle_timeout"
    STEP_DEADLINE = "step_deadline"
    CONNECT_ERROR = "connect_error"
    TRANSPORT_ERROR = "transport_error"


class SourceError(Exception):
    def __init__(
        self,
        source: str,
        message: str,
        status: int | None = None,
        body: str = "",
        query: str = "",
        failure_kind: SourceFailureKind | None = None,
    ) -> None:
        super().__init__(message)
        self.source = source
        self.status = status
        self.body = body
        self.query = query
        self.failure_kind = failure_kind
