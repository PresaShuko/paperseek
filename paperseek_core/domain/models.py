from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PaperAuthor:
    display_name: str = ""
    wos_standard: str = ""
    researcher_id: str = ""


@dataclass
class PaperNames:
    authors: List[PaperAuthor] = field(default_factory=list)


@dataclass
class PaperSource:
    source_title: str = ""
    publish_year: Optional[int] = None
    publish_month: str = ""
    volume: str = ""
    issue: str = ""
    pages: Any = None


@dataclass
class PaperLinks:
    record: str = ""
    citing_articles: str = ""
    references: str = ""
    related: str = ""
    landing_page: str = ""
    pdf: str = ""


@dataclass
class PaperCitation:
    db: str = ""
    count: int = 0


@dataclass
class PaperIdentifiers:
    doi: str = ""
    issn: str = ""
    eissn: str = ""
    isbn: str = ""
    eisbn: str = ""
    pmid: str = ""
    openalex: str = ""
    arxiv: str = ""
    semanticscholar: str = ""


@dataclass
class PaperKeywords:
    author_keywords: List[str] = field(default_factory=list)


@dataclass
class PaperRecord:
    uid: str
    title: str = ""
    types: List[str] = field(default_factory=list)
    source_types: List[str] = field(default_factory=list)
    source: Optional[PaperSource] = None
    names: Optional[PaperNames] = None
    links: Optional[PaperLinks] = None
    citations: List[PaperCitation] = field(default_factory=list)
    identifiers: Optional[PaperIdentifiers] = None
    keywords: Optional[PaperKeywords] = None
    abstract: str = ""
    provider: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
