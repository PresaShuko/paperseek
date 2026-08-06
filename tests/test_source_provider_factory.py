import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paperseek_core.sources.factory import create_source_provider


class SourceProviderFactoryTest(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            openalex_api_key="openalex-key",
            openalex_email="openalex@example.org",
            crossref_email="crossref@example.org",
            semantic_scholar_api_key="semantic-key",
            pubmed_api_key="pubmed-key",
            pubmed_email="pubmed@example.org",
            pubmed_tool="paperseek-test",
            serper_api_key="serper-key",
            wos_api_key="wos-key",
            wos_db="WOK",
        )

    def test_forwards_source_specific_configuration(self):
        cases = (
            ("openalex", "OpenAlexProvider", {"api_key": "openalex-key", "email": "openalex@example.org"}),
            ("crossref", "CrossrefProvider", {"email": "crossref@example.org"}),
            ("semanticscholar", "SemanticScholarProvider", {"api_key": "semantic-key"}),
            (
                "pubmed",
                "PubMedProvider",
                {"api_key": "pubmed-key", "email": "pubmed@example.org", "tool": "paperseek-test"},
            ),
            ("googlescholar", "GoogleScholarSerperProvider", {"api_key": "serper-key"}),
        )
        for source, constructor_name, expected_kwargs in cases:
            with self.subTest(source=source), patch(
                f"paperseek_core.sources.factory.{constructor_name}"
            ) as constructor:
                create_source_provider(self.config, source)
                constructor.assert_called_once_with(**expected_kwargs)

    def test_constructs_parameterless_sources(self):
        for source, constructor_name in (("arxiv", "ArxivProvider"), ("paperhub", "PaperHubProvider")):
            with self.subTest(source=source), patch(
                f"paperseek_core.sources.factory.{constructor_name}"
            ) as constructor:
                create_source_provider(self.config, source)
                constructor.assert_called_once_with()

    def test_wos_remains_the_default_adapter(self):
        log = Mock()
        with patch("paperseek_core.sources.factory.WosProvider") as constructor:
            create_source_provider(self.config, "unknown", log=log)
            constructor.assert_called_once_with(api_key="wos-key", db="WOK", log=log)


if __name__ == "__main__":
    unittest.main()
