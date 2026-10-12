from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
import os
from pathlib import Path
from urllib.parse import urlparse

from paperseek_mcp.application import CommunityMCPApplication
from paperseek_mcp.transports import TransportConfig, create_runtime


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _comma_separated(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperseek-mcp")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse-legacy"),
        default="stdio",
    )
    parser.add_argument("--database")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--path", default="/mcp")
    parser.add_argument("--sse-path", default="/sse")
    parser.add_argument("--message-path", default="/messages/")
    return parser


def parse_config(
    arguments: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> TransportConfig:
    values = _parser().parse_args(arguments)
    env = os.environ if environment is None else environment
    database = values.database or env.get(
        "PAPERSEEK_DATABASE",
        str(Path.home() / ".paperseek" / "paperseek.db"),
    )
    for name, value in {
        "MCP path": values.path,
        "legacy SSE path": values.sse_path,
        "legacy message path": values.message_path,
    }.items():
        if not value.startswith("/"):
            raise ValueError(f"{name} must start with '/'.")
    if values.port < 1 or values.port > 65535:
        raise ValueError("The MCP port must be between 1 and 65535.")

    token = env.get("PAPERSEEK_MCP_SERVICE_TOKEN", "").strip()
    public_url = env.get("PAPERSEEK_MCP_PUBLIC_URL", "").strip().rstrip("/")
    allowed_hosts = _comma_separated(env.get("PAPERSEEK_MCP_ALLOWED_HOSTS", ""))
    allowed_origins = _comma_separated(env.get("PAPERSEEK_MCP_ALLOWED_ORIGINS", ""))
    if values.host not in LOOPBACK_HOSTS:
        if not token:
            raise ValueError("A service token is required for non-loopback MCP HTTP.")
        if not public_url or urlparse(public_url).scheme != "https":
            raise ValueError(
                "An HTTPS public URL is required; TLS must terminate at the reverse proxy."
            )
        if not allowed_hosts:
            raise ValueError("At least one allowed Host is required for non-loopback MCP HTTP.")
        if not allowed_origins:
            raise ValueError("At least one allowed Origin is required for non-loopback MCP HTTP.")
    elif values.transport != "stdio" and not allowed_hosts:
        allowed_hosts = ("127.0.0.1:*", "localhost:*", "[::1]:*")
        allowed_origins = (
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
        )

    return TransportConfig(
        transport=values.transport,
        database=database,
        host=values.host,
        port=values.port,
        path=values.path,
        sse_path=values.sse_path,
        message_path=values.message_path,
        service_token=token,
        public_url=public_url,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def main(arguments: Sequence[str] | None = None) -> None:
    config = parse_config(arguments)
    application = CommunityMCPApplication(config.database)
    runtime = create_runtime(config, application)
    asyncio.run(runtime.serve())


if __name__ == "__main__":
    main()
