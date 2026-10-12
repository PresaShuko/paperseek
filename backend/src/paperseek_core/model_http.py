"""Shared JSON model transport; wire formats stay in their protocol adapters."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from paperseek_core.http_retry import cancellable_request, request_with_retries
from paperseek_core.key_pool import RequestKeys
from paperseek_core.ports import CancellationToken


def bearer_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def post_model_json(
    client: httpx.AsyncClient,
    cancellation: CancellationToken,
    url: str,
    body: dict,
    keys: tuple[str, ...],
    headers: Callable[[str], dict[str, str]] = bearer_headers,
) -> tuple[httpx.Response, str]:
    rotation = RequestKeys(keys)

    async def send(_attempt: int) -> httpx.Response:
        request_headers = headers(rotation.next_key())
        return await cancellable_request(
            lambda: client.post(url, json=body, headers=request_headers),
            cancellation,
        )

    response, _ = await request_with_retries(
        send,
        cancellation=cancellation,
        retry_auth=rotation.reject_current,
    )
    return response, rotation.current
