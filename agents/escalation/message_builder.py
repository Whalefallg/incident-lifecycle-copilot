"""
Message builder for the Escalation & On-call Dispatch Agent.
Constructs response messages for incident escalation flows.
"""

from typing import Dict, Any, List
from config.domain_knowledge import ON_CALL_ROSTER, get_oncall_for_service


class MessageBuilder:
    """Builds response messages for incident escalation flows."""

    def __init__(self):
        self.missing_info_prompts = {
            "severity": "What is the severity level? (P0 = customer-facing outage / P1 = degraded with workaround / P2 = warning)",
            "service": "Which service is affected? (e.g. checkout-service, payment-gateway, redis-cache)",
            "impact_scope": "What is the impact scope? (affected user count, regions, revenue impact)",
            "symptoms": "What symptoms are you observing? (error rates, latency, timeouts)",
        }

    def create_escalation_dispatched_message(self, incident_context: Dict[str, Any]) -> str:
        """Create a message confirming on-call dispatch with escalation details."""
        severity = incident_context.get("severity", "unknown")
        service = incident_context.get("service", "unknown service")
        impact = incident_context.get("impact_scope", "unknown")
        symptoms = incident_context.get("symptoms", "unknown")
        suspected_cause = incident_context.get("suspected_cause", "unknown")
        recent_changes = incident_context.get("recent_changes", "none reported")

        oncall = get_oncall_for_service(service)
        if not oncall:
            oncall_line = "On-call rotation could not be determined automatically. Check PagerDuty for the current on-call engineer."
        else:
            oncall_line = (
                f"On-call dispatched: {oncall['team']} | "
                f"Primary: {oncall['primary']} | Secondary: {oncall['secondary']} | "
                f"Bridge channel: {oncall['slack_channel']}"
            )

        lines = [
            f"Incident escalation initiated — {severity}",
            "",
            f"Service:         {service}",
            f"Impact:          {impact}",
            f"Symptoms:        {symptoms}",
            f"Suspected cause: {suspected_cause}",
            f"Recent changes:  {recent_changes}",
            "",
            oncall_line,
            "",
            "Next steps:",
            "  1. Open a bridge in the Slack channel above",
            "  2. Post status page acknowledgement if customer-facing",
            "  3. Check Datadog APM and recent deploy history",
            "  4. Update this thread with findings every 15 minutes",
            "",
            "When the incident is resolved, say 'incident resolved' to generate the postmortem.",
        ]
        return "\n".join(lines)

    def create_oncall_recommendation_message(
        self,
        original_oncall: Dict[str, Any],
        recommended_oncall: Dict[str, Any],
        incident_context: Dict[str, Any],
        llm=None,
    ) -> str:
        """Create a message recommending an alternate on-call engineer."""
        service = incident_context.get("service", "the affected service")
        severity = incident_context.get("severity", "unknown")

        if llm:
            try:
                prompt = (
                    f"You are an incident coordinator. The primary on-call for {service} is unavailable. "
                    f"Recommend {recommended_oncall['primary']} ({recommended_oncall['team']}) as the alternate. "
                    f"Incident severity: {severity}. Keep the message under 60 words, professional tone."
                )
                response = llm.invoke(prompt)
                if hasattr(response, "content") and response.content.strip():
                    return f"\nCoordinator: {response.content.strip()}\n"
            except Exception as e:
                print(f"[MessageBuilder] LLM recommendation failed: {e}")

        return (
            f"\nCoordinator: {original_oncall['primary']} ({original_oncall['team']}) is currently unavailable. "
            f"Recommending {recommended_oncall['primary']} ({recommended_oncall['team']}) who covers adjacent services. "
            f"Shall I page them for this {severity} incident?\n"
        )

    def create_recommendation_declined_message(self, llm=None) -> str:
        """Create a message when the engineer declines the recommended on-call."""
        if llm:
            try:
                prompt = (
                    "An engineer declined the recommended on-call. Respond professionally, "
                    "offer to look up alternate contacts in PagerDuty, and remind them to check "
                    "the escalation path. Under 50 words."
                )
                response = llm.invoke(prompt)
                if hasattr(response, "content") and response.content.strip():
                    return f"\nCoordinator: {response.content.strip()}\n"
            except Exception as e:
                print(f"[MessageBuilder] LLM decline message failed: {e}")

        return (
            "\nCoordinator: Understood. Please check PagerDuty for the current on-call schedule, "
            "or escalate directly via your team's escalation path. "
            "I can also help you draft a bridge message.\n"
        )

    def create_escalation_failure_message(self, service: str) -> str:
        """Create a message when on-call dispatch could not be determined."""
        return (
            f"\nCoordinator: Could not automatically determine on-call for '{service}'. "
            "Please check PagerDuty or your team's on-call schedule directly. "
            "If this is a P0, escalate immediately to your VP Engineering escalation path.\n"
        )

    def create_missing_info_questions(self, missing_info: List[str]) -> str:
        """Ask for missing incident context fields."""
        questions = [
            self.missing_info_prompts.get(field, f"Please provide: {field}")
            for field in missing_info
        ]
        return "\n" + " ".join(questions) + "\n"

    def create_unrelated_message(self) -> str:
        return (
            "[REPLY][Escalation Agent] I can only assist with incident escalation. "
            "Please describe the incident alert or affected service.\n"
        )

    def create_parse_error_message(self) -> str:
        return "[REPLY][Escalation Agent] Failed to parse incident details. Please re-describe the incident.\n"

    def create_save_failure_message(self) -> str:
        return "\nCoordinator: Failed to record incident context. Please retry.\n"
