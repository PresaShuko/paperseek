"""Small, independently implemented models for WoS Starter responses."""

from __future__ import annotations

import json
import pprint
from typing import Any, Dict, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


ModelT = TypeVar("ModelT", bound="WosModel")


class WosModel(BaseModel):
    """Shared serialization helpers for the public PaperSeek WoS models."""

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        extra="ignore",
        protected_namespaces=(),
    )

    def to_str(self) -> str:
        return pprint.pformat(self.to_dict())

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls: type[ModelT], value: str) -> ModelT:
        return cls.from_dict(json.loads(value))

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)

    @classmethod
    def from_dict(cls: type[ModelT], value: Any) -> Optional[ModelT]:
        if value is None:
            return None
        return cls.model_validate(value)


class AuthorName(WosModel):
    display_name: Optional[str] = Field(default=None, alias="displayName")
    wos_standard: Optional[str] = Field(default=None, alias="wosStandard")
    researcher_id: Optional[str] = Field(default=None, alias="researcherId")


class OtherName(AuthorName):
    pass


class DocumentCitationsInner(WosModel):
    db: Optional[str] = None
    count: Optional[int] = None


class DocumentIdentifiers(WosModel):
    doi: Optional[str] = None
    issn: Optional[str] = None
    eissn: Optional[str] = None
    isbn: Optional[str] = None
    eisbn: Optional[str] = None
    pmid: Optional[str] = None


class DocumentKeywords(WosModel):
    author_keywords: Optional[List[str]] = Field(default=None, alias="authorKeywords")


class DocumentLinks(WosModel):
    record: Optional[str] = None
    citing_articles: Optional[str] = Field(default=None, alias="citingArticles")
    references: Optional[str] = None
    related: Optional[str] = None


class DocumentNames(WosModel):
    authors: Optional[List[AuthorName]] = None
    editors: Optional[List[OtherName]] = None
    corp: Optional[List[OtherName]] = None
    inventors: Optional[List[OtherName]] = None
    books: Optional[List[OtherName]] = None
    anonymous: Optional[List[OtherName]] = None
    assignees: Optional[List[OtherName]] = None
    investigators: Optional[List[OtherName]] = None
    sponsors: Optional[List[OtherName]] = None
    book_corp: Optional[List[OtherName]] = Field(default=None, alias="bookCorp")
    additional_authors: Optional[List[OtherName]] = Field(default=None, alias="additionalAuthors")
    book_editors: Optional[List[OtherName]] = Field(default=None, alias="bookEditors")
    issuing_organizations: Optional[List[OtherName]] = Field(default=None, alias="issuingOrganizations")


class DocumentSourcePages(WosModel):
    range: Optional[str] = None
    begin: Optional[str] = None
    end: Optional[str] = None
    count: Optional[int] = None


class DocumentSource(WosModel):
    source_title: Optional[str] = Field(default=None, alias="sourceTitle")
    publish_year: Optional[int] = Field(default=None, alias="publishYear")
    publish_month: Optional[str] = Field(default=None, alias="publishMonth")
    volume: Optional[str] = None
    issue: Optional[str] = None
    supplement: Optional[str] = None
    special_issue: Optional[str] = Field(default=None, alias="specialIssue")
    article_number: Optional[str] = Field(default=None, alias="articleNumber")
    pages: Optional[DocumentSourcePages] = None


class Metadata(WosModel):
    page: Optional[int] = None
    limit: Optional[int] = None
    total: Optional[int] = None


class Document(WosModel):
    uid: str
    title: Optional[str] = None
    types: Optional[List[str]] = None
    source_types: Optional[List[str]] = Field(default=None, alias="sourceTypes")
    source: Optional[DocumentSource] = None
    names: Optional[DocumentNames] = None
    links: Optional[DocumentLinks] = None
    citations: Optional[List[DocumentCitationsInner]] = None
    identifiers: Optional[DocumentIdentifiers] = None
    keywords: Optional[DocumentKeywords] = None


class DocumentsList(WosModel):
    metadata: Optional[Metadata] = None
    hits: Optional[List[Document]] = None
