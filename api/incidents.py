from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from api.chat_handler import get_conversation_repository
from api.contracts.incidents import (
    CreateIncidentRequest,
    CreateMessageRequest,
    IncidentListResponse,
    IncidentResponse,
    IncidentTimelineResponse,
    MessageListResponse,
)
from api.contracts.knowledge import PostmortemResponse
from api.contracts.observability import RunbookListResponse, TraceListResponse
from api.core.exceptions import ErrorResponse
from conversation.repository import ConversationRepository
from services.incidents import IncidentService
from services.incidents.streaming import IncidentStreamingService

router = APIRouter(
    prefix="/api/incidents",
    tags=["incidents"],
    responses={
        404: {"model": ErrorResponse, "description": "Incident not found"},
        409: {"model": ErrorResponse, "description": "State or idempotency conflict"},
        422: {"model": ErrorResponse, "description": "Request validation failed"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)


RepositoryDependency = Annotated[ConversationRepository, Depends(get_conversation_repository)]


async def get_incident_service(repository: RepositoryDependency) -> IncidentService:
    return IncidentService(repository)


IncidentServiceDependency = Annotated[IncidentService, Depends(get_incident_service)]


async def get_incident_streaming_service(
    repository: RepositoryDependency,
) -> IncidentStreamingService:
    return IncidentStreamingService(repository)


IncidentStreamingDependency = Annotated[
    IncidentStreamingService, Depends(get_incident_streaming_service)
]


@router.get("", response_model=IncidentListResponse)
async def list_incidents(service: IncidentServiceDependency) -> IncidentListResponse:
    return await service.list_incidents()


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(
    request: CreateIncidentRequest, service: IncidentServiceDependency
) -> IncidentResponse:
    return await service.create_incident(request)


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str, service: IncidentServiceDependency) -> IncidentResponse:
    return await service.get_incident(incident_id)


@router.get("/{incident_id}/events", response_model=IncidentTimelineResponse)
async def get_incident_events(
    incident_id: str, service: IncidentServiceDependency
) -> IncidentTimelineResponse:
    return await service.get_timeline(incident_id)


@router.get("/{incident_id}/messages", response_model=MessageListResponse)
async def get_incident_messages(
    incident_id: str, service: IncidentServiceDependency
) -> MessageListResponse:
    return await service.get_messages(incident_id)


@router.get("/{incident_id}/trace", response_model=TraceListResponse)
async def get_incident_trace(
    incident_id: str, service: IncidentServiceDependency
) -> TraceListResponse:
    return await service.get_trace(incident_id)


@router.get("/{incident_id}/runbooks", response_model=RunbookListResponse)
async def get_incident_runbooks(
    incident_id: str, service: IncidentServiceDependency
) -> RunbookListResponse:
    return await service.get_runbooks(incident_id)


@router.get("/{incident_id}/postmortem", response_model=PostmortemResponse)
async def get_incident_postmortem(
    incident_id: str, service: IncidentServiceDependency
) -> PostmortemResponse:
    return await service.get_postmortem(incident_id)


@router.post(
    "/{incident_id}/messages",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Ordered typed server-sent events",
            "content": {"text/event-stream": {}},
        }
    },
)
async def stream_incident_message(
    incident_id: str,
    request: CreateMessageRequest,
    service: IncidentServiceDependency,
    streaming: IncidentStreamingDependency,
) -> StreamingResponse:
    await service.get_incident(incident_id)
    return StreamingResponse(
        streaming.stream_message(incident_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
