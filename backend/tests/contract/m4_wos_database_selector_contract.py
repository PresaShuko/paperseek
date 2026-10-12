from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from paperseek_app.services import RunSubmissionService
from paperseek_community.cli import _parser
from paperseek_community.composition import CommunityExecutionResolver
from paperseek_community.credentials import EncryptedRunCredentialStore
from paperseek_community.diagnostics import run_configuration_diagnostics
from paperseek_community.persistence import SQLiteRunUnitOfWork, migrate_database
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_app.submission import RunSubmission, prepare_run_submission
from paperseek_core.disciplines import WOS_CATEGORIES
from paperseek_core.execution import NEVER_CANCELLED
from paperseek_core.sources.contracts import SourceSearchRequest
from paperseek_core.sources.wos import WosSource


def _settings(*, wos_db: str = "WOS") -> CommunityDeploymentSettings:
    return CommunityDeploymentSettings(
        llm_api_type="openai_chat",
        llm_base_url="https://llm.example.invalid/v1",
        llm_model="controlled-model",
        llm_api_key="controlled-llm-key",
        openalex_api_key="",
        semantic_scholar_api_key="",
        pubmed_api_key="",
        wos_api_key="controlled-wos-key",
        google_scholar_api_key="",
        contact_email="paperseek-test@example.invalid",
        wos_db=wos_db,
    )


class M4WosDatabaseSelectorContract(unittest.TestCase):
    def test_submission_normalizes_database_separately_from_category_and_digest(self) -> None:
        category = WOS_CATEGORIES[0]
        default = prepare_run_submission(
            RunSubmission(
                question="default WoS database",
                source="wos",
                field_ids=[category],
            ),
            _settings(),
        )
        selected = prepare_run_submission(
            RunSubmission(
                question="default WoS database",
                source="wos",
                field_ids=[category],
                wos_db="  WOK  ",
            ),
            _settings(),
        )

        self.assertEqual(default.config_snapshot["wos_db"], "WOS")
        self.assertEqual(selected.config_snapshot["wos_db"], "WOK")
        self.assertEqual(selected.config_snapshot["field_ids"], [category])
        self.assertNotEqual(default.request_digest, selected.request_digest)

    def test_environment_and_cli_expose_the_new_configuration_name(self) -> None:
        with patch.dict(os.environ, {"PAPERSEEK_WOS_DB": "WOK"}, clear=True):
            self.assertEqual(CommunityDeploymentSettings.from_environment().wos_db, "WOK")

        search = _parser().parse_args(
            ["search", "WoS database contract", "--source", "wos", "--wos-db", "WOK"]
        )
        doctor = _parser().parse_args(
            ["doctor", "--source", "wos", "--wos-db", "WOK", "--json"]
        )
        self.assertEqual(search.wos_db, "WOK")
        self.assertEqual(doctor.wos_db, "WOK")

    def test_doctor_reports_the_effective_wos_database_without_network(self) -> None:
        report = run_configuration_diagnostics(
            {
                "source": "wos",
                "wos_db": "WOK",
                "credentials": {
                    "source": {"api_key": "controlled-wos-key"},
                    "llm": {"api_key": "controlled-llm-key"},
                },
            },
            _settings(),
        )
        database = next(
            check for check in report["checks"] if check["id"] == "source.wos_database"
        )

        self.assertEqual(database["status"], "pass")
        self.assertEqual(database["details"], {"database": "WOK"})
        self.assertNotIn("category", database["details"])


class M4WosDatabaseResolverContract(unittest.IsolatedAsyncioTestCase):
    async def test_resolver_sends_selected_database_and_keeps_category_in_query(self) -> None:
        requests: list[httpx.Request] = []

        async def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={"metadata": {"total": 0, "page": 1, "limit": 5}, "hits": []},
                request=request,
            )

        controlled = httpx.MockTransport(handle)
        real_client = httpx.AsyncClient

        class ControlledAsyncClient(real_client):
            def __init__(self, *args, **kwargs) -> None:
                kwargs["transport"] = controlled
                super().__init__(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "paperseek.db"
            migrate_database(database)
            uow = SQLiteRunUnitOfWork(database)
            service = RunSubmissionService(uow)
            credentials = EncryptedRunCredentialStore(database)
            category = WOS_CATEGORIES[0]
            prepared = prepare_run_submission(
                RunSubmission(
                    question="WoS database composition",
                    source="wos",
                    field_ids=[category],
                    wos_db="WOK",
                ),
                _settings(),
            )
            run = service.submit_run(
                subject="wos-database-contract",
                idempotency_key=str(uuid4()),
                request_digest=prepared.request_digest,
                question=prepared.question,
                source=prepared.source,
                config_snapshot=prepared.config_snapshot,
            )
            resolver = CommunityExecutionResolver(_settings(), credentials)
            try:
                with patch(
                    "paperseek_community.model_transport.httpx.AsyncClient",
                    ControlledAsyncClient,
                ):
                    execution = resolver(run, NEVER_CANCELLED)
                    self.assertIsInstance(execution.source, WosSource)
                    query = f'TS=(governance) AND WC=("{category}")'
                    await execution.source.search(
                        SourceSearchRequest(query=query, limit=5, lane="relevance")
                    )
                    await execution.close()
            finally:
                uow.close()

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.params["db"], "WOK")
        self.assertEqual(requests[0].url.params["q"], query)


if __name__ == "__main__":
    unittest.main()
