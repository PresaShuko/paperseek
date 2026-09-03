from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from paperseek_community.api_dependencies import open_query_service
from paperseek_community.api_schemas import DiagnosticOutput, SourceListOutput
from paperseek_community.diagnostics import run_configuration_diagnostics
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_community.submission import DiagnosticSubmission
from paperseek_community.source_capabilities import list_community_source_descriptors


def register_system_routes(
    app: FastAPI,
    *,
    database: Path,
    settings: CommunityDeploymentSettings,
) -> None:
    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": "0.3.0"}

    @app.get("/ready")
    def ready() -> dict:
        run_service, uow = open_query_service(database)
        try:
            run_service.get_history_page(page_size=1)
            return {"status": "ready"}
        finally:
            uow.close()

    @app.get("/api/v1/sources", response_model=SourceListOutput)
    def get_sources() -> SourceListOutput:
        return {"sources": list_community_source_descriptors()}

    @app.post("/api/v1/diagnostics", response_model=DiagnosticOutput)
    def diagnostics(submission: DiagnosticSubmission) -> dict[str, object]:
        return run_configuration_diagnostics(submission.model_dump(mode="json"), settings)
