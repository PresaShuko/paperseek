from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient


MCP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MCP_ROOT / "src"))


def _submission_digest(database: Path) -> str:
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute(
            "SELECT request_digest FROM run_submissions ORDER BY created_at LIMIT 1"
        ).fetchone()
    assert row is not None
    return str(row[0])


class M4SubmissionEquivalenceContract(unittest.TestCase):
    def test_api_and_mcp_share_frozen_omitted_defaults(self):
        from paperseek_community.api import create_app
        from paperseek_mcp.application import CommunityMCPApplication

        with tempfile.TemporaryDirectory() as directory:
            api_database = Path(directory) / "api-defaults.db"
            mcp_database = Path(directory) / "mcp-defaults.db"
            api = create_app(api_database, execution_resolver=lambda *_args: None)
            client = TestClient(api)
            response = client.post(
                "/api/v1/runs",
                headers={"Idempotency-Key": "frozen-defaults"},
                json={"question": "  Frozen omission semantics  "},
            )
            self.assertEqual(response.status_code, 202, response.text)
            client.close()

            mcp = CommunityMCPApplication(mcp_database)
            started = mcp.start_search(
                question="  Frozen omission semantics  ",
                idempotency_key="frozen-defaults",
            )
            api_detail = response.json()
            mcp_detail = mcp.get_search_status(run_id=started["run_id"])

            self.assertEqual(api_detail["question"], "Frozen omission semantics")
            self.assertEqual(api_detail["source"], "openalex")
            self.assertEqual(api_detail["config_snapshot"], mcp_detail["config_snapshot"])
            self.assertEqual(api_detail["config_snapshot"]["search_budget"], "fast")
            self.assertTrue(api_detail["config_snapshot"]["citation_enabled"])
            self.assertFalse(api_detail["config_snapshot"]["fetch_abstracts"])
            self.assertEqual(
                api_detail["config_snapshot"]["llm"],
                {
                    "provider": "openai",
                    "api_type": "openai_responses",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-5.4-mini",
                },
            )
            self.assertEqual(
                _submission_digest(api_database),
                _submission_digest(mcp_database),
            )

    def test_api_and_mcp_share_one_normalized_snapshot_and_digest(self):
        from paperseek_community.api import create_app
        from paperseek_app.source_catalog import SOURCE_BY_ID
        from paperseek_app.submission import prepare_run_submission
        from paperseek_mcp.application import CommunityMCPApplication

        self.assertTrue(callable(prepare_run_submission))
        field_id = SOURCE_BY_ID["openalex"].descriptor()["capabilities"]["filter"]["options"][0]["id"]
        values = {
            "question": "  Durable submission equivalence  ",
            "source": "openalex",
            "search_budget": "high",
            "field_ids": [field_id, field_id],
            "field_hint": "",
            "citation_enabled": True,
            "fetch_abstracts": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            api_database = Path(directory) / "api.db"
            mcp_database = Path(directory) / "mcp.db"
            api = create_app(api_database, execution_resolver=lambda *_args: None)
            client = TestClient(api)
            response = client.post(
                "/api/v1/runs",
                headers={"Idempotency-Key": "equivalent-submission"},
                json=values,
            )
            client.close()
            self.assertEqual(response.status_code, 202, response.text)

            mcp = CommunityMCPApplication(mcp_database)
            started = mcp.start_search(
                **values,
                idempotency_key="equivalent-submission",
            )
            mcp_detail = mcp.get_search_status(run_id=started["run_id"])
            api_detail = response.json()

            self.assertEqual(mcp_detail["question"], api_detail["question"])
            self.assertEqual(mcp_detail["source"], api_detail["source"])
            self.assertEqual(mcp_detail["config_snapshot"], api_detail["config_snapshot"])
            self.assertTrue(mcp_detail["config_snapshot"]["fetch_abstracts"])
            self.assertEqual(
                _submission_digest(mcp_database),
                _submission_digest(api_database),
            )

    def test_api_and_mcp_share_semantic_validation_codes(self):
        from paperseek_community.api import create_app
        from paperseek_app.submission import SubmissionValidationError
        from paperseek_mcp.application import CommunityMCPApplication

        invalid_cases = [
            ({"question": "x", "source": "missing"}, "unsupported_source"),
            (
                {"question": "x", "source": "openalex", "search_budget": "unlimited"},
                "unsupported_search_budget",
            ),
            (
                {"question": "x", "source": "arxiv", "citation_enabled": True},
                "unsupported_source_capability",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            api = create_app(Path(directory) / "api.db", execution_resolver=lambda *_args: None)
            mcp = CommunityMCPApplication(Path(directory) / "mcp.db")
            client = TestClient(api)

            for index, (values, expected_code) in enumerate(invalid_cases):
                response = client.post(
                    "/api/v1/runs",
                    headers={"Idempotency-Key": f"invalid-{index}"},
                    json=values,
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], expected_code)
                with self.assertRaises(SubmissionValidationError) as caught:
                    mcp.start_search(
                        question=values["question"],
                        source=values["source"],
                        search_budget=values.get("search_budget", "fast"),
                        field_ids=values.get("field_ids", []),
                        field_hint=values.get("field_hint", ""),
                        citation_enabled=values.get("citation_enabled"),
                        idempotency_key=f"invalid-{index}",
                    )
                self.assertEqual(caught.exception.code, expected_code)
            client.close()


if __name__ == "__main__":
    unittest.main()
