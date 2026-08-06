import unittest
from types import SimpleNamespace

from paperseek_core.query_contract import QueryContractGuard
from paperseek_core.sources.contracts import ProviderError


class QueryContractGuardTest(unittest.TestCase):
    @staticmethod
    def _host(source="openalex", llm=None):
        host = SimpleNamespace(
            data_source=source,
            llm=llm,
            last_query_audit="",
            logs=[],
        )
        host._apply_discipline_filter = lambda query: query
        host._source_label = lambda: "OpenAlex" if source == "openalex" else source
        host._emit_log = host.logs.append
        host._run_cancellable = lambda operation: operation()
        host._intent_context = lambda: ""
        host._discipline_context = lambda: ""
        host._llm_request_log = lambda purpose: None
        host._llm_response_log = lambda purpose: None
        return host

    def test_finalize_parses_audit_and_sanitizes_source_query(self):
        host = self._host()
        guard = QueryContractGuard(host)

        query = guard.finalize(
            "AI governance",
            '{"query":"search=(AI govern*)", "rationale":"Removed unsupported syntax."}',
        )

        self.assertEqual(query, "(AI govern)")
        self.assertEqual(host.last_query_audit, "Removed unsupported syntax.")
        self.assertEqual(host.logs, [])

    def test_finalize_keeps_previous_query_when_bounded_retry_fails(self):
        host = self._host()
        guard = QueryContractGuard(host)
        guard.retry_malformed = lambda *args, **kwargs: ""

        query = guard.finalize(
            "AI governance",
            "Let's finalize: AI governance",
            current_query="AI governance policy",
        )

        self.assertEqual(query, "AI governance policy")
        self.assertEqual(host.last_query_audit, "")
        self.assertEqual(len(host.logs), 1)

    def test_chat_json_preserves_zero_temperature_and_token_limit(self):
        calls = []

        class JsonLLM:
            def chat_json(self, messages, *, temperature, max_tokens):
                calls.append((messages, temperature, max_tokens))
                return '{"query":"AI governance", "rationale":"ok"}'

        host = self._host(llm=JsonLLM())

        result = QueryContractGuard(host).chat_json([{"role": "user", "content": "query"}])

        self.assertIn("AI governance", result)
        self.assertEqual(calls[0][1:], (0.0, 2048))

    def test_provider_syntax_errors_are_repairable_but_auth_errors_are_not(self):
        self.assertTrue(
            QueryContractGuard.is_repairable_provider_error(
                ProviderError("openalex", "Invalid query parameters", status=400)
            )
        )
        self.assertFalse(
            QueryContractGuard.is_repairable_provider_error(
                ProviderError("openalex", "Authentication failed", status=401)
            )
        )


if __name__ == "__main__":
    unittest.main()
