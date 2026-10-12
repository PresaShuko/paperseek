from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from paperseek_core import query_loop
from paperseek_core.query_parsing import parse_search_plan

try:
    from paperseek_core import query_compiler
except ImportError:
    query_compiler = None


ROOT = Path(__file__).resolve().parents[3]
QUESTION = "How do transparent AI decision systems affect accountability in public agencies?"


class QueryValidationCompilerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = parse_search_plan(
            (ROOT / "tests" / "fixtures" / "llm" / "intent_search_plan.json").read_text(
                encoding="utf-8"
            ),
            QUESTION,
        )
        assert cls.plan is not None

    def test_validation_and_compilation_have_one_module_owner(self) -> None:
        self.assertIsNotNone(query_compiler)
        self.assertNotIn("compile_query_view", query_loop.__dict__)
        self.assertIs(query_loop.validate_source_query, query_compiler.validate_source_query)
        self.assertNotIn("strict_query_output_instruction", query_loop.__dict__)

    def test_eight_source_compilers_remain_exact(self) -> None:
        expected = {
            "arxiv": '(all:"AI decision systems" OR all:"automated decision systems") AND (all:accountability OR all:"algorithmic accountability")',
            "crossref": "AI decision systems automated decision systems accountability algorithmic accountability",
            "googlescholar": '("AI decision systems" OR "automated decision systems") (accountability OR "algorithmic accountability")',
            "openalex": '("AI decision systems" OR "automated decision systems") AND (accountability OR "algorithmic accountability")',
            "paperhub": '"AI decision systems" OR "automated decision systems" accountability OR "algorithmic accountability"',
            "pubmed": '("AI decision systems"[Title/Abstract] OR "automated decision systems"[Title/Abstract]) AND (accountability[Title/Abstract] OR "algorithmic accountability"[Title/Abstract])',
            "semanticscholar": "AI decision systems automated decision systems accountability algorithmic accountability",
            "wos": 'TS=(("AI decision systems" OR "automated decision systems") AND (accountability OR "algorithmic accountability"))',
        }

        for source, query in expected.items():
            with self.subTest(source=source):
                compiled = query_compiler.compile_query_view(source, self.plan.query_views[0])
                self.assertEqual(compiled.query, query)
                self.assertTrue(query_loop.validate_source_query(source, query).ok)

    def test_validation_failure_codes_and_openalex_length_boundary_remain_exact(self) -> None:
        cases = (
            ("openalex", "", "missing query field in JSON response"),
            ("unknown", "query", "unsupported data source: unknown"),
            (
                "openalex",
                '"AI governance" AND (accountability OR',
                "unbalanced quotation marks, parentheses, or trailing Boolean operator",
            ),
            (
                "arxiv",
                "all:test\nall:second",
                "query contains control characters or multiple lines",
            ),
            (
                "openalex",
                "search=query&page=1",
                "query must contain only the source query value, not a URL or API parameter",
            ),
            (
                "crossref",
                "governance AND accountability",
                "crossref relevance search requires plain text, not Boolean operators",
            ),
            (
                "googlescholar",
                "governance AND accountability",
                "googlescholar uses implicit AND with OR groups and minus exclusions",
            ),
            (
                "openalex",
                "governance AND accountability OR transparency",
                "OpenAlex mixed top-level AND/OR requires each OR synonym group to be parenthesized",
            ),
            (
                "openalex",
                "governance*",
                "OpenAlex search= does not accept wildcard syntax; use complete terms",
            ),
            (
                "arxiv",
                "title:governance",
                "arXiv field prefixes must use all:, ti:, abs:, au:, cat:, id:, jr:, co:, or rn:",
            ),
            (
                "pubmed",
                "all:governance",
                "PubMed fields must use bracketed tags such as [Title/Abstract]",
            ),
        )
        for source, query, issue in cases:
            with self.subTest(source=source, issue=issue):
                result = query_loop.validate_source_query(source, query)
                self.assertFalse(result.ok)
                self.assertEqual(result.issue, issue)

        long_query = " ".join(f"term{index}" for index in range(600))
        result = query_loop.validate_source_query("openalex", long_query)
        self.assertFalse(result.ok)
        self.assertEqual(
            result.issue,
            "OpenAlex search query is too long for a safe request URL; use fewer established terms or split the search into query views",
        )

    def test_source_safe_normalization_remains_exact(self) -> None:
        self.assertEqual(
            query_compiler.source_safe_query("semanticscholar", "cross-modal retrieval"),
            "cross modal retrieval",
        )
        self.assertEqual(
            query_compiler.source_safe_query(
                "openalex",
                "search = (AI* AND accountability) AND (AI* AND accountability) filter=x",
            ),
            "(AI AND accountability)",
        )
        self.assertEqual(query_compiler.source_safe_query("arxiv", " all:test "), "all:test")

    def test_output_instruction_hashes_remain_exact(self) -> None:
        expected = {
            "OpenAlex search query string": "54411C0F37310EC600A16F954969CF3F49A7FD04EB73FB09593224F62F1A7A37",
            "broadened OpenAlex search query string": "34A138CEF77C0AF917129405A2968202901346E64864BE427A45501BACCB1423",
            "narrowed OpenAlex search query string": "CD2AFBB08667219ED795233E990622541586A574DB642E0457FFA3945AE9A727",
        }
        for label, digest in expected.items():
            with self.subTest(label=label):
                instruction = query_compiler.strict_query_output_instruction(label)
                self.assertEqual(
                    hashlib.sha256(instruction.encode("utf-8")).hexdigest().upper(),
                    digest,
                )


if __name__ == "__main__":
    unittest.main()
