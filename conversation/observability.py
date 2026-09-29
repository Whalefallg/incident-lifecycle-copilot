from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentTraceStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    agent: str
    action: str
    status: str = "completed"
    duration_ms: int = Field(ge=0)
    error_type: str | None = None


class RunbookResult(BaseModel):
    document_id: str
    content: str
    source: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalTrace(BaseModel):
    retrieval_id: str = Field(default_factory=lambda: str(uuid4()))
    query: str
    collection: str
    duration_ms: int = Field(ge=0)
    results: list[RunbookResult] = Field(default_factory=list)


class RequestTrace(BaseModel):
    trace_id: str
    request_id: str
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    steps: list[AgentTraceStep] = Field(default_factory=list)
    retrievals: list[RetrievalTrace] = Field(default_factory=list)
