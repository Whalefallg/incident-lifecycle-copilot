from conversation.repository import ConcurrentConversationUpdate, ConversationRepository
from knowledge.approval import KnowledgeDraft, transition_draft


class KnowledgeDraftNotFound(LookupError):
    pass


class KnowledgeTransitionConflict(RuntimeError):
    pass


class SnapshotKnowledgeService:
    def __init__(self, repository: ConversationRepository, max_retries: int = 3) -> None:
        self.repository = repository
        self.max_retries = max_retries

    async def list_drafts(self) -> list[KnowledgeDraft]:
        snapshots = await self.repository.list()
        drafts = [
            draft.model_copy(deep=True)
            for snapshot in snapshots
            for draft in snapshot.postmortem_context.drafts
        ]
        return sorted(drafts, key=lambda item: item.created_at, reverse=True)

    async def get_draft(self, draft_id: str) -> KnowledgeDraft:
        for draft in await self.list_drafts():
            if draft.draft_id == draft_id:
                return draft
        raise KnowledgeDraftNotFound(draft_id)

    async def transition(self, draft_id: str, action: str, actor: str) -> KnowledgeDraft:
        for attempt in range(self.max_retries):
            snapshots = await self.repository.list()
            snapshot = next(
                (
                    item
                    for item in snapshots
                    if any(draft.draft_id == draft_id for draft in item.postmortem_context.drafts)
                ),
                None,
            )
            if snapshot is None:
                raise KnowledgeDraftNotFound(draft_id)
            draft = next(
                draft for draft in snapshot.postmortem_context.drafts if draft.draft_id == draft_id
            )
            try:
                transition_draft(draft, action, actor)
            except ValueError as exc:
                raise KnowledgeTransitionConflict(str(exc)) from exc
            try:
                await self.repository.save(snapshot, snapshot.revision)
                return draft
            except ConcurrentConversationUpdate as exc:
                if attempt + 1 >= self.max_retries:
                    raise KnowledgeTransitionConflict(
                        "Knowledge draft was updated by another request"
                    ) from exc
        raise AssertionError("bounded retry loop exhausted")
