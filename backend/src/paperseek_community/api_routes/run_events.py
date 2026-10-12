from pathlib import Path

from fastapi import FastAPI, Header, Request
from starlette.concurrency import run_in_threadpool

from paperseek_app.errors import RunNotFound
from paperseek_app.models import PersistedEvent
from paperseek_community.api_dependencies import ApiError, open_query_service
from paperseek_community.api_routes.event_stream import event_cursor, event_response


def register_run_event_routes(app: FastAPI, *, database: Path) -> None:
    @app.get("/api/v1/runs/{run_id}/events", response_model=None,
             responses={200: {"model": PersistedEvent, "content": {"text/event-stream": {}}}})
    async def get_events(request: Request, run_id: str,
                         last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
        sequence = event_cursor(last_event_id)

        def check() -> None:
            service, uow = open_query_service(database)
            try:
                service.get_run(run_id)
            except RunNotFound as exc:
                raise ApiError(404, "run_not_found", "Run not found.") from exc
            finally:
                uow.close()

        await run_in_threadpool(check)

        def open_reader():
            service, uow = open_query_service(database)
            return lambda after: service.poll_events(run_id, after_sequence=after, limit=200), uow.close

        return event_response(request, sequence, open_reader)
