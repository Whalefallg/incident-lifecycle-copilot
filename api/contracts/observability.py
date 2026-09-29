from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class TraceStepResponse(BaseModel):
    step_id: str
    agent: str
    action: str
    status: str
    duration_ms: int
    error_type: str | None


class RetrievalSummaryResponse(BaseModel):
    retrieval_id: str
    query: str
    collection: str
    duration_ms: int
    result_count: int


class RequestTraceResponse(BaseModel):
    trace_id: str
    request_id: str
    started_at: datetime
    completed_at: datetime | None
    steps: list[TraceStepResponse]
    retrievals: list[RetrievalSummaryResponse]
    visibility: Literal["execution_metadata"] = "execution_metadata"


class TraceListResponse(BaseModel):
    incident_id: str
    items: list[RequestTraceResponse]
    total: int


class RunbookResultResponse(BaseModel):
    document_id: str
    content: str
    source: str
    score: float | None
    metadata: dict[str, Any]


class RunbookRetrievalResponse(BaseModel):
    retrieval_id: str
    request_id: str
    query: str
    collection: str
    duration_ms: int
    results: list[RunbookResultResponse]


class RunbookListResponse(BaseModel):
    incident_id: str
    items: list[RunbookRetrievalResponse]
    total: int
