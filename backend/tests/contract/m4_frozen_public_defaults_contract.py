from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from paperseek_community.cli import _parser
from paperseek_community.composition import CommunityExecutionResolver
from paperseek_community.settings import CommunityDeploymentSettings
from paperseek_core.execution import NEVER_CANCELLED
from paperseek_app.submission import (
    LLMRouteInput,
    RunSubmission,
    SubmissionValidationError,
    prepare_run_submission,
)


def settings() -> CommunityDeploymentSettings:
    return CommunityDeploymentSettings(
        llm_api_type="openai_responses",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-5.4-mini",
        llm_api_key="",
        openalex_api_key="",
        semantic_scholar_api_key="",
        pubmed_api_key="",
        wos_api_key="",
        google_scholar_api_key="",
        contact_email="",
    )


class M4FrozenPublicDefaultsContract(unittest.TestCase):
    def test_each_budget_reaches_the_workflow_with_frozen_limits(self) -> None:
        # Frozen SearchBudgetPreset values, checked at the product composition boundary.
        fields = ("max_iterations", "query_portfolio_max", "query_portfolio_limit",
                  "retrieval_lane_limit", "retrieval_pool_max", "ranking_candidate_limit",
                  "citation_seed_count", "citation_per_seed", "citation_max_records", "citation_depth")
        presets = {
            "fast": (5, 3, 100, 500, 3000, 256, 3, 4, 40, 2),
            "medium": (7, 3, 100, 750, 4500, 384, 8, 6, 80, 2),
            "high": (9, 4, 100, 1000, 7000, 512, 16, 8, 160, 3),
            "max": (12, 6, 100, 1000, 10000, 1024, 30, 10, 320, 3),
        }

        async def check():
            resolver = CommunityExecutionResolver(settings(), SimpleNamespace(resolve=lambda _id: {}))
            for name, values in presets.items():
                with self.subTest(budget=name):
                    prepared = prepare_run_submission(RunSubmission(question="limits", search_budget=name), settings())
                    run = SimpleNamespace(id="controlled", source=prepared.source, question=prepared.question,
                                          config_snapshot=prepared.config_snapshot)
                    execution = resolver(run, NEVER_CANCELLED)
                    try:
                        request, query = execution.request, execution.request.query_budget
                        for field, expected in zip(fields, values):
                            self.assertEqual(getattr(request if field.startswith("citation_") else query, field), expected)
                        self.assertEqual((query.target_min, query.target_max, query.retrieval_pool_min), (5, 50, 5))
                        self.assertTrue(query.query_portfolio_enabled)
                    finally:
                        await execution.close()

        asyncio.run(check())

    def test_omitted_public_options_preserve_frozen_defaults(self) -> None:
        prepared = prepare_run_submission(
            RunSubmission(question="  evidence synthesis  "),
            settings(),
        )

        self.assertEqual(prepared.question, "evidence synthesis")
        self.assertEqual(prepared.source, "openalex")
        self.assertEqual(prepared.config_snapshot["question"], "evidence synthesis")
        self.assertEqual(prepared.config_snapshot["search_budget"], "fast")
        self.assertTrue(prepared.config_snapshot["citation_enabled"])
        self.assertFalse(prepared.config_snapshot["fetch_abstracts"])
        self.assertEqual(
            prepared.config_snapshot["llm"],
            {
                "provider": "openai",
                "api_type": "openai_responses",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-5.4-mini",
            },
        )

    def test_omitted_citation_option_follows_source_capability(self) -> None:
        arxiv = prepare_run_submission(
            RunSubmission(question="evidence synthesis", source="arxiv"),
            settings(),
        )
        disabled = prepare_run_submission(
            RunSubmission(
                question="evidence synthesis",
                source="openalex",
                citation_enabled=False,
            ),
            settings(),
        )

        self.assertFalse(arxiv.config_snapshot["citation_enabled"])
        self.assertFalse(disabled.config_snapshot["citation_enabled"])
        with self.assertRaises(SubmissionValidationError) as raised:
            prepare_run_submission(
                RunSubmission(
                    question="evidence synthesis",
                    source="arxiv",
                    citation_enabled=True,
                ),
                settings(),
            )
        self.assertEqual(raised.exception.code, "unsupported_source_capability")

    def test_abstract_enrichment_is_explicit_and_part_of_run_identity(self) -> None:
        omitted = prepare_run_submission(RunSubmission(question="evidence synthesis"), settings())
        disabled = prepare_run_submission(
            RunSubmission(question="evidence synthesis", fetch_abstracts=False), settings()
        )
        enabled = prepare_run_submission(
            RunSubmission(question="evidence synthesis", fetch_abstracts=True), settings()
        )
        self.assertEqual(omitted.config_snapshot, disabled.config_snapshot)
        self.assertEqual(omitted.request_digest, disabled.request_digest)
        self.assertTrue(enabled.config_snapshot["fetch_abstracts"])
        self.assertNotEqual(enabled.request_digest, disabled.request_digest)

    def test_public_values_are_normalized_and_blank_question_is_rejected(self) -> None:
        prepared = prepare_run_submission(
            RunSubmission(
                question="  evidence synthesis  ",
                source=" OpenAlex ",
                search_budget=" FAST ",
                llm=LLMRouteInput(provider=" ANTHROPIC "),
            ),
            settings(),
        )

        self.assertEqual(prepared.source, "openalex")
        self.assertEqual(prepared.config_snapshot["search_budget"], "fast")
        self.assertEqual(
            prepared.config_snapshot["llm"],
            {
                "provider": "anthropic",
                "api_type": "anthropic_messages",
                "base_url": "https://api.anthropic.com",
                "model": "claude-sonnet-4-6",
            },
        )
        with self.assertRaises(SubmissionValidationError) as raised:
            prepare_run_submission(RunSubmission(question="   "), settings())
        self.assertEqual(raised.exception.code, "invalid_question")

    def test_unknown_llm_provider_is_rejected_by_submission_contract(self) -> None:
        with self.assertRaises(SubmissionValidationError) as raised:
            prepare_run_submission(
                RunSubmission(
                    question="evidence synthesis",
                    llm=LLMRouteInput(provider="not-a-provider"),
                ),
                settings(),
            )
        self.assertEqual(raised.exception.code, "unsupported_llm_provider")

    def test_formal_cli_uses_the_same_frozen_omission_semantics(self) -> None:
        args = _parser().parse_args(["search", "evidence synthesis"])

        self.assertEqual(args.source, "openalex")
        self.assertEqual(args.search_budget, "fast")
        self.assertIsNone(args.citation_enabled)
        self.assertFalse(args.fetch_abstracts)
        enabled = _parser().parse_args(["search", "evidence synthesis", "--fetch-abstracts"])
        self.assertTrue(enabled.fetch_abstracts)


if __name__ == "__main__":
    unittest.main()
