from types import SimpleNamespace
import unittest

from paperseek_app.submission import RunSubmission, SubmissionValidationError, prepare_run_submission


class SharedSubmissionTests(unittest.TestCase):
    def setUp(self):
        # Hosted supplies deployment defaults, not a Community environment reader or credentials.
        self.defaults = SimpleNamespace(llm_api_type="openai_responses", llm_base_url="https://api.openai.com/v1",
                                        llm_model="gpt-5.4-mini", wos_db="WOS")

    def test_equivalent_inputs_share_effective_config_digest_and_exclude_credentials(self):
        first = prepare_run_submission(RunSubmission(question="  evidence  ", source=" OpenAlex ",
                                                      credentials={"llm": {"api_key": "private-test-key"}}), self.defaults)
        second = prepare_run_submission(RunSubmission(question="evidence", source="openalex"), self.defaults)
        self.assertEqual(first, second)
        self.assertEqual(first.config_snapshot["llm"], {"provider": "openai", "api_type": "openai_responses",
                                                       "base_url": "https://api.openai.com/v1", "model": "gpt-5.4-mini"})
        self.assertEqual(first.config_snapshot["wos_db"], "WOS")
        self.assertNotIn("private-test-key", str(first))

    def test_shared_validation_retains_public_error_codes_and_source_capabilities(self):
        for values, code in (({"question": " "}, "invalid_question"),
                             ({"source": "missing"}, "unsupported_source"),
                             ({"source": "arxiv", "citation_enabled": True}, "unsupported_source_capability")):
            with self.subTest(code=code), self.assertRaises(SubmissionValidationError) as caught:
                prepare_run_submission(RunSubmission.model_validate({"question": "evidence"} | values), self.defaults)
            self.assertEqual(caught.exception.code, code)
