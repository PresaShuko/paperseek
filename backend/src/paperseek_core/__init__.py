"""Research-core package boundary for the v0.3.0 cutover."""

from paperseek_core.models import (
    PaperAuthor,
    PaperCitation,
    PaperIdentifiers,
    PaperKeywords,
    PaperLinks,
    PaperNames,
    PaperRecord,
    PaperSource,
)

__version__ = "0.3.0"

__all__ = [
    "PaperAuthor",
    "PaperCitation",
    "PaperIdentifiers",
    "PaperKeywords",
    "PaperLinks",
    "PaperNames",
    "PaperRecord",
    "PaperSource",
    "__version__",
]
