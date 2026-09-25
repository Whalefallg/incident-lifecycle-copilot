"""
State manager for the incident lifecycle conversation flow.

States:
    CLASSIFY        — awaiting classification of next input
    ESCALATION      — active P0/P1 incident; escalation agent owns the turn
    RUNBOOK_LOOKUP  — runbook / historical incident RAG in progress
    COMMS_DRAFTING  — stakeholder status update being drafted
    POSTMORTEM      — postmortem generation in progress

Suspend / Resume:
    When an agent (e.g. EscalationAgent) detects an off-topic request mid-flow,
    it calls suspend_current() to push the current state + agent snapshot onto
    the suspend stack instead of discarding context.  After the inserted task
    completes, ClassificationProcessor calls resume_suspended() to pop the stack
    and hand control back to the original agent with its saved snapshot.

    Stack depth is capped at MAX_SUSPEND_DEPTH (default 2) to prevent runaway
    nesting (e.g. runbook query mid-escalation that itself triggers another
    off-topic branch).

Persistence is deliberately outside this class.  A request coordinator hydrates
the manager from a ConversationSnapshot and atomically saves the whole snapshot.
"""

from config.constants import SharedState, StateEnum
from typing import Optional

from conversation.models import ConversationSnapshot, EscalationContext

MAX_SUSPEND_DEPTH = 2


class SuspendedFrame:
    """A single entry in the suspend stack."""

    def __init__(self, state: StateEnum, agent_snapshot: Optional[dict] = None):
        self.state = state
        self.agent_snapshot = agent_snapshot or {}  # serialisable incident context

    def __repr__(self) -> str:
        return f"SuspendedFrame(state={self.state}, keys={list(self.agent_snapshot.keys())})"


class StateManager:
    """Manages conversation state transitions and the suspend / resume stack."""

    def __init__(self, shared_state: Optional[SharedState] = None, session_id: Optional[str] = None):
        self.state = shared_state or SharedState()
        self._suspend_stack: list[SuspendedFrame] = []
        self.session_id = session_id

    def get_current_state(self) -> StateEnum:
        return self.state.value or StateEnum.CLASSIFY

    def set_state(self, new_state: StateEnum) -> None:
        old_state = self.state.value
        self.state.value = new_state
        print(f"[StateManager] {old_state} → {new_state}")

    def hydrate(self, snapshot: ConversationSnapshot) -> None:
        """Load workflow-only state from the request's authoritative snapshot."""
        self.state.value = snapshot.current_state
        self._suspend_stack = [
            SuspendedFrame(
                frame.state,
                frame.escalation_context.to_legacy_dict()
                if frame.escalation_context
                else {},
            )
            for frame in snapshot.suspend_stack
        ]

    def apply_to_snapshot(self, snapshot: ConversationSnapshot) -> None:
        """Copy workflow-only state back without persisting it independently."""
        from conversation.models import SuspendedFrame as SnapshotFrame

        snapshot.current_state = self.get_current_state()
        snapshot.suspend_stack = [
            SnapshotFrame(
                state=frame.state,
                escalation_context=EscalationContext.from_legacy_dict(
                    frame.agent_snapshot
                ),
            )
            for frame in self._suspend_stack
        ]

    def reset_to_classify(self) -> None:
        self.set_state(StateEnum.CLASSIFY)

    def should_classify(self) -> bool:
        return self.get_current_state() == StateEnum.CLASSIFY

    # ------------------------------------------------------------------ #
    # Suspend / Resume stack                                               #
    # ------------------------------------------------------------------ #

    def suspend_current(self, agent_snapshot: Optional[dict] = None) -> bool:
        """
        Push the current state + agent snapshot onto the suspend stack and
        transition to CLASSIFY so the inserted task can be routed normally.

        Returns False (and does nothing) if the stack is already at max depth,
        preventing runaway nesting.
        """
        if len(self._suspend_stack) >= MAX_SUSPEND_DEPTH:
            print(f"[StateManager] Suspend stack full (depth={MAX_SUSPEND_DEPTH}) — falling back to discard")
            return False
        frame = SuspendedFrame(self.get_current_state(), agent_snapshot or {})
        self._suspend_stack.append(frame)
        print(f"[StateManager] Suspended {frame.state} → stack depth {len(self._suspend_stack)}")
        self.set_state(StateEnum.CLASSIFY)
        return True

    def resume_suspended(self) -> Optional[SuspendedFrame]:
        """
        Pop the most-recently suspended frame, restore its state, and return
        it so the caller can hand the snapshot back to the original agent.

        Returns None if nothing is suspended.
        """
        if not self._suspend_stack:
            return None
        frame = self._suspend_stack.pop()
        self.set_state(frame.state)
        print(f"[StateManager] Resumed {frame.state} ← stack depth {len(self._suspend_stack)}")
        return frame

    def peek_suspended(self) -> Optional[SuspendedFrame]:
        """Return the top frame without popping it."""
        return self._suspend_stack[-1] if self._suspend_stack else None

    def has_suspended_context(self) -> bool:
        return len(self._suspend_stack) > 0

    def clear_suspend_stack(self) -> None:
        self._suspend_stack.clear()
        print("[StateManager] Suspend stack cleared")

    # ------------------------------------------------------------------ #
    # Incident lifecycle transitions                                        #
    # ------------------------------------------------------------------ #

    def transition_to_escalation(self) -> None:
        self.set_state(StateEnum.ESCALATION)

    def transition_to_runbook_lookup(self) -> None:
        self.set_state(StateEnum.RUNBOOK_LOOKUP)

    def transition_to_comms_drafting(self) -> None:
        self.set_state(StateEnum.COMMS_DRAFTING)

    def transition_to_postmortem(self) -> None:
        self.set_state(StateEnum.POSTMORTEM)

    # ------------------------------------------------------------------ #
    # State queries                                                         #
    # ------------------------------------------------------------------ #

    def is_in_escalation_flow(self) -> bool:
        return self.get_current_state() == StateEnum.ESCALATION

    def is_in_runbook_flow(self) -> bool:
        return self.get_current_state() == StateEnum.RUNBOOK_LOOKUP

    def is_in_comms_flow(self) -> bool:
        return self.get_current_state() == StateEnum.COMMS_DRAFTING

    def is_in_postmortem_flow(self) -> bool:
        return self.get_current_state() == StateEnum.POSTMORTEM

    def get_state_description(self) -> str:
        descriptions = {
            StateEnum.CLASSIFY:       "Awaiting next input — ready to triage",
            StateEnum.ESCALATION:     "Active incident escalation — collecting impact & dispatching on-call",
            StateEnum.RUNBOOK_LOOKUP: "Runbook / incident memory lookup in progress",
            StateEnum.COMMS_DRAFTING: "Drafting stakeholder status updates",
            StateEnum.POSTMORTEM:     "Generating postmortem from session history",
        }
        return descriptions.get(self.get_current_state(), "Unknown state")

    def can_transition_to(self, target_state: StateEnum) -> bool:
        current = self.get_current_state()
        allowed = {
            StateEnum.CLASSIFY:       [
                StateEnum.ESCALATION, StateEnum.RUNBOOK_LOOKUP,
                StateEnum.COMMS_DRAFTING, StateEnum.POSTMORTEM,
            ],
            StateEnum.ESCALATION:     [StateEnum.CLASSIFY, StateEnum.POSTMORTEM],
            StateEnum.RUNBOOK_LOOKUP: [StateEnum.CLASSIFY],
            StateEnum.COMMS_DRAFTING: [StateEnum.CLASSIFY],
            StateEnum.POSTMORTEM:     [StateEnum.CLASSIFY],
        }
        return target_state in allowed.get(current, [])

    def force_reset(self) -> None:
        print("[StateManager] Force reset to CLASSIFY")
        self.clear_suspend_stack()
        self.reset_to_classify()
