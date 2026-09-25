"""
Agent router — dispatches classified incidents to the appropriate specialist agent.

Routing table:
    escalation    → EscalationAgent
    query         → RunbookAgent (ConsultantAgent)
    comms_update  → CommunicationAgent
    postmortem    → PostmortemAgent
    other         → rejection message
"""

from typing import Any, AsyncGenerator, Optional
from .state_manager import StateManager


class AgentRouter:
    """Routes classified requests to the appropriate specialist agent."""

    def __init__(
        self,
        escalation_agent: Any,
        consultant_agent: Any,
        state_manager: StateManager,
        communication_agent: Any = None,
        postmortem_agent: Any = None,
    ):
        self.escalation_agent = escalation_agent      # EscalationAgent
        self.consultant_agent = consultant_agent        # RunbookAgent
        self.communication_agent = communication_agent  # CommunicationAgent
        self.postmortem_agent = postmortem_agent        # PostmortemAgent
        self.state_manager = state_manager
        self.event_sink = None
        self._setup_agent_states()

    def _setup_agent_states(self):
        for agent in (self.escalation_agent, self.consultant_agent):
            if agent and hasattr(agent, 'set_shared_state'):
                agent.set_shared_state(self.state_manager.state)

    # ------------------------------------------------------------------ #
    # Core routing methods                                                  #
    # ------------------------------------------------------------------ #

    async def route_to_escalation(self, task: str) -> AsyncGenerator[str, None]:
        """Route a P0/P1 alert to the Escalation & On-call Dispatch Agent."""
        if not self.escalation_agent:
            yield "[ERROR] Escalation service unavailable"
            return
        self.state_manager.transition_to_escalation()
        if self.event_sink:
            from conversation.events import IncidentEventType
            self.event_sink(
                IncidentEventType.ALERT_RECEIVED,
                actor="TriageRouter",
                source="user_request",
                payload={"message": task},
            )
        yield "[THOUGHT][Triage Router] P0/P1 incident detected — routing to Escalation Agent for impact assessment and on-call dispatch."
        try:
            async for token in self.escalation_agent.run_stream(user_input=task):
                yield token
            if getattr(self.escalation_agent, "workflow_complete", False):
                self.state_manager.reset_to_classify()
        except Exception as e:
            yield f"[ERROR] Escalation failed: {e}"
            self.state_manager.reset_to_classify()

    async def route_to_runbook(self, task: str) -> AsyncGenerator[str, None]:
        """Route a knowledge query to the Runbook & Incident Memory Agent."""
        if not self.consultant_agent:
            yield "[ERROR] Runbook service unavailable"
            return
        self.state_manager.transition_to_runbook_lookup()
        yield "[THOUGHT][Triage Router] Knowledge query detected — routing to Runbook Agent for RAG retrieval."
        try:
            async for token in self.consultant_agent.consult_stream(task):
                yield token
            if self.event_sink:
                from conversation.events import IncidentEventType
                self.event_sink(
                    IncidentEventType.RUNBOOK_RETRIEVED,
                    actor="RunbookAgent",
                    source="retrieval",
                    payload={"query": task},
                )
            self.state_manager.reset_to_classify()
        except Exception as e:
            yield f"[ERROR] Runbook lookup failed: {e}"
            self.state_manager.reset_to_classify()

    async def route_to_comms(self, task: str) -> AsyncGenerator[str, None]:
        """Route a comms request to the Multi-Stakeholder Communication Agent."""
        if not self.communication_agent:
            yield "[ERROR] Communication agent unavailable"
            return
        self.state_manager.transition_to_comms_drafting()
        yield "[THOUGHT][Triage Router] Stakeholder update requested — routing to Communication Agent."
        try:
            async for token in self.communication_agent.draft_stream(task):
                yield token
            if self.event_sink:
                from conversation.events import IncidentEventType
                self.event_sink(
                    IncidentEventType.STATUS_UPDATE_DRAFTED,
                    actor="CommunicationAgent",
                    source="comms_drafting",
                    payload={"request": task},
                )
            self.state_manager.reset_to_classify()
        except Exception as e:
            yield f"[ERROR] Comms drafting failed: {e}"
            self.state_manager.reset_to_classify()

    async def route_to_postmortem(self, task: str) -> AsyncGenerator[str, None]:
        """Route a postmortem request to the Postmortem Generator Agent."""
        if not self.postmortem_agent:
            yield "[ERROR] Postmortem agent unavailable"
            return
        self.state_manager.transition_to_postmortem()
        if self.event_sink and any(
            word in task.lower() for word in ("resolved", "recovered", "closed", "fixed")
        ):
            from conversation.events import IncidentEventType
            self.event_sink(
                IncidentEventType.INCIDENT_RESOLVED,
                actor="engineer",
                source="user_confirmation",
                payload={"statement": task},
            )
        yield "[THOUGHT][Triage Router] Incident resolved — routing to Postmortem Agent to reconstruct timeline and generate draft."
        try:
            async for token in self.postmortem_agent.generate_stream(task):
                yield token
            self.state_manager.reset_to_classify()
        except Exception as e:
            yield f"[ERROR] Postmortem generation failed: {e}"
            self.state_manager.reset_to_classify()

    async def handle_unsupported_task(self, category: str) -> AsyncGenerator[str, None]:
        yield "[REPLY][Triage Router]"
        msg = (
            "This request is outside the scope of the Incident Lifecycle Copilot. "
            "I can help with: active incident escalation, runbook lookups, "
            "stakeholder status updates, and postmortem generation."
        )
        for char in msg:
            yield char

    # ------------------------------------------------------------------ #
    # State-continuation routing (multi-turn flows)                        #
    # ------------------------------------------------------------------ #

    async def route_by_state(self, task: str) -> AsyncGenerator[str, None]:
        """Continue processing based on current conversation state."""
        if self.state_manager.is_in_escalation_flow():
            async for token in self.escalation_agent.run_stream(user_input=task):
                yield token
        elif self.state_manager.is_in_runbook_flow():
            async for token in self.consultant_agent.consult_stream(task):
                yield token
        elif self.state_manager.is_in_comms_flow():
            async for token in self.communication_agent.draft_stream(task):
                yield token
        elif self.state_manager.is_in_postmortem_flow():
            async for token in self.postmortem_agent.generate_stream(task):
                yield token
        else:
            self.state_manager.reset_to_classify()
            yield "[ERROR] Session state inconsistency — reset. Please re-send your message."

    # ------------------------------------------------------------------ #
    # Suspend / Resume routing                                             #
    # ------------------------------------------------------------------ #

    async def route_with_suspend(
        self, task: str, agent_snapshot: Optional[dict] = None
    ) -> AsyncGenerator[str, None]:
        """
        Suspend the current flow context, route the inserted task normally,
        then automatically resume the original flow when the task completes.

        Called by EscalationAgent (or any agent) when it detects an off-topic
        request mid-flow and wants to preserve its incident_history context
        instead of discarding it.

        If the suspend stack is full (max depth reached), falls back to the
        legacy discard-and-reroute behaviour.
        """
        suspended = self.state_manager.suspend_current(agent_snapshot)

        if suspended:
            yield "[THOUGHT][Triage Router] Pausing current flow — handling your question, then resuming where we left off."
        else:
            yield "[THOUGHT][Triage Router] Cannot nest further — re-routing (context will reset)."

        # Route the inserted task in CLASSIFY state
        from .task_classifier import TaskClassifier  # avoid circular import at module level
        category = await self._classify_task(task)
        async for token in self._route_by_category(category, task):
            yield token

        # After inserted task completes, attempt to resume
        if suspended and self.state_manager.has_suspended_context():
            frame = self.state_manager.resume_suspended()
            if frame and frame.agent_snapshot:
                yield f"[THOUGHT][Triage Router] Resuming {frame.state.value} flow — restoring your incident context."
                # Hand snapshot back to EscalationAgent via callback if registered
                if (
                    hasattr(self.escalation_agent, "restore_snapshot")
                    and frame.state in (
                        self.state_manager.state.__class__.__mro__[0].__dict__.get(
                            "ESCALATION", None
                        ),
                        # resolve dynamically
                    )
                ):
                    self.escalation_agent.restore_snapshot(frame.agent_snapshot)
                # Trigger the agent to prompt the engineer to continue
                if frame.state.value == "escalation" and self.escalation_agent:
                    async for token in self.escalation_agent.prompt_resume_stream():
                        yield token
            elif frame:
                yield f"[THOUGHT][Triage Router] Resuming {frame.state.value} — please continue your previous request."

    async def resume_suspended_flow(self, task: str) -> AsyncGenerator[str, None]:
        """
        Explicitly resume a suspended flow with new input.
        Used when the engineer explicitly continues after an inserted task.
        """
        frame = self.state_manager.peek_suspended()
        if not frame:
            async for token in self.route_by_state(task):
                yield token
            return

        popped = self.state_manager.resume_suspended()
        if popped and popped.agent_snapshot and hasattr(self.escalation_agent, "restore_snapshot"):
            self.escalation_agent.restore_snapshot(popped.agent_snapshot)

        async for token in self.route_by_state(task):
            yield token

    async def _classify_task(self, task: str) -> str:
        """Internal helper — classify without re-importing at call site."""
        from .task_classifier import TaskClassifier
        if hasattr(self, "_task_classifier"):
            return await self._task_classifier.classify_task(task)
        return "other"

    async def _route_by_category(self, category: str, task: str) -> AsyncGenerator[str, None]:
        """Internal helper — route by category string."""
        if category == "escalation":
            async for t in self.route_to_escalation(task):
                yield t
        elif category == "query":
            async for t in self.route_to_runbook(task):
                yield t
        elif category == "comms_update":
            async for t in self.route_to_comms(task):
                yield t
        elif category == "postmortem":
            async for t in self.route_to_postmortem(task):
                yield t
        else:
            async for t in self.handle_unsupported_task(category):
                yield t

    def set_task_classifier(self, classifier: Any) -> None:
        """Inject the task classifier so route_with_suspend can classify inserted tasks."""
        self._task_classifier = classifier

    def get_available_services(self) -> list:
        services = []
        if self.escalation_agent:
            services.append("Incident Escalation & On-call Dispatch")
        if self.consultant_agent:
            services.append("Runbook & Incident Memory RAG")
        if self.communication_agent:
            services.append("Multi-Stakeholder Status Updates")
        if self.postmortem_agent:
            services.append("Postmortem Generation")
        return services
