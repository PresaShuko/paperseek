"""Whole-workspace data actions behind Settings › User: a summary and clearing all history."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI

from paperseek_app.bibliometrics.services import AnalysisService
from paperseek_app.services.workspace_reset import HistoryClearResult, WorkspaceResetService, WorkspaceSummary
from paperseek_community.api_dependencies import drain_cleanup_jobs
from paperseek_community.api_routes.bibliometrics import cleanup_analyses
from paperseek_community.api_routes.reviews import open_reviews
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.persistence.sqlite_bibliometrics import SQLiteAnalysisStore


def register_workspace_data_routes(app: FastAPI, *, database: Path, credentials: EncryptedRunCredentialStore) -> None:
    @contextmanager
    def reset_service():
        analyses = SQLiteAnalysisStore(database)
        try:
            with open_reviews(database, credentials) as store:
                files = AnalysisService(analyses, FileArtifactStore(database.parent))
                yield WorkspaceResetService(store, store, analyses, files.delete)
        finally:
            analyses.close()

    folder = database.parent.resolve()
    try:
        location = "~/" + folder.relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        location = folder.as_posix()

    @app.get("/api/v1/data/summary", response_model=WorkspaceSummary)
    def summary() -> WorkspaceSummary:
        with reset_service() as service:
            return service.summary().model_copy(update={"location": location})

    @app.post("/api/v1/data/history/clear", response_model=HistoryClearResult)
    def clear_history(background_tasks: BackgroundTasks) -> HistoryClearResult:
        """Stops running tasks first ("stopping"); call again until it reports "cleared"."""
        with reset_service() as service:
            result = service.clear_history()
        if result.status == "cleared":
            background_tasks.add_task(drain_cleanup_jobs, database, max_jobs=10_000)
            background_tasks.add_task(cleanup_analyses, database)
        return result
