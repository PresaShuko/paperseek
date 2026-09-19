from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import unittest


MCP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MCP_ROOT / "src"))


EXPECTED_TOOLS = [
    "start_search",
    "get_search_status",
    "get_search_events",
    "get_search_results",
    "get_citation_graph",
    "cancel_search",
    "export_results",
    "list_sources",
    "get_source_capabilities",
]


class RecordingApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def _record(self, name: str, values: dict) -> dict:
        self.calls.append((name, values))
        return {"operation": name, **values}

    def start_search(self, **values):
        self._record("start_search", values)
        return {"run_id": "00000000-0000-0000-0000-000000000001", "status": "queued"}

    def get_search_status(self, **values):
        return self._record("get_search_status", values)

    def get_search_events(self, **values):
        return self._record("get_search_events", values)

    def get_search_results(self, **values):
        return self._record("get_search_results", values)

    def get_citation_graph(self, **values):
        return self._record("get_citation_graph", values)

    def cancel_search(self, **values):
        return self._record("cancel_search", values)

    def export_results(self, **values):
        return self._record("export_results", values)

    def list_sources(self):
        return {"sources": [{"id": "openalex"}]}

    def get_source_capabilities(self, **values):
        return self._record("get_source_capabilities", values)


def _payload(result) -> dict:
    structured = getattr(result, "structured_content", None)
    if structured:
        return dict(structured)
    for item in result.content:
        text = getattr(item, "text", "")
        if text:
            return json.loads(text)
    raise AssertionError("Tool result did not contain a structured object.")


class M4MCPToolRegistryContract(unittest.TestCase):
    def test_one_registry_exposes_the_exact_durable_run_tool_set(self):
        from paperseek_mcp.server import create_server

        server = create_server(RecordingApplication())
        tools = asyncio.run(server.list_tools())

        self.assertEqual([tool.name for tool in tools], EXPECTED_TOOLS)
        self.assertEqual(server.name, "paperseek")
        self.assertEqual(server.version, "0.3.0")
        abstract_option = tools[0].input_schema["properties"]["fetch_abstracts"]
        self.assertEqual(abstract_option["type"], "boolean")
        self.assertFalse(abstract_option["default"])

    def test_start_returns_run_id_without_waiting_for_completion(self):
        from paperseek_mcp.server import create_server

        application = RecordingApplication()
        server = create_server(application)
        result = asyncio.run(
            server.call_tool(
                "start_search",
                {"question": "Durable literature search", "source": "openalex", "fetch_abstracts": True},
            )
        )

        self.assertEqual(
            _payload(result),
            {"run_id": "00000000-0000-0000-0000-000000000001", "status": "queued"},
        )
        self.assertTrue(application.calls[0][1]["fetch_abstracts"])

    def test_cursor_cancel_export_and_capability_arguments_reach_one_application(self):
        from paperseek_mcp.server import create_server

        application = RecordingApplication()
        server = create_server(application)
        calls = [
            ("get_search_status", {"run_id": "run-1"}),
            ("get_search_events", {"run_id": "run-1", "after_sequence": 7, "limit": 20}),
            ("get_search_results", {"run_id": "run-1", "cursor": "next", "page_size": 10}),
            ("get_citation_graph", {"run_id": "run-1"}),
            ("cancel_search", {"run_id": "run-1"}),
            ("export_results", {"run_id": "run-1", "format": "csv"}),
            ("get_source_capabilities", {"source": "openalex"}),
        ]

        for name, arguments in calls:
            asyncio.run(server.call_tool(name, arguments))

        self.assertEqual(application.calls, calls)


if __name__ == "__main__":
    unittest.main()
