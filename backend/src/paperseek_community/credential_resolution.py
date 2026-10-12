"""Resolve model credentials identically for diagnostics and execution."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from paperseek_app.configuration import resolve_llm_route
from paperseek_community.settings import CommunityDeploymentSettings


def _endpoint(route: Mapping) -> tuple | None:
    try:
        url = urlsplit(str(route.get("base_url") or ""))
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            return None
        return (
            url.scheme,
            url.hostname,
            url.port or (443 if url.scheme == "https" else 80),
            url.path.rstrip("/"),
        )
    except ValueError:
        return None


def _can_share(left: Mapping, right: Mapping) -> bool:
    return bool(
        left.get("provider")
        and left.get("provider") == right.get("provider")
        and _endpoint(left) is not None
        and _endpoint(left) == _endpoint(right)
    )


def resolve_model_credentials(
    settings: CommunityDeploymentSettings,
    llm_route: Mapping,
    retrieval: Mapping,
    credentials: Mapping,
) -> dict[str, str]:
    def explicit(kind: str) -> str:
        return str((credentials.get(kind) or {}).get("api_key") or "").strip()

    deployment_route = resolve_llm_route(settings)
    llm_key = explicit("llm") or (
        settings.llm_api_key if _can_share(llm_route, deployment_route) else ""
    )
    result = {"llm": llm_key, "decision": explicit("decision")}
    for kind in ("embedding", "reranker"):
        result[kind] = explicit(kind) or (
            llm_key if _can_share(retrieval.get(kind) or {}, llm_route) else ""
        )
    return result
