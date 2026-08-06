from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from paperseek.api.run_schemas import (
    RunCancelResponse,
    RunDetailResponse,
    RunEventsResponse,
    RunResultsResponse,
    RunSubmissionResponse,
)
from paperseek.api.schemas import SearchRequest
from paperseek.application.ports import RunStore
from paperseek.run_executor import InProcessRunExecutor


StoreFactory = Callable[[Request], RunStore]
StoreErrorMapper = Callable[[Exception], HTTPException]
RunSubmitter = Callable[[Request, SearchRequest, str, str], dict]


def build_runs_router(
    store_factory: StoreFactory,
    executor: InProcessRunExecutor,
    *,
    store_error_type: type[Exception] | tuple[type[Exception], ...] = (),
    store_error_mapper: Optional[StoreErrorMapper] = None,
    submitter: Optional[RunSubmitter] = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

    def load_run(request: Request, run_id: str) -> dict:
        try:
            run = store_factory(request).get_run(run_id)
        except store_error_type as exc:
            if store_error_mapper is None:
                raise
            raise store_error_mapper(exc) from exc
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return run

    if submitter is not None:

        @router.post("", response_model=RunSubmissionResponse, status_code=202)
        def run_create(request: Request, payload: SearchRequest):
            return submitter(request, payload, "create", "")

        @router.post(
            "/{run_id}/resume",
            response_model=RunSubmissionResponse,
            status_code=202,
        )
        def run_resume(request: Request, run_id: str, payload: SearchRequest):
            run = load_run(request, run_id)
            if not run.get("resumable"):
                raise HTTPException(status_code=409, detail="Run has no recoverable checkpoint.")
            return submitter(request, payload, "resume", run_id)

        @router.post(
            "/{run_id}/retry",
            response_model=RunSubmissionResponse,
            status_code=202,
        )
        def run_retry(request: Request, run_id: str, payload: SearchRequest):
            run = load_run(request, run_id)
            if run.get("status") not in {"success", "error", "cancelled"}:
                raise HTTPException(status_code=409, detail="Run is still active.")
            return submitter(request, payload, "retry", run_id)

    @router.get("/{run_id}", response_model=RunDetailResponse)
    def run_detail(request: Request, run_id: str):
        return load_run(request, run_id)

    @router.get("/{run_id}/events", response_model=RunEventsResponse)
    def run_events(
        request: Request,
        run_id: str,
        after_id: int = Query(default=0, ge=0),
    ):
        run = load_run(request, run_id)
        events = [
            event
            for event in run.get("events") or []
            if int(event.get("id") or 0) > after_id
        ]
        next_after_id = max([after_id, *(int(event.get("id") or 0) for event in events)])
        return {"run_id": run_id, "events": events, "next_after_id": next_after_id}

    @router.get("/{run_id}/results", response_model=RunResultsResponse)
    def run_results(request: Request, run_id: str):
        run = load_run(request, run_id)
        return {"run_id": run_id, "results": run.get("ranked") or []}

    @router.post("/{run_id}/cancel", response_model=RunCancelResponse)
    def run_cancel(request: Request, run_id: str):
        active = executor.cancel(run_id)
        try:
            cancelled = store_factory(request).cancel_run(run_id)
        except store_error_type as exc:
            if store_error_mapper is None:
                raise
            raise store_error_mapper(exc) from exc
        if not active and not cancelled:
            raise HTTPException(status_code=404, detail="Run not found or already terminal.")
        return {"cancelled": run_id}

    return router
