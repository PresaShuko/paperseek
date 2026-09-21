from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Query

from paperseek_app.errors import InvalidCursor, RunNotFound, RunStateError
from paperseek_app.models import DeletionReceipt, HistoryPage
from paperseek_community.api_dependencies import (
    ApiError,
    drain_cleanup_jobs,
    open_cleanup_service,
    open_query_service,
)


def register_history_routes(app: FastAPI, *, database: Path) -> None:
    @app.get("/api/v1/history", response_model=HistoryPage)
    def get_history(
        cursor: str | None = None,
        page_size: int = Query(default=50, ge=1, le=200),
        query: str | None = None,
    ) -> HistoryPage:
        run_service, uow = open_query_service(database)
        try:
            return run_service.get_history_page(
                cursor=cursor,
                page_size=page_size,
                query=query,
            ).model_dump(mode="json")
        except InvalidCursor as exc:
            raise ApiError(400, "invalid_cursor", "The history cursor is invalid.") from exc
        finally:
            uow.close()

    @app.delete("/api/v1/history/{run_id}", status_code=202, response_model=DeletionReceipt)
    def delete_history(
        run_id: str,
        background_tasks: BackgroundTasks,
    ) -> DeletionReceipt:
        run_service, uow = open_cleanup_service(database)
        try:
            receipt = run_service.delete_history_run(run_id)
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        except RunStateError as exc:
            raise ApiError(409, "run_not_terminal", "An active run cannot be deleted.") from exc
        finally:
            uow.close()
        background_tasks.add_task(drain_cleanup_jobs, database)
        return receipt.model_dump(mode="json")
