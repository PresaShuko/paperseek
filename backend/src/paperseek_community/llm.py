from __future__ import annotations

import asyncio
from typing import Any

import httpx

from paperseek_core.errors import LLMRequestError
from paperseek_core.ports import CancellationToken


class CommunityLLMAdapter:
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
        self.api_key = api_key

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
        response = await self._post(
            f"{self.base_url}/chat/completions",
            body,
            self._bearer_headers(),
            allow_status={400, 422},
        )
        if response.status_code in {400, 422}:
            body.pop("response_format")
            response = await self._post(
                f"{self.base_url}/chat/completions",
                body,
                self._bearer_headers(),
            )
        try:
            choice = (response.json().get("choices") or [])[0]
            message = choice.get("message") or {}
            return str(message.get("content") or message.get("reasoning_content") or "") or self._missing()
        except (ValueError, TypeError, IndexError, AttributeError) as exc:
            raise LLMRequestError("The LLM chat response is invalid.") from exc

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
        response = await self._post(f"{self.base_url}/responses", body, self._bearer_headers())
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
            raise LLMRequestError("The LLM responses payload is invalid.") from exc

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
        response = await self._post(
            f"{self.base_url}/v1/messages",
            body,
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        try:
            texts = [
                str(item["text"])
                for item in response.json().get("content", [])
                if item.get("text")
            ]
            return "\n".join(texts) or self._missing()
        except (ValueError, TypeError, AttributeError) as exc:
            raise LLMRequestError("The Anthropic response is invalid.") from exc

    async def _post(
        self,
        url: str,
        body: dict,
        headers: dict[str, str],
        *,
        allow_status: set[int] | None = None,
    ) -> httpx.Response:
        if not self.api_key and not url.startswith(("http://127.0.0.1", "http://localhost")):
            raise LLMRequestError("The configured LLM credential is unavailable.")
        request = asyncio.create_task(self.client.post(url, json=body, headers=headers))
        cancelled = asyncio.create_task(self.cancellation.wait())
        try:
            done, _ = await asyncio.wait({request, cancelled}, return_when=asyncio.FIRST_COMPLETED)
            if cancelled in done:
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
                self.cancellation.raise_if_cancelled()
                raise asyncio.CancelledError
            response = await request
        except httpx.RequestError as exc:
            raise LLMRequestError("The LLM endpoint could not be reached.") from exc
        finally:
            for task in (request, cancelled):
                if not task.done():
                    task.cancel()
            await asyncio.gather(request, cancelled, return_exceptions=True)
        if response.status_code not in (allow_status or set()) and not 200 <= response.status_code < 300:
            raise LLMRequestError(f"The LLM endpoint returned HTTP {response.status_code}.")
        return response

    def _bearer_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _missing() -> str:
        raise LLMRequestError("The LLM response did not contain text.")
