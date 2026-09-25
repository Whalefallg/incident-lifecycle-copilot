"""
Timeline extractor — reconstructs incident timeline from session conversation history.

Extracts key events from the dialogue between engineers and the Copilot:
- alert detection time
- triage classification
- runbook lookups
- escalation events
- mitigation attempts
- resolution confirmation
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


class LegacyTranscriptTimelineExtractor:
    """Best-effort importer for historical transcripts without event ledgers."""

    # Keywords that signal important timeline events
    TRIAGE_KEYWORDS = ["p0", "p1", "p2", "critical", "severity", "alert", "error rate", "down", "unavailable"]
    RUNBOOK_KEYWORDS = ["runbook", "lookup", "how did", "how do", "last time", "what happened", "steps"]
    ESCALATION_KEYWORDS = ["escalat", "on-call", "oncall", "paged", "dispatch", "bridge", "notify"]
    MITIGATION_KEYWORDS = ["rollback", "restart", "scale", "kill", "fix", "deploy", "patch", "workaround", "mitigat"]
    RESOLUTION_KEYWORDS = ["resolved", "fixed", "recovered", "stable", "back to normal", "closed", "postmortem"]

    def extract_timeline(
        self,
        session_messages: List[Dict[str, Any]],
        session_start_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract ordered timeline events from conversation history.

        Args:
            session_messages: List of message dicts with 'role', 'content', 'timestamp' keys.
            session_start_time: Optional override for when the session started.

        Returns:
            List of timeline event dicts sorted by sequence.
        """
        events = []
        start_ts = session_start_time or datetime.now(timezone.utc)

        for i, msg in enumerate(session_messages):
            content = msg.get("content", "").lower()
            role = msg.get("role", "unknown")
            ts = msg.get("timestamp", start_ts.isoformat())

            event_type = self._classify_event(content, role)
            if event_type:
                events.append({
                    "sequence": i,
                    "timestamp": ts,
                    "role": role,
                    "event_type": event_type,
                    "content_preview": msg.get("content", "")[:200],
                })

        return events

    def _classify_event(self, content: str, role: str) -> Optional[str]:
        """Classify a message into an incident lifecycle event type."""
        if role in ("system", "thought"):
            return None

        if any(kw in content for kw in self.RESOLUTION_KEYWORDS):
            return "resolution"
        if any(kw in content for kw in self.MITIGATION_KEYWORDS):
            return "mitigation"
        if any(kw in content for kw in self.ESCALATION_KEYWORDS):
            return "escalation"
        if any(kw in content for kw in self.RUNBOOK_KEYWORDS):
            return "runbook_lookup"
        if any(kw in content for kw in self.TRIAGE_KEYWORDS):
            return "triage"

        return None

    def build_timeline_summary(self, events: List[Dict[str, Any]]) -> str:
        """Format timeline events into a readable summary string."""
        if not events:
            return "No structured timeline events could be extracted from the session."

        lines = ["INCIDENT TIMELINE (reconstructed from session history)", ""]
        for event in events:
            ts = event.get("timestamp", "unknown time")
            etype = event.get("event_type", "event").upper().replace("_", " ")
            preview = event.get("content_preview", "")[:150]
            lines.append(f"[{ts}] {etype}")
            lines.append(f"  > {preview}")
            lines.append("")

        return "\n".join(lines)

    def extract_incident_metadata(self, session_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract high-level incident metadata from the session.
        Used to pre-populate postmortem fields.
        """
        full_text = " ".join(
            msg.get("content", "").lower() for msg in session_messages
        )

        severity = "unknown"
        for level in ["p0", "p1", "p2", "p3"]:
            if level in full_text:
                severity = level.upper()
                break

        service = "unknown"
        known_services = [
            "checkout-service", "payment-gateway", "auth-service",
            "redis-cache", "lambda-processor", "postgres-primary",
        ]
        for svc in known_services:
            if svc.replace("-", " ") in full_text or svc in full_text:
                service = svc
                break

        detected_at = None
        resolved_at = None
        for msg in session_messages:
            content_lower = msg.get("content", "").lower()
            ts = msg.get("timestamp")
            if not detected_at and any(kw in content_lower for kw in self.TRIAGE_KEYWORDS):
                detected_at = ts
            if not resolved_at and any(kw in content_lower for kw in self.RESOLUTION_KEYWORDS):
                resolved_at = ts

        return {
            "severity": severity,
            "service": service,
            "detected_at": detected_at or "unknown",
            "resolved_at": resolved_at or "ongoing",
            "message_count": len(session_messages),
        }


# Compatibility alias for callers importing old transcripts explicitly.
TimelineExtractor = LegacyTranscriptTimelineExtractor
