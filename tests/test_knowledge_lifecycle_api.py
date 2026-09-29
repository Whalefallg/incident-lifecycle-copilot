import asyncio

from fastapi.testclient import TestClient

from api.knowledge_lifecycle import get_knowledge_lifecycle_service
from app import create_app
from conversation.models import ConversationSnapshot
from conversation.repository import InMemoryConversationRepository
from knowledge.approval import KnowledgeDraft
from services.knowledge_lifecycle import SnapshotKnowledgeService


def test_lifecycle_list_route_precedes_legacy_knowledge_catch_all():
    repository = InMemoryConversationRepository()
    snapshot = ConversationSnapshot(session_id="INC-api-knowledge")
    snapshot.postmortem_context.drafts.append(
        KnowledgeDraft.create(snapshot.session_id, 1, "review me")
    )
    asyncio.run(repository.create(snapshot))

    app = create_app()
    app.dependency_overrides[get_knowledge_lifecycle_service] = lambda: SnapshotKnowledgeService(
        repository
    )
    response = TestClient(app, raise_server_exceptions=False).get("/api/knowledge/drafts")

    assert response.status_code == 200
    assert response.json()["items"][0]["source_incident_id"] == "INC-api-knowledge"
