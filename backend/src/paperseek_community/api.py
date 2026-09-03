from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from paperseek_app.execution import WorkflowExecution
from paperseek_app.services import RunExecutionService
from paperseek_community import api_dependencies
from paperseek_community.api_routes import history as history_routes
from paperseek_community.api_routes import runs as run_routes
from paperseek_community.api_routes import system as system_routes
from paperseek_community.artifacts import FileArtifactStore
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_community.worker import EmbeddedRunExecutor
from paperseek_core.ports import CancellationToken


class SpaStaticFiles(StaticFiles):
    @staticmethod
    def _is_spa_route(path: str) -> bool:
        parts = [part for part in path.replace("\\", "/").strip("/").split("/") if part]
        if not parts or parts == ["search"] or parts == ["history"]:
            return True
        return (
            len(parts) in {2, 3}
            and parts[0] == "runs"
            and (len(parts) == 2 or parts[2] in {"results", "citation-map"})
        )

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if (
                exc.status_code == 404
                and scope["method"] in {"GET", "HEAD"}
                and self._is_spa_route(path)
            ):
                return await super().get_response("index.html", scope)
            raise
        if (
            response.status_code == 404
            and scope["method"] in {"GET", "HEAD"}
            and self._is_spa_route(path)
        ):
            return await super().get_response("index.html", scope)
        return response


def create_app(
    database_path: Path | str,
    *,
    execution_resolver: Callable[[object, CancellationToken], WorkflowExecution] | None = None,
    accept_submissions_without_worker: bool = False,
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
        api_dependencies.drain_cleanup_jobs(database)
        worker_uow = None
        worker_task = None
        stop = asyncio.Event()
        if execution_resolver is not None:
            worker_uow = SQLiteRunUnitOfWork(database)
            executor = EmbeddedRunExecutor(
                RunExecutionService(worker_uow, FileArtifactStore(database.parent)),
                execution_resolver,
                owner_id=f"community-embedded-{uuid4()}",
            )

            async def work() -> None:
                while not stop.is_set():
                    detail = await executor.run_once()
                    if detail is not None and detail.status in api_dependencies.TERMINAL_STATUSES:
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

    api_dependencies.register_error_handlers(app)
    system_routes.register_system_routes(app, database=database, settings=settings)
    run_routes.register_run_routes(
        app,
        database=database,
        settings=settings,
        credentials=credentials,
        execution_resolver=execution_resolver,
        accept_submissions_without_worker=accept_submissions_without_worker,
    )
    history_routes.register_history_routes(app, database=database)

    if static_dir is not None:
        root = Path(static_dir).expanduser().resolve()
        if not (root / "index.html").is_file():
            raise ValueError("The Community static directory must contain index.html.")
        app.mount("/", SpaStaticFiles(directory=root, html=True), name="community-web")

    return app
