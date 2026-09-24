"""
Triage Pattern Analyzer

Analyzes engineer incident triage patterns for learning and improvement:
1. Tracks severity classification decisions
2. Learns service ownership patterns
3. Identifies on-call routing preferences
4. Provides pattern-based insights
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging


class PatternAnalyzer:
    """Analyzes engineer incident triage patterns."""

    def __init__(self, behavior_service=None):
        self.behavior_service = behavior_service
        self.logger = logging.getLogger(__name__)

    @property
    def behavior_db(self):
        """Backward compatibility property."""
        if hasattr(self, 'behavior_service') and self.behavior_service:
            return self.behavior_service.user_behavior_repo
        return None

    def analyze_user_preferences(self, user_id: str = "default_user") -> Optional[Dict[str, Any]]:
        """
        Analyze engineer's incident triage patterns.

        Returns patterns like:
        - Most escalated services
        - Typical severity classifications
        - Team/on-call preferences
        """
        try:
            if self.behavior_service:
                escalations = self.behavior_service.get_user_behaviors(
                    user_id=user_id,
                    action_type='incident_escalation'
                )
            else:
                escalations = self.behavior_db.get_user_behaviors(
                    user_id=user_id,
                    action_type='incident_escalation'
                )

            if not escalations:
                return None

            service_counts = {}
            severity_counts = {}
            team_counts = {}

            for escalation in escalations:
                data = escalation.get('action_data', {})

                service = data.get('service')
                if service:
                    service_counts[service] = service_counts.get(service, 0) + 1

                severity = data.get('severity')
                if severity:
                    severity_counts[severity] = severity_counts.get(severity, 0) + 1

                team = data.get('team')
                if team:
                    team_counts[team] = team_counts.get(team, 0) + 1

            most_escalated_service = max(service_counts, key=service_counts.get) if service_counts else None
            most_used_severity = max(severity_counts, key=severity_counts.get) if severity_counts else None
            preferred_team = max(team_counts, key=team_counts.get) if team_counts else None

            return {
                'most_escalated_service': most_escalated_service,
                'most_used_severity': most_used_severity,
                'preferred_team': preferred_team,
                'total_escalations': len(escalations),
                'last_escalation_date': escalations[0]['created_at'] if escalations else None
            }

        except Exception as e:
            self.logger.error(f"Pattern analysis failed: {str(e)}")
            return None

    def should_send_return_reminder(self, user_id: str = "default_user", days_threshold: int = 30) -> bool:
        """
        Check if pattern-based reminder should be sent.

        Currently returns False as this feature is not yet implemented for incident ops.
        """
        return False

    def generate_return_message(self, user_id: str = "default_user") -> Optional[str]:
        """
        Generate pattern-based insight message.

        Currently returns None as this feature is not yet implemented for incident ops.
        """
        return None
