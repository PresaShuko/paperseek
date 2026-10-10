from datetime import datetime

from pydantic import Field

from paperseek_app.models import AppModel, StoredArtifact
from paperseek_core.bibliometrics.models import MetricOverview


class AnalysisError(Exception):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


class AnalysisCreate(AppModel):
    source_run_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=200)


class AnalysisRename(AppModel):
    title: str = Field(min_length=1, max_length=200, pattern=r"\S")


class AnalysisSummary(AppModel):
    id: str
    source_run_id: str
    title: str
    paper_count: int
    scope: str
    created_at: datetime


class AnalysisRecord(AnalysisSummary):
    source_reported_total: int | None = None
    retrieval_pool_limit: int | None = None
    scoring_limit: int | None = None
    warnings: list[str] = Field(default_factory=list)
    corpus: StoredArtifact
    overview: StoredArtifact
    networks: dict[str, StoredArtifact] = Field(default_factory=dict)
    request_digest: str


class AnalysisDetail(AnalysisSummary):
    statistics: MetricOverview
    source_reported_total: int | None = None
    retrieval_pool_limit: int | None = None
    scoring_limit: int | None = None
    warnings: list[str] = Field(default_factory=list)


class AnalysisPage(AppModel):
    items: list[AnalysisSummary]
    total_count: int
    next_offset: int | None = None
