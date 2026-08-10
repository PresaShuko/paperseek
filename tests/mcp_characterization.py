from __future__ import annotations

import importlib.metadata
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from tests.helpers import CONFIG_ENV_KEYS, ROOT


EXPECTED_MCP_VERSION = "2.0.0"
CLIENT_NAME = "paperseek-m0-characterization"
CLIENT_VERSION = "0.3.0"


def mcp_available() -> bool:
    try:
        importlib.metadata.version("mcp")
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def _stdio_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in CONFIG_ENV_KEYS:
        environment.pop(key, None)
    environment.update(
        {
            "DATA_SOURCE": "arxiv",
            "LLM_PROVIDER": "ollama",
            "LLM_API_TYPE": "openai_chat",
            "LLM_MODEL": "fixture-model",
            "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "LLM_API_KEY": "",
            "PAPERSEEK_DOTENV_DISABLED": "true",
            "PAPERSEEK_CONFIG_DIR": str(ROOT / "tests/fixtures/mcp/no-user-config"),
            "PAPERSEEK_HISTORY_ENABLED": "false",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(ROOT),
            "PYTHONUTF8": "1",
        }
    )
    return environment


def _model_payload(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


def _decoded_json_text(tool_result: Any) -> dict[str, Any]:
    for item in getattr(tool_result, "content", None) or []:
        text = getattr(item, "text", None)
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    raise AssertionError("MCP tool response did not contain a JSON object text block")


async def capture_stdio_characterization() -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.types import Implementation

    sdk_version = importlib.metadata.version("mcp")
    console_name = "paperseek-mcp.exe" if os.name == "nt" else "paperseek-mcp"
    console_path = Path(sys.executable).with_name(console_name)
    if not console_path.is_file():
        raise AssertionError(f"installed PaperSeek MCP console entry was not found: {console_path}")
    parameters = StdioServerParameters(
        command=str(console_path),
        args=[],
        cwd=Path(ROOT),
        env=_stdio_environment(),
        encoding="utf-8",
        encoding_error_handler="strict",
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        async with stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                client_info=Implementation(name=CLIENT_NAME, version=CLIENT_VERSION),
            ) as session:
                initialize_result = await session.initialize()
                tools_result = await session.list_tools()
                call_result = await session.call_tool("list_sources")
        stderr.seek(0)
        stderr_text = stderr.read()
    return {
        "sdk": {
            "distribution": "mcp",
            "version": sdk_version,
        },
        "client": {
            "name": CLIENT_NAME,
            "version": CLIENT_VERSION,
        },
        "server_command": {
            "command": "paperseek-mcp",
            "args": [],
            "transport": "stdio",
        },
        "initialize": _model_payload(initialize_result),
        "tools": [_model_payload(tool) for tool in tools_result.tools],
        "call": {
            "name": "list_sources",
            "arguments": {},
            "result": _model_payload(call_result),
            "decoded_json": _decoded_json_text(call_result),
        },
        "transport_observation": {
            "stderr_empty": not bool(stderr_text.strip()),
            "stderr_line_count": len(stderr_text.splitlines()),
            "stderr_contains_jsonrpc": '"jsonrpc"' in stderr_text,
        },
    }
