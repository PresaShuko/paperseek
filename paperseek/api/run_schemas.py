from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class RunEventResponse(BaseModel):
    id: Optional[int] = None
    type: str = ""
    stage: str = ""
    status: str = ""
    message: str = ""
    created_at: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class RunDetailResponse(BaseModel):
    id: str
    question: str
    source: str = ""
    final_query: str = ""
    db: str = ""
    field: str = ""
    total: Optional[int] = None
    iterations: Optional[int] = None
    status: str
    error_message: str = ""
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    result_count: int = 0
    event_count: int = 0
    checkpoint_count: int = 0
    checkpoint_stage: str = ""
    resumable: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    search_loop: dict[str, Any] = Field(default_factory=dict)
    search_state: dict[str, Any] = Field(default_factory=dict)
    citation_map: dict[str, Any] = Field(default_factory=dict)
    ranking_steps: list[dict[str, Any]] = Field(default_factory=list)
    events: list[RunEventResponse] = Field(default_factory=list)
    ranked: list[dict[str, Any]] = Field(default_factory=list)
    checkpoint: Optional[dict[str, Any]] = None


class RunEventsResponse(BaseModel):
    run_id: str
    events: list[RunEventResponse] = Field(default_factory=list)
    next_after_id: int = 0


class RunResultsResponse(BaseModel):
    run_id: str
    results: list[dict[str, Any]] = Field(default_factory=list)


class RunCancelResponse(BaseModel):
    cancelled: str


class RunSubmissionResponse(BaseModel):
    run_id: str
    status: str = "running"
    source_run_id: str = ""
