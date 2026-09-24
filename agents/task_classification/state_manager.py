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

Production Enhancement:
    状态机现在支持 Redis 共享存储，实现 FastAPI 节点无状态化。
    当 REDIS_STATE_ENABLED=true 时，状态自动持久化到 Redis。
"""

from config.constants import SharedState, StateEnum
from typing import Any, Optional
import os
import logging

logger = logging.getLogger(__name__)

MAX_SUSPEND_DEPTH = 2
REDIS_STATE_ENABLED = os.getenv("REDIS_STATE_ENABLED", "false").lower() == "true"


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
        self._redis_store = None

        if REDIS_STATE_ENABLED and session_id:
            from config.redis_config import redis_state_store
            self._redis_store = redis_state_store

    def get_current_state(self) -> StateEnum:
        return self.state.value or StateEnum.CLASSIFY

    def set_state(self, new_state: StateEnum) -> None:
        old_state = self.state.value
        self.state.value = new_state
        print(f"[StateManager] {old_state} → {new_state}")

        if REDIS_STATE_ENABLED and self._redis_store and self.session_id:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._persist_to_redis())
                else:
                    loop.run_until_complete(self._persist_to_redis())
            except Exception as e:
                logger.error(f"Failed to persist state to Redis: {e}")

    async def _persist_to_redis(self):
        """持久化状态到 Redis"""
        if not self._redis_store or not self.session_id:
            return

        state_data = {
            "current_state": self.state.value.value,
            "suspend_stack": [
                {"state": f.state.value, "snapshot": f.agent_snapshot}
                for f in self._suspend_stack
            ],
        }
        await self._redis_store.save_state(self.session_id, state_data)

    async def load_from_redis(self) -> bool:
        """从 Redis 恢复状态"""
        if not REDIS_STATE_ENABLED or not self._redis_store or not self.session_id:
            return False

        try:
            state_data = await self._redis_store.load_state(self.session_id)
            if not state_data:
                return False

            self.state.value = StateEnum(state_data["current_state"])

            self._suspend_stack = [
                SuspendedFrame(StateEnum(f["state"]), f["snapshot"])
                for f in state_data.get("suspend_stack", [])
            ]

            logger.info(f"State restored from Redis: session={self.session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to load state from Redis: {e}")
            return False

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

        if REDIS_STATE_ENABLED and self._redis_store and self.session_id:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._persist_to_redis())
                else:
                    loop.run_until_complete(self._persist_to_redis())
            except Exception as e:
                logger.error(f"Failed to persist suspend stack to Redis: {e}")

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
