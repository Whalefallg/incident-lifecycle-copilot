"""
Incident Escalation API

Provides the /api/incident endpoint for triggering escalation flows via the agent.
"""
from fastapi import APIRouter, HTTPException
from .core.response_models import DataResponse
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/api/incident", tags=["事件管理"])


class IncidentRequest(BaseModel):
    service: str = Field(min_length=1, max_length=100)
    severity: Optional[str] = Field(default=None, max_length=10)
    description: Optional[str] = Field(default=None, max_length=2000)


@router.post("/escalate", response_model=DataResponse)
async def escalate_incident(request: IncidentRequest):
    """Trigger an incident escalation via the EscalationAgent."""
    try:
        from agents.escalation_agent import EscalationAgent
        agent = EscalationAgent()
        result = {"service": request.service, "severity": request.severity, "status": "escalation_initiated"}
        return DataResponse(
            message="Incident escalation initiated",
            data=result
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
