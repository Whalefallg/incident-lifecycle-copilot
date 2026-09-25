"""Typed, factual incident event ledger."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IncidentEventType(str, Enum):
    ALERT_RECEIVED = "alert_received"
    SEVERITY_CLASSIFIED = "severity_classified"
    IMPACT_UPDATED = "impact_updated"
    SYMPTOM_RECORDED = "symptom_recorded"
    RUNBOOK_RETRIEVED = "runbook_retrieved"
    ONCALL_DISPATCHED = "oncall_dispatched"
    MITIGATION_PROPOSED = "mitigation_proposed"
    MITIGATION_EXECUTED = "mitigation_executed"
    STATUS_UPDATE_DRAFTED = "status_update_drafted"
    STATUS_UPDATE_SENT = "status_update_sent"
    INCIDENT_RESOLVED = "incident_resolved"


class IncidentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    incident_id: str | None = None
    type: IncidentEventType
    timestamp: datetime = Field(default_factory=utc_now)
    actor: str
    source: str
    request_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def build_timeline(events: list[IncidentEvent]) -> list[IncidentEvent]:
    """Return a stable, de-duplicated factual timeline."""
    unique = {event.event_id: event for event in events}
    return sorted(unique.values(), key=lambda event: (event.timestamp, event.event_id))


def format_timeline(events: list[IncidentEvent]) -> str:
    ordered = build_timeline(events)
    if not ordered:
        return "No structured incident events were recorded."
    lines = ["INCIDENT TIMELINE (recorded system events)", ""]
    for event in ordered:
        detail = ", ".join(
            f"{key}={value}" for key, value in sorted(event.payload.items())
        ) or "no additional payload"
        lines.append(
            f"[{event.timestamp.isoformat()}] {event.type.value.upper()} — {detail}"
        )
    return "\n".join(lines)
