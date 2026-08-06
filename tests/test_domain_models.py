from paperseek_core.domain import PaperAuthor, PaperNames, PaperRecord
from paperseek_core.sources.providers import PaperRecord as CompatibilityPaperRecord


def test_provider_facade_reexports_canonical_paper_record():
    assert CompatibilityPaperRecord is PaperRecord


def test_paper_record_mutable_defaults_are_isolated():
    first = PaperRecord(uid="first")
    second = PaperRecord(uid="second")
    first.types.append("article")
    first.names = PaperNames(authors=[PaperAuthor(display_name="Ada")])

    assert second.types == []
    assert second.names is None
