from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import StreamingResponse

from paperseek_app.errors import RunNotFound
from paperseek_app.models import PersistedEvent
from paperseek_community.api_dependencies import (
    ApiError,
    TERMINAL_STATUSES,
    open_query_service,
)


def register_run_event_routes(app: FastAPI, *, database: Path) -> None:
    @app.get(
        "/api/v1/runs/{run_id}/events",
        response_model=None,
        responses={200: {"model": PersistedEvent, "content": {"text/event-stream": {}}}},
    )
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
        run_service, uow = open_query_service(database)
        try:
            run_service.get_run(run_id)
        except RunNotFound as exc:
            raise ApiError(404, "run_not_found", "Run not found.") from exc
        finally:
            uow.close()

        async def stream():
            replay, replay_uow = open_query_service(database)
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
