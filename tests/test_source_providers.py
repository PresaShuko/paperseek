import unittest
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from paperseek_core.retrieval import RetrievalLane
from paperseek_core.domain.models import PaperIdentifiers, PaperRecord
from paperseek_core.sources.arxiv import ArxivProvider
from paperseek_core.sources.contracts import ProviderError
from paperseek_core.sources.crossref import CrossrefProvider
from paperseek_core.sources.google_scholar import GoogleScholarSerperProvider
from paperseek_core.sources.http import retry_delay
from paperseek_core.sources.normalization import normalize_doi, reconstruct_abstract
from paperseek_core.sources.openalex import OpenAlexProvider
from paperseek_core.sources.paperhub import PaperHubProvider
from paperseek_core.sources.pubmed import PubMedProvider
from paperseek_core.sources.semantic_scholar import SemanticScholarProvider


class FakeResponse:
    def __init__(self, payload=None, text="", status_code=200, url="https://example.test"):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.url = url

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class SourceProviderTest(unittest.TestCase):
    def setUp(self):
        SemanticScholarProvider._last_request_at = 0.0
        PaperHubProvider.reset_cache()

    @patch("paperseek_core.sources.semantic_scholar.time.sleep")
    @patch("paperseek_core.sources.semantic_scholar.time.monotonic", side_effect=[10.0, 10.0, 10.25, 11.05])
    def test_semantic_scholar_throttle_enforces_one_request_per_second(self, _monotonic, sleep):
        SemanticScholarProvider._throttle()
        SemanticScholarProvider._throttle()

        sleep.assert_called_once_with(0.95)

    def test_semantic_scholar_429_uses_source_specific_backoff(self):
        response = FakeResponse(status_code=429)
        response.headers = {}

        self.assertEqual(retry_delay(response, 1, "semanticscholar"), 2.0)
        self.assertEqual(retry_delay(response, 2, "semanticscholar"), 4.0)

    def test_normalize_doi(self):
        self.assertEqual(normalize_doi(None), "")
        self.assertEqual(normalize_doi(""), "")
        self.assertEqual(normalize_doi("  "), "")

        self.assertEqual(normalize_doi("10.1234/5678"), "10.1234/5678")
        self.assertEqual(normalize_doi(" 10.1234/5678  "), "10.1234/5678")

        self.assertEqual(normalize_doi("https://doi.org/10.1234/5678"), "10.1234/5678")
        self.assertEqual(normalize_doi("http://doi.org/10.1234/5678"), "10.1234/5678")
        self.assertEqual(normalize_doi("doi:10.1234/5678"), "10.1234/5678")
        self.assertEqual(normalize_doi(" DOI:10.1234/5678 "), "10.1234/5678")
        self.assertEqual(normalize_doi("HTTPS://DOI.ORG/10.1234/5678"), "10.1234/5678")

    def test_openalex_semantic_lane_uses_semantic_parameter_without_keyword_sort(self):
        captured = {}

        def fake_get(provider, url, params=None, headers=None, timeout=0, query="", attempts=None):
            captured.update({"provider": provider, "url": url, "params": dict(params or {})})
            payload = {"meta": {"count": 1, "page": 1, "per_page": 1}, "results": []}
            return FakeResponse(payload=payload), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        with patch("paperseek_core.sources.openalex.get_with_retries", fake_get):
            OpenAlexProvider(api_key="test-key").search(
                "methods for calibrating peer review bias",
                limit=100,
                lane=RetrievalLane.SEMANTIC,
            )

        self.assertEqual(captured["params"]["search.semantic"], "methods for calibrating peer review bias")
        self.assertNotIn("search", captured["params"])
        self.assertNotIn("sort", captured["params"])
        self.assertEqual(captured["params"]["per-page"], 50)
        self.assertEqual(captured["params"]["api_key"], "test-key")

    def test_openalex_semantic_lane_requires_api_key_before_request(self):
        with self.assertRaisesRegex(Exception, "semantic search requires an API key"):
            OpenAlexProvider().search("semantic retrieval", lane=RetrievalLane.SEMANTIC)

    def test_openalex_normalizes_escaped_whitespace_before_deduplication(self):
        record = OpenAlexProvider()._to_record(
            {
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1/example",
                "title": "Unified Text-to-Text\\n Transformer",
            },
        )

        self.assertEqual(record.title, "Unified Text-to-Text Transformer")

    def test_openalex_advertises_semantic_lane_only_with_api_key(self):
        self.assertNotIn(RetrievalLane.SEMANTIC, OpenAlexProvider().retrieval_capabilities().lanes)
        self.assertIn(RetrievalLane.SEMANTIC, OpenAlexProvider(api_key="key").retrieval_capabilities().lanes)

    def test_crossref_lane_contract_preserves_paging_sort_and_polite_email(self):
        calls = []

        def fake_get(provider, url, params=None, headers=None, timeout=0, query="", attempts=None):
            calls.append({"provider": provider, "url": url, "params": dict(params or {}), "headers": dict(headers or {})})
            payload = {"message": {"total-results": 0, "items": []}}
            return FakeResponse(payload=payload), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        provider = CrossrefProvider(email="researcher@example.org")
        with patch("paperseek_core.sources.crossref.get_with_retries", fake_get):
            provider.search("AI governance", limit=25, page=3, lane=RetrievalLane.RELEVANCE)
            provider.search("AI governance", limit=25, page=1, lane=RetrievalLane.IMPACT)
            provider.search("AI governance", limit=25, page=1, lane=RetrievalLane.RECENT)

        self.assertEqual(calls[0]["provider"], "crossref")
        self.assertEqual(calls[0]["params"]["query.bibliographic"], "AI governance")
        self.assertEqual(calls[0]["params"]["rows"], 25)
        self.assertEqual(calls[0]["params"]["offset"], 50)
        self.assertEqual(calls[0]["params"]["mailto"], "researcher@example.org")
        self.assertNotIn("sort", calls[0]["params"])
        self.assertEqual(calls[1]["params"]["sort"], "is-referenced-by-count")
        self.assertEqual(calls[2]["params"]["sort"], "published")

    def test_arxiv_provider_parses_atom_records(self):
        atom = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Graph Retrieval</title>
    <summary>Graph retrieval abstract.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
    <link href="http://arxiv.org/abs/2401.00001v1" rel="alternate"/>
    <link href="http://arxiv.org/pdf/2401.00001v1" title="pdf" type="application/pdf"/>
    <arxiv:doi>10.1234/example</arxiv:doi>
    <arxiv:primary_category term="cs.IR"/>
  </entry>
</feed>"""
        captured = {}

        def fake_get(provider, url, params=None, headers=None, timeout=0, query="", attempts=None):
            captured.update({
                "provider": provider,
                "url": url,
                "params": params,
                "headers": headers,
                "timeout": timeout,
                "query": query,
                "attempts": attempts,
            })
            return FakeResponse(text=atom), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        with patch("paperseek_core.sources.arxiv.get_with_retries", fake_get):
            result = ArxivProvider().search("graph retrieval", limit=1)

        self.assertEqual(result.metadata.total, 1)
        self.assertEqual(result.hits[0].provider, "arxiv")
        self.assertEqual(result.hits[0].identifiers.arxiv, "2401.00001v1")
        self.assertEqual(result.hits[0].identifiers.doi, "10.1234/example")
        self.assertEqual(captured["url"], "http://export.arxiv.org/api/query")
        self.assertEqual(captured["attempts"], 3)
        self.assertEqual(captured["timeout"], 45)
        self.assertEqual(captured["params"]["search_query"], 'all:"graph retrieval"')

    def test_arxiv_provider_escapes_quotes_in_plain_query(self):
        self.assertEqual(
            ArxivProvider._search_query('graph "neural" retrieval'),
            'all:"graph \\"neural\\" retrieval"',
        )

    def test_semantic_scholar_provider_uses_api_key_and_maps_fields(self):
        payload = {
            "total": 1,
            "data": [
                {
                    "paperId": "S2",
                    "title": "Graph Learning",
                    "abstract": "Abstract.",
                    "year": 2024,
                    "authors": [{"name": "Ada"}],
                    "externalIds": {"DOI": "10.1234/s2", "PubMed": "123", "ArXiv": "2401.00001"},
                    "citationCount": 7,
                    "fieldsOfStudy": ["Computer Science"],
                    "openAccessPdf": {"url": "https://example.test/paper.pdf"},
                }
            ],
        }
        captured = {}

        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            captured.update({"provider": provider, "headers": headers, "params": params})
            return FakeResponse(payload=payload), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        with patch("paperseek_core.sources.semantic_scholar.get_with_retries", fake_get):
            result = SemanticScholarProvider(api_key="s2-key").search("graph learning", limit=1)

        record = result.hits[0]
        self.assertEqual(captured["headers"]["x-api-key"], "s2-key")
        self.assertEqual(record.provider, "semanticscholar")
        self.assertEqual(record.identifiers.doi, "10.1234/s2")
        self.assertEqual(record.identifiers.pmid, "123")
        self.assertEqual(record.identifiers.arxiv, "2401.00001")
        self.assertEqual(record.citations[0].count, 7)

    def test_semantic_scholar_provider_falls_back_to_basic_fields_after_5xx(self):
        calls = []

        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            calls.append(dict(params or {}))
            if len(calls) == 1:
                return FakeResponse(payload={"message": "Internal Server Error"}, text='{"message":"Internal Server Error"}', status_code=500), {
                    "method": "GET",
                    "url": url,
                    "status": 500,
                    "elapsed_ms": 1,
                }
            return FakeResponse(payload={
                "total": 1,
                "data": [{
                    "paperId": "S2",
                    "title": "Graph Learning",
                    "year": 2024,
                    "authors": [{"name": "Ada"}],
                    "citationCount": 7,
                }],
            }), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 2}

        with patch("paperseek_core.sources.semantic_scholar.get_with_retries", fake_get):
            provider = SemanticScholarProvider(api_key="s2-key")
            result = provider.search("graph learning", limit=1)

        self.assertEqual(len(calls), 2)
        self.assertIn("abstract", calls[0]["fields"])
        self.assertNotIn("abstract", calls[1]["fields"])
        self.assertEqual(provider.last_response_info["fallback"], "basic_fields")
        self.assertEqual(result.metadata.total, 1)
        self.assertEqual(result.hits[0].title, "Graph Learning")

    def test_pubmed_provider_uses_eutilities_and_parses_abstracts(self):
        calls = []

        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            calls.append((url, dict(params or {})))
            if url.endswith("esearch.fcgi"):
                return FakeResponse(payload={"esearchresult": {"count": "1", "idlist": ["123"]}}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            if url.endswith("esummary.fcgi"):
                return FakeResponse(payload={"result": {"123": {"title": "Cancer Immunotherapy", "uid": "123", "pubdate": "2024", "authors": [{"name": "Lin"}], "articleids": [{"idtype": "doi", "value": "10.1234/pubmed"}]}}}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            if url.endswith("efetch.fcgi"):
                xml = "<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><Abstract><AbstractText>PubMed abstract.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"
                return FakeResponse(text=xml), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            raise AssertionError(url)

        with patch("paperseek_core.sources.pubmed.get_with_retries", fake_get):
            result = PubMedProvider(api_key="ncbi-key", email="you@example.org", tool="paperseek-test").search("cancer", limit=1)

        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][1]["api_key"], "ncbi-key")
        self.assertEqual(calls[0][1]["email"], "you@example.org")
        self.assertEqual(calls[0][1]["tool"], "paperseek-test")
        record = result.hits[0]
        self.assertEqual(record.provider, "pubmed")
        self.assertEqual(record.identifiers.pmid, "123")
        self.assertEqual(record.identifiers.doi, "10.1234/pubmed")
        self.assertEqual(record.abstract, "PubMed abstract.")

    def test_google_scholar_serper_provider_posts_query_and_maps_results(self):
        payload = {
            "organic": [
                {
                    "id": "gs-1",
                    "title": "AI Governance and Accountability",
                    "link": "https://example.org/paper",
                    "pdfUrl": "https://example.org/paper.pdf",
                    "snippet": "A Google Scholar result snippet.",
                    "year": 2024,
                    "publicationInfo": {
                        "summary": "A Ada - Journal of AI Policy, 2024",
                        "authors": [{"name": "A Ada"}],
                    },
                    "citedBy": {"total": 12, "link": "https://scholar.google.com/scholar?cites=1"},
                }
            ]
        }
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=0):
            captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return FakeResponse(payload=payload, status_code=200, url=url)

        with patch("paperseek_core.sources.google_scholar.requests.post", fake_post):
            result = GoogleScholarSerperProvider(api_key="serper-a,serper-b").search("AI governance", limit=5, page=2)

        self.assertEqual(captured["url"], "https://google.serper.dev/scholar")
        self.assertEqual(captured["json"]["q"], "AI governance")
        self.assertEqual(captured["json"]["page"], 2)
        self.assertNotIn("num", captured["json"])
        self.assertIn(captured["headers"]["X-API-KEY"], {"serper-a", "serper-b"})
        self.assertEqual(result.metadata.total, 11)
        record = result.hits[0]
        self.assertEqual(record.provider, "googlescholar")
        self.assertEqual(record.uid, "googlescholar:gs-1")
        self.assertEqual(record.links.pdf, "https://example.org/paper.pdf")
        self.assertEqual(record.citations[0].count, 12)
        self.assertEqual(record.abstract, "A Google Scholar result snippet.")

    def test_openalex_citation_neighbors_reports_progress(self):
        provider = OpenAlexProvider()
        seed = PaperRecord(
            uid="https://openalex.org/W1",
            title="Seed Paper",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/W1"),
            raw={"referenced_works": ["https://openalex.org/W2"]},
        )
        neighbor = PaperRecord(
            uid="https://openalex.org/W2",
            title="Neighbor Paper",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/W2"),
            raw={},
        )
        progress = []

        with patch.object(provider, "_fetch_works", return_value=[neighbor]) as fetch_works:
            result = provider.citation_neighbors_with_graph(
                [seed],
                per_seed=1,
                max_records=5,
                depth=1,
                progress_callback=progress.append,
                request_attempts=1,
                request_timeout=5,
            )

        self.assertEqual([record.title for record in result["records"]], ["Neighbor Paper"])
        fetch_works.assert_called_once_with(["https://openalex.org/W2"], attempts=1, timeout=5)
        self.assertEqual(result["frontier"]["direction_stats"]["backward"]["requests"], 1)
        self.assertTrue(any(item.get("event") == "start" for item in progress))
        self.assertTrue(any(item.get("event") == "seed_complete" and item.get("records") == 1 for item in progress))

    def test_openalex_fetches_forward_and_backward_neighbors_concurrently(self):
        provider = OpenAlexProvider()
        seed = PaperRecord(
            uid="https://openalex.org/W1",
            title="Seed Paper",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/W1"),
            raw={"referenced_works": ["https://openalex.org/W2"]},
        )
        backward = PaperRecord(
            uid="https://openalex.org/W2",
            title="Backward",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/W2"),
            raw={},
        )
        forward = PaperRecord(
            uid="https://openalex.org/W3",
            title="Forward",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/W3"),
            raw={},
        )
        barrier = threading.Barrier(2, timeout=2)

        def fetch_backward(*args, **kwargs):
            barrier.wait()
            return [backward]

        def fetch_forward(*args, **kwargs):
            barrier.wait()
            return [forward]

        with (
            patch.object(provider, "_fetch_works", side_effect=fetch_backward),
            patch.object(provider, "_fetch_forward_citations", side_effect=fetch_forward),
        ):
            result = provider.citation_neighbors_with_graph(
                [seed],
                per_seed=1,
                max_records=5,
                depth=1,
                request_attempts=1,
                request_timeout=5,
            )

        self.assertEqual({record.uid for record in result["records"]}, {
            "https://openalex.org/W2",
            "https://openalex.org/W3",
        })

    def test_openalex_batch_fetches_referenced_work_ids_in_one_request(self):
        provider = OpenAlexProvider(api_key="oa-test")
        captured = {}

        def fake_get(_, url, *, params=None, headers=None, timeout=30, query="", attempts=3):
            captured.update({"url": url, "params": dict(params or {}), "query": query})
            return FakeResponse(
                payload={
                    "results": [
                        {"id": "https://openalex.org/W2", "title": "Second"},
                        {"id": "https://openalex.org/W1", "title": "First"},
                    ]
                },
                status_code=200,
                url=url,
            ), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        with patch("paperseek_core.sources.openalex.get_with_retries", side_effect=fake_get):
            records = provider._fetch_works(
                ["https://openalex.org/W1", "W2", "W1"],
                attempts=1,
                timeout=5,
            )

        self.assertEqual(captured["url"], provider.BASE_URL)
        self.assertEqual(captured["params"]["filter"], "openalex:W1|W2")
        self.assertEqual(captured["params"]["per-page"], 2)
        self.assertEqual(captured["params"]["api_key"], "oa-test")
        self.assertEqual([record.uid for record in records], ["https://openalex.org/W1", "https://openalex.org/W2"])

    def test_openalex_citation_neighbors_respects_cancel_callback(self):
        provider = OpenAlexProvider()
        seed = PaperRecord(
            uid="https://openalex.org/W1",
            title="Seed Paper",
            identifiers=PaperIdentifiers(openalex="https://openalex.org/W1"),
            raw={"referenced_works": ["https://openalex.org/W2"]},
        )

        def cancel():
            raise RuntimeError("cancelled")

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            provider.citation_neighbors_with_graph(
                [seed],
                per_seed=1,
                max_records=5,
                depth=1,
                cancel_check=cancel,
                request_attempts=1,
                request_timeout=5,
            )

    def test_google_scholar_serper_provider_rejects_unexpected_json(self):
        def fake_post(url, json=None, headers=None, timeout=0):
            return FakeResponse(payload=["not", "a", "dict"], status_code=200, url=url)

        with patch("paperseek_core.sources.google_scholar.requests.post", fake_post):
            with self.assertRaisesRegex(Exception, "unexpected JSON structure"):
                GoogleScholarSerperProvider(api_key="serper-a").search("AI governance", limit=5)

    def test_google_scholar_serper_provider_ignores_non_list_authors(self):
        payload = {
            "organic": [
                {
                    "id": "gs-authors",
                    "title": "AI Governance",
                    "publicationInfo": {"authors": "Alice, Bob"},
                }
            ]
        }

        def fake_post(url, json=None, headers=None, timeout=0):
            return FakeResponse(payload=payload, status_code=200, url=url)

        with patch("paperseek_core.sources.google_scholar.requests.post", fake_post):
            result = GoogleScholarSerperProvider(api_key="serper-a").search("AI governance", limit=1)

        self.assertEqual(result.hits[0].names.authors, [])

    def test_google_scholar_serper_provider_cleans_summary_metadata(self):
        payload = {
            "organic": [
                {
                    "id": "gs-clean",
                    "title": "Digital\u9225\u63dceal Economy Integration",
                    "link": "https://example.org/clean",
                    "snippet": "\u9225?, resource allocation and industrial innovation \u9225?",
                    "publicationInfo": {
                        "summary": "Y Feng, Y Gao, L Yang\u9225? - Resources Policy, 2024 - Elsevier",
                    },
                    "citedBy": {"cites": 41},
                }
            ]
        }

        def fake_post(url, json=None, headers=None, timeout=0):
            return FakeResponse(payload=payload, status_code=200, url=url)

        with patch("paperseek_core.sources.google_scholar.requests.post", fake_post):
            result = GoogleScholarSerperProvider(api_key="serper-a").search("digital economy", limit=1)

        record = result.hits[0]
        self.assertEqual(record.title, "Digital\u2013Real Economy Integration")
        self.assertEqual([author.display_name for author in record.names.authors], ["Y Feng", "Y Gao", "L Yang"])
        self.assertEqual(record.source.source_title, "Resources Policy")
        self.assertEqual(record.source.publish_year, 2024)
        self.assertEqual(record.abstract, "resource allocation and industrial innovation")
        self.assertEqual(record.citations[0].count, 41)

    def test_google_scholar_serper_provider_uses_domain_when_summary_has_no_venue(self):
        payload = {
            "organic": [
                {
                    "id": "gs-book",
                    "title": "Governing China's Digital Transformation",
                    "publicationInfo": {"summary": "J Qian - 2025 - books.google.com"},
                }
            ]
        }

        def fake_post(url, json=None, headers=None, timeout=0):
            return FakeResponse(payload=payload, status_code=200, url=url)

        with patch("paperseek_core.sources.google_scholar.requests.post", fake_post):
            result = GoogleScholarSerperProvider(api_key="serper-a").search("digital transformation", limit=1)

        record = result.hits[0]
        self.assertEqual([author.display_name for author in record.names.authors], ["J Qian"])
        self.assertEqual(record.source.source_title, "books.google.com")
        self.assertEqual(record.source.publish_year, 2025)

    def test_google_scholar_serper_provider_rejects_implausible_item_year(self):
        payload = {
            "organic": [
                {
                    "id": "gs-ssrn",
                    "title": "Do Foreign Direct Investments Crowd In or Crowd Out Domestic Investment?",
                    "year": 3505,
                    "publicationInfo": {
                        "summary": "JMR Oualy\u0431\u043d - Available at SSRN 3505572, 2019 - papers.ssrn.com",
                    },
                    "citedBy": {"total": 12},
                }
            ]
        }

        def fake_post(url, json=None, headers=None, timeout=0):
            return FakeResponse(payload=payload, status_code=200, url=url)

        with patch("paperseek_core.sources.google_scholar.requests.post", fake_post):
            result = GoogleScholarSerperProvider(api_key="serper-a").search("foreign direct investment", limit=1)

        record = result.hits[0]
        self.assertEqual([author.display_name for author in record.names.authors], ["JMR Oualy"])
        self.assertEqual(record.source.source_title, "SSRN")
        self.assertEqual(record.source.publish_year, 2019)

    def test_google_scholar_serper_provider_skips_transient_empty_pages(self):
        payloads = [
            {"organic": []},
            {
                "organic": [
                    {"id": "gs-2", "title": "AI Governance", "link": "https://example.org/2"},
                    {"id": "gs-3", "title": "AI Accountability", "link": "https://example.org/3"},
                ]
            },
        ]
        pages = []

        def fake_post(url, json=None, headers=None, timeout=0):
            pages.append(json["page"])
            payload = payloads.pop(0) if payloads else {"organic": []}
            return FakeResponse(payload=payload, status_code=200, url=url)

        with patch("paperseek_core.sources.google_scholar.requests.post", fake_post):
            result = GoogleScholarSerperProvider(api_key="serper-a").search("AI governance", limit=5)

        self.assertEqual(pages[:2], [1, 2])
        self.assertEqual(len(result.hits), 2)
        self.assertEqual(result.metadata.total, 12)

    def test_paperhub_provider_loads_manifest_and_scores_shards(self):
        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            if url.endswith("manifest.json"):
                return FakeResponse(payload={"shards": [{"file": "shards/iclr-2025.fake.json"}]}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            if url.endswith("iclr-2025.fake.json"):
                return FakeResponse(payload={"papers": [{"id": "p1", "title": "Graph Neural Retrieval", "authors": ["Ada"], "conference": "ICLR", "year": 2025, "abstract": "retrieval with graphs"}]}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            raise AssertionError(url)

        with patch("paperseek_core.sources.paperhub.get_with_retries", fake_get):
            result = PaperHubProvider().search("graph retrieval", limit=1)

        self.assertEqual(result.metadata.total, 1)
        record = result.hits[0]
        self.assertEqual(record.provider, "paperhub")
        self.assertEqual(record.source.source_title, "ICLR")
        self.assertEqual(record.source.publish_year, 2025)

    def test_paperhub_provider_initializes_cache_once_under_concurrency(self):
        calls = []

        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            calls.append(url)
            time.sleep(0.01)
            if url.endswith("manifest.json"):
                return FakeResponse(payload={"shards": [{"file": "shards/iclr-2025.fake.json"}]}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            if url.endswith("iclr-2025.fake.json"):
                return FakeResponse(payload={"papers": [{"id": "p1", "title": "Graph Neural Retrieval", "authors": ["Ada"], "conference": "ICLR", "year": 2025, "abstract": "retrieval with graphs"}]}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            raise AssertionError(url)

        with patch("paperseek_core.sources.paperhub.get_with_retries", fake_get):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: PaperHubProvider().search("graph retrieval", limit=1), range(2)))

        self.assertEqual([result.metadata.total for result in results], [1, 1])
        self.assertEqual(sum(1 for url in calls if url.endswith("manifest.json")), 1)
        self.assertEqual(sum(1 for url in calls if url.endswith("iclr-2025.fake.json")), 1)

    def test_paperhub_provider_loads_current_multi_shard_manifest_atomically(self):
        shards = [
            {"conference": "AAAI", "year": 2026, "count": 1, "file": "shards/aaai-2026.fake.json"},
            {"conference": "ICLR", "year": 2025, "count": 1, "file": "shards/iclr-2025.fake.json"},
            {"conference": "ICLR", "year": 2026, "count": 1, "file": "shards/iclr-2026.fake.json"},
            {"conference": "ICML", "year": 2025, "count": 1, "file": "shards/icml-2025.fake.json"},
            {"conference": "ICML", "year": 2026, "count": 1, "file": "shards/icml-2026.fake.json"},
            {"conference": "NDSS", "year": 2026, "count": 1, "file": "shards/ndss-2026.fake.json"},
            {"conference": "NeurIPS", "year": 2025, "count": 1, "file": "shards/neurips-2025.fake.json"},
        ]

        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            if url.endswith("manifest.json"):
                payload = {"built_at": "2026-07-20T15:35:26+08:00", "shards": shards}
                return FakeResponse(payload=payload), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            shard = next(item for item in shards if url.endswith(item["file"]))
            payload = {
                "papers": [{
                    "id": f"{shard['conference']}-{shard['year']}",
                    "title": "Top Conference Paper",
                    "authors": ["Ada"],
                    "conference": shard["conference"],
                    "year": shard["year"],
                    "abstract": "computer science research",
                }]
            }
            return FakeResponse(payload=payload), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        with patch("paperseek_core.sources.paperhub.get_with_retries", fake_get):
            provider = PaperHubProvider()
            result = provider.search("conference:ICML year:2026", limit=10)

        self.assertEqual(result.metadata.total, 1)
        self.assertEqual(result.hits[0].uid, "ICML-2026")
        self.assertEqual(len(PaperHubProvider._paper_cache), 7)
        self.assertIn("2026-07-20T15:35:26+08:00", provider.last_response_info["manifest_version"])

    def test_paperhub_provider_never_caches_a_partial_snapshot(self):
        manifest = {
            "built_at": "2026-07-20T15:35:26+08:00",
            "shards": [
                {"count": 1, "file": "shards/good.fake.json"},
                {"count": 1, "file": "shards/broken.fake.json"},
            ],
        }

        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            if url.endswith("manifest.json"):
                return FakeResponse(payload=manifest), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            if url.endswith("good.fake.json"):
                return FakeResponse(payload={"papers": [{"id": "good", "title": "Good", "authors": ["Ada"]}]}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            return FakeResponse(status_code=503, text="unavailable"), {"method": "GET", "url": url, "status": 503, "elapsed_ms": 1}

        with patch("paperseek_core.sources.paperhub.get_with_retries", fake_get):
            with self.assertRaisesRegex(ProviderError, "broken.fake.json returned HTTP 503"):
                PaperHubProvider().search("graph", limit=10)

        self.assertIsNone(PaperHubProvider._paper_cache)

    def test_paperhub_provider_revalidates_unchanged_manifest_without_redownloading_shards(self):
        calls = []
        manifest = {
            "built_at": "2026-07-20T15:35:26+08:00",
            "shards": [{"count": 1, "file": "shards/icml-2026.fake.json"}],
        }

        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            calls.append(url)
            if url.endswith("manifest.json"):
                return FakeResponse(payload=manifest), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}
            return FakeResponse(payload={"papers": [{"id": "p1", "title": "Graph Retrieval", "authors": ["Ada"]}]}), {"method": "GET", "url": url, "status": 200, "elapsed_ms": 1}

        with patch("paperseek_core.sources.paperhub.get_with_retries", fake_get):
            provider = PaperHubProvider()
            provider.search("graph", limit=1)
            PaperHubProvider._paper_cache_loaded_at = time.monotonic() - provider.CACHE_TTL_SECONDS - 1
            provider.search("graph", limit=1)

        self.assertEqual(sum(url.endswith("manifest.json") for url in calls), 2)
        self.assertEqual(sum(url.endswith("icml-2026.fake.json") for url in calls), 1)
        self.assertTrue(provider.last_response_info["cache_revalidated"])

    def test_paperhub_provider_uses_last_complete_snapshot_when_refresh_fails(self):
        PaperHubProvider._paper_cache = [{"id": "cached", "title": "Graph Retrieval", "authors": ["Ada"]}]
        PaperHubProvider._paper_cache_loaded_at = (
            time.monotonic() - PaperHubProvider.CACHE_TTL_SECONDS - 1
        )
        PaperHubProvider._paper_cache_manifest_version = "old"

        def fake_get(provider, url, params=None, headers=None, timeout=0, query=""):
            return FakeResponse(status_code=503, text="unavailable"), {"method": "GET", "url": url, "status": 503, "elapsed_ms": 1}

        with patch("paperseek_core.sources.paperhub.get_with_retries", fake_get):
            provider = PaperHubProvider()
            result = provider.search("graph", limit=1)

        self.assertEqual(result.hits[0].uid, "cached")
        self.assertEqual(provider.last_response_info["status"], "stale_cache")



class TestReconstructAbstract(unittest.TestCase):
    def test_none_input(self):
        self.assertEqual(reconstruct_abstract(None), "")

    def test_empty_dict(self):
        self.assertEqual(reconstruct_abstract({}), "")

    def test_standard_inverted_index(self):
        index = {"hello": [0], "world": [1]}
        self.assertEqual(reconstruct_abstract(index), "hello world")

    def test_word_multiple_times(self):
        index = {"a": [0, 2], "test": [1]}
        self.assertEqual(reconstruct_abstract(index), "a test a")

    def test_invalid_values(self):
        # "invalid" has an invalid list
        # "world" has a valid index 1
        # "ignored" has invalid inner values
        index = {
            "invalid": "not a list",
            "world": [1],
            "hello": [0],
            "ignored": ["string", 2.5]
        }
        self.assertEqual(reconstruct_abstract(index), "hello world")

    def test_no_valid_positions(self):
        index = {"invalid": "not a list", "ignored": ["str"]}
        self.assertEqual(reconstruct_abstract(index), "")

if __name__ == "__main__":
    unittest.main()
