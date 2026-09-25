"""Human-reviewed, versioned and idempotent knowledge write-back."""

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeDraftStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    INGESTED = "ingested"
    REJECTED = "rejected"


class KnowledgeDraft(BaseModel):
    draft_id: str = Field(default_factory=lambda: str(uuid4()))
    source_incident_id: str
    version: int
    content: str
    content_hash: str
    status: KnowledgeDraftStatus = KnowledgeDraftStatus.DRAFT
    created_at: datetime = Field(default_factory=utc_now)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    ingested_at: datetime | None = None

    @classmethod
    def create(cls, source_incident_id: str, version: int, content: str):
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls(
            source_incident_id=source_incident_id,
            version=version,
            content=content,
            content_hash=digest,
        )


class KnowledgeIngestor(Protocol):
    async def ingest(self, draft: KnowledgeDraft) -> str: ...


class KnowledgeDraftRepository(ABC):
    @abstractmethod
    async def get(self, draft_id: str) -> KnowledgeDraft | None: ...

    @abstractmethod
    async def save(self, draft: KnowledgeDraft) -> KnowledgeDraft: ...

    @abstractmethod
    async def find_version(
        self, source_incident_id: str, version: int
    ) -> KnowledgeDraft | None: ...


class InMemoryKnowledgeDraftRepository(KnowledgeDraftRepository):
    def __init__(self):
        self._drafts: dict[str, KnowledgeDraft] = {}

    async def get(self, draft_id: str) -> KnowledgeDraft | None:
        draft = self._drafts.get(draft_id)
        return draft.model_copy(deep=True) if draft else None

    async def save(self, draft: KnowledgeDraft) -> KnowledgeDraft:
        existing = await self.find_version(draft.source_incident_id, draft.version)
        if existing and existing.draft_id != draft.draft_id:
            raise ValueError("knowledge draft version already exists")
        self._drafts[draft.draft_id] = draft.model_copy(deep=True)
        return draft.model_copy(deep=True)

    async def find_version(self, source_incident_id: str, version: int):
        for draft in self._drafts.values():
            if draft.source_incident_id == source_incident_id and draft.version == version:
                return draft.model_copy(deep=True)
        return None


class KnowledgeApprovalService:
    def __init__(self, repository: KnowledgeDraftRepository, ingestor: KnowledgeIngestor):
        self.repository = repository
        self.ingestor = ingestor

    async def create_draft(
        self, source_incident_id: str, version: int, content: str
    ) -> KnowledgeDraft:
        existing = await self.repository.find_version(source_incident_id, version)
        candidate = KnowledgeDraft.create(source_incident_id, version, content)
        if existing:
            if existing.content_hash != candidate.content_hash:
                raise ValueError("version already exists with different content")
            return existing
        return await self.repository.save(candidate)

    async def review(self, draft_id: str, reviewer: str) -> KnowledgeDraft:
        draft = await self._required(draft_id)
        if draft.status != KnowledgeDraftStatus.DRAFT:
            raise ValueError("only draft knowledge can be reviewed")
        draft.status = KnowledgeDraftStatus.REVIEWED
        draft.reviewed_by = reviewer
        draft.reviewed_at = utc_now()
        return await self.repository.save(draft)

    async def approve(self, draft_id: str, approver: str) -> KnowledgeDraft:
        draft = await self._required(draft_id)
        if draft.status != KnowledgeDraftStatus.REVIEWED:
            raise ValueError("knowledge must be reviewed before approval")
        draft.status = KnowledgeDraftStatus.APPROVED
        draft.approved_by = approver
        draft.approved_at = utc_now()
        return await self.repository.save(draft)

    async def reject(self, draft_id: str, reviewer: str) -> KnowledgeDraft:
        draft = await self._required(draft_id)
        if draft.status not in {KnowledgeDraftStatus.DRAFT, KnowledgeDraftStatus.REVIEWED}:
            raise ValueError("approved or ingested knowledge cannot be rejected")
        draft.status = KnowledgeDraftStatus.REJECTED
        draft.reviewed_by = reviewer
        draft.reviewed_at = utc_now()
        return await self.repository.save(draft)

    async def ingest(self, draft_id: str) -> KnowledgeDraft:
        draft = await self._required(draft_id)
        if draft.status == KnowledgeDraftStatus.INGESTED:
            return draft
        if draft.status != KnowledgeDraftStatus.APPROVED:
            raise ValueError("only approved knowledge can be ingested")
        await self.ingestor.ingest(draft)
        draft.status = KnowledgeDraftStatus.INGESTED
        draft.ingested_at = utc_now()
        return await self.repository.save(draft)

    async def _required(self, draft_id: str) -> KnowledgeDraft:
        draft = await self.repository.get(draft_id)
        if not draft:
            raise KeyError(draft_id)
        return draft


class InMemoryKnowledgeIngestor:
    """Test adapter proving ingestion idempotency without choosing an MCP backend."""

    def __init__(self):
        self.documents: dict[tuple[str, int], str] = {}

    async def ingest(self, draft: KnowledgeDraft) -> str:
        key = (draft.source_incident_id, draft.version)
        self.documents.setdefault(key, draft.content)
        return f"{draft.source_incident_id}:v{draft.version}"
