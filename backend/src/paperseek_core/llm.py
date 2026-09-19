from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from paperseek_core.key_pool import ApiKeyPool, retryable_key_status
from paperseek_core.errors import LLMRequestError
from paperseek_core.ports import CancellationToken


class HttpLLMAdapter:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        cancellation: CancellationToken,
        api_type: str,
        base_url: str,
        model: str,
        api_key: str,
    ) -> None:
        self.client = client
        self.cancellation = cancellation
        self.api_type = api_type
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_keys = ApiKeyPool(api_key)

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        if self.api_type == "anthropic_messages":
            return await self._anthropic(messages, temperature, max_tokens)
        if self.api_type == "openai_responses":
            return await self._responses(messages, temperature, max_tokens)
        if self.api_type != "openai_chat":
            raise LLMRequestError("The configured LLM API type is unsupported.")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        response, api_key = await self._post(
            f"{self.base_url}/chat/completions",
            body,
            self._bearer_headers,
            allow_status={400, 422},
        )
        if response.status_code in {400, 422}:
            body.pop("response_format")
            response, _ = await self._post(
                f"{self.base_url}/chat/completions",
                body,
                self._bearer_headers,
                attempt_keys=(api_key,),
            )
        try:
            choice = (response.json().get("choices") or [])[0]
            message = choice.get("message") or {}
            return str(message.get("content") or message.get("reasoning_content") or "") or self._missing()
        except (ValueError, TypeError, IndexError, AttributeError) as exc:
            raise LLMRequestError("The LLM chat response is invalid.", code="provider_invalid_response") from exc

    async def _responses(self, messages, temperature: float, max_tokens: int) -> str:
        instructions = "\n\n".join(item["content"] for item in messages if item.get("role") == "system")
        body: dict[str, Any] = {
            "model": self.model,
            "input": [item for item in messages if item.get("role") != "system"],
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if instructions:
            body["instructions"] = instructions
        response, _ = await self._post(
            f"{self.base_url}/responses",
            body,
            self._bearer_headers,
        )
        try:
            payload = response.json()
            if payload.get("output_text"):
                return str(payload["output_text"])
            texts = [
                str(content["text"])
                for item in payload.get("output", [])
                for content in item.get("content", [])
                if content.get("type") in {"output_text", "text"} and content.get("text")
            ]
            return "\n".join(texts) or self._missing()
        except (ValueError, TypeError, AttributeError) as exc:
            raise LLMRequestError("The LLM responses payload is invalid.", code="provider_invalid_response") from exc

    async def _anthropic(self, messages, temperature: float, max_tokens: int) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [item for item in messages if item.get("role") != "system"],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        system = "\n\n".join(item["content"] for item in messages if item.get("role") == "system")
        if system:
            body["system"] = system
        response, _ = await self._post(
            f"{self.base_url}/v1/messages",
            body,
            self._anthropic_headers,
        )
        try:
            texts = [
                str(item["text"])
                for item in response.json().get("content", [])
                if item.get("text")
            ]
            return "\n".join(texts) or self._missing()
        except (ValueError, TypeError, AttributeError) as exc:
            raise LLMRequestError("The Anthropic response is invalid.", code="provider_invalid_response") from exc

    async def _post(
        self,
        url: str,
        body: dict,
        headers: Callable[[str], dict[str, str]],
        *,
        allow_status: set[int] | None = None,
        attempt_keys: tuple[str, ...] | None = None,
    ) -> tuple[httpx.Response, str]:
        if not self.api_keys.available and not url.startswith(("http://127.0.0.1", "http://localhost")):
            raise LLMRequestError("The configured LLM credential is unavailable.", code="provider_authentication_failed")
        keys = attempt_keys or self.api_keys.attempts()
        for index, api_key in enumerate(keys):
            try:
                response = await self._cancellable_post(url, body, headers(api_key))
            except httpx.RequestError as exc:
                if index + 1 < len(keys):
                    continue
                raise LLMRequestError("The LLM endpoint could not be reached.", code="provider_connection_failed") from exc
            if response.status_code in (allow_status or set()) or 200 <= response.status_code < 300:
                return response, api_key
            if retryable_key_status(response.status_code) and index + 1 < len(keys):
                continue
            raise LLMRequestError(f"The LLM endpoint returned HTTP {response.status_code}.",
                                  code=self._response_error_code(response))
        raise LLMRequestError("The LLM endpoint could not be reached.")

    async def _cancellable_post(
        self,
        url: str,
        body: dict,
        headers: dict[str, str],
    ) -> httpx.Response:
        self.cancellation.raise_if_cancelled()
        request = asyncio.create_task(self.client.post(url, json=body, headers=headers))
        cancelled = asyncio.create_task(self.cancellation.wait())
        try:
            done, _ = await asyncio.wait({request, cancelled}, return_when=asyncio.FIRST_COMPLETED)
            if cancelled in done:
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
                self.cancellation.raise_if_cancelled()
                raise asyncio.CancelledError
            return await request
        finally:
            for task in (request, cancelled):
                if not task.done():
                    task.cancel()
            await asyncio.gather(request, cancelled, return_exceptions=True)

    @staticmethod
    def _bearer_headers(api_key: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _anthropic_headers(api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _response_error_code(response: httpx.Response) -> str:
        if response.status_code in {401, 403}:
            return "provider_authentication_failed"
        if response.status_code == 402:
            return "provider_quota_exhausted"
        if response.status_code == 429:
            # OpenAI-compatible APIs distinguish billing from rate limits by code/type,
            # never by the provider's free-text message (which may contain private data).
            try:
                payload = response.json()
            except ValueError:
                payload = None
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict) and "insufficient_quota" in (error.get("code"), error.get("type")):
                return "provider_quota_exhausted"
            return "provider_rate_limited"
        if response.status_code >= 500:
            return "provider_unavailable"
        return "provider_request_rejected"

    @staticmethod
    def _missing() -> str:
        raise LLMRequestError("The LLM response did not contain text.", code="provider_invalid_response")
