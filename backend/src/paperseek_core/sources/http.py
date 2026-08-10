from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
import asyncio
from contextlib import nullcontext
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from paperseek_core.execution import RequestContext
from paperseek_core.sources.contracts import SourceError, SourceFailureKind


TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


def split_api_keys(value: str) -> tuple[str, ...]:
    normalized = str(value or "").replace("\r", "\n").replace(",", "\n").replace(";", "\n")
    return tuple(dict.fromkeys(part.strip() for part in normalized.split("\n") if part.strip()))


def _redacted_url(url: str) -> str:
    parts = urlsplit(str(url))
    sensitive = {"api_key", "apikey", "key", "token", "x-api-key"}
    query = [
        (key, "***" if key.lower() in sensitive else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class AsyncHttpTransport:
    """Small injectable async HTTP boundary shared by concrete source adapters."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        context: RequestContext | None = None,
    ) -> None:
        self._owned_client = client is None
        self._client = client
        self._sleep = sleep
        self._context = context or RequestContext(step_key="source.request")

    async def aclose(self) -> None:
        if self._owned_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def wait(self, seconds: float) -> None:
        await self._sleep(seconds)

    async def request(
        self,
        source: str,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout = 45,
        query: str = "",
        attempts: int = 3,
        retry_statuses: frozenset[int] = TRANSIENT_STATUSES,
        retry_transport: bool = True,
        context: RequestContext | None = None,
    ) -> tuple[httpx.Response, dict[str, Any]]:
        request_context = context or self._context
        started = time.perf_counter()
        last_error: httpx.RequestError | None = None
        last_failure_kind = SourceFailureKind.TRANSPORT_ERROR
        if self._client is None:
            self._client = httpx.AsyncClient()
        client = self._client
        attempted = 0
        for attempt in range(1, max(1, attempts) + 1):
            request_context.cancellation.raise_if_cancelled()
            attempted = attempt
            response_headers_received = False

            async def trace(name: str, _info: dict[str, Any]) -> None:
                nonlocal response_headers_received
                if name.endswith("receive_response_headers.complete"):
                    response_headers_received = True

            kwargs = {
                "params": dict(params) if params is not None else None,
                "json": json,
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
            if isinstance(client, httpx.AsyncClient):
                kwargs["extensions"] = {"trace": trace}
            try:
                remaining = self._remaining(request_context)
                deadline_scope = (
                    asyncio.timeout(remaining)
                    if remaining is not None
                    else nullcontext()
                )
                async with deadline_scope:
                    response = await self._send_with_cancellation(
                        client,
                        method,
                        url,
                        kwargs,
                        request_context,
                    )
            except TimeoutError as exc:
                raise self._deadline_error(source, query, attempted) from exc
            except httpx.RequestError as exc:
                last_error = exc
                last_failure_kind = self._failure_kind(exc, response_headers_received)
                if not retry_transport or attempt >= attempts:
                    break
                await self._wait_with_context(0.7 * attempt, request_context, source, query, attempted)
                continue

            request_context.cancellation.raise_if_cancelled()
            info = {
                "method": method.upper(),
                "url": _redacted_url(str(response.request.url) if response.request else url),
                "status": response.status_code,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "attempts": attempt,
            }
            if response.status_code not in retry_statuses or attempt >= attempts:
                return response, info
            await self._wait_with_context(
                self._retry_delay(response, attempt, source),
                request_context,
                source,
                query,
                attempted,
            )

        raise SourceError(
            source,
            f"Source request failed after {attempted} attempt(s).",
            query=query,
            failure_kind=last_failure_kind,
        ) from last_error

    @staticmethod
    async def _send_with_cancellation(
        client: Any,
        method: str,
        url: str,
        kwargs: dict[str, Any],
        context: RequestContext,
    ) -> httpx.Response:
        request_task = asyncio.create_task(client.request(method, url, **kwargs))
        cancellation_task = asyncio.create_task(context.cancellation.wait())
        try:
            done, _ = await asyncio.wait(
                {request_task, cancellation_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_task in done:
                request_task.cancel()
                await asyncio.gather(request_task, return_exceptions=True)
                context.cancellation.raise_if_cancelled()
                raise asyncio.CancelledError
            return await request_task
        finally:
            for task in (request_task, cancellation_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(request_task, cancellation_task, return_exceptions=True)

    @staticmethod
    def _remaining(context: RequestContext) -> float | None:
        if context.deadline_at is None:
            return None
        remaining = context.deadline_at - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request step deadline exceeded")
        return remaining

    async def _wait_with_context(
        self,
        seconds: float,
        context: RequestContext,
        source: str,
        query: str,
        attempted: int,
    ) -> None:
        context.cancellation.raise_if_cancelled()
        try:
            remaining = self._remaining(context)
            deadline_scope = asyncio.timeout(remaining) if remaining is not None else nullcontext()
            async with deadline_scope:
                await self._sleep(seconds)
        except TimeoutError as exc:
            raise self._deadline_error(source, query, attempted) from exc
        context.cancellation.raise_if_cancelled()

    @staticmethod
    def _deadline_error(source: str, query: str, attempted: int) -> SourceError:
        return SourceError(
            source,
            f"Source request step deadline exceeded after {attempted} attempt(s).",
            query=query,
            failure_kind=SourceFailureKind.STEP_DEADLINE,
        )

    @staticmethod
    def _failure_kind(
        exc: httpx.RequestError,
        response_headers_received: bool,
    ) -> SourceFailureKind:
        if isinstance(exc, httpx.ConnectTimeout):
            return SourceFailureKind.CONNECT_TIMEOUT
        if isinstance(exc, httpx.WriteTimeout):
            return SourceFailureKind.SEND_TIMEOUT
        if isinstance(exc, httpx.ReadTimeout):
            return (
                SourceFailureKind.READ_IDLE_TIMEOUT
                if response_headers_received
                else SourceFailureKind.FIRST_BYTE_TIMEOUT
            )
        if isinstance(exc, httpx.ConnectError):
            return SourceFailureKind.CONNECT_ERROR
        return SourceFailureKind.TRANSPORT_ERROR

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int, source: str) -> float:
        retry_after = response.headers.get("Retry-After", "").strip()
        try:
            if retry_after:
                return max(0.0, min(float(retry_after), 30.0))
        except ValueError:
            pass
        base = 2.0 if source == "wos" else 0.7
        return base * attempt
