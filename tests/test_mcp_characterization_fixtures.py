import asyncio
import importlib.metadata
import unittest

from tests.helpers import read_json
from tests.mcp_characterization import (
    EXPECTED_MCP_VERSION,
    capture_stdio_characterization,
    mcp_available,
)


FIXTURE_PATH = "tests/fixtures/mcp/stdio_characterization.json"
EXPECTED_TOOLS = [
    "search_papers",
    "check_config",
    "smoke_test",
    "list_sources",
    "list_history",
    "get_history_run",
]


@unittest.skipUnless(mcp_available(), "mcp package is not installed")
class McpStdioCharacterizationFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = asyncio.run(asyncio.wait_for(capture_stdio_characterization(), timeout=30))
        cls.second = asyncio.run(asyncio.wait_for(capture_stdio_characterization(), timeout=30))
        cls.expected = read_json(FIXTURE_PATH)

    def test_exact_sdk_version_and_two_sessions_are_stable(self):
        self.assertEqual(importlib.metadata.version("mcp"), EXPECTED_MCP_VERSION)
        self.assertEqual(self.first, self.second)

    def test_initialize_tools_and_call_match_fixture(self):
        self.assertEqual(self.first, self.expected)

    def test_current_initialize_contract_is_fixed(self):
        initialize = self.first["initialize"]
        self.assertEqual(initialize["protocolVersion"], "2025-11-25")
        self.assertEqual(initialize["serverInfo"], {"name": "paperseek", "version": ""})

    def test_current_tool_order_and_names_are_fixed(self):
        self.assertEqual([tool["name"] for tool in self.first["tools"]], EXPECTED_TOOLS)

    def test_real_list_sources_call_returns_all_current_sources(self):
        sources = self.first["call"]["decoded_json"]["sources"]
        self.assertEqual(
            [source["id"] for source in sources],
            ["openalex", "arxiv", "semanticscholar", "pubmed", "googlescholar", "paperhub", "crossref", "wos"],
        )

    def test_stdio_protocol_is_not_written_to_stderr(self):
        observation = self.first["transport_observation"]
        self.assertTrue(observation["stderr_empty"])
        self.assertEqual(observation["stderr_line_count"], 0)
        self.assertFalse(observation["stderr_contains_jsonrpc"])


if __name__ == "__main__":
    unittest.main()
