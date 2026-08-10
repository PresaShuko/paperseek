from __future__ import annotations

from dataclasses import dataclass
import os


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

    @classmethod
    def from_environment(cls) -> "CommunityDeploymentSettings":
        api_type = os.environ.get("PAPERSEEK_LLM_API_TYPE", "openai_chat").strip()
        default_base = (
            "https://api.anthropic.com"
            if api_type == "anthropic_messages"
            else "https://api.openai.com/v1"
        )
        return cls(
            llm_api_type=api_type,
            llm_base_url=os.environ.get("PAPERSEEK_LLM_BASE_URL", default_base).strip(),
            llm_model=os.environ.get("PAPERSEEK_LLM_MODEL", "gpt-4o-mini").strip(),
            llm_api_key=os.environ.get("PAPERSEEK_LLM_API_KEY", "").strip(),
            openalex_api_key=os.environ.get("PAPERSEEK_OPENALEX_API_KEY", "").strip(),
            semantic_scholar_api_key=os.environ.get("PAPERSEEK_SEMANTIC_SCHOLAR_API_KEY", "").strip(),
            pubmed_api_key=os.environ.get("PAPERSEEK_PUBMED_API_KEY", "").strip(),
            wos_api_key=os.environ.get("PAPERSEEK_WOS_API_KEY", "").strip(),
            google_scholar_api_key=os.environ.get("PAPERSEEK_GOOGLE_SCHOLAR_API_KEY", "").strip(),
            contact_email=os.environ.get("PAPERSEEK_CONTACT_EMAIL", "").strip(),
        )

    def llm_route(self, requested: dict | None = None) -> dict[str, str]:
        requested = requested or {}
        return {
            "provider": str(requested.get("provider") or "custom"),
            "api_type": str(requested.get("api_type") or self.llm_api_type),
            "base_url": str(requested.get("base_url") or self.llm_base_url).rstrip("/"),
            "model": str(requested.get("model") or self.llm_model),
        }
