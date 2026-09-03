from __future__ import annotations

from dataclasses import dataclass
import os


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


@dataclass(frozen=True, slots=True)
class CommunityDeploymentSettings:
    llm_api_type: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    openalex_api_key: str
    semantic_scholar_api_key: str
    pubmed_api_key: str
    wos_api_key: str
    google_scholar_api_key: str
    contact_email: str
    wos_db: str = "WOS"

    @classmethod
    def from_environment(cls) -> "CommunityDeploymentSettings":
        api_type = os.environ.get("PAPERSEEK_LLM_API_TYPE", "openai_responses").strip()
        default_base = (
            "https://api.anthropic.com"
            if api_type == "anthropic_messages"
            else "https://api.openai.com/v1"
        )
        return cls(
            llm_api_type=api_type,
            llm_base_url=os.environ.get("PAPERSEEK_LLM_BASE_URL", default_base).strip(),
            llm_model=os.environ.get("PAPERSEEK_LLM_MODEL", "gpt-5.4-mini").strip(),
            llm_api_key=os.environ.get("PAPERSEEK_LLM_API_KEY", "").strip(),
            openalex_api_key=os.environ.get("PAPERSEEK_OPENALEX_API_KEY", "").strip(),
            semantic_scholar_api_key=os.environ.get("PAPERSEEK_SEMANTIC_SCHOLAR_API_KEY", "").strip(),
            pubmed_api_key=os.environ.get("PAPERSEEK_PUBMED_API_KEY", "").strip(),
            wos_api_key=os.environ.get("PAPERSEEK_WOS_API_KEY", "").strip(),
            google_scholar_api_key=os.environ.get("PAPERSEEK_GOOGLE_SCHOLAR_API_KEY", "").strip(),
            contact_email=os.environ.get("PAPERSEEK_CONTACT_EMAIL", "").strip(),
            wos_db=normalize_wos_db(os.environ.get("PAPERSEEK_WOS_DB")),
        )

    def llm_route(self, requested: dict | None = None) -> dict[str, str]:
        requested = requested or {}
        provider = str(requested.get("provider") or "").strip().lower()
        requested_api_type = str(requested.get("api_type") or "").strip().lower()
        requested_base_url = str(requested.get("base_url") or "").strip().rstrip("/")
        requested_model = str(requested.get("model") or "").strip()
        if provider:
            default_api_type, default_base_url, default_model = LLM_ROUTE_DEFAULTS.get(
                provider,
                (self.llm_api_type, self.llm_base_url, self.llm_model),
            )
            return {
                "provider": provider,
                "api_type": requested_api_type or default_api_type,
                "base_url": requested_base_url or default_base_url,
                "model": requested_model or default_model,
            }
        api_type = requested_api_type or self.llm_api_type
        base_url = requested_base_url or self.llm_base_url.rstrip("/")
        model = requested_model or self.llm_model
        inferred_provider = "custom"
        for name, defaults in LLM_ROUTE_DEFAULTS.items():
            if defaults == (api_type, base_url, model):
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
