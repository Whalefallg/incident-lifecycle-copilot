from uuid import uuid4

from api.contracts.incidents import (
    CreateIncidentRequest,
    IncidentEventResponse,
    IncidentListResponse,
    IncidentResponse,
    IncidentTimelineResponse,
)
from conversation.events import IncidentEvent, IncidentEventType, build_timeline
from conversation.models import ConversationSnapshot, EscalationContext, IncidentMetadata
from conversation.repository import ConversationRepository


class IncidentNotFound(LookupError):
    pass


class IncidentService:
    """Application boundary for incident resources backed by snapshots."""

    def __init__(self, repository: ConversationRepository) -> None:
        self.repository = repository

    async def list_incidents(self) -> IncidentListResponse:
        snapshots = await self.repository.list()
        items = [self._to_response(item) for item in snapshots]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return IncidentListResponse(items=items, total=len(items))

    async def create_incident(self, request: CreateIncidentRequest) -> IncidentResponse:
        incident_id = request.incident_id or f"INC-{str(uuid4())[:8].upper()}"
        payload = {
            "title": request.title,
            "service": request.service,
        }
        if request.severity:
            payload["severity"] = request.severity
        if request.description:
            payload["description"] = request.description
        snapshot = ConversationSnapshot(
            session_id=incident_id,
            incident=IncidentMetadata(title=request.title),
            escalation_context=EscalationContext(
                service=request.service,
                severity=request.severity,
            ),
            events=[
                IncidentEvent(
                    incident_id=incident_id,
                    type=IncidentEventType.ALERT_RECEIVED,
                    actor="engineer",
                    source="incident_api",
                    payload=payload,
                )
            ],
        )
        created = await self.repository.create(snapshot)
        return self._to_response(created)

    async def get_incident(self, incident_id: str) -> IncidentResponse:
        return self._to_response(await self._required(incident_id))

    async def get_timeline(self, incident_id: str) -> IncidentTimelineResponse:
        snapshot = await self._required(incident_id)
        items = [
            IncidentEventResponse(
                event_id=event.event_id,
                incident_id=event.incident_id or incident_id,
                type=event.type,
                timestamp=event.timestamp,
                actor=event.actor,
                source=event.source,
                request_id=event.request_id,
                payload=event.payload,
            )
            for event in build_timeline(snapshot.events)
        ]
        return IncidentTimelineResponse(incident_id=incident_id, items=items, total=len(items))

    async def _required(self, incident_id: str) -> ConversationSnapshot:
        snapshot = await self.repository.load(incident_id)
        if snapshot is None:
            raise IncidentNotFound(incident_id)
        return snapshot

    @staticmethod
    def _to_response(snapshot: ConversationSnapshot) -> IncidentResponse:
        resolved = any(
            event.type is IncidentEventType.INCIDENT_RESOLVED for event in snapshot.events
        )
        status = "resolved" if resolved else snapshot.incident.status
        service = snapshot.escalation_context.service
        title = snapshot.incident.title or (f"{service} incident" if service else snapshot.session_id)
        return IncidentResponse(
            incident_id=snapshot.session_id,
            title=title,
            service=service,
            severity=snapshot.escalation_context.severity,
            status=status,
            workflow_state=snapshot.current_state,
            revision=snapshot.revision,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
        )
