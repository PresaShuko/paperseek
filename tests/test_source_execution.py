from types import SimpleNamespace

import pytest

from paperseek_core.domain.models import PaperRecord
from paperseek_core.retrieval import RetrievalLane
from paperseek_core.source_execution import SourceRequestExecutor
from paperseek_core.sources.contracts import ProviderSearchResult, SearchMetadata


def make_executor(source: str, *, fields: tuple[str, ...] = ()) -> SourceRequestExecutor:
    return SourceRequestExecutor(
        SimpleNamespace(wos_db="WOS"),
        source,
        fields,
        lambda operation: operation(),
    )


class RecordingProvider:
    def __init__(self) -> None:
        self.calls = []
        self.last_response_info = {
            "method": "GET",
            "url": "https://example.test/works?secret=redacted",
            "status": 200,
            "elapsed_ms": 12,
            "attempts": 2,
        }

    def search(self, **parameters):
        self.calls.append(parameters)
        return ProviderSearchResult(
            SearchMetadata(total=3, page=parameters["page"], limit=parameters["limit"]),
            [PaperRecord(uid="record-1", title="Result", provider="test")],
        )


def test_openalex_executor_passes_normalized_field_ids_and_lane() -> None:
    provider = RecordingProvider()
    executor = make_executor("openalex", fields=("17", "14"))

    result = executor.search_lane(
        "AI governance",
        RetrievalLane.IMPACT,
        25,
        page=3,
        provider=provider,
    )

    assert result.metadata == SearchMetadata(total=3, page=3, limit=25)
    assert provider.calls == [
        {
            "query": "AI governance",
            "limit": 25,
            "page": 3,
            "lane": RetrievalLane.IMPACT,
            "field_ids": ("17", "14"),
        }
    ]


def test_executor_filters_parameters_to_provider_signature() -> None:
    calls = []

    class Provider:
        def search(self, query, limit, page):
            calls.append((query, limit, page))
            return ProviderSearchResult(SearchMetadata(total=0, page=page, limit=limit), [])

    make_executor("crossref").search_lane(
        "platform governance",
        RetrievalLane.RECENT,
        10,
        page=2,
        provider=Provider(),
    )

    assert calls == [("platform governance", 10, 2)]


def test_wos_executor_synchronizes_documents_client_before_search() -> None:
    replacement_client = object()

    class Provider:
        def __init__(self) -> None:
            self.documents_api = object()

        def search(self, query, limit, page, lane):
            assert self.documents_api is replacement_client
            return ProviderSearchResult(SearchMetadata(total=1, page=page, limit=limit), [])

    provider = Provider()
    make_executor("wos").search_lane(
        "TS=(governance)",
        RetrievalLane.RELEVANCE,
        50,
        page=1,
        provider=provider,
        documents_api=replacement_client,
    )

    assert provider.documents_api is replacement_client


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("wos", "GET /documents db=WOS q=governance"),
        ("openalex", "GET /works search=governance"),
        ("crossref", "GET /works query.bibliographic=governance"),
        ("arxiv", "GET /api/query search_query=governance"),
        ("semanticscholar", "GET /graph/v1/paper/search query=governance"),
        ("pubmed", "GET /entrez/eutils/esearch.fcgi term=governance"),
        ("googlescholar", "POST /scholar q=governance"),
        ("paperhub", "GET paper-hub shards query=governance"),
    ],
)
def test_request_labels_cover_supported_sources(source: str, expected: str) -> None:
    assert make_executor(source).request_label("governance") == expected


def test_response_log_uses_provider_request_metadata_without_query_string() -> None:
    provider = RecordingProvider()
    result = ProviderSearchResult(
        SearchMetadata(total=12, page=1, limit=10),
        [PaperRecord(uid="record-1", title="Result", provider="openalex")],
    )

    message = make_executor("openalex").response_log(result, provider=provider)

    assert message == (
        "OpenAlex GET https://example.test/works -> HTTP 200 OK in 12ms; "
        "attempts=2; total=12; returned=1."
    )
