"""Session-scoped orchestration for chat requests."""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

from agents.escalation_agent import EscalationAgent
from agents.communication_agent import CommunicationAgent
from agents.consultant_agent import ConsultantAgent
from agents.postmortem_agent import PostmortemAgent
from agents.task_classification_agent import TaskClassificationAgent
from config.request_trace import new_trace_id, trace_step
from config.semantic_cache import semantic_cache

logger = logging.getLogger(__name__)

SEMANTIC_CACHE_ENABLED = os.getenv("SEMANTIC_CACHE_ENABLED", "false").lower() == "true"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
MAX_LOCAL_SESSIONS = int(os.getenv("MAX_LOCAL_SESSIONS", "500"))


@dataclass
class SessionAgents:
    """All mutable agent state owned by one browser session."""

    task_agent: TaskClassificationAgent
    escalation_agent: EscalationAgent
    consultant_agent: ConsultantAgent
    postmortem_agent: PostmortemAgent
    last_accessed: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def reset(self) -> None:
        self.task_agent.reset_conversation()
        self.escalation_agent.reset()
        self.postmortem_agent.session_messages.clear()


_sessions: dict[str, SessionAgents] = {}


def _build_session_agents(session_id: str) -> SessionAgents:
    escalation_agent = EscalationAgent(session_id=session_id)
    consultant_agent = ConsultantAgent(session_id=session_id)
    communication_agent = CommunicationAgent(session_id=session_id)
    postmortem_agent = PostmortemAgent(session_id=session_id)
    task_agent = TaskClassificationAgent(
        escalation_agent=escalation_agent,
        consultant_agent=consultant_agent,
        communication_agent=communication_agent,
        postmortem_agent=postmortem_agent,
        session_id=session_id,
    )
    return SessionAgents(
        task_agent=task_agent,
        escalation_agent=escalation_agent,
        consultant_agent=consultant_agent,
        postmortem_agent=postmortem_agent,
    )


def _prune_local_sessions() -> None:
    now = time.monotonic()
    expired = [
        session_id
        for session_id, bundle in _sessions.items()
        if now - bundle.last_accessed > SESSION_TTL_SECONDS and not bundle.lock.locked()
    ]
    for session_id in expired:
        _sessions.pop(session_id, None)

    if len(_sessions) > MAX_LOCAL_SESSIONS:
        oldest = sorted(
            (
                (session_id, bundle)
                for session_id, bundle in _sessions.items()
                if not bundle.lock.locked()
            ),
            key=lambda item: item[1].last_accessed,
        )
        for session_id, _ in oldest[: len(_sessions) - MAX_LOCAL_SESSIONS]:
            _sessions.pop(session_id, None)


def get_session_agents(session_id: str) -> SessionAgents:
    _prune_local_sessions()
    bundle = _sessions.get(session_id)
    if bundle is None:
        bundle = _build_session_agents(session_id)
        _sessions[session_id] = bundle
    bundle.last_accessed = time.monotonic()
    return bundle


async def reset_session(session_id: str) -> None:
    bundle = _sessions.get(session_id)
    if bundle is not None:
        async with bundle.lock:
            bundle.reset()
            _sessions.pop(session_id, None)

    if os.getenv("REDIS_STATE_ENABLED", "false").lower() == "true":
        from config.redis_config import redis_state_store

        await redis_state_store.delete_state(session_id)


async def ProcessUserInput_stream(
    user_input, state=None, context=None, session_id="default"
):
    """Route one user turn through the session's isolated agent graph."""
    bundle = get_session_agents(session_id)
    cache_context = {**(context or {}), "session_id": session_id}

    async with bundle.lock:
        bundle.last_accessed = time.monotonic()

        if SEMANTIC_CACHE_ENABLED:
            cached_text = await semantic_cache.get(user_input, cache_context)
            if cached_text:
                logger.info("Semantic cache hit")
                for char in cached_text:
                    yield char
                return

        bundle.postmortem_agent.add_session_message(role="engineer", content=user_input)

        new_trace_id()
        with trace_step("classify_and_route", agent="TriageRouter"):
            response_tokens = []
            async for token in bundle.task_agent.classify_task_stream(user_input):
                response_tokens.append(token)
                yield token

        full_response = "".join(response_tokens)
        bundle.postmortem_agent.add_session_message(role="agent", content=full_response)

        if SEMANTIC_CACHE_ENABLED and len(full_response) > 20:
            await semantic_cache.set(user_input, full_response, cache_context)
            logger.debug("Semantic cache set for session=%s", session_id[:8])
