from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from paperseek_core.domain.models import PaperRecord
from paperseek_core.retrieval import RetrievalLane
from paperseek_core.sources.contracts import ProviderError
from paperseek_core.sources.openalex import OpenAlexProvider
from tests.golden_search_fixture import GoldenOpenAlexProvider
from tests.test_source_provider_contract_fixtures import FixtureResponse, load_json


CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "tests"
    / "contract"
    / "fixtures"
    / "m2_source_model_contract.json"
)


class M2SourceModelCharacterizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_provider_fixture_maps_to_the_frozen_canonical_record(self) -> None:
        response = FixtureResponse(
            payload=load_json("openalex.json"),
            url=OpenAlexProvider.BASE_URL,
        )
        with patch(
            "paperseek_core.sources.http.requests.get",
            return_value=response,
        ):
            result = OpenAlexProvider(
                api_key="fixture-openalex-key",
                email="fixture@example.org",
            ).search(
                "AI governance",
                limit=25,
                page=3,
                field_ids=("17", "14"),
                lane=RetrievalLane.IMPACT,
            )

        self.assertEqual(asdict(result.metadata), self.contract["metadata"])
        self.assertEqual(asdict(result.hits[0]), self.contract["provider_record"])

    def test_golden_search_mapper_keeps_the_same_nested_record(self) -> None:
        result = GoldenOpenAlexProvider().search(
            "transparent AI accountability",
            limit=1,
        )

        self.assertEqual(asdict(result.hits[0]), self.contract["golden_record"])

    def test_empty_defaults_and_provider_error_fields_are_frozen(self) -> None:
        self.assertEqual(asdict(PaperRecord(uid="empty")), self.contract["empty_record"])
        expected = self.contract["error"]
        error = ProviderError(
            expected["source"],
            expected["message"],
            status=expected["status"],
            body=expected["body"],
            query=expected["query"],
        )
        self.assertEqual(str(error), expected["message"])
        self.assertEqual(
            {
                "source": error.source,
                "status": error.status,
                "body": error.body,
                "query": error.query,
            },
            {
                key: expected[key]
                for key in ("source", "status", "body", "query")
            },
        )


if __name__ == "__main__":
    unittest.main()
