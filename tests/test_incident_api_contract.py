from datetime import datetime, timezone

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from api.contracts.streaming import (
    MessageDeltaEvent,
    MessageDeltaPayload,
    StreamEvent,
    WorkflowStateChangedEvent,
    WorkflowStateChangedPayload,
)
from api.incidents import get_incident_service
from app import create_app
from conversation.models import ConversationSnapshot
from conversation.repository import (
    ConcurrentConversationUpdate,
    IdempotencyKeyMismatch,
    InMemoryConversationRepository,
)
from services.incidents import IncidentService


def client_for(repository: InMemoryConversationRepository) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_incident_service] = lambda: IncidentService(repository)
    return TestClient(app, raise_server_exceptions=False)


def test_incident_resource_contract_and_recorded_timeline():
    repository = InMemoryConversationRepository()
    client = client_for(repository)

    created = client.post(
        "/api/incidents",
        headers={"X-Request-ID": "create-1"},
        json={
            "incident_id": "INC-1024",
            "title": "Checkout API outage",
            "service": "checkout-service",
            "severity": "P0",
            "description": "Error rate reached 8%",
        },
    )
    assert created.status_code == 201
    assert created.json() == {
        "incident_id": "INC-1024",
        "title": "Checkout API outage",
        "service": "checkout-service",
        "severity": "P0",
        "status": "open",
        "workflow_state": "classify",
        "revision": 0,
        "created_at": created.json()["created_at"],
        "updated_at": created.json()["updated_at"],
    }

    detail = client.get("/api/incidents/INC-1024")
    assert detail.status_code == 200
    assert detail.json()["revision"] == 0

    listing = client.get("/api/incidents")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    timeline = client.get("/api/incidents/INC-1024/events")
    assert timeline.status_code == 200
    assert timeline.json()["items"][0]["type"] == "alert_received"
    assert timeline.json()["items"][0]["provenance"] == "recorded_fact"
    assert timeline.json()["items"][0]["payload"]["description"] == "Error rate reached 8%"


def test_not_found_and_validation_use_structured_errors():
    client = client_for(InMemoryConversationRepository())
    missing = client.get("/api/incidents/does-not-exist", headers={"X-Request-ID": "read-1"})
    assert missing.status_code == 404
    assert missing.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "Incident 'does-not-exist' was not found",
        "request_id": "read-1",
        "details": {},
    }

    invalid = client.post(
        "/api/incidents",
        headers={"X-Request-ID": "create-invalid"},
        json={"title": "", "service": ""},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert invalid.json()["error"]["request_id"] == "create-invalid"


class FailingService:
    def __init__(self, error: Exception):
        self.error = error

    async def get_incident(self, _incident_id: str):
        raise self.error


def test_repository_conflicts_have_stable_409_codes():
    for error, code in (
        (ConcurrentConversationUpdate("stale"), "CONVERSATION_CONFLICT"),
        (IdempotencyKeyMismatch("mismatch"), "IDEMPOTENCY_MISMATCH"),
    ):
        app = create_app()
        app.dependency_overrides[get_incident_service] = lambda error=error: FailingService(error)
        response = TestClient(app, raise_server_exceptions=False).get(
            "/api/incidents/INC-1", headers={"X-Request-ID": "request-1"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == code
        assert response.json()["error"]["request_id"] == "request-1"


def test_stream_events_form_a_discriminated_union_and_preserve_sequence():
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        WorkflowStateChangedEvent(
            incident_id="INC-1",
            request_id="request-1",
            sequence=1,
            timestamp=timestamp,
            payload=WorkflowStateChangedPayload.model_validate(
                {"from": "classify", "to": "escalation"}
            ),
        ),
        MessageDeltaEvent(
            incident_id="INC-1",
            request_id="request-1",
            sequence=2,
            timestamp=timestamp,
            payload=MessageDeltaPayload(text="hello"),
        ),
    ]
    adapter = TypeAdapter(StreamEvent)
    restored = [adapter.validate_json(adapter.dump_json(event)) for event in events]
    assert [event.type for event in restored] == ["workflow.state_changed", "message.delta"]
    assert [event.sequence for event in restored] == [1, 2]


def test_legacy_snapshot_without_incident_metadata_still_loads():
    legacy = ConversationSnapshot(session_id="legacy").model_dump(mode="json")
    legacy.pop("incident")
    legacy["schema_version"] = 1
    restored = ConversationSnapshot.model_validate(legacy)
    assert restored.incident.status == "open"
