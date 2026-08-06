import unittest
from pathlib import Path

from paperseek_core.client import ApiClient, ApiException, Configuration, DocumentsApi
from paperseek_core.client.models import DocumentNames, DocumentsList, OtherName


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload, status_code=200, reason="OK"):
        self._payload = payload
        self.status_code = status_code
        self.reason = reason
        self.text = "response body"
        self.content = self.text.encode("utf-8")
        self.headers = {"content-type": "application/json"}

    def json(self):
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


class WosClientModelTest(unittest.TestCase):
    def test_other_name_payload_can_be_instantiated(self):
        names = DocumentNames.from_dict(
            {
                "authors": [{"displayName": "Ada Lovelace", "wosStandard": "Lovelace, Ada"}],
                "editors": [{"displayName": "Grace Hopper"}],
                "bookCorp": [{"displayName": "Research Press"}],
            }
        )

        self.assertEqual(names.authors[0].display_name, "Ada Lovelace")
        self.assertIsInstance(names.editors[0], OtherName)
        self.assertEqual(names.editors[0].display_name, "Grace Hopper")
        self.assertEqual(names.book_corp[0].display_name, "Research Press")

    def test_documents_list_resolves_nested_models_without_future_annotations(self):
        payload = {
            "metadata": {"page": 1, "limit": 10, "total": 1},
            "hits": [
                {
                    "uid": "WOS:1",
                    "title": "A test record",
                    "names": {"editors": [{"displayName": "Grace Hopper"}]},
                }
            ],
        }

        documents = DocumentsList.from_dict(payload)

        self.assertEqual(documents.hits[0].uid, "WOS:1")
        self.assertEqual(documents.hits[0].names.editors[0].display_name, "Grace Hopper")

    def test_documents_api_sends_auth_and_wos_parameter_names(self):
        client = ApiClient(Configuration(api_key={"ClarivateApiKeyAuth": "test-key"}))
        client.session = FakeSession(
            [FakeResponse({"metadata": {"total": 1}, "hits": [{"uid": "WOS:1", "title": "Result"}]})]
        )

        result = DocumentsApi(client).documents_get(
            q="TS=(governance)",
            db="WOS",
            limit=100,
            page=2,
            sort_field="RS+D",
        )

        method, url, kwargs = client.session.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.clarivate.com/apis/wos-starter/v1/documents")
        self.assertEqual(kwargs["headers"]["X-ApiKey"], "test-key")
        self.assertEqual(
            kwargs["params"],
            {"q": "TS=(governance)", "db": "WOS", "limit": 50, "page": 2, "sortField": "RS+D"},
        )
        self.assertEqual(result.metadata.total, 1)
        self.assertEqual(result.hits[0].title, "Result")

    def test_documents_api_preserves_http_error_details(self):
        client = ApiClient(Configuration(api_key={"ClarivateApiKeyAuth": "bad-key"}))
        client.session = FakeSession([FakeResponse({"error": "invalid"}, status_code=401, reason="Unauthorized")])

        with self.assertRaises(ApiException) as raised:
            DocumentsApi(client).documents_get(q="TS=(governance)")

        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.reason, "Unauthorized")
        self.assertEqual(raised.exception.body, "response body")

    def test_documents_api_omits_limit_when_caller_does_not_set_it(self):
        client = ApiClient(Configuration(api_key={"ClarivateApiKeyAuth": "test-key"}))
        client.session = FakeSession([FakeResponse({"metadata": {"total": 0}, "hits": []})])

        DocumentsApi(client).documents_get(q="TS=(governance)", db="WOS")

        self.assertEqual(client.session.calls[0][2]["params"], {"q": "TS=(governance)", "db": "WOS"})

    def test_uid_endpoint_parses_single_document(self):
        client = ApiClient(Configuration(api_key={"ClarivateApiKeyAuth": "test-key"}))
        client.session = FakeSession([FakeResponse({"uid": "WOS:2", "title": "Single result"})])

        result = DocumentsApi(client).documents_uid_get("WOS:2", db="WOS", detail="full")

        self.assertEqual(result.uid, "WOS:2")
        self.assertEqual(client.session.calls[0][1], "https://api.clarivate.com/apis/wos-starter/v1/documents/WOS:2")
        self.assertEqual(client.session.calls[0][2]["params"], {"db": "WOS", "detail": "full"})

    def test_uid_http_variants_preserve_detail_parameter(self):
        payload = {"uid": "WOS:3", "title": "Detailed result"}
        client = ApiClient(Configuration(api_key={"ClarivateApiKeyAuth": "test-key"}))
        client.session = FakeSession([FakeResponse(payload), FakeResponse(payload)])
        api = DocumentsApi(client)

        response = api.documents_uid_get_with_http_info(uid="WOS:3", db="WOS", detail="short")
        raw = api.documents_uid_get_without_preload_content(uid="WOS:3", detail="full")

        self.assertEqual(response.data.uid, "WOS:3")
        self.assertEqual(raw.status_code, 200)
        self.assertEqual(client.session.calls[0][2]["params"], {"db": "WOS", "detail": "short"})
        self.assertEqual(client.session.calls[1][2]["params"], {"detail": "full"})

    def test_wos_adapter_does_not_ship_generated_client_templates(self):
        client_dir = ROOT / "paperseek_core" / "client"
        source = "\n".join(path.read_text(encoding="utf-8") for path in client_dir.glob("*.py"))

        self.assertNotIn("This class is auto generated by OpenAPI Generator", source)
        self.assertNotIn("clarivate.wos_starter.client", source)


if __name__ == "__main__":
    unittest.main()
