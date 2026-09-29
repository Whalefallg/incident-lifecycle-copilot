from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.chat_handler import get_conversation_repository
from api.contracts.incidents import (
    CreateIncidentRequest,
    IncidentListResponse,
    IncidentResponse,
    IncidentTimelineResponse,
)
from api.core.exceptions import ErrorResponse
from conversation.repository import ConversationRepository
from services.incidents import IncidentService

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
