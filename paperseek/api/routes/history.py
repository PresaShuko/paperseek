from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request


HistoryStoreFactory = Callable[[Request], Any]
StoreErrorMapper = Callable[[Exception], HTTPException]


def build_history_router(
    store_factory: HistoryStoreFactory,
    *,
    store_error_type: type[Exception] | tuple[type[Exception], ...] = (),
    store_error_mapper: Optional[StoreErrorMapper] = None,
    clear_confirmation_detail: str = "Pass confirm=true to clear history.",
) -> APIRouter:
    router = APIRouter(prefix="/api/history", tags=["history"])

    def map_store_error(exc: Exception) -> None:
        if store_error_mapper is None:
            raise exc
        raise store_error_mapper(exc) from exc

    @router.get("/status")
    def history_status(request: Request):
        try:
            return store_factory(request).status()
        except store_error_type as exc:
            map_store_error(exc)

    @router.get("")
    def history_list(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        try:
            store = store_factory(request)
            return {
                **store.status(),
                "history": store.list_runs(limit=limit, offset=offset),
            }
        except store_error_type as exc:
            map_store_error(exc)

    @router.get("/{run_id}")
    def history_detail(request: Request, run_id: str):
        try:
            run = store_factory(request).get_run(run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="History run not found.")
            return run
        except store_error_type as exc:
            map_store_error(exc)

    @router.delete("/{run_id}")
    def history_delete(request: Request, run_id: str):
        try:
            if not store_factory(request).delete_run(run_id):
                raise HTTPException(status_code=404, detail="History run not found.")
            return {"deleted": run_id}
        except store_error_type as exc:
            map_store_error(exc)

    @router.delete("")
    def history_clear(request: Request, confirm: bool = Query(default=False)):
        if not confirm:
            raise HTTPException(status_code=400, detail=clear_confirmation_detail)
        try:
            return {"deleted": store_factory(request).clear()}
        except store_error_type as exc:
            map_store_error(exc)

    return router
