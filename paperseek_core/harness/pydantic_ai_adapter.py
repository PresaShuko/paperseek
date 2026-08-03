
import json
import os
from typing import Any, Dict, Iterable, List

from paperseek_core.harness.schemas import QueryProposal


class PydanticAIAdapterUnavailable(RuntimeError):
    """Raised when the optional PydanticAI query contract path is unavailable."""


def pydantic_ai_available() -> bool:
    try:
        import pydantic_ai  # noqa: F401
    except Exception:
        return False
    return True


def pydantic_ai_query_retry_enabled() -> bool:
    value = os.environ.get("PAPERSEEK_PYDANTICAI_QUERY_RETRY", "auto").strip().lower()
    if value in {"0", "false", "no", "off", "native", "disabled"}:
        return False
    if value in {"1", "true", "yes", "on", "pydanticai", "auto"}:
        return pydantic_ai_available()
    return False


def run_query_proposal_agent(
    llm: Any,
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.3,
    retries: int = 1,
    model_name: str = "paperseek-llm-client",
) -> QueryProposal:
    """Run a PydanticAI Agent while preserving PaperSeek's existing LLM client.

    PaperSeek supports endpoints that do not reliably implement tool calling or
    provider-native structured output. This adapter lets PydanticAI own schema
    validation and retry prompts, while the underlying request still goes
    through the configured ``LLMClient.chat`` path, including key pools,
    provider fallbacks, logging side effects, and endpoint-specific behavior.
    """

    try:
        from pydantic_ai import Agent
    except Exception as exc:  # pragma: no cover - exercised by fallback callers
        raise PydanticAIAdapterUnavailable(str(exc)) from exc

    system_prompt, user_prompt = _split_chat_prompt(messages)
    model = PaperSeekLLMModel(llm, temperature=temperature, model_name=model_name)
    agent = Agent(
        model,
        output_type=QueryProposal,
        system_prompt=system_prompt,
        retries=max(0, int(retries or 0)),
    )
    result = agent.run_sync(user_prompt)
    output = getattr(result, "output", None)
    if isinstance(output, QueryProposal):
        return output
    if isinstance(output, dict):
        return QueryProposal(**output)
    raise PydanticAIAdapterUnavailable("PydanticAI did not return a QueryProposal output.")


def _split_chat_prompt(messages: Iterable[Dict[str, str]]) -> tuple[str, str]:
    system_parts: list[str] = []
    user_parts: list[str] = []
    for message in messages or []:
        role = (message.get("role") or "user").strip().lower()
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        else:
            user_parts.append(content)
    return "\n\n".join(system_parts).strip(), "\n\n".join(user_parts).strip()


class PaperSeekLLMModel:  # intentionally not subclassed until optional imports succeed
    def __new__(cls, *args, **kwargs):
        try:
            from pydantic_ai.models import Model
        except Exception as exc:  # pragma: no cover - exercised by fallback callers
            raise PydanticAIAdapterUnavailable(str(exc)) from exc

        class _PaperSeekLLMModel(Model):
            def __init__(self, llm: Any, *, temperature: float = 0.3, model_name: str = "paperseek-llm-client"):
                super().__init__()
                self.llm = llm
                self.temperature = temperature
                self._model_name = model_name

            @property
            def model_name(self) -> str:
                return self._model_name

            @property
            def system(self) -> str:
                return "paperseek"

            async def request(self, messages, model_settings, model_request_parameters):
                from pydantic_ai.messages import ModelResponse, TextPart
                from pydantic_ai.usage import RequestUsage

                chat_messages = _model_messages_to_chat(messages)
                schema_instruction = _output_schema_instruction(model_request_parameters)
                if schema_instruction:
                    chat_messages.append({"role": "system", "content": schema_instruction})
                temperature = _model_temperature(model_settings, self.temperature)
                content = self.llm.chat(chat_messages, temperature=temperature)
                return ModelResponse(
                    parts=[TextPart(content=str(content or ""))],
                    usage=RequestUsage(),
                    model_name=self._model_name,
                )

        return _PaperSeekLLMModel(*args, **kwargs)


def _model_temperature(model_settings: Any, default: float) -> float:
    if isinstance(model_settings, dict) and model_settings.get("temperature") is not None:
        try:
            return float(model_settings["temperature"])
        except (TypeError, ValueError):
            return default
    return default


def _model_messages_to_chat(messages: Iterable[Any]) -> list[dict[str, str]]:
    chat_messages: list[dict[str, str]] = []
    for message in messages or []:
        kind = getattr(message, "kind", "")
        for part in getattr(message, "parts", []) or []:
            part_kind = getattr(part, "part_kind", "")
            content = _part_content_to_text(part)
            if not content:
                continue
            if part_kind == "system-prompt":
                role = "system"
            elif part_kind == "text" and kind == "response":
                role = "assistant"
            else:
                role = "user"
            chat_messages.append({"role": role, "content": content})
    return chat_messages


def _part_content_to_text(part: Any) -> str:
    content = getattr(part, "content", "")
    if isinstance(content, str):
        return content.strip()
    if content in (None, ""):
        return ""
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content).strip()


def _output_schema_instruction(model_request_parameters: Any) -> str:
    output_object = getattr(model_request_parameters, "output_object", None)
    schema = getattr(output_object, "json_schema", None) if output_object is not None else None
    if not isinstance(schema, dict):
        return (
            "Return exactly one JSON object with keys query and rationale. "
            "Do not wrap it in markdown and do not include prose outside JSON."
        )
    compact_schema = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return (
        "Return exactly one JSON object that satisfies this schema. "
        "Do not use tool calls, markdown fences, or prose outside JSON. "
        f"Schema: {compact_schema}"
    )
