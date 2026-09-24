"""
Preference Manager

Manages engineer preferences during incident handling:
1. Service ownership preferences
2. Severity classification patterns
3. Team/on-call routing preferences
"""

from typing import Dict, Any, Optional
from datetime import datetime
import logging


class PreferenceManager:
    """Manages engineer incident handling preferences."""

    def __init__(self, behavior_service=None):
        self.behavior_service = behavior_service
        self.logger = logging.getLogger(__name__)

    @property
    def behavior_db(self):
        """Backward compatibility property."""
        if hasattr(self, 'behavior_service') and self.behavior_service:
            return self.behavior_service.user_behavior_repo
        return None

    def update_preferences_from_escalation(self, action_data: Dict[str, Any]):
        """
        Update preferences from incident escalation data.

        Args:
            action_data: Escalation action data containing service, severity, team, etc.
        """
        try:
            if action_data.get('service'):
                self.update_service_preference(action_data['service'])

            if action_data.get('severity'):
                self.update_severity_preference(action_data['severity'])

            if action_data.get('team'):
                self.update_team_preference(action_data['team'])

        except Exception as e:
            self.logger.error(f"Failed to update preferences: {str(e)}")

    def update_service_preference(self, service: str):
        """Update service preference."""
        try:
            self.behavior_db.update_user_preference('service', service)
            self.logger.info(f"Updated service preference: {service}")
        except Exception as e:
            self.logger.error(f"Failed to update service preference: {str(e)}")

    def update_severity_preference(self, severity: str):
        """Update severity classification preference."""
        try:
            self.behavior_db.update_user_preference('severity', severity)
            self.logger.info(f"Updated severity preference: {severity}")
        except Exception as e:
            self.logger.error(f"Failed to update severity preference: {str(e)}")

    def update_team_preference(self, team: str):
        """Update team/on-call routing preference."""
        try:
            self.behavior_db.update_user_preference('team', team)
            self.logger.info(f"Updated team preference: {team}")
        except Exception as e:
            self.logger.error(f"Failed to update team preference: {str(e)}")

    def get_user_preferences(self) -> Dict[str, Any]:
        """Get all user preferences."""
        try:
            return self.behavior_db.get_user_preferences()
        except Exception as e:
            self.logger.error(f"Failed to get preferences: {str(e)}")
            return {}

    def get_preferred_service(self) -> Optional[str]:
        """Get most escalated service."""
        try:
            preferences = self.get_user_preferences()
            return preferences.get('service')
        except Exception as e:
            self.logger.error(f"Failed to get preferred service: {str(e)}")
            return None

    def get_preferred_severity(self) -> Optional[str]:
        """Get most used severity level."""
        try:
            preferences = self.get_user_preferences()
            return preferences.get('severity')
        except Exception as e:
            self.logger.error(f"Failed to get preferred severity: {str(e)}")
            return None

    def get_preferred_team(self) -> Optional[str]:
        """Get most used team."""
        try:
            preferences = self.get_user_preferences()
            return preferences.get('team')
        except Exception as e:
            self.logger.error(f"Failed to get preferred team: {str(e)}")
            return None

    def get_preference_summary(self) -> Dict[str, Any]:
        """Get preference summary."""
        try:
            preferences = self.get_user_preferences()

            summary = {
                'has_service_preference': bool(preferences.get('service')),
                'has_severity_preference': bool(preferences.get('severity')),
                'has_team_preference': bool(preferences.get('team')),
                'preference_count': len([v for v in preferences.values() if v])
            }

            if preferences.get('service'):
                summary['preferred_service'] = preferences['service']
            if preferences.get('severity'):
                summary['preferred_severity'] = preferences['severity']
            if preferences.get('team'):
                summary['preferred_team'] = preferences['team']

            return summary

        except Exception as e:
            self.logger.error(f"Failed to get preference summary: {str(e)}")
            return {}

    def clear_preference(self, preference_type: str):
        """Clear specific preference type."""
        try:
            self.behavior_db.update_user_preference(preference_type, None)
            self.logger.info(f"Cleared preference: {preference_type}")
        except Exception as e:
            self.logger.error(f"Failed to clear preference: {str(e)}")

    def clear_all_preferences(self):
        """Clear all preferences."""
        try:
            preference_types = ['service', 'severity', 'team']
            for pref_type in preference_types:
                self.clear_preference(pref_type)
            self.logger.info("Cleared all preferences")
        except Exception as e:
            self.logger.error(f"Failed to clear all preferences: {str(e)}")
