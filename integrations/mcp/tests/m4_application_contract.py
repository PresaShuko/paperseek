from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


MCP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MCP_ROOT / "src"))


class M4MCPApplicationContract(unittest.TestCase):
    def test_start_status_events_and_cancel_are_one_durable_run(self):
        from paperseek_mcp.application import CommunityMCPApplication

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "paperseek.db"
            application = CommunityMCPApplication(database)
            field_id = application.get_source_capabilities(source="openalex")["capabilities"]["filter"]["options"][0]["id"]

            started = application.start_search(
                question="Durable literature search",
                source="openalex",
                search_budget="medium",
                field_ids=[field_id, field_id],
                field_hint="",
                citation_enabled=True,
                idempotency_key="mcp-contract-start",
            )
            run_id = started["run_id"]

            self.assertEqual(started["status"], "queued")
            self.assertEqual(application.get_search_status(run_id=run_id)["id"], run_id)
            first_events = application.get_search_events(
                run_id=run_id,
                after_sequence=0,
                limit=20,
            )
            self.assertEqual(first_events["next_sequence"], 1)
            self.assertEqual(first_events["events"][0]["event_type"], "run.created")
            self.assertEqual(
                application.get_search_events(
                    run_id=run_id,
                    after_sequence=1,
                    limit=20,
                ),
                {"events": [], "next_sequence": 1},
            )
            self.assertEqual(application.cancel_search(run_id=run_id)["status"], "cancelled")
            self.assertEqual(application.get_search_status(run_id=run_id)["status"], "cancelled")

    def test_source_capabilities_and_input_validation_use_community_contract(self):
        from paperseek_mcp.application import CommunityMCPApplication

        with tempfile.TemporaryDirectory() as directory:
            application = CommunityMCPApplication(Path(directory) / "paperseek.db")

            sources = application.list_sources()["sources"]
            self.assertEqual(len(sources), 8)
            self.assertEqual(application.get_source_capabilities(source="openalex"), sources[0])
            with self.assertRaisesRegex(ValueError, "not supported"):
                application.get_source_capabilities(source="missing")
            with self.assertRaisesRegex(ValueError, "Citation expansion is not supported"):
                application.start_search(
                    question="Invalid capability",
                    source="arxiv",
                    search_budget="fast",
                    field_ids=[],
                    field_hint="",
                    citation_enabled=True,
                    idempotency_key="mcp-contract-capability",
                )

    def test_pagination_arguments_are_validated_before_storage_access(self):
        from paperseek_mcp.application import CommunityMCPApplication

        with tempfile.TemporaryDirectory() as directory:
            application = CommunityMCPApplication(Path(directory) / "paperseek.db")

            with self.assertRaisesRegex(ValueError, "event cursor"):
                application.get_search_events(
                    run_id="missing",
                    after_sequence=-1,
                    limit=20,
                )
            with self.assertRaisesRegex(ValueError, "Event limit"):
                application.get_search_events(
                    run_id="missing",
                    after_sequence=0,
                    limit=201,
                )


if __name__ == "__main__":
    unittest.main()
