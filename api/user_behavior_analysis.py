"""
Incident Pattern Analysis API

Provides engineer triage pattern analysis endpoints.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/user-behavior", tags=["Incident Pattern Analysis"])
router_underscore = APIRouter(prefix="/api/user_behavior", tags=["Incident Pattern Analysis"])


class PatternAnalysisResponse(BaseModel):
    """Engineer triage pattern analysis response."""
    most_escalated_service: Optional[str] = None
    most_used_severity: Optional[str] = None
    preferred_team: Optional[str] = None
    total_escalations: int = 0
    days_since_last_escalation: Optional[int] = None
    should_send_reminder: bool = False


async def get_pattern_analysis(user_id: str = "default_user") -> PatternAnalysisResponse:
    """Get engineer triage pattern analysis."""
    try:
        from agents.user_behavior_agent import UserBehaviorAgent

        agent = UserBehaviorAgent()
        analysis = agent.get_user_analysis(user_id)

        if not analysis:
            return PatternAnalysisResponse()

        return PatternAnalysisResponse(
            most_escalated_service=analysis.get('most_escalated_service'),
            most_used_severity=analysis.get('most_used_severity'),
            preferred_team=analysis.get('preferred_team'),
            total_escalations=analysis.get('total_escalations', 0),
            days_since_last_escalation=analysis.get('days_since_last_escalation'),
            should_send_reminder=analysis.get('should_send_reminder', False)
        )
    except Exception as e:
        import logging
        logging.error(f"Failed to get pattern analysis: {e}")
        return PatternAnalysisResponse()


@router.get("/analysis", response_model=PatternAnalysisResponse)
async def get_default_user_analysis():
    """Get default engineer's triage pattern analysis."""
    return await get_pattern_analysis("default_user")


@router.get("/dashboard_data", response_model=PatternAnalysisResponse)
async def get_dashboard_data():
    """Get triage pattern dashboard data."""
    return await get_pattern_analysis("default_user")


@router_underscore.get("/dashboard_data", response_model=PatternAnalysisResponse)
async def get_dashboard_data_underscore():
    """Get triage pattern dashboard data (underscore version)."""
    return await get_pattern_analysis("default_user")


class InsightRequest(BaseModel):
    """Pattern insight request."""
    user_id: str = "default_user"


class InsightResponse(BaseModel):
    """Pattern insight response."""
    message: str
    context: Optional[dict] = None


@router.post("/send-reminder", response_model=InsightResponse, summary="Generate pattern insights")
async def send_reminder(request: InsightRequest):
    """
    Generate pattern-based insights.

    Note: This endpoint is currently a placeholder.
    Pattern-based recommendations are not yet implemented.
    """
    try:
        from agents.user_behavior_agent import UserBehaviorAgent

        agent = UserBehaviorAgent()
        result = await agent.get_reminder_with_schedule(request.user_id)

        return InsightResponse(
            message=result.get("message", "Pattern insights not yet available."),
            context=result
        )

    except Exception as e:
        import logging
        logging.error(f"Failed to generate insights: {e}")
        return InsightResponse(
            message="Pattern insight generation is not yet available.",
            context={}
        )
