from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from config.constants import StateEnum
from conversation.events import IncidentEventType


class CreateIncidentRequest(BaseModel):
    incident_id: str | None = Field(default=None, min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    service: str = Field(min_length=1, max_length=100)
    severity: str | None = Field(default=None, max_length=10)
    description: str | None = Field(default=None, max_length=2000)


class CreateMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=1, max_length=100)


class MessageResponse(BaseModel):
    role: str
    content: str
    timestamp: datetime


class MessageListResponse(BaseModel):
    incident_id: str
    items: list[MessageResponse]
    total: int


class IncidentResponse(BaseModel):
    incident_id: str
    title: str
    service: str | None
    severity: str | None
    status: str
    workflow_state: StateEnum
    revision: int
    created_at: datetime
    updated_at: datetime


class IncidentListResponse(BaseModel):
    items: list[IncidentResponse]
    total: int


class IncidentEventResponse(BaseModel):
    event_id: str
    incident_id: str
    type: IncidentEventType
    timestamp: datetime
    actor: str
    source: str
    request_id: str | None
    payload: dict[str, Any]
    provenance: Literal["recorded_fact"] = "recorded_fact"


class IncidentTimelineResponse(BaseModel):
    incident_id: str
    items: list[IncidentEventResponse]
    total: int
