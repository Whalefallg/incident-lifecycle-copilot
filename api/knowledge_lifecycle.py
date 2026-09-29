from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from api.chat_handler import get_conversation_repository
from api.contracts.knowledge import (
    KnowledgeDecisionRequest,
    KnowledgeDraftListResponse,
    KnowledgeDraftResponse,
)
from api.core.exceptions import ApiException, ErrorCode, ErrorResponse
from api.core.security import require_admin
from conversation.repository import ConversationRepository
from services.knowledge_lifecycle import (
    KnowledgeDraftNotFound,
    KnowledgeTransitionConflict,
    SnapshotKnowledgeService,
)

router = APIRouter(
    prefix="/api/knowledge/drafts",
    tags=["knowledge-lifecycle"],
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)

RepositoryDependency = Annotated[ConversationRepository, Depends(get_conversation_repository)]


async def get_knowledge_lifecycle_service(
    repository: RepositoryDependency,
) -> SnapshotKnowledgeService:
    return SnapshotKnowledgeService(repository)


ServiceDependency = Annotated[SnapshotKnowledgeService, Depends(get_knowledge_lifecycle_service)]


def response(draft) -> KnowledgeDraftResponse:
    return KnowledgeDraftResponse.model_validate(draft, from_attributes=True)


@router.get("", response_model=KnowledgeDraftListResponse)
async def list_drafts(service: ServiceDependency) -> KnowledgeDraftListResponse:
    drafts = await service.list_drafts()
    return KnowledgeDraftListResponse(
        items=[response(draft) for draft in drafts], total=len(drafts)
    )


@router.get("/item/{draft_id}", response_model=KnowledgeDraftResponse)
async def get_draft(draft_id: str, service: ServiceDependency) -> KnowledgeDraftResponse:
    try:
        return response(await service.get_draft(draft_id))
    except KnowledgeDraftNotFound as exc:
        raise ApiException(
            status_code=404, code=ErrorCode.NOT_FOUND, message="Knowledge draft not found"
        ) from exc


@router.post(
    "/{draft_id}/{action}",
    response_model=KnowledgeDraftResponse,
    dependencies=[Depends(require_admin)],
)
async def transition(
    draft_id: str,
    action: Literal["review", "approve", "reject"],
    decision: KnowledgeDecisionRequest,
    service: ServiceDependency,
) -> KnowledgeDraftResponse:
    try:
        return response(await service.transition(draft_id, action, decision.actor))
    except KnowledgeDraftNotFound as exc:
        raise ApiException(
            status_code=404, code=ErrorCode.NOT_FOUND, message="Knowledge draft not found"
        ) from exc
    except KnowledgeTransitionConflict as exc:
        raise ApiException(
            status_code=409, code=ErrorCode.KNOWLEDGE_TRANSITION_CONFLICT, message=str(exc)
        ) from exc
