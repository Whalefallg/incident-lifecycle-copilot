import pytest

from knowledge.approval import (
    InMemoryKnowledgeDraftRepository,
    InMemoryKnowledgeIngestor,
    KnowledgeApprovalService,
    KnowledgeDraftStatus,
)
from conversation.models import ConversationSnapshot


def service():
    repository = InMemoryKnowledgeDraftRepository()
    ingestor = InMemoryKnowledgeIngestor()
    return KnowledgeApprovalService(repository, ingestor), ingestor


@pytest.mark.asyncio
async def test_draft_cannot_be_ingested_before_approval():
    approval, ingestor = service()
    draft = await approval.create_draft("INC-1", 1, "postmortem")
    with pytest.raises(ValueError, match="only approved"):
        await approval.ingest(draft.draft_id)
    assert ingestor.documents == {}


@pytest.mark.asyncio
async def test_review_approval_and_ingestion_are_audited_and_idempotent():
    approval, ingestor = service()
    draft = await approval.create_draft("INC-1", 1, "postmortem")
    reviewed = await approval.review(draft.draft_id, "reviewer@example.com")
    approved = await approval.approve(draft.draft_id, "approver@example.com")
    ingested = await approval.ingest(draft.draft_id)
    repeated = await approval.ingest(draft.draft_id)

    assert reviewed.status is KnowledgeDraftStatus.REVIEWED
    assert reviewed.reviewed_at is not None
    assert approved.status is KnowledgeDraftStatus.APPROVED
    assert approved.approved_at is not None
    assert ingested.status is KnowledgeDraftStatus.INGESTED
    assert ingested.ingested_at is not None
    assert repeated == ingested
    assert len(ingestor.documents) == 1


@pytest.mark.asyncio
async def test_rejected_draft_cannot_be_ingested():
    approval, ingestor = service()
    draft = await approval.create_draft("INC-2", 1, "rejected content")
    rejected = await approval.reject(draft.draft_id, "reviewer@example.com")
    assert rejected.status is KnowledgeDraftStatus.REJECTED
    with pytest.raises(ValueError, match="only approved"):
        await approval.ingest(draft.draft_id)
    assert ingestor.documents == {}


@pytest.mark.asyncio
async def test_versions_are_unique_but_new_version_can_ingest():
    approval, ingestor = service()
    first = await approval.create_draft("INC-3", 1, "v1")
    same = await approval.create_draft("INC-3", 1, "v1")
    assert same.draft_id == first.draft_id
    with pytest.raises(ValueError, match="different content"):
        await approval.create_draft("INC-3", 1, "changed v1")

    second = await approval.create_draft("INC-3", 2, "v2")
    await approval.review(second.draft_id, "reviewer")
    await approval.approve(second.draft_id, "approver")
    await approval.ingest(second.draft_id)
    assert ("INC-3", 2) in ingestor.documents


@pytest.mark.asyncio
async def test_persisted_draft_api_transition_updates_snapshot(monkeypatch):
    from api import chat_handler
    from api.knowledge import _transition_draft
    from conversation.repository import InMemoryConversationRepository
    from knowledge.approval import KnowledgeDraft

    repository = InMemoryConversationRepository()
    draft = KnowledgeDraft.create("session-approval", 1, "draft")
    snapshot = ConversationSnapshot(session_id="session-approval")
    snapshot.postmortem_context.drafts.append(draft)
    await repository.create(snapshot)
    monkeypatch.setattr(chat_handler, "_in_memory_repository", repository)

    reviewed = await _transition_draft(
        "session-approval", draft.draft_id, "review", "reviewer"
    )
    approved = await _transition_draft(
        "session-approval", draft.draft_id, "approve", "approver"
    )
    persisted = await repository.load("session-approval")

    assert reviewed.status is KnowledgeDraftStatus.REVIEWED
    assert approved.status is KnowledgeDraftStatus.APPROVED
    assert persisted.postmortem_context.drafts[0].approved_by == "approver"
    assert persisted.revision == 2


def test_knowledge_draft_round_trip_is_part_of_snapshot():
    from knowledge.approval import KnowledgeDraft

    snapshot = ConversationSnapshot(session_id="draft-round-trip")
    snapshot.postmortem_context.drafts.append(
        KnowledgeDraft.create("draft-round-trip", 1, "review content")
    )
    restored = ConversationSnapshot.from_json_payload(snapshot.json_payload())
    draft = restored.postmortem_context.drafts[0]
    assert draft.content == "review content"
    assert draft.status is KnowledgeDraftStatus.DRAFT
