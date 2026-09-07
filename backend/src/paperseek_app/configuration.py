from __future__ import annotations

from typing import Protocol


LLM_ROUTE_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "openai": ("openai_responses", "https://api.openai.com/v1", "gpt-5.4-mini"),
    "anthropic": ("anthropic_messages", "https://api.anthropic.com", "claude-sonnet-4-6"),
    "google": ("openai_chat", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.5-flash"),
    "deepseek": ("openai_chat", "https://api.deepseek.com", "deepseek-v4-flash"),
    "cstcloud": ("openai_chat", "https://uni-api.cstcloud.cn/v1", "deepseek-v4-flash"),
    "dashscope": ("openai_chat", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.6-plus"),
    "moonshot": ("openai_chat", "https://api.moonshot.cn/v1", "kimi-k2.6"),
    "zhipu": ("openai_chat", "https://open.bigmodel.cn/api/paas/v4", "glm-5.1"),
    "siliconflow": ("openai_chat", "https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V4-Flash"),
    "openrouter": ("openai_chat", "https://openrouter.ai/api/v1", "openai/gpt-5.4-mini"),
    "nvidia": ("openai_chat", "https://integrate.api.nvidia.com/v1", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
    "volcengine": ("openai_chat", "https://ark.cn-beijing.volces.com/api/v3", "doubao-seed-2-0-mini-260428"),
    "hunyuan": ("openai_chat", "https://tokenhub.tencentmaas.com/v1", "hunyuan-turbos-latest"),
    "qianfan": ("openai_chat", "https://qianfan.baidubce.com/v2", "ernie-5.0"),
    "modelscope": ("openai_chat", "https://api-inference.modelscope.cn/v1", "Qwen/Qwen3-235B-A22B-Instruct-2507"),
    "ollama": ("openai_chat", "http://127.0.0.1:11434/v1", "qwen3:8b"),
    "custom": ("openai_chat", "", ""),
}
LLM_PROVIDERS = frozenset(LLM_ROUTE_DEFAULTS)


class SubmissionDefaults(Protocol):
    """Non-secret defaults supplied by Community and Hosted deployments."""

    llm_api_type: str
    llm_base_url: str
    llm_model: str
    wos_db: str


def resolve_llm_route(defaults: SubmissionDefaults, requested: dict | None = None) -> dict[str, str]:
    requested = requested or {}
    provider = str(requested.get("provider") or "").strip().lower()
    requested_api_type = str(requested.get("api_type") or "").strip().lower()
    requested_base_url = str(requested.get("base_url") or "").strip().rstrip("/")
    requested_model = str(requested.get("model") or "").strip()
    if provider:
        default_api_type, default_base_url, default_model = LLM_ROUTE_DEFAULTS.get(
            provider,
            (defaults.llm_api_type, defaults.llm_base_url, defaults.llm_model),
        )
        return {
            "provider": provider,
            "api_type": requested_api_type or default_api_type,
            "base_url": requested_base_url or default_base_url,
            "model": requested_model or default_model,
        }
    api_type = requested_api_type or defaults.llm_api_type
    base_url = requested_base_url or defaults.llm_base_url.rstrip("/")
    model = requested_model or defaults.llm_model
    inferred_provider = "custom"
    for name, provider_defaults in LLM_ROUTE_DEFAULTS.items():
        if provider_defaults == (api_type, base_url, model):
            inferred_provider = name
            break
    return {
        "provider": inferred_provider,
        "api_type": api_type,
        "base_url": base_url,
        "model": model,
    }


def normalize_wos_db(value: object, default: object = "WOS") -> str:
    selected = str(value or "").strip()
    if selected:
        return selected
    return str(default or "WOS").strip() or "WOS"
