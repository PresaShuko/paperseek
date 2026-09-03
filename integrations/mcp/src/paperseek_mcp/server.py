from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings

from paperseek_mcp.build_info import VERSION
from paperseek_mcp.tools import PaperSeekApplication, register_tools


def create_server(
    application: PaperSeekApplication,
    *,
    token_verifier: TokenVerifier | None = None,
    auth: AuthSettings | None = None,
) -> MCPServer:
    application_lifespan = getattr(application, "lifespan", None)
    lifespan = None
    if application_lifespan is not None:
        @asynccontextmanager
        async def lifespan(_server: MCPServer) -> AsyncIterator[None]:
            async with application_lifespan():
                yield

    server = MCPServer(
        name="paperseek",
        version=VERSION,
        description="Durable PaperSeek literature search integration.",
        lifespan=lifespan,
        token_verifier=token_verifier,
        auth=auth,
    )
    register_tools(server, application)
    return server


__all__ = ["create_server"]
