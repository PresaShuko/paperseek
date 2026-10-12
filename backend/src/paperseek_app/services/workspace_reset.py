"""Clear a workspace's history: stop running tasks first, then delete every saved record."""
from __future__ import annotations

from typing import Callable, Literal, Protocol

from paperseek_app.bibliometrics.ports import AnalysisStore
from paperseek_app.errors import RunNotFound, RunStateError
from paperseek_app.models import AppModel, DeletionReceipt, RunDetail
from paperseek_app.review.ports import ReviewStore

PAGE = 100


class WorkspaceRuns(Protocol):
    def active_run_ids(self) -> list[str]: ...
    def history_run_ids(self) -> list[str]: ...
    def request_cancel(self, run_id: str) -> RunDetail: ...
    def stage_run_deletion(self, run_id: str) -> DeletionReceipt: ...


class WorkspaceSummary(AppModel):
    searches: int
    analyses: int
    reviews: int
    active: int
    # Where a local deployment keeps its data; empty for hosted accounts.
    location: str = ""


class HistoryClearResult(AppModel):
    # "stopping": cancellation was requested and nothing was deleted yet; call again once tasks stop.
    status: Literal["stopping", "cleared"]
    active: int = 0
    searches: int = 0
    analyses: int = 0
    reviews: int = 0


class WorkspaceResetService:
    def __init__(self, runs: WorkspaceRuns, reviews: ReviewStore, analyses: AnalysisStore,
                 delete_analysis: Callable[[str], None]) -> None:
        self.runs, self.reviews, self.analyses = runs, reviews, analyses
        # Analysis deletion also removes its files, so the owning service performs it.
        self.delete_analysis = delete_analysis

    def summary(self) -> WorkspaceSummary:
        return WorkspaceSummary(
            searches=len(self.runs.history_run_ids()),
            analyses=self.analyses.list_analyses("", 0, 1).total_count,
            reviews=self.reviews.list_reviews(0, 1).total_count,
            active=len(self.runs.active_run_ids()),
        )

    def clear_history(self) -> HistoryClearResult:
        active = self.runs.active_run_ids()
        if active:
            for run_id in active:
                try:
                    self.runs.request_cancel(run_id)
                except (RunNotFound, RunStateError):
                    pass  # It finished or vanished meanwhile; the next call sees the new state.
            return HistoryClearResult(status="stopping", active=len(active))
        # Reviews and analyses refer to searches, so they go first.
        reviews = 0
        while page := self.reviews.list_reviews(0, PAGE).items:
            for item in page:
                self.reviews.delete_review(item.id, self.reviews.get_review(item.id).version)
                reviews += 1
        analyses = 0
        while page := self.analyses.list_analyses("", 0, PAGE).items:
            for item in page:
                self.delete_analysis(item.id)
                analyses += 1
        searches = 0
        for run_id in self.runs.history_run_ids():
            self.runs.stage_run_deletion(run_id)
            searches += 1
        return HistoryClearResult(status="cleared", searches=searches, analyses=analyses, reviews=reviews)
