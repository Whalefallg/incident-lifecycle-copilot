from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from api.core.exceptions import ErrorCode


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StreamEventBase(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    incident_id: str
    request_id: str
    sequence: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=utc_now)


class EmptyPayload(BaseModel):
    pass


class WorkflowStateChangedPayload(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    from_state: str = Field(alias="from")
    to: str


class AgentPayload(BaseModel):
    agent: str
    duration_ms: int | None = Field(default=None, ge=0)
    input_summary: str | None = None
    output_summary: str | None = None


class RetrievalStartedPayload(BaseModel):
    query: str


class RetrievalCompletedPayload(RetrievalStartedPayload):
    result_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)


class IncidentEventPayload(BaseModel):
    event: dict[str, Any]


class MessageDeltaPayload(BaseModel):
    text: str


class MessageCompletedPayload(BaseModel):
    message_id: str
    text: str


class PostmortemGeneratedPayload(BaseModel):
    draft_id: str
    version: int = Field(ge=1)


class RequestCompletedPayload(BaseModel):
    revision: int = Field(ge=0)


class ErrorPayload(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class RequestStartedEvent(StreamEventBase):
    type: Literal["request.started"] = "request.started"
    payload: EmptyPayload = Field(default_factory=EmptyPayload)


class WorkflowStateChangedEvent(StreamEventBase):
    type: Literal["workflow.state_changed"] = "workflow.state_changed"
    payload: WorkflowStateChangedPayload


class AgentStartedEvent(StreamEventBase):
    type: Literal["agent.started"] = "agent.started"
    payload: AgentPayload


class AgentCompletedEvent(StreamEventBase):
    type: Literal["agent.completed"] = "agent.completed"
    payload: AgentPayload


class RetrievalStartedEvent(StreamEventBase):
    type: Literal["retrieval.started"] = "retrieval.started"
    payload: RetrievalStartedPayload


class RetrievalCompletedEvent(StreamEventBase):
    type: Literal["retrieval.completed"] = "retrieval.completed"
    payload: RetrievalCompletedPayload


class IncidentRecordedEvent(StreamEventBase):
    type: Literal["incident.event"] = "incident.event"
    payload: IncidentEventPayload


class MessageDeltaEvent(StreamEventBase):
    type: Literal["message.delta"] = "message.delta"
    payload: MessageDeltaPayload


class MessageCompletedEvent(StreamEventBase):
    type: Literal["message.completed"] = "message.completed"
    payload: MessageCompletedPayload


class PostmortemGeneratedEvent(StreamEventBase):
    type: Literal["postmortem.generated"] = "postmortem.generated"
    payload: PostmortemGeneratedPayload


class RequestCompletedEvent(StreamEventBase):
    type: Literal["request.completed"] = "request.completed"
    payload: RequestCompletedPayload


class StreamErrorEvent(StreamEventBase):
    type: Literal["error"] = "error"
    payload: ErrorPayload


StreamEvent = Annotated[
    Union[
        RequestStartedEvent,
        WorkflowStateChangedEvent,
        AgentStartedEvent,
        AgentCompletedEvent,
        RetrievalStartedEvent,
        RetrievalCompletedEvent,
        IncidentRecordedEvent,
        MessageDeltaEvent,
        MessageCompletedEvent,
        PostmortemGeneratedEvent,
        RequestCompletedEvent,
        StreamErrorEvent,
    ],
    Field(discriminator="type"),
]
