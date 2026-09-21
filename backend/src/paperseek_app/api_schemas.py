from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from paperseek_core.models import FinalPaperResult


class DiagnosticCheckOutput(BaseModel):
    id: str
    status: str
    severity: str
    summary: str
    actions: list[str]
    details: dict[str, object]
    ok: bool


class DiagnosticSummaryOutput(BaseModel):
    passed: int = Field(alias="pass", serialization_alias="pass")
    warning: int
    fail: int


class DiagnosticOutput(BaseModel):
    ok: bool
    status: str
    checks: list[DiagnosticCheckOutput]
    summary: DiagnosticSummaryOutput


class SourceFilterOptionOutput(BaseModel):
    id: str
    label: str
    domain: str


class SourceFilterOutput(BaseModel):
    mode: str
    label: str
    options: list[SourceFilterOptionOutput]


class SourceCapabilitiesOutput(BaseModel):
    citation_expansion: bool
    filter: SourceFilterOutput


class SourceCredentialOutput(BaseModel):
    input_label: str
    guidance_label: str
    guidance_url: str


class SourceDescriptorOutput(BaseModel):
    id: str
    label: str
    api_key: str
    status: str
    default: bool
    credential: SourceCredentialOutput | None
    capabilities: SourceCapabilitiesOutput


class SourceListOutput(BaseModel):
    sources: list[SourceDescriptorOutput]


class ResultOutput(FinalPaperResult):
    metadata_status: str = "not_requested"


class ResultPageOutput(BaseModel):
    results: list[ResultOutput] = Field(default_factory=list)
    next_cursor: str | None = None
    total_count: int = 0
    matched_count: int = 0
    scored_count: int = 0
    max_score: float | None = None


class CitationNodeOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str = ""
    rank: int | None = None
    year: int | None = None
    source: str = ""
    citations: int = 0
    roles: list[str] = Field(default_factory=list)
    score: float | None = None
    reasoning: str = ""
    seed_uids: list[str] = Field(default_factory=list)


class CitationEdgeOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str
    target: str
    type: str


class CitationMapOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = ""
    nodes: list[CitationNodeOutput] = Field(default_factory=list)
    edges: list[CitationEdgeOutput] = Field(default_factory=list)
