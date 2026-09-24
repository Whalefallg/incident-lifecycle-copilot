"""
Behavior Recorder

Records engineer incident handling actions for pattern learning:
1. Incident escalation decisions
2. Runbook lookup queries
3. Communication draft requests
4. Postmortem generation triggers
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import logging


class BehaviorRecorder:
    """Records engineer behavior during incident handling."""

    def __init__(self, behavior_service=None):
        self.behavior_service = behavior_service
        self.logger = logging.getLogger(__name__)

    @property
    def behavior_db(self):
        """Backward compatibility property."""
        if hasattr(self, 'behavior_service') and self.behavior_service:
            return self.behavior_service.user_behavior_repo
        return None

    def record_behavior(self, action_type: str, action_data: Dict[str, Any] = None,
                       session_id: str = None) -> Optional[int]:
        """
        Record engineer action.

        Args:
            action_type: Action type (incident_escalation, runbook_lookup, etc.)
            action_data: Action context data
            session_id: Session ID

        Returns:
            Record ID or None if failed
        """
        try:
            if self.behavior_service:
                success = self.behavior_service.record_behavior(
                    user_id="default_user",
                    action_type=action_type,
                    action_data=action_data,
                    session_id=session_id or "default_session"
                )
                return 1 if success else None
            else:
                behavior_id = self.behavior_db.record_behavior(
                    user_id="default_user",
                    action_type=action_type,
                    action_data=action_data,
                    session_id=session_id
                )
                return behavior_id

        except Exception as e:
            self.logger.error(f"Failed to record behavior: {str(e)}")
            return None

    def record_incident_escalation(self, escalation_data: Dict[str, Any],
                                  session_id: str = None) -> Optional[int]:
        """Convenience method for recording incident escalations."""
        return self.record_behavior(
            action_type='incident_escalation',
            action_data=escalation_data,
            session_id=session_id
        )

    def record_runbook_lookup(self, lookup_data: Dict[str, Any],
                             session_id: str = None) -> Optional[int]:
        """Convenience method for recording runbook lookups."""
        return self.record_behavior(
            action_type='runbook_lookup',
            action_data=lookup_data,
            session_id=session_id
        )

    def get_user_behaviors(self, action_type: str = None,
                          days_back: int = 30) -> List[Dict[str, Any]]:
        """Get recorded behaviors."""
        try:
            return self.behavior_db.get_user_behaviors(
                action_type=action_type,
                days_back=days_back
            )
        except Exception as e:
            self.logger.error(f"Failed to get behaviors: {str(e)}")
            return []

    def get_behavior_statistics(self, days_back: int = 30) -> Dict[str, Any]:
        """Get behavior statistics."""
        try:
            return self.behavior_db.get_user_statistics(days_back=days_back)
        except Exception as e:
            self.logger.error(f"Failed to get statistics: {str(e)}")
            return {}
