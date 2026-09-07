from types import SimpleNamespace
import unittest
from uuid import uuid4

from pydantic import ValidationError

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

    def test_service_choice_is_explicit_and_part_of_the_same_request_digest(self):
        connection_id = str(uuid4())
        choices = ({"mode": "paperseek"}, {"mode": "byok"},
                   {"mode": "third_party", "connection_id": connection_id})
        default = prepare_run_submission(RunSubmission(question="evidence"), self.defaults)
        null = prepare_run_submission(RunSubmission(question="evidence", service=None), self.defaults)
        self.assertEqual(default, null)
        self.assertNotIn("service_mode", default.config_snapshot)
        digests = {default.request_digest}
        for choice in choices:
            with self.subTest(choice=choice):
                prepared = prepare_run_submission(RunSubmission(question="evidence", service=choice,
                    credentials={"llm": {"api_key": "not-in-snapshot"}}), self.defaults)
                self.assertEqual(prepared.config_snapshot["service_mode"], choice["mode"])
                if choice["mode"] == "third_party":
                    self.assertEqual(prepared.config_snapshot["connection_id"], connection_id)
                else:
                    self.assertNotIn("connection_id", prepared.config_snapshot)
                self.assertNotIn("not-in-snapshot", str(prepared))
                self.assertNotIn(prepared.request_digest, digests)
                digests.add(prepared.request_digest)
        another = prepare_run_submission(RunSubmission(question="evidence",
            service={"mode": "third_party", "connection_id": str(uuid4())}), self.defaults)
        self.assertNotIn(another.request_digest, digests)

    def test_service_choice_rejects_ambiguous_or_invalid_connection_selection(self):
        for choice in ({"mode": "auto"}, {"mode": "third_party"},
                       {"mode": "third_party", "connection_id": "not-a-uuid"},
                       {"mode": "paperseek", "connection_id": str(uuid4())},
                       {"mode": "byok", "connection_id": str(uuid4())}):
            with self.subTest(choice=choice), self.assertRaises(ValidationError):
                RunSubmission(question="evidence", service=choice)
