"""
Incident Processor — coordinates incident escalation and on-call dispatch.
"""

from typing import Dict, Any, AsyncGenerator, Optional
from .input_parser import InputParser
from .oncall_matcher import OnCallMatcher
from .message_builder import MessageBuilder


class IncidentProcessor:
    """Processes incident escalation requests and dispatches to on-call engineers."""

    def __init__(
        self,
        input_parser: InputParser,
        oncall_matcher: OnCallMatcher,
        message_builder: MessageBuilder,
        llm=None,
    ):
        self.input_parser = input_parser
        self.oncall_matcher = oncall_matcher
        self.message_builder = message_builder
        self.llm = llm
        self.event_sink = None

    def update_history_from_data(
        self, incident_history: Dict[str, Any], data: Dict[str, Any]
    ) -> bool:
        """
        Update incident history from parsed data.

        Returns True if all required info is present (severity + service).
        """
        if incident_history.get("awaiting_confirmation"):
            return self._handle_recommendation_response(incident_history, data)

        for key in [
            "severity",
            "service",
            "impact_scope",
            "symptoms",
            "suspected_cause",
            "recent_changes",
            "oncall_preference",
        ]:
            if data.get(key) and data[key] != "unknown":
                incident_history[key] = data[key]

        required_fields = ["severity", "service"]
        has_all_required = all(
            incident_history.get(field) and incident_history[field] != "unknown"
            for field in required_fields
        )

        return has_all_required

    def _handle_recommendation_response(
        self, incident_history: Dict[str, Any], data: Dict[str, Any]
    ) -> bool:
        """Handle engineer response to recommended alternate on-call."""
        user_response = data.get("confirmation", "").lower()

        positive_responses = ["是", "好", "可以", "同意", "确定", "yes", "ok", "行", "proceed"]
        negative_responses = ["不", "不要", "不行", "不同意", "换", "no"]

        is_positive = any(pos in user_response for pos in positive_responses)
        is_negative = any(neg in user_response for neg in negative_responses)

        if is_positive and not is_negative:
            recommended_oncall = incident_history.get("recommended_oncall")
            if recommended_oncall:
                incident_history["confirmed_oncall"] = recommended_oncall
                incident_history["awaiting_confirmation"] = False
                return True
        elif is_negative:
            incident_history["recommendation_declined"] = True
            incident_history["awaiting_confirmation"] = False
            return True

        return False

    async def handle_unrelated_request(
        self, user_input: str, unrelated_callback, state
    ) -> AsyncGenerator[str, None]:
        """Route unrelated requests back to triage."""
        yield "[REPLY][Escalation Agent] This request is unrelated to incident escalation. Routing back to triage...\n"

        if unrelated_callback:
            try:
                result = await unrelated_callback(user_input)
                if hasattr(result, "__aiter__"):
                    async for token in result:
                        yield token
                else:
                    yield result
            except Exception as e:
                yield f"[ERROR] Failed to route request: {str(e)}\n"
                yield self.message_builder.create_unrelated_message()
        else:
            yield self.message_builder.create_unrelated_message()

    async def handle_complete_incident(
        self, incident_history: Dict[str, Any], session_id: str
    ) -> AsyncGenerator[str, None]:
        """Handle incident when all required info is present."""
        if incident_history.get("recommendation_declined"):
            reply = self.message_builder.create_recommendation_declined_message(self.llm)
            yield f"[REPLY][Escalation Agent]{reply}"
            incident_history.pop("recommendation_declined", None)
            incident_history.pop("recommended_oncall", None)
            incident_history.pop("original_oncall", None)
            return

        if incident_history.get("confirmed_oncall"):
            oncall = incident_history["confirmed_oncall"]
            oncall["is_recommendation"] = True
            oncall["original_oncall"] = incident_history.get("original_oncall")
            reply = await self._process_successful_escalation(
                oncall, incident_history, session_id
            )
            yield f"[REPLY][Escalation Agent]{reply}"
            incident_history.pop("confirmed_oncall", None)
            incident_history.pop("recommended_oncall", None)
            incident_history.pop("original_oncall", None)
            return

        if incident_history.get("awaiting_confirmation"):
            yield '[REPLY][Escalation Agent]\nCoordinator: Please confirm with "yes" or "no" so I can proceed with escalation.\n'
            return

        thought_msgs = []

        def collect_thoughts(msg):
            thought_msgs.append(msg)

        oncall = self.oncall_matcher.find_oncall_for_incident(
            incident_history, collect_thoughts
        )

        for msg in thought_msgs:
            yield msg

        oncall_preference = incident_history.get("oncall_preference")

        if oncall:
            if oncall.get("requires_confirmation"):
                original_oncall = oncall.get("original_oncall")
                recommended_oncall = oncall.get("recommended_oncall")

                recommendation_msg = (
                    self.message_builder.create_oncall_recommendation_message(
                        original_oncall, recommended_oncall, incident_history, self.llm
                    )
                )
                yield f"[REPLY][Escalation Agent]{recommendation_msg}"

                incident_history["recommended_oncall"] = recommended_oncall
                incident_history["original_oncall"] = original_oncall
                incident_history["awaiting_confirmation"] = True
                yield "[SIGNAL]recommendation_pending"
                return
            else:
                reply = await self._process_successful_escalation(
                    oncall, incident_history, session_id
                )
                yield f"[REPLY][Escalation Agent]{reply}"
        else:
            service = incident_history.get("service", "unknown service")
            reply = self.message_builder.create_escalation_failure_message(service)
            yield f"[REPLY][Escalation Agent]{reply}"

    async def _process_successful_escalation(
        self, oncall: Dict[str, Any], incident_history: Dict[str, Any], session_id: str
    ) -> str:
        """Process successful on-call dispatch."""
        incident_context = {
            "severity": incident_history.get("severity", "unknown"),
            "service": incident_history.get("service", "unknown"),
            "impact_scope": incident_history.get("impact_scope", "unknown"),
            "symptoms": incident_history.get("symptoms", "unknown"),
            "suspected_cause": incident_history.get("suspected_cause", "unknown"),
            "recent_changes": incident_history.get("recent_changes", "none reported"),
        }
        if self.event_sink:
            from conversation.events import IncidentEventType

            self.event_sink(
                IncidentEventType.ONCALL_DISPATCHED,
                actor="EscalationAgent",
                source="oncall_dispatch",
                payload={
                    "service": incident_context["service"],
                    "severity": incident_context["severity"],
                    "team": oncall.get("team") or oncall.get("primary"),
                },
            )
        return self.message_builder.create_escalation_dispatched_message(incident_context)

    async def handle_incomplete_info(
        self, data: Dict[str, Any], incident_history: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Ask for missing incident context."""
        missing = []

        if (
            not incident_history.get("severity")
            or incident_history.get("severity") == "unknown"
        ):
            missing.append("severity")
        if (
            not incident_history.get("service")
            or incident_history.get("service") == "unknown"
        ):
            missing.append("service")

        if not missing and not incident_history.get("impact_scope"):
            missing.append("impact_scope")
        if not missing and not incident_history.get("symptoms"):
            missing.append("symptoms")

        reply = self.message_builder.create_missing_info_questions(missing)
        yield f"[THOUGHT][Escalation Agent] Incident info incomplete, missing: {', '.join(missing)}\n"
        yield f"[REPLY][Escalation Agent]{reply}"
