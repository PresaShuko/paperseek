"""Shared durable SSE replay for research runs and review stage jobs."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import json

from anyio import CancelScope
from fastapi import Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from paperseek_app.errors import RunNotFound
from paperseek_app.models import PersistedEvent, RunDetail
from paperseek_community.api_dependencies import ApiError, TERMINAL_STATUSES


def event_cursor(value: str | None) -> int:
    try:
        sequence = int(value or 0)
    except ValueError as exc:
        raise ApiError(400, "invalid_event_cursor", "Last-Event-ID must be an integer.") from exc
    if not 0 <= sequence <= 2**63 - 1:
        raise ApiError(400, "invalid_event_cursor", "Last-Event-ID is outside the supported range.")
    return sequence


def event_response(request: Request, after_sequence: int,
                   open_reader: Callable[[], tuple[Callable[[int], tuple[RunDetail, list[PersistedEvent]]], Callable[[], None]]]):
    async def stream():
        read, close = await run_in_threadpool(open_reader)
        sequence = after_sequence
        keepalive_at = asyncio.get_running_loop().time() + 10
        poll_delay = 0.1
        try:
            while True:
                try:
                    detail, events = await run_in_threadpool(read, sequence)
                except RunNotFound:
                    return
                for event in events:
                    sequence = event.sequence
                    payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":"))
                    yield f"id: {sequence}\nevent: {event.event_type}\ndata: {payload}\n\n".encode()
                if detail.status in TERMINAL_STATUSES and sequence >= detail.last_event_sequence:
                    return
                if await request.is_disconnected():
                    return
                now = asyncio.get_running_loop().time()
                if now >= keepalive_at:
                    yield b": keepalive\n\n"
                    keepalive_at = now + 10
                if len(events) == 200:
                    continue
                poll_delay = 0.1 if events else min(poll_delay * 2, 1)
                await asyncio.sleep(poll_delay)
        finally:
            with CancelScope(shield=True):
                await run_in_threadpool(close)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
