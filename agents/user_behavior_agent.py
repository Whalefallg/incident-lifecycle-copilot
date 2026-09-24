"""
Incident Pattern Agent

Tracks and analyzes engineer incident triage patterns for learning and improvement.

This agent learns from how engineers classify incidents, route escalations,
and make triage decisions to provide insights and improve future workflows.
"""

import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from config.model_provider import create_chat_model
from .user_behavior import PatternAnalyzer, BehaviorRecorder, PreferenceManager

load_dotenv()


class UserBehaviorAgent:
    """
    Incident Pattern Agent (alias: UserBehaviorAgent for backward compatibility).

    Tracks triage patterns and engineer preferences to improve incident response.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._user_behavior_service = None
        self.llm = self._initialize_llm()

        try:
            from services.user_behavior_service import UserBehaviorService
            self.behavior_service = UserBehaviorService()
            self.pattern_analyzer = PatternAnalyzer(self.behavior_service)
            self.behavior_recorder = BehaviorRecorder(self.behavior_service)
            self.preference_manager = PreferenceManager(self.behavior_service)
        except ImportError:
            from db import DatabaseRouter
            self.db = DatabaseRouter()
            self.behavior_service = None
            self.pattern_analyzer = PatternAnalyzer(self.db.user_behavior)
            self.behavior_recorder = BehaviorRecorder(self.db.user_behavior)
            self.preference_manager = PreferenceManager(self.db.user_behavior)

    @property
    def user_behavior_service(self):
        """Lazy load user behavior service."""
        if self._user_behavior_service is None:
            from services.user_behavior_service import UserBehaviorService
            self._user_behavior_service = UserBehaviorService()
        return self._user_behavior_service

    def _initialize_llm(self):
        """Initialize chat model."""
        return create_chat_model(temperature=0.7)

    def record_behavior(self, action_type: str, action_data: Dict[str, Any],
                       session_id: str = "default_session") -> bool:
        """
        Record engineer incident handling behavior.

        Args:
            action_type: Type of action ('incident_escalation', 'runbook_lookup', etc.)
            action_data: Action context data
            session_id: Session identifier
        """
        try:
            return self.user_behavior_service.record_behavior(
                user_id="default_user",
                action_type=action_type,
                action_data=action_data,
                session_id=session_id
            )
        except Exception as e:
            self.logger.error(f"Failed to record behavior: {str(e)}")
            try:
                return self.behavior_recorder.record_behavior(
                    action_type=action_type,
                    action_data=action_data,
                    session_id=session_id
                )
            except Exception as fallback_error:
                self.logger.error(f"Fallback also failed: {str(fallback_error)}")
                return False

    def get_user_analysis(self, user_id: str = "default_user") -> Optional[Dict[str, Any]]:
        """
        Get engineer triage pattern analysis.

        Returns patterns like most escalated services, severity preferences, etc.
        """
        try:
            preferences = self.pattern_analyzer.analyze_user_preferences(user_id)
            if not preferences:
                return None

            last_escalation = preferences.get('last_escalation_date')
            days_since_last = None
            if last_escalation:
                from datetime import datetime
                if isinstance(last_escalation, str):
                    last_escalation = datetime.fromisoformat(last_escalation.replace('Z', '+00:00'))
                days_since_last = (datetime.now() - last_escalation).days

            return {
                'most_escalated_service': preferences.get('most_escalated_service'),
                'most_used_severity': preferences.get('most_used_severity'),
                'preferred_team': preferences.get('preferred_team'),
                'total_escalations': preferences.get('total_escalations'),
                'days_since_last_escalation': days_since_last,
                'should_send_reminder': False
            }
        except Exception as e:
            self.logger.error(f"Analysis failed: {str(e)}")
            return None

    def generate_reminder_message(self, user_id: str = "default_user") -> Optional[str]:
        """
        Generate pattern-based insight message.

        Currently not implemented for incident ops workflow.
        """
        return None

    async def generate_personalized_reminder(self, user_id: str = "default_user",
                                           available_times: list = None) -> Optional[str]:
        """
        Generate personalized insight using LLM.

        Currently not implemented for incident ops workflow.
        """
        return "Pattern-based insights not yet available."

    async def get_reminder_with_schedule(self, user_id: str = "default_user") -> Dict[str, Any]:
        """
        Get pattern insights with context.

        Currently returns minimal data as this feature is not yet implemented.
        """
        return {
            "message": "Pattern-based insights not yet available.",
            "recommended_workflows": []
        }


# Alias for clarity in incident ops context
IncidentPatternAgent = UserBehaviorAgent
