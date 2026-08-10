from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from paperseek_app.errors import (
    ActiveRunExists,
    ArtifactNotFound,
    IdempotencyConflict,
    InvalidCursor,
    RunNotFound,
    RunStateError,
)
from paperseek_app.models import RunStatus
from paperseek_app.execution import WorkflowExecution
from paperseek_app.services import RunService
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_community.worker import EmbeddedRunExecutor
from paperseek_core.ports import CancellationToken


TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_WITH_WARNINGS,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}

SOURCES = (
    ("openalex", "OpenAlex", "recommended"),
    ("arxiv", "arXiv", "not_required"),
    ("crossref", "Crossref", "not_required"),
    ("semanticscholar", "Semantic Scholar", "optional"),
    ("pubmed", "PubMed", "optional"),
    ("wos", "Web of Science", "required"),
    ("googlescholar", "Google Scholar", "required"),
    ("paperhub", "PaperHub", "not_required"),
)


class LLMRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = ""
    api_type: str = ""
    base_url: str = ""
    model: str = ""


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""


class RunCredentialsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: CredentialInput = Field(default_factory=CredentialInput)
    source: CredentialInput = Field(default_factory=CredentialInput)


class RunSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=10_000)
    source: str
    search_budget: str = "medium"
    field: str = ""
    citation_enabled: bool = True
    llm: LLMRouteInput = Field(default_factory=LLMRouteInput)
    credentials: RunCredentialsInput = Field(default_factory=RunCredentialsInput)


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and scope["method"] in {"GET", "HEAD"}:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and scope["method"] in {"GET", "HEAD"}:
            return await super().get_response("index.html", scope)
        return response


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


def _error_payload(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": str(uuid4()),
            "details": details or {},
        }
    }


def _drain_cleanup_jobs(database: Path, *, max_jobs: int = 100) -> None:
    uow = SQLiteRunUnitOfWork(database)
    try:
        service = RunService(uow, FileArtifactStore(database.parent))
        owner_id = f"community-cleanup-{uuid4()}"
        for _ in range(max_jobs):
            if not service.cleanup_next_deleted_run(owner_id):
                break
    finally:
        uow.close()


def _content_response(content, *, disposition: bool = False) -> Response:
    headers = {
        "ETag": f'"{content.sha256}"',
        "X-Content-SHA256": content.sha256,
    }
    if disposition:
        headers["Content-Disposition"] = f'attachment; filename="{content.filename}"'
    return Response(content=content.content, media_type=content.media_type, headers=headers)


def create_app(
    database_path: Path | str,
    *,
    execution_resolver: Callable[[object, CancellationToken], WorkflowExecution] | None = None,
    static_dir: Path | str | None = None,
    deployment_settings: CommunityDeploymentSettings | None = None,
    credential_store: EncryptedRunCredentialStore | None = None,
) -> FastAPI:
    database = Path(database_path).expanduser().resolve()
    migrate_database(database)
    settings = deployment_settings or CommunityDeploymentSettings.from_environment()
    credentials = credential_store or EncryptedRunCredentialStore(database)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _drain_cleanup_jobs(database)
        worker_uow = None
        worker_task = None
        stop = asyncio.Event()
        if execution_resolver is not None:
            worker_uow = SQLiteRunUnitOfWork(database)
            executor = EmbeddedRunExecutor(
                RunService(worker_uow, FileArtifactStore(database.parent)),
                execution_resolver,
                owner_id=f"community-embedded-{uuid4()}",
            )

            async def work() -> None:
                while not stop.is_set():
                    detail = await executor.run_once()
                    if detail is not None and detail.status in TERMINAL_STATUSES:
                        credentials.delete(detail.id)
                    if detail is None:
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=0.05)
                        except TimeoutError:
                            pass

            worker_task = asyncio.create_task(work())
        try:
            yield
        finally:
            stop.set()
            if worker_task is not None:
                await worker_task
            if worker_uow is not None:
                worker_uow.close()

    app = FastAPI(
        title="PaperSeek Community API",
        version="0.3.0",
        lifespan=lifespan,
    )

    def service() -> tuple[RunService, SQLiteRunUnitOfWork]:
        uow = SQLiteRunUnitOfWork(database)
        return RunService(uow, FileArtifactStore(database.parent)), uow

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_payload("invalid_request", "The request is invalid."),
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": "0.3.0"}

    @app.get("/ready")
    def ready() -> dict:
        run_service, uow = service()
        try:
            run_service.get_history_page(page_size=1)
            return {"status": "ready"}
        finally:
            uow.close()

    @app.get("/api/v1/sources")
    def get_sources() -> dict:
        return {
            "sources": [
                {"id": source_id, "label": label, "api_key": api_key}
                for source_id, label, api_key in SOURCES
            ]
        }

    @app.post("/api/v1/runs", status_code=202)
    def submit_run(
        submission: RunSubmission,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ) -> dict:
        if execution_resolver is None:
            raise ApiError(503, "executor_unavailable", "The embedded executor is not configured.")
        allowed_sources = {item[0] for item in SOURCES}
        if submission.source not in allowed_sources:
            raise ApiError(422, "unsupported_source", "The selected source is not supported.")
        if submission.search_budget not in {"fast", "medium", "high", "max"}:
            raise ApiError(422, "unsupported_search_budget", "The selected search budget is not supported.")
        snapshot = {
            "question": submission.question.strip(),
            "source": submission.source,
            "search_budget": submission.search_budget,
            "field": submission.field.strip(),
            "citation_enabled": submission.citation_enabled,
            "llm": settings.llm_route(submission.llm.model_dump()),
        }
        if snapshot["llm"]["api_type"] not in {
            "openai_chat",
            "openai_responses",
            "anthropic_messages",
        }:
            raise ApiError(422, "unsupported_llm_api_type", "The selected LLM API type is not supported.")
        digest = hashlib.sha256(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        run_service, uow = service()
        try:
            detail = run_service.submit_run(
                subject="community",
                idempotency_key=idempotency_key,
                request_digest=digest,
                question=submission.question,
                source=submission.source,
                config_snapshot=snapshot,
            )
            if detail.status not in TERMINAL_STATUSES:
                try:
                    credentials.save(
                        detail.id,
                        submission.credentials.model_dump(mode="json"),
                    )
                except Exception as exc:
                    run_service.request_cancel(detail.id)
                    raise ApiError(
                        500,
                        "credential_persistence_failed",
                        "Temporary credentials could not be stored safely.",
                    ) from exc
            return detail.model_dump(mode="json")
        except IdempotencyConflict as exc:
            raise ApiError(409, "idempotency_conflict", "The idempotency key belongs to another request.") from exc
        except ActiveRunExists as exc:
            raise ApiError(
                409,
                "active_run_exists",
                "A run is already active.",
                {"run_id": exc.run_id},
            ) from exc
        finally:
            uow.close()

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run_service, uow = service()
        try:
            return run_service.get_run(run_id).model_dump(mode="json")
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        finally:
            uow.close()

    @app.get("/api/v1/runs/{run_id}/events", response_model=None)
    async def get_events(
        request: Request,
        run_id: str,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            after_sequence = int(last_event_id or 0)
        except ValueError as exc:
            raise ApiError(400, "invalid_event_cursor", "Last-Event-ID must be an integer.") from exc
        if after_sequence < 0:
            raise ApiError(400, "invalid_event_cursor", "Last-Event-ID must not be negative.")
        run_service, uow = service()
        try:
            run_service.get_run(run_id)
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        finally:
            uow.close()

        async def stream():
            replay_uow = SQLiteRunUnitOfWork(database)
            replay = RunService(replay_uow, FileArtifactStore(database.parent))
            sequence = after_sequence
            keepalive_at = asyncio.get_running_loop().time() + 10.0
            try:
                while True:
                    try:
                        detail = replay.get_run(run_id)
                    except RunNotFound:
                        return
                    events = replay.list_events(
                        run_id,
                        after_sequence=sequence,
                        limit=200,
                    )
                    for event in events:
                        sequence = event.sequence
                        payload = json.dumps(
                            event.model_dump(mode="json"),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        yield (
                            f"id: {event.sequence}\n"
                            f"event: {event.event_type}\n"
                            f"data: {payload}\n\n"
                        ).encode("utf-8")
                    if detail.status in TERMINAL_STATUSES and sequence >= detail.last_event_sequence:
                        return
                    if await request.is_disconnected():
                        return
                    now = asyncio.get_running_loop().time()
                    if now >= keepalive_at:
                        yield b": keepalive\n\n"
                        keepalive_at = now + 10.0
                    await asyncio.sleep(0.1)
            finally:
                replay_uow.close()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/v1/runs/{run_id}/results")
    def get_results(
        run_id: str,
        cursor: str | None = None,
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        run_service, uow = service()
        try:
            page = run_service.get_result_page(
                run_id,
                cursor=cursor,
                page_size=page_size,
            )
            return {
                "results": [item.record.model_dump(mode="json") for item in page.results],
                "next_cursor": page.next_cursor,
            }
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        except InvalidCursor as exc:
            raise ApiError(400, "invalid_cursor", "The result cursor is invalid.") from exc
        finally:
            uow.close()

    @app.get("/api/v1/runs/{run_id}/citation-map")
    def get_citation_map(run_id: str) -> Response:
        run_service, uow = service()
        try:
            return _content_response(run_service.get_citation_map(run_id))
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        except ArtifactNotFound as exc:
            raise ApiError(404, "artifact_not_found", "Citation map not found.") from exc
        finally:
            uow.close()

    @app.get("/api/v1/runs/{run_id}/artifacts")
    def get_artifacts(run_id: str) -> dict:
        run_service, uow = service()
        try:
            return {
                "artifacts": [
                    item.model_dump(mode="json")
                    for item in run_service.list_user_artifacts(run_id)
                ]
            }
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        finally:
            uow.close()

    @app.get("/api/v1/runs/{run_id}/artifacts/{artifact_id}")
    def download_artifact(run_id: str, artifact_id: str) -> Response:
        run_service, uow = service()
        try:
            return _content_response(
                run_service.read_user_artifact(run_id, artifact_id),
                disposition=True,
            )
        except (RunNotFound, ArtifactNotFound) as exc:
            raise ApiError(404, "artifact_not_found", "Artifact not found.") from exc
        finally:
            uow.close()

    @app.get("/api/v1/runs/{run_id}/export")
    def export_run(run_id: str, format: str) -> Response:
        run_service, uow = service()
        try:
            return _content_response(
                run_service.get_export(run_id, format),
                disposition=True,
            )
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        except ArtifactNotFound as exc:
            raise ApiError(404, "artifact_not_found", "Export not found.") from exc
        except ValueError as exc:
            raise ApiError(400, "invalid_export_format", "Export format must be csv or json.") from exc
        finally:
            uow.close()

    @app.get("/api/v1/history")
    def get_history(
        cursor: str | None = None,
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        run_service, uow = service()
        try:
            return run_service.get_history_page(
                cursor=cursor,
                page_size=page_size,
            ).model_dump(mode="json")
        except InvalidCursor as exc:
            raise ApiError(400, "invalid_cursor", "The history cursor is invalid.") from exc
        finally:
            uow.close()

    @app.delete("/api/v1/history/{run_id}", status_code=202)
    def delete_history(
        run_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict:
        run_service, uow = service()
        try:
            receipt = run_service.delete_history_run(run_id)
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        except RunStateError as exc:
            raise ApiError(409, "run_not_terminal", "An active run cannot be deleted.") from exc
        finally:
            uow.close()
        background_tasks.add_task(_drain_cleanup_jobs, database)
        return receipt.model_dump(mode="json")

    @app.post("/api/v1/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: str) -> dict:
        run_service, uow = service()
        try:
            return run_service.request_cancel(run_id).model_dump(mode="json")
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        except RunStateError as exc:
            raise ApiError(409, "run_not_cancellable", "Run cannot be cancelled.") from exc
        finally:
            uow.close()

    if static_dir is not None:
        root = Path(static_dir).expanduser().resolve()
        if not (root / "index.html").is_file():
            raise ValueError("The Community static directory must contain index.html.")
        app.mount("/", SpaStaticFiles(directory=root, html=True), name="community-web")

    return app
