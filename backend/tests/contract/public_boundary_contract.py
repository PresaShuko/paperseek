"""Public removal and generated boundary contracts, using no upstream services."""
import io
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from paperseek_app.configuration import RunConfigurationSnapshot
from paperseek_community.api import create_app
from paperseek_community.cli import _parser
from paperseek_core.models import CoreProgressEvent


class PublicBoundaryContract(unittest.TestCase):
    def test_removed_abstract_option_is_rejected_and_absent_from_openapi_and_cli(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Path(directory) / "test.db", accept_submissions_without_worker=True)) as client:
            schema = client.get("/openapi.json").json()
            for name in ("RunSubmission", "DiagnosticSubmission"):
                self.assertNotIn("fetch_abstracts", schema["components"]["schemas"][name]["properties"])
            for endpoint, values in (("runs", {"question": "Native abstracts"}), ("diagnostics", {})):
                response = client.post(f"/api/v1/{endpoint}", json={**values, "fetch_abstracts": True}, headers={"Idempotency-Key": "removed"})
                self.assertEqual(response.status_code, 422)
            self.assertIn("ErrorResponse", schema["components"]["schemas"])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _parser().parse_args(["search", "Native abstracts", "--fetch-abstracts"])

    def test_crossref_metadata_enrichment_is_removed_from_submission_and_cli(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(Path(directory) / "test.db", accept_submissions_without_worker=True)) as client:
            schema = client.get("/openapi.json").json()
            self.assertNotIn("crossref_metadata_enrichment", schema["components"]["schemas"]["RetrievalRouteInput"]["properties"])
            for endpoint in ("runs", "diagnostics"):
                response = client.post(f"/api/v1/{endpoint}", json={"question": "Native metadata", "retrieval": {"crossref_metadata_enrichment": True}})
                self.assertEqual(response.status_code, 422)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _parser().parse_args(["search", "Native metadata", "--retrieval-crossref-enrichment"])

    def test_recorded_config_keeps_missing_fields_missing_and_validates_known_values(self):
        adapter = TypeAdapter(RunConfigurationSnapshot)
        old = {"source": "openalex", "legacy_id": "old-1"}
        self.assertEqual(adapter.validate_python(old), old)
        with self.assertRaises(ValidationError):
            adapter.validate_python({"retrieval": {"embedding": {"model": 42}}})
        snapshot = {"retrieval": {"embedding": {"model": "recorded-model"}}}
        self.assertEqual(adapter.validate_python(snapshot), snapshot)

    def test_event_metrics_are_checked_but_audit_extensions_survive(self):
        event = CoreProgressEvent(event_type="ranking.completed", stage="ranking", payload={"candidate_count": 3, "audit_extension": [1, 2]})
        self.assertEqual(event.payload["audit_extension"], [1, 2])
        with self.assertRaises(ValidationError):
            CoreProgressEvent(event_type="ranking.completed", stage="ranking", payload={"candidate_count": "three"})


if __name__ == "__main__":
    unittest.main()
