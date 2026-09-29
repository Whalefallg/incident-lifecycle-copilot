import json
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from api.contracts.incidents import CreateMessageRequest
from api.incidents import get_incident_service, get_incident_streaming_service
from app import create_app
from config.constants import StateEnum
from conversation.events import IncidentEvent, IncidentEventType
from conversation.models import ConversationSnapshot, SessionMessage
from conversation.repository import IdempotencyKeyMismatch, InMemoryConversationRepository
from services.incidents import IncidentService
from services.incidents.streaming import IncidentStreamingService


def parse_events(chunks: list[str]) -> list[dict]:
    return [
        json.loads(next(line[6:] for line in chunk.splitlines() if line.startswith("data: ")))
        for chunk in chunks
    ]


class SuccessfulCoordinator:
    def __init__(self, repository):
        self.repository = repository

    async def process(self, message, incident_id, request_id, *, request_payload):
        snapshot = await self.repository.load(incident_id)
        snapshot.current_state = StateEnum.ESCALATION
        snapshot.messages.extend(
            [
                SessionMessage(role="engineer", content=message),
                SessionMessage(role="agent", content="Escalation started"),
            ]
        )
        snapshot.events.append(
            IncidentEvent(
                incident_id=incident_id,
                type=IncidentEventType.SEVERITY_CLASSIFIED,
                actor="TriageRouter",
                source="test",
                request_id=request_id,
                payload={"severity": "P0"},
            )
        )
        snapshot.processed_requests[request_id] = "Escalation started"
        await self.repository.save(snapshot, snapshot.revision)
        return "Escalation started"


@pytest.mark.asyncio
async def test_stream_orders_committed_workflow_events_without_artificial_deltas():
    repository = InMemoryConversationRepository()
    await repository.create(ConversationSnapshot(session_id="INC-1"))
    service = IncidentStreamingService(repository, coordinator_factory=SuccessfulCoordinator)

    chunks = [
        chunk
        async for chunk in service.stream_message(
            "INC-1", CreateMessageRequest(message="checkout down", request_id="request-1")
        )
    ]
    events = parse_events(chunks)

    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert [event["type"] for event in events] == [
        "request.started",
        "workflow.state_changed",
        "incident.event",
        "message.completed",
        "request.completed",
    ]
    assert events[1]["payload"] == {"from": "classify", "to": "escalation"}
    assert events[2]["payload"]["event"]["type"] == "severity_classified"
    assert events[3]["payload"]["text"] == "Escalation started"
    assert events[-1]["payload"]["revision"] == 1


class MismatchCoordinator:
    def __init__(self, _repository):
        pass

    async def process(self, *_args, **_kwargs):
        raise IdempotencyKeyMismatch("mismatch")


@pytest.mark.asyncio
async def test_stream_converts_execution_error_to_typed_error_event():
    repository = InMemoryConversationRepository()
    await repository.create(ConversationSnapshot(session_id="INC-1"))
    service = IncidentStreamingService(repository, coordinator_factory=MismatchCoordinator)
    chunks = [
        chunk
        async for chunk in service.stream_message(
            "INC-1", CreateMessageRequest(message="changed", request_id="request-1")
        )
    ]
    events = parse_events(chunks)
    assert events[-1]["type"] == "error"
    assert events[-1]["payload"]["code"] == "IDEMPOTENCY_MISMATCH"
    assert [event["type"] for event in events] == ["request.started", "error"]


class StubStreamingService:
    async def stream_message(self, incident_id, request) -> AsyncIterator[str]:
        yield "event: request.completed\ndata: {}\n\n"


def test_message_endpoint_uses_event_stream_contract():
    repository = InMemoryConversationRepository()
    app = create_app()

    async def service_override():
        await repository.create(ConversationSnapshot(session_id="INC-1"))
        return IncidentService(repository)

    app.dependency_overrides[get_incident_service] = service_override
    app.dependency_overrides[get_incident_streaming_service] = StubStreamingService
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/incidents/INC-1/messages",
        json={"message": "checkout down", "request_id": "request-1"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
