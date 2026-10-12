from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from paperseek_core.models import PaperRecord
from paperseek_core.sources.contracts import (
    SourceCapabilities,
    SourceSearchMetadata,
    SourceSearchRequest,
    SourceSearchResult,
)


class FixedSourceFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    fixture_id: str
    source: str
    question: str
    records: list[PaperRecord]
    llm_responses: list[str] = Field(default_factory=list)
    expected: dict


class FixedSourceAdapter:
    capabilities = SourceCapabilities(
        source="fixed",
        lanes=("relevance",),
        metadata_fields=("title", "names", "source", "identifiers", "abstract"),
        supports_abstracts=True,
        max_page_size=50,
    )

    def __init__(self, fixture: FixedSourceFixture) -> None:
        self.fixture = fixture
        self.name = fixture.source
        self.capabilities = self.capabilities.model_copy(update={"source": self.name})

    @classmethod
    def from_file(cls, fixture_path: Path | str) -> FixedSourceAdapter:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        return cls(FixedSourceFixture.model_validate(payload))

    async def search(self, request: SourceSearchRequest) -> SourceSearchResult:
        if request.query != self.fixture.question:
            raise ValueError("The fixed source only accepts its fixture question.")
        return SourceSearchResult(
            metadata=SourceSearchMetadata(
                total=len(self.fixture.records),
                page=request.page,
                limit=request.limit,
            ),
            hits=list(self.fixture.records),
        )

class FixedLLMAdapter:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        del messages, temperature, max_tokens
        if not self.responses:
            raise AssertionError("The fixed LLM response sequence was exhausted.")
        return self.responses.pop(0)
