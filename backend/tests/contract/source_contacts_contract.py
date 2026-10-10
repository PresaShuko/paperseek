"""User-selected source contact metadata reaches the actual source adapters."""

import asyncio
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx

from paperseek_app.submission import RunSubmission, prepare_run_submission
from paperseek_community.composition import CommunityExecutionResolver
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_core.execution import NEVER_CANCELLED
from paperseek_core.sources.contracts import SourceSearchRequest


CONTACTS = {"openalex_email": "openalex@example.test", "crossref_email": "crossref@example.test",
            "pubmed_email": "pubmed@example.test", "pubmed_tool": "research-team"}


class SourceContactsContract(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"PAPERSEEK_CONTACT_EMAIL": "deployment@example.test"}, clear=True):
            self.settings = CommunityDeploymentSettings.from_environment()

    def test_contacts_are_normalized_in_snapshot_and_digest(self):
        default = prepare_run_submission(RunSubmission(question="source metadata"), self.settings)
        selected = prepare_run_submission(RunSubmission(question="source metadata",
            source_contacts={key: f" {value} " for key, value in CONTACTS.items()}), self.settings)
        self.assertEqual(selected.config_snapshot["source_contacts"], CONTACTS)
        self.assertNotEqual(default.request_digest, selected.request_digest)
        self.assertEqual(default.config_snapshot["source_contacts"],
            {"openalex_email": "", "crossref_email": "", "pubmed_email": "", "pubmed_tool": "paperseek"})

    def test_composition_sends_separate_source_contacts_and_keeps_crossref_independent(self):
        requests = []

        async def handle(request):
            requests.append(request)
            if request.url.host == "api.openalex.org":
                return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
            if request.url.host == "api.crossref.org":
                return httpx.Response(200, json={"message": {"items": [], "total-results": 0}})
            return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})

        real_client = httpx.AsyncClient
        def client(*args, **kwargs):
            return real_client(*args, **kwargs, transport=httpx.MockTransport(handle))

        async def exercise():
            for source in ("openalex", "crossref", "pubmed"):
                prepared = prepare_run_submission(RunSubmission(question="source metadata", source=source,
                    source_contacts=CONTACTS), self.settings)
                run = SimpleNamespace(id=source, source=source, question=prepared.question,
                                      config_snapshot=prepared.config_snapshot,
                                      deadline_at=datetime.now(timezone.utc) + timedelta(minutes=10))
                with patch("paperseek_community.model_transport.httpx.AsyncClient", client):
                    execution = CommunityExecutionResolver(self.settings, Mock(resolve=Mock(return_value={})))(run, NEVER_CANCELLED)
                try:
                    await execution.source.search(SourceSearchRequest(query="governance", limit=1, lane="relevance"))
                finally:
                    await execution.close()

        asyncio.run(exercise())
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[0].url.params["mailto"], CONTACTS["openalex_email"])
        self.assertEqual(requests[1].url.params["mailto"], CONTACTS["crossref_email"])
        self.assertEqual(requests[2].url.params["email"], CONTACTS["pubmed_email"])
        self.assertEqual(requests[2].url.params["tool"], CONTACTS["pubmed_tool"])


if __name__ == "__main__":
    unittest.main()
