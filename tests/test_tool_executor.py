import unittest

from paperseek_core.frontier import FrontierScheduler
from paperseek_core.sources.providers import PaperRecord, ProviderSearchResult, SearchMetadata
from paperseek_core.tool_executor import ToolExecution, ToolExecutor


class _Cancel(RuntimeError):
    pass


class ToolExecutorTest(unittest.TestCase):
    def setUp(self):
        self.action = FrontierScheduler.make_action("search", source="openalex", query="AI governance")

    def test_provider_result_is_normalized(self):
        result = ProviderSearchResult(
            metadata=SearchMetadata(total=27, page=1, limit=10),
            hits=[PaperRecord(uid="W1", title="Paper")],
        )
        execution = ToolExecutor({"search": lambda action: result}).execute(self.action)

        self.assertEqual(execution.status, "done")
        self.assertEqual(execution.total, 27)
        self.assertEqual([record.uid for record in execution.records], ["W1"])

    def test_mapping_metadata_is_preserved(self):
        execution = ToolExecutor(
            {"search": lambda action: {"records": [], "total": 3, "request_count": 2}}
        ).execute(self.action)

        self.assertEqual(execution.total, 3)
        self.assertEqual(execution.metadata, {"request_count": 2})

    def test_unsupported_action_is_skipped(self):
        action = FrontierScheduler.make_action("read", candidate_id="W1")
        execution = ToolExecutor({}).execute(action)

        self.assertEqual(execution.status, "skipped")
        self.assertEqual(execution.error, "unsupported_action:read")

    def test_handler_failure_is_isolated(self):
        def fail(action):
            raise ValueError("bad source response")

        execution = ToolExecutor({"search": fail}).execute(self.action)

        self.assertEqual(execution.status, "failed")
        self.assertIn("ValueError: bad source response", execution.error)

    def test_cancellation_is_not_swallowed(self):
        def cancel(action):
            raise _Cancel("stop")

        with self.assertRaises(_Cancel):
            ToolExecutor({"search": cancel}, passthrough_exceptions=(_Cancel,)).execute(self.action)

    def test_existing_tool_execution_is_accepted(self):
        original = ToolExecution(action=self.action, status="done", records=[], total=9)
        execution = ToolExecutor({"search": lambda action: original}).execute(self.action)

        self.assertIs(execution, original)
        self.assertEqual(execution.total, 9)


if __name__ == "__main__":
    unittest.main()
