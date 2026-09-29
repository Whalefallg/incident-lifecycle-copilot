from datetime import datetime

from pydantic import BaseModel, Field

from api.contracts.incidents import IncidentEventResponse
from knowledge.approval import KnowledgeDraftStatus


class KnowledgeDraftResponse(BaseModel):
    draft_id: str
    source_incident_id: str
    version: int
    content: str
    content_hash: str
    status: KnowledgeDraftStatus
    created_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    approved_by: str | None
    approved_at: datetime | None
    ingested_at: datetime | None


class KnowledgeDraftListResponse(BaseModel):
    items: list[KnowledgeDraftResponse]
    total: int


class KnowledgeDecisionRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)


class PostmortemResponse(BaseModel):
    incident_id: str
    factual_timeline: list[IncidentEventResponse]
    generated_analysis: KnowledgeDraftResponse | None
