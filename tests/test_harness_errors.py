import unittest

from paperseek_core.harness import classify_error
from paperseek_core.sources.contracts import ProviderError


class HarnessErrorTest(unittest.TestCase):
    def test_classify_error_records_status_and_retryability(self):
        exc = ProviderError("openalex", "rate limited", status=429, query="AI governance")

        observation = classify_error(exc, stage="source_search", source="openalex", query="AI governance")

        self.assertEqual(observation.stage, "source_search")
        self.assertEqual(observation.source, "openalex")
        self.assertEqual(observation.status, 429)
        self.assertTrue(observation.retryable)

    def test_classify_error_redacts_credentials(self):
        secret = "sk-secret-abcdef123456"
        exc = ProviderError(
            "openalex",
            f"Authorization: Bearer {secret}",
            status=401,
            body=f"x-api-key: {secret}",
            query="AI governance",
        )

        observation = classify_error(exc, stage="source_search", source="openalex", query="AI governance")

        self.assertNotIn(secret, observation.message)
        self.assertIn("[redacted]", observation.message)


if __name__ == "__main__":
    unittest.main()
