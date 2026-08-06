import unittest

from pydantic import ValidationError

from paperseek.api.schemas import SearchRequest
from paperseek.web_app import app


class ApiSchemaContractTest(unittest.TestCase):
    def test_openapi_routes_reference_canonical_request_components(self):
        schema = app.openapi()
        components = schema["components"]["schemas"]

        self.assertIn("SearchRequest", components)
        self.assertEqual(components["SearchRequest"]["required"], ["question"])
        self.assertIn("data_source", components["SearchRequest"]["properties"])
        self.assertEqual(
            schema["paths"]["/api/search"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/SearchRequest",
        )
        self.assertEqual(
            schema["paths"]["/api/diagnostics"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/DiagnosticRequest",
        )

    def test_search_request_preserves_boundary_validation(self):
        self.assertEqual(SearchRequest(question="  open innovation  ").question, "open innovation")

        with self.assertRaises(ValidationError):
            SearchRequest(question="   ")
        with self.assertRaises(ValidationError):
            SearchRequest(question="test", data_source="unknown")


if __name__ == "__main__":
    unittest.main()
