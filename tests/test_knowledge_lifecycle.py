import pytest

from conversation.events import IncidentEvent, IncidentEventType
from conversation.models import ConversationSnapshot
from conversation.repository import InMemoryConversationRepository
from knowledge.approval import KnowledgeDraft, KnowledgeDraftStatus
from services.incidents import IncidentService
from services.knowledge_lifecycle import KnowledgeTransitionConflict, SnapshotKnowledgeService


@pytest.mark.asyncio
async def test_snapshot_knowledge_service_lists_and_transitions_persisted_drafts():
    repository = InMemoryConversationRepository()
    snapshot = ConversationSnapshot(session_id="INC-knowledge")
    draft = KnowledgeDraft.create(snapshot.session_id, 1, "generated analysis")
    snapshot.postmortem_context.drafts.append(draft)
    await repository.create(snapshot)
    service = SnapshotKnowledgeService(repository)

    assert [item.draft_id for item in await service.list_drafts()] == [draft.draft_id]
    reviewed = await service.transition(draft.draft_id, "review", "reviewer")
    assert reviewed.status is KnowledgeDraftStatus.REVIEWED
    assert (await repository.load(snapshot.session_id)).revision == 1

    with pytest.raises(KnowledgeTransitionConflict, match="invalid review transition"):
        await service.transition(draft.draft_id, "review", "reviewer")


@pytest.mark.asyncio
async def test_postmortem_response_separates_recorded_facts_from_generated_analysis():
    repository = InMemoryConversationRepository()
    snapshot = ConversationSnapshot(
        session_id="INC-postmortem",
        events=[
            IncidentEvent(
                incident_id="INC-postmortem",
                type=IncidentEventType.ALERT_RECEIVED,
                actor="monitor",
                source="alerting",
                payload={"summary": "latency high"},
            )
        ],
    )
    snapshot.postmortem_context.drafts.extend(
        [
            KnowledgeDraft.create(snapshot.session_id, 1, "old draft"),
            KnowledgeDraft.create(snapshot.session_id, 2, "latest generated analysis"),
        ]
    )
    await repository.create(snapshot)

    response = await IncidentService(repository).get_postmortem(snapshot.session_id)
    assert response.factual_timeline[0].provenance == "recorded_fact"
    assert response.factual_timeline[0].payload == {"summary": "latency high"}
    assert response.generated_analysis.version == 2
    assert response.generated_analysis.content == "latest generated analysis"
