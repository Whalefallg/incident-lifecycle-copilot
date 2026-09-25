"""Serializable source of truth for a recoverable conversation."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from config.constants import StateEnum
from conversation.events import IncidentEvent
from knowledge.approval import KnowledgeDraft


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionMessage(BaseModel):
    role: str
    content: str
    timestamp: datetime = Field(default_factory=utc_now)


class EscalationContext(BaseModel):
    severity: str | None = None
    service: str | None = None
    impact_scope: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    suspected_cause: str | None = None
    recent_changes: list[str] = Field(default_factory=list)
    oncall_preference: str | None = None
    recommended_oncall: dict[str, Any] | str | None = None
    confirmed_oncall: dict[str, Any] | str | None = None
    original_oncall: dict[str, Any] | str | None = None
    awaiting_confirmation: bool = False
    recommendation_declined: bool = False

    @classmethod
    def from_legacy_dict(cls, value: dict[str, Any] | None) -> "EscalationContext":
        data = dict(value or {})
        for field_name in ("symptoms", "recent_changes"):
            field_value = data.get(field_name)
            if field_value is None:
                data[field_name] = []
            elif isinstance(field_value, str):
                data[field_name] = [field_value]
        return cls.model_validate(data)

    def to_legacy_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        for field_name in ("symptoms", "recent_changes"):
            values = data[field_name]
            data[field_name] = values if len(values) != 1 else values[0]
        return data


class SuspendedFrame(BaseModel):
    state: StateEnum
    escalation_context: EscalationContext | None = None


class PostmortemContext(BaseModel):
    drafts: list[KnowledgeDraft] = Field(default_factory=list)


class ConversationSnapshot(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    schema_version: int = 1
    session_id: str
    revision: int = 0
    current_state: StateEnum = StateEnum.CLASSIFY
    suspend_stack: list[SuspendedFrame] = Field(default_factory=list)
    escalation_context: EscalationContext = Field(default_factory=EscalationContext)
    communication_context: dict[str, Any] = Field(default_factory=dict)
    postmortem_context: PostmortemContext = Field(default_factory=PostmortemContext)
    messages: list[SessionMessage] = Field(default_factory=list)
    events: list[IncidentEvent] = Field(default_factory=list)
    processed_requests: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def json_payload(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json_payload(cls, payload: str | bytes) -> "ConversationSnapshot":
        return cls.model_validate_json(payload)
