from __future__ import annotations

import json
from pathlib import Path
import asyncio
import unittest

from paperseek_core.models import PaperRecord
from paperseek_core.ports import SourcePort
from paperseek_core.sources.contracts import (
    SourceCapabilities,
    SourceError,
    SourceSearchMetadata,
    SourceSearchRequest,
    SourceSearchResult,
)


CONTRACT = Path(__file__).parent / "fixtures" / "m2_source_model_contract.json"


class RecordingSource:
    name = "openalex"
    capabilities = SourceCapabilities(
        source="openalex",
        lanes=("relevance", "impact", "recent"),
        max_page_size=200,
    )

    def __init__(self, response: SourceSearchResult) -> None:
        self.response = response
        self.requests: list[SourceSearchRequest] = []

    async def search(self, request: SourceSearchRequest) -> SourceSearchResult:
        self.requests.append(request)
        return self.response


class M2SourceModelContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_m0_provider_and_golden_records_round_trip_without_field_loss(self) -> None:
        for key in ("provider_record", "golden_record", "empty_record"):
            with self.subTest(record=key):
                record = PaperRecord.model_validate(self.contract[key])
                self.assertEqual(record.model_dump(mode="json"), self.contract[key])

    def test_source_request_result_capabilities_and_error_are_explicit(self) -> None:
        request = SourceSearchRequest.model_validate(self.contract["request"])
        record = PaperRecord.model_validate(self.contract["provider_record"])
        result = SourceSearchResult(
            metadata=SourceSearchMetadata.model_validate(self.contract["metadata"]),
            hits=[record],
        )
        capabilities = SourceCapabilities(
            source="openalex",
            lanes=("relevance", "impact", "recent"),
            max_page_size=200,
        )
        expected_error = self.contract["error"]
        error = SourceError(
            expected_error["source"],
            expected_error["message"],
            status=expected_error["status"],
            body=expected_error["body"],
            query=expected_error["query"],
        )

        self.assertEqual(request.model_dump(mode="json"), self.contract["request"])
        self.assertEqual(result.metadata.model_dump(mode="json"), self.contract["metadata"])
        self.assertEqual(result.hits[0], record)
        self.assertTrue(capabilities.supports("impact"))
        self.assertFalse(capabilities.supports("semantic"))
        self.assertEqual(str(error), expected_error["message"])
        self.assertEqual(error.status, 429)

    def test_source_adapter_consumes_only_the_new_source_port_contract(self) -> None:
        record = PaperRecord.model_validate(self.contract["golden_record"])
        response = SourceSearchResult(
            metadata=SourceSearchMetadata(total=1, page=1, limit=50),
            hits=[record],
        )
        source = RecordingSource(response)
        request = SourceSearchRequest(query="transparent AI accountability")

        result = asyncio.run(source.search(request))

        self.assertIsInstance(source, SourcePort)
        self.assertEqual(source.requests, [request])
        self.assertEqual(result.hits, [record])
        self.assertEqual(result.hits[0].model_dump(mode="json"), self.contract["golden_record"])


if __name__ == "__main__":
    unittest.main()
