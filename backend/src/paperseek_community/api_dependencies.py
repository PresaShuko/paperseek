from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from paperseek_app.models import RunStatus
from paperseek_app.services import (
    RunCleanupService,
    RunQueryService,
    RunSubmissionService,
)
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.persistence import SQLiteRunUnitOfWork


TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_WITH_WARNINGS,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def error_payload(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": str(uuid4()),
            "details": details or {},
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload("invalid_request", "The request is invalid."),
        )


def open_submission_service(database: Path) -> tuple[RunSubmissionService, SQLiteRunUnitOfWork]:
    uow = SQLiteRunUnitOfWork(database)
    return RunSubmissionService(uow), uow


def open_query_service(database: Path) -> tuple[RunQueryService, SQLiteRunUnitOfWork]:
    uow = SQLiteRunUnitOfWork(database)
    return RunQueryService(uow, FileArtifactStore(database.parent)), uow


def open_cleanup_service(database: Path) -> tuple[RunCleanupService, SQLiteRunUnitOfWork]:
    uow = SQLiteRunUnitOfWork(database)
    return RunCleanupService(uow, FileArtifactStore(database.parent)), uow


def drain_cleanup_jobs(database: Path, *, max_jobs: int = 100) -> None:
    uow = SQLiteRunUnitOfWork(database)
    try:
        service = RunCleanupService(uow, FileArtifactStore(database.parent))
        owner_id = f"community-cleanup-{uuid4()}"
        for _ in range(max_jobs):
            if not service.cleanup_next_deleted_run(owner_id):
                break
    finally:
        uow.close()


def content_response(content, *, disposition: bool = False) -> Response:
    headers = {
        "ETag": f'"{content.sha256}"',
        "X-Content-SHA256": content.sha256,
    }
    if disposition:
        headers["Content-Disposition"] = f'attachment; filename="{content.filename}"'
    return Response(content=content.content, media_type=content.media_type, headers=headers)
