"""
On-call matcher — matches incidents to appropriate on-call engineers.
"""

from typing import Optional, Dict, Any, Callable
from config.domain_knowledge import ON_CALL_ROSTER, get_oncall_for_service


class OnCallMatcher:
    """Matches incidents to on-call rotations based on service ownership."""

    def __init__(self):
        pass

    def find_oncall_for_incident(
        self,
        incident_context: Dict[str, Any],
        yield_func: Optional[Callable] = None,
    ) -> Optional[Dict]:
        """
        Find the appropriate on-call rotation for an incident.

        Args:
            incident_context: Dict with keys: service, severity, oncall_preference
            yield_func: Optional callback for thought messages

        Returns:
            Dict with on-call rotation info, or None if not found
        """
        service = incident_context.get("service", "unknown")
        severity = incident_context.get("severity", "unknown")
        oncall_preference = incident_context.get("oncall_preference", "unknown")

        if yield_func:
            yield_func(f"[THOUGHT][Escalation Agent] Looking up on-call for service: {service}\n")

        if oncall_preference and oncall_preference != "unknown":
            if yield_func:
                yield_func(f"[THOUGHT][Escalation Agent] Engineer specified on-call preference: {oncall_preference}\n")
            for rotation_key, rotation in ON_CALL_ROSTER.items():
                if (
                    oncall_preference.lower() in rotation["team"].lower()
                    or oncall_preference.lower() == rotation["primary"].lower()
                ):
                    if yield_func:
                        yield_func(f"[THOUGHT][Escalation Agent] Matched to {rotation['team']}\n")
                    return rotation

        oncall = get_oncall_for_service(service)
        if oncall:
            if yield_func:
                yield_func(
                    f"[THOUGHT][Escalation Agent] Found on-call: {oncall['team']} "
                    f"(primary: {oncall['primary']}, channel: {oncall['slack_channel']})\n"
                )
            return oncall
        else:
            if yield_func:
                yield_func(f"[THOUGHT][Escalation Agent] Could not determine on-call for service '{service}'\n")
            return None
