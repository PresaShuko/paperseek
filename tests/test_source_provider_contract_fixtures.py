import json
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import requests

from paperseek_core.client import ApiException
from paperseek_core.domain.models import PaperRecord
from paperseek_core.retrieval import RetrievalLane
from paperseek_core.sources.arxiv import ArxivProvider
from paperseek_core.sources.contracts import ProviderError
from paperseek_core.sources.crossref import CrossrefProvider
from paperseek_core.sources.google_scholar import GoogleScholarSerperProvider
from paperseek_core.sources.openalex import OpenAlexProvider
from paperseek_core.sources.paperhub import PaperHubProvider
from paperseek_core.sources.pubmed import PubMedProvider
from paperseek_core.sources.semantic_scholar import SemanticScholarProvider
from paperseek_core.sources.wos import WosProvider, result_from_json


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "providers"
NO_JSON = object()


def load_json(name):
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def load_text(name):
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


class FixtureResponse:
    def __init__(
        self,
        *,
        payload=NO_JSON,
        text=None,
        status_code=200,
        url="https://fixture.invalid",
        reason="OK",
        headers=None,
    ):
        self._payload = payload
        self.text = (
            text
            if text is not None
            else (json.dumps(payload) if payload is not NO_JSON else "fixture response")
        )
        self.status_code = status_code
        self.url = url
        self.reason = reason
        self.headers = dict(headers or {})
        self.content = self.text.encode("utf-8")

    def json(self):
        if self._payload is NO_JSON:
            raise ValueError("fixture has no JSON")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def close(self):
        return None


def captured_get(mock_call):
    args, kwargs = mock_call
    return {
        "method": "GET",
        "url": args[0],
        "params": kwargs.get("params"),
        "headers": kwargs.get("headers"),
        "timeout": kwargs.get("timeout"),
    }


def captured_post(mock_call):
    args, kwargs = mock_call
    return {
        "method": "POST",
        "url": args[0],
        "json": kwargs.get("json"),
        "headers": kwargs.get("headers"),
        "timeout": kwargs.get("timeout"),
    }


def captured_session_request(session_call):
    method, url, kwargs = session_call
    return {
        "method": method,
        "url": url,
        "params": kwargs.get("params"),
        "headers": kwargs.get("headers"),
        "timeout": kwargs.get("timeout"),
    }


class ProviderFixtureContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = load_json("request_contracts.json")

    def setUp(self):
        PaperHubProvider.reset_cache()
        ArxivProvider._last_request_at = 0.0
        SemanticScholarProvider._last_request_at = 0.0

    def test_openalex_request_and_mapping_fixture(self):
        response = FixtureResponse(
            payload=load_json("openalex.json"),
            url=OpenAlexProvider.BASE_URL,
        )
        with patch("paperseek_core.sources.http.requests.get", return_value=response) as request:
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

        self.assertEqual(captured_get(request.call_args), self.contracts["openalex"])
        self.assertEqual(result.metadata.total, 1)
        self.assertEqual(result.metadata.page, 3)
        self.assertEqual(result.metadata.limit, 25)
        record = result.hits[0]
        self.assertIsInstance(record, PaperRecord)
        self.assertEqual(record.uid, "https://openalex.org/W123")
        self.assertEqual(record.identifiers.doi, "10.1234/openalex.fixture")
        self.assertEqual(record.identifiers.pmid, "123")
        self.assertEqual(record.names.authors[0].display_name, "Ada Lovelace")
        self.assertEqual(record.source.source_title, "Journal of AI Governance")
        self.assertEqual(record.abstract, "Governance evidence")
        self.assertEqual(record.citations[0].count, 12)

    def test_crossref_request_and_mapping_fixture(self):
        response = FixtureResponse(
            payload=load_json("crossref.json"),
            url=CrossrefProvider.BASE_URL,
        )
        with patch("paperseek_core.sources.http.requests.get", return_value=response) as request:
            result = CrossrefProvider(email="fixture@example.org").search(
                "AI governance",
                limit=25,
                page=3,
                lane=RetrievalLane.IMPACT,
            )

        self.assertEqual(captured_get(request.call_args), self.contracts["crossref"])
        record = result.hits[0]
        self.assertIsInstance(record, PaperRecord)
        self.assertEqual(record.uid, "DOI:10.1234/crossref.fixture")
        self.assertEqual(record.names.authors[0].display_name, "Ada Lovelace")
        self.assertEqual(record.source.source_title, "Journal of AI Governance")
        self.assertEqual(record.source.publish_year, 2023)
        self.assertEqual(record.abstract, "Crossref abstract.")
        self.assertEqual(record.identifiers.issn, "1234-5678")
        self.assertEqual(record.citations[0].count, 9)

    def test_arxiv_request_and_mapping_fixture(self):
        response = FixtureResponse(
            text=load_text("arxiv.xml"),
            url=ArxivProvider.BASE_URL,
        )
        with (
            patch.object(ArxivProvider, "_throttle"),
            patch("paperseek_core.sources.http.requests.get", return_value=response) as request,
        ):
            result = ArxivProvider().search(
                "graph retrieval",
                limit=1,
                page=2,
                lane=RetrievalLane.RECENT,
            )

        self.assertEqual(captured_get(request.call_args), self.contracts["arxiv"])
        record = result.hits[0]
        self.assertIsInstance(record, PaperRecord)
        self.assertEqual(result.metadata.total, 1)
        self.assertEqual(result.metadata.page, 2)
        self.assertEqual(record.uid, "arxiv:2401.00001v1")
        self.assertEqual(record.identifiers.doi, "10.1234/arxiv.fixture")
        self.assertEqual(record.keywords.author_keywords, ["cs.IR"])
        self.assertEqual(record.abstract, "Graph retrieval abstract.")

    def test_semantic_scholar_request_and_mapping_fixture(self):
        response = FixtureResponse(
            payload=load_json("semantic_scholar.json"),
            url=SemanticScholarProvider.BASE_URL,
        )
        with (
            patch.object(SemanticScholarProvider, "_throttle"),
            patch("paperseek_core.sources.http.requests.get", return_value=response) as request,
        ):
            result = SemanticScholarProvider(api_key="fixture-semantic-key").search(
                "graph learning",
                limit=1,
                page=3,
            )

        self.assertEqual(captured_get(request.call_args), self.contracts["semanticscholar"])
        record = result.hits[0]
        self.assertIsInstance(record, PaperRecord)
        self.assertEqual(record.uid, "S2-FIXTURE")
        self.assertEqual(record.identifiers.doi, "10.1234/semantic.fixture")
        self.assertEqual(record.identifiers.pmid, "456")
        self.assertEqual(record.links.pdf, "https://example.org/semantic.pdf")
        self.assertEqual(record.source.source_title, "Graph Journal")
        self.assertEqual(record.citations[0].count, 7)

    def test_semantic_scholar_bulk_lane_sort_contract(self):
        response = FixtureResponse(payload={"total": 0, "data": []})
        with (
            patch.object(SemanticScholarProvider, "_throttle"),
            patch("paperseek_core.sources.http.requests.get", return_value=response) as request,
        ):
            provider = SemanticScholarProvider()
            provider.search("graph learning", limit=125, page=4, lane=RetrievalLane.IMPACT)
            provider.search("graph learning", limit=125, page=4, lane=RetrievalLane.RECENT)

        impact = captured_get(request.call_args_list[0])
        recent = captured_get(request.call_args_list[1])
        self.assertEqual(impact["url"], SemanticScholarProvider.BULK_URL)
        self.assertEqual(recent["url"], SemanticScholarProvider.BULK_URL)
        self.assertEqual(impact["params"]["limit"], 125)
        self.assertEqual(impact["params"]["sort"], "citationCount:desc")
        self.assertEqual(recent["params"]["sort"], "publicationDate:desc")
        self.assertNotIn("offset", impact["params"])

    def test_pubmed_request_sequence_and_mapping_fixture(self):
        responses = {
            "esearch.fcgi": FixtureResponse(payload=load_json("pubmed_esearch.json")),
            "esummary.fcgi": FixtureResponse(payload=load_json("pubmed_esummary.json")),
            "efetch.fcgi": FixtureResponse(text=load_text("pubmed_efetch.xml")),
        }

        def route(url, **_kwargs):
            response = next(value for endpoint, value in responses.items() if url.endswith(endpoint))
            response.url = url
            return response

        with patch("paperseek_core.sources.http.requests.get", side_effect=route) as request:
            result = PubMedProvider(
                api_key="fixture-pubmed-key",
                email="fixture@example.org",
                tool="paperseek-fixture",
            ).search("cancer", limit=1, page=2, lane=RetrievalLane.RECENT)

        actual = [captured_get(call) for call in request.call_args_list]
        expected = [
            {"method": "GET", **item}
            for item in self.contracts["pubmed"]["requests"]
        ]
        self.assertEqual(actual, expected)
        record = result.hits[0]
        self.assertIsInstance(record, PaperRecord)
        self.assertEqual(record.uid, "PMID:123")
        self.assertEqual(record.identifiers.doi, "10.1234/pubmed.fixture")
        self.assertEqual(record.source.source_title, "Medical Evidence Journal")
        self.assertEqual(record.abstract, "BACKGROUND: PubMed fixture abstract.")

    def test_google_scholar_request_and_mapping_fixture(self):
        response = FixtureResponse(
            payload=load_json("google_scholar.json"),
            url=GoogleScholarSerperProvider.BASE_URL,
        )
        with patch(
            "paperseek_core.sources.google_scholar.requests.post",
            return_value=response,
        ) as request:
            result = GoogleScholarSerperProvider(api_key="fixture-serper-key").search(
                "AI governance",
                limit=1,
                page=2,
            )

        self.assertEqual(captured_post(request.call_args), self.contracts["googlescholar"])
        record = result.hits[0]
        self.assertIsInstance(record, PaperRecord)
        self.assertEqual(result.metadata.total, 11)
        self.assertEqual(record.uid, "googlescholar:GS-FIXTURE")
        self.assertEqual(record.names.authors[0].display_name, "Ada Lovelace")
        self.assertEqual(record.source.source_title, "Journal of AI Policy")
        self.assertEqual(record.abstract, "A Google Scholar result snippet.")
        self.assertEqual(record.citations[0].count, 12)

    def test_paperhub_request_sequence_paging_sort_and_mapping_fixture(self):
        manifest_url = PaperHubProvider.MANIFEST_URL
        shard_url = f"{PaperHubProvider.RAW_BASE_URL}/shards/iclr.fixture.json"
        responses = {
            manifest_url: FixtureResponse(payload=load_json("paperhub_manifest.json")),
            shard_url: FixtureResponse(payload=load_json("paperhub_shard.json")),
        }

        def route(url, **_kwargs):
            response = responses[url]
            response.url = url
            return response

        with patch("paperseek_core.sources.http.requests.get", side_effect=route) as request:
            result = PaperHubProvider().search(
                "graph retrieval",
                limit=1,
                page=2,
                lane=RetrievalLane.RECENT,
            )

        actual = [captured_get(call) for call in request.call_args_list]
        expected = [
            {"method": "GET", **item}
            for item in self.contracts["paperhub"]["requests"]
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(result.metadata.total, 2)
        self.assertEqual(result.metadata.page, 2)
        record = result.hits[0]
        self.assertIsInstance(record, PaperRecord)
        self.assertEqual(record.uid, "paperhub-old")
        self.assertEqual(record.source.source_title, "ICLR")
        self.assertEqual(record.source.publish_year, 2023)
        self.assertEqual(record.names.authors[0].display_name, "Grace Hopper")

    def test_wos_request_and_mapping_fixture(self):
        payload = load_json("wos.json")
        response = FixtureResponse(payload=payload, url=WosProvider.BASE_URL)
        provider = WosProvider(api_key="fixture-wos-key")
        session = FakeSession([response])
        provider.documents_api.api_client.session = session

        result = provider.search("TS=(governance)", limit=100, page=2)

        self.assertEqual(
            captured_session_request(session.calls[0]),
            self.contracts["wos"],
        )
        self.assertEqual(result.metadata.total, 1)
        self.assertEqual(result.hits[0].uid, "WOS:FIXTURE")
        normalized = result_from_json(payload, 50)
        record = normalized.hits[0]
        self.assertIsInstance(record, PaperRecord)
        self.assertEqual(record.provider, "wos")
        self.assertEqual(record.identifiers.doi, "10.1234/wos.fixture")
        self.assertEqual(record.names.authors[0].wos_standard, "Lovelace, Ada")
        self.assertEqual(record.citations[0].count, 8)

    def test_optional_request_values_are_omitted(self):
        empty_json = FixtureResponse(payload={"meta": {"count": 0}, "results": []})
        with patch("paperseek_core.sources.http.requests.get", return_value=empty_json) as request:
            OpenAlexProvider().search("governance", field_ids=None)
        params = captured_get(request.call_args)["params"]
        self.assertNotIn("api_key", params)
        self.assertNotIn("mailto", params)
        self.assertNotIn("filter", params)

        empty_json = FixtureResponse(payload={"message": {"total-results": 0, "items": []}})
        with patch("paperseek_core.sources.http.requests.get", return_value=empty_json) as request:
            CrossrefProvider().search("governance")
        request_data = captured_get(request.call_args)
        self.assertNotIn("mailto", request_data["params"])
        self.assertNotIn("sort", request_data["params"])
        self.assertEqual(request_data["headers"]["User-Agent"], "paperseek/1.0")

        empty_json = FixtureResponse(payload={"total": 0, "data": []})
        with (
            patch.object(SemanticScholarProvider, "_throttle"),
            patch("paperseek_core.sources.http.requests.get", return_value=empty_json) as request,
        ):
            SemanticScholarProvider().search("governance")
        self.assertNotIn("x-api-key", captured_get(request.call_args)["headers"])

        empty_json = FixtureResponse(payload={"esearchresult": {"count": "0", "idlist": []}})
        with patch("paperseek_core.sources.http.requests.get", return_value=empty_json) as request:
            PubMedProvider().search("governance")
        params = captured_get(request.call_args)["params"]
        self.assertNotIn("api_key", params)
        self.assertNotIn("email", params)
        self.assertEqual(params["tool"], "paperseek")

    def test_wos_lane_sort_and_client_optional_parameter_contract(self):
        self.assertEqual(WosProvider.sort_field_for_lane(RetrievalLane.RELEVANCE), "RS+D")
        self.assertEqual(WosProvider.sort_field_for_lane(RetrievalLane.IMPACT), "TC+D")
        self.assertEqual(WosProvider.sort_field_for_lane(RetrievalLane.RECENT), "PY+D")

        payload = {"metadata": {"total": 0}, "hits": []}
        provider = WosProvider(api_key="fixture-wos-key")
        session = FakeSession([FixtureResponse(payload=payload)])
        provider.documents_api.api_client.session = session
        provider.documents_api.documents_get(q="TS=(governance)", db="WOS")
        self.assertEqual(session.calls[0][2]["params"], {"q": "TS=(governance)", "db": "WOS"})

        uid_payload = {"uid": "WOS:DETAIL", "title": "Detailed"}
        session.responses.append(FixtureResponse(payload=uid_payload))
        provider.documents_api.documents_uid_get("WOS:DETAIL", db="WOS", detail="full")
        self.assertEqual(session.calls[1][2]["params"], {"db": "WOS", "detail": "full"})


class ProviderFailureSemanticsTest(unittest.TestCase):
    GET_SOURCES = (
        "openalex",
        "crossref",
        "arxiv",
        "semanticscholar",
        "pubmed",
        "paperhub",
    )

    def setUp(self):
        PaperHubProvider.reset_cache()
        ArxivProvider._last_request_at = 0.0
        SemanticScholarProvider._last_request_at = 0.0

    @staticmethod
    def invoke_get_source(source):
        if source == "openalex":
            return OpenAlexProvider().search("governance")
        if source == "crossref":
            return CrossrefProvider().search("governance")
        if source == "arxiv":
            return ArxivProvider().search("governance")
        if source == "semanticscholar":
            return SemanticScholarProvider().search("governance")
        if source == "pubmed":
            return PubMedProvider().search("governance")
        if source == "paperhub":
            return PaperHubProvider().search("governance")
        raise AssertionError(source)

    def get_source_context(self, response_or_exception):
        stack = ExitStack()
        if isinstance(response_or_exception, BaseException):
            stack.enter_context(
                patch(
                    "paperseek_core.sources.http.requests.get",
                    side_effect=response_or_exception,
                )
            )
        else:
            stack.enter_context(
                patch(
                    "paperseek_core.sources.http.requests.get",
                    return_value=response_or_exception,
                )
            )
        stack.enter_context(patch("paperseek_core.sources.http.time.sleep"))
        stack.enter_context(patch.object(ArxivProvider, "_throttle"))
        stack.enter_context(patch.object(SemanticScholarProvider, "_throttle"))
        return stack

    def test_final_http_status_classification_for_every_provider(self):
        for source in self.GET_SOURCES:
            for status in (401, 403, 429, 503):
                with self.subTest(source=source, status=status):
                    PaperHubProvider.reset_cache()
                    response = FixtureResponse(
                        payload={"error": "fixture failure"},
                        status_code=status,
                        reason="Fixture failure",
                    )
                    with self.get_source_context(response):
                        with self.assertRaises(ProviderError) as raised:
                            self.invoke_get_source(source)
                    self.assertEqual(raised.exception.source, source)
                    self.assertEqual(raised.exception.status, status)
                    self.assertEqual(raised.exception.query, "governance")

        for status in (401, 403, 429, 503):
            with self.subTest(source="googlescholar", status=status):
                response = FixtureResponse(
                    payload={"error": "fixture failure"},
                    status_code=status,
                    reason="Fixture failure",
                )
                with (
                    patch(
                        "paperseek_core.sources.google_scholar.requests.post",
                        return_value=response,
                    ),
                    patch("paperseek_core.sources.google_scholar.time.sleep"),
                ):
                    with self.assertRaises(ProviderError) as raised:
                        GoogleScholarSerperProvider(api_key="fixture-key").search("governance")
                self.assertEqual(raised.exception.source, "googlescholar")
                self.assertEqual(raised.exception.status, status)
                self.assertEqual(raised.exception.query, "governance")

        for status in (401, 403, 429, 503):
            with self.subTest(source="wos", status=status):
                responses = [
                    FixtureResponse(status_code=status, reason="Fixture failure")
                    for _ in range(2 if status == 429 else 1)
                ]
                provider = WosProvider(api_key="fixture-key")
                provider.documents_api.api_client.session = FakeSession(responses)
                with patch("paperseek_core.sources.wos.time.sleep"):
                    with self.assertRaises(ApiException) as raised:
                        provider.search("TS=(governance)")
                self.assertEqual(raised.exception.status, status)

    def test_transport_failure_classification_for_every_provider(self):
        for source in self.GET_SOURCES:
            with self.subTest(source=source):
                PaperHubProvider.reset_cache()
                with self.get_source_context(requests.Timeout("fixture timeout")):
                    with self.assertRaises(ProviderError) as raised:
                        self.invoke_get_source(source)
                self.assertEqual(raised.exception.source, source)
                self.assertIsNone(raised.exception.status)
                self.assertIn("failed after 3 attempts", str(raised.exception))

        with (
            patch(
                "paperseek_core.sources.google_scholar.requests.post",
                side_effect=requests.Timeout("fixture timeout"),
            ),
            patch("paperseek_core.sources.google_scholar.time.sleep"),
        ):
            with self.assertRaises(ProviderError) as raised:
                GoogleScholarSerperProvider(api_key="fixture-key").search("governance")
        self.assertEqual(raised.exception.source, "googlescholar")
        self.assertIsNone(raised.exception.status)
        self.assertIn("failed after 3 attempts", str(raised.exception))

        provider = WosProvider(api_key="fixture-key")
        provider.documents_api.api_client.session = FakeSession([])
        with patch.object(
            provider.documents_api.api_client.session,
            "request",
            side_effect=requests.Timeout("fixture timeout"),
        ):
            with self.assertRaises(ApiException) as raised:
                provider.search("TS=(governance)")
        self.assertIsNone(raised.exception.status)
        self.assertIn("network error", str(raised.exception))

    def test_invalid_payload_classification_for_every_provider(self):
        invalid_json = FixtureResponse(text="not-json")
        for source in ("openalex", "crossref", "semanticscholar", "pubmed", "paperhub"):
            with self.subTest(source=source):
                PaperHubProvider.reset_cache()
                with self.get_source_context(invalid_json):
                    with self.assertRaises(ProviderError) as raised:
                        self.invoke_get_source(source)
                self.assertEqual(raised.exception.source, source)
                self.assertIsNone(raised.exception.status)

        with self.get_source_context(FixtureResponse(text="not-xml")):
            with self.assertRaises(ProviderError) as raised:
                ArxivProvider().search("governance")
        self.assertEqual(raised.exception.source, "arxiv")
        self.assertIn("invalid Atom XML", str(raised.exception))

        with patch(
            "paperseek_core.sources.google_scholar.requests.post",
            return_value=invalid_json,
        ):
            with self.assertRaises(ProviderError) as raised:
                GoogleScholarSerperProvider(api_key="fixture-key").search("governance")
        self.assertEqual(raised.exception.source, "googlescholar")
        self.assertIn("non-JSON", str(raised.exception))

        provider = WosProvider(api_key="fixture-key")
        provider.documents_api.api_client.session = FakeSession([invalid_json])
        with self.assertRaises(ApiException) as raised:
            provider.search("TS=(governance)")
        self.assertEqual(raised.exception.status, 200)
        self.assertIn("invalid JSON", str(raised.exception))

    def test_empty_result_classification_for_every_provider(self):
        cases = {
            "openalex": FixtureResponse(payload={"meta": {"count": 0}, "results": []}),
            "crossref": FixtureResponse(payload={"message": {"total-results": 0, "items": []}}),
            "arxiv": FixtureResponse(
                text=(
                    '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
                    'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
                    '<opensearch:totalResults>0</opensearch:totalResults></feed>'
                )
            ),
            "semanticscholar": FixtureResponse(payload={"total": 0, "data": []}),
            "pubmed": FixtureResponse(payload={"esearchresult": {"count": "0", "idlist": []}}),
        }
        for source, response in cases.items():
            with self.subTest(source=source):
                with self.get_source_context(response):
                    result = self.invoke_get_source(source)
                self.assertEqual(result.metadata.total, 0)
                self.assertEqual(result.hits, [])

        empty_google = FixtureResponse(payload={"organic": []})
        with patch(
            "paperseek_core.sources.google_scholar.requests.post",
            return_value=empty_google,
        ):
            result = GoogleScholarSerperProvider(api_key="fixture-key").search("governance")
        self.assertEqual(result.metadata.total, 0)
        self.assertEqual(result.hits, [])

        manifest = load_json("paperhub_manifest.json")
        manifest["shards"][0]["count"] = 0
        responses = [
            FixtureResponse(payload=manifest),
            FixtureResponse(payload={"papers": []}),
        ]
        with patch("paperseek_core.sources.http.requests.get", side_effect=responses):
            result = PaperHubProvider().search("governance")
        self.assertEqual(result.metadata.total, 0)
        self.assertEqual(result.hits, [])

        provider = WosProvider(api_key="fixture-key")
        provider.documents_api.api_client.session = FakeSession(
            [FixtureResponse(payload={"metadata": {"total": 0}, "hits": []})]
        )
        result = provider.search("TS=(governance)")
        self.assertEqual(result.metadata.total, 0)
        self.assertEqual(result.hits, [])


if __name__ == "__main__":
    unittest.main()
