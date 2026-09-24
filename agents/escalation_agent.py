from dotenv import load_dotenv
import uuid
from langchain_core.chat_history import InMemoryChatMessageHistory
from config.model_provider import create_chat_model
from .escalation import (
    InputParser,
    OnCallMatcher,
    IncidentProcessor,
    MessageBuilder,
)

load_dotenv()


class EscalationAgent:
    """
    Escalation Agent — coordinates incident triage, on-call dispatch, and escalation.

    Collects incident context (severity, service, impact) from the engineer,
    matches the appropriate on-call rotation, and dispatches the escalation.
    """

    def __init__(self, session_id=None, unrelated_callback=None, suspend_callback=None):
        self.session_id = session_id or str(uuid.uuid4())
        self.unrelated_callback = unrelated_callback  # legacy fallback
        self.suspend_callback = suspend_callback       # preferred: suspend + resume
        self.state = None

        self.llm = create_chat_model(temperature=0)

        self.input_parser = InputParser(self.llm)
        self.oncall_matcher = OnCallMatcher()
        self.message_builder = MessageBuilder()
        self.incident_processor = IncidentProcessor(
            self.input_parser,
            self.oncall_matcher,
            self.message_builder,
            self.llm,
        )

        self.chats_by_session_id = {}
        self.chat_history = self._get_chat_history(self.session_id)

        self.reset()

    def _get_chat_history(self, session_id: str) -> InMemoryChatMessageHistory:
        chat_history = self.chats_by_session_id.get(session_id)
        if chat_history is None:
            chat_history = InMemoryChatMessageHistory()
            self.chats_by_session_id[session_id] = chat_history
        return chat_history

    def reset(self):
        """Reset incident context and conversation state."""
        self.incident_history = {
            "severity": None,
            "service": None,
            "impact_scope": None,
            "symptoms": None,
            "suspected_cause": None,
            "recent_changes": None,
            "oncall_preference": None,
        }
        self.finished = False
        self.chat_history.clear()

    def set_shared_state(self, shared_state):
        self.state = shared_state

    async def run_stream(self, user_input=None):
        """
        Stream-process an incident escalation request.

        Entry point: parses engineer input, checks completeness, dispatches on-call or asks for more info.
        """
        if user_input is None:
            user_input = input("Engineer: ")

        ai_content = ""
        for token in self.input_parser.parse_stream(user_input, self.chat_history):
            ai_content += token

        try:
            data = self.input_parser.parse_data(ai_content)
            self.finished = self.incident_processor.update_history_from_data(
                self.incident_history, data
            )

            if data.get("unrelated", False) and not self.incident_history.get(
                "awaiting_confirmation"
            ):
                # Prefer suspend+resume over discard-and-reroute so the
                # engineer's incident context is preserved across the detour.
                snapshot = self._build_snapshot()

                if self.suspend_callback:
                    # New path: suspend current context, handle inserted task,
                    # then ClassificationProcessor will auto-resume.
                    yield "[THOUGHT][EscalationAgent] Off-topic request detected — suspending incident context."
                    async for token in self.suspend_callback(user_input, snapshot):
                        yield token
                else:
                    # Legacy fallback: discard context and reroute
                    if self.state:
                        from config.constants import StateEnum
                        self.state.value = StateEnum.CLASSIFY
                    async for token in self.incident_processor.handle_unrelated_request(
                        user_input, self.unrelated_callback, self.state
                    ):
                        yield token
                return

            if self.finished:
                recommendation_pending = False
                async for token in self.incident_processor.handle_complete_incident(
                    self.incident_history, self.session_id
                ):
                    if token == "[SIGNAL]recommendation_pending":
                        recommendation_pending = True
                        self.finished = False
                        continue
                    yield token

                if not recommendation_pending and not self.incident_history.get(
                    "awaiting_confirmation"
                ):
                    self._reset_state_after_escalation()
                return

            async for token in self.incident_processor.handle_incomplete_info(
                data, self.incident_history
            ):
                yield token

        except Exception as e:
            yield self.message_builder.create_parse_error_message()

    def _reset_state_after_escalation(self):
        """Reset state after escalation is dispatched."""
        self.reset()
        if self.state:
            from config.constants import StateEnum
            self.state.value = StateEnum.CLASSIFY

    def _build_snapshot(self) -> dict:
        """Serialise current incident_history for the suspend stack."""
        return {k: v for k, v in self.incident_history.items()}

    def restore_snapshot(self, snapshot: dict) -> None:
        """
        Restore incident_history from a suspend-stack snapshot.
        Called by ClassificationProcessor after the inserted task completes.
        """
        for k, v in snapshot.items():
            if k in self.incident_history:
                self.incident_history[k] = v
        print(f"[EscalationAgent] Snapshot restored: {list(snapshot.keys())}")

    async def prompt_resume_stream(self):
        """
        Yield a brief prompt reminding the engineer where the escalation was
        paused, so they can continue without re-entering all context.
        """
        sev = self.incident_history.get("severity") or "unknown severity"
        svc = self.incident_history.get("service") or "unknown service"
        collected = [
            k for k, v in self.incident_history.items()
            if v and k not in ("awaiting_confirmation",)
        ]
        missing = [
            k for k, v in self.incident_history.items()
            if not v and k not in ("awaiting_confirmation",)
        ]

        msg = (
            f"[REPLY][EscalationAgent] Resuming your incident escalation "
            f"({sev} / {svc}). "
        )
        if collected:
            msg += f"I still have: {', '.join(collected)}. "
        if missing:
            msg += f"Still needed: {', '.join(missing)}. Please continue."
        else:
            msg += "All required fields are collected — ready to dispatch on-call."

        for char in msg:
            yield char
