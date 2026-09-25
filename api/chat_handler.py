"""Stateless request orchestration backed by a ConversationRepository."""

import os
import uuid
import hashlib
import json
from dataclasses import dataclass
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

from agents.escalation_agent import EscalationAgent
from agents.communication_agent import CommunicationAgent
from agents.consultant_agent import ConsultantAgent
from agents.postmortem_agent import PostmortemAgent
from agents.task_classification_agent import TaskClassificationAgent
from config.request_trace import new_trace_id, trace_step
from conversation.models import ConversationSnapshot, EscalationContext, SessionMessage
from conversation.events import IncidentEvent, IncidentEventType
from conversation.repository import (
    ConcurrentConversationUpdate,
    ConversationAlreadyExists,
    ConversationRepository,
    InMemoryConversationRepository,
    RedisConversationRepository,
)

MAX_CONVERSATION_RETRIES = int(os.getenv("CONVERSATION_MAX_RETRIES", "3"))


@dataclass
class SessionAgents:
    """A disposable object graph hydrated for exactly one request attempt."""

    task_agent: TaskClassificationAgent
    escalation_agent: EscalationAgent
    consultant_agent: ConsultantAgent
    postmortem_agent: PostmortemAgent
    pending_events: list[IncidentEvent] = None
    _request_id: str | None = None
    _event_ordinal: int = 0

    def __post_init__(self) -> None:
        self.pending_events = []
        self.escalation_agent.event_sink = self.record_event
        self.escalation_agent.incident_processor.event_sink = self.record_event
        self.task_agent.agent_router.event_sink = self.record_event

    def begin_request(self, request_id: str) -> None:
        self._request_id = request_id
        self._event_ordinal = 0

    def record_event(
        self,
        event_type: IncidentEventType,
        *,
        actor: str,
        source: str,
        payload: dict | None = None,
    ) -> None:
        event_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{self.escalation_agent.session_id}:{self._request_id}:"
                f"{self._event_ordinal}:{event_type.value}",
            )
        )
        self._event_ordinal += 1
        event = IncidentEvent(
            event_id=event_id,
            incident_id=self.escalation_agent.session_id,
            type=event_type,
            actor=actor,
            source=source,
            request_id=self._request_id,
            payload=payload or {},
        )
        self.pending_events.append(event)
        self.postmortem_agent.incident_events.append(event)

    def hydrate(self, snapshot: ConversationSnapshot) -> None:
        self.task_agent.hydrate(snapshot)
        self.escalation_agent.restore_snapshot(
            snapshot.escalation_context.to_legacy_dict()
        )
        self.postmortem_agent.session_messages = [
            message.model_dump(mode="json") for message in snapshot.messages
        ]
        self.postmortem_agent.incident_events = [
            event.model_copy(deep=True) for event in snapshot.events
        ]
        self.postmortem_agent.escalation_context = (
            snapshot.escalation_context.model_copy(deep=True)
        )
        self.postmortem_agent.next_draft_version = (
            max(
                (draft.version for draft in snapshot.postmortem_context.drafts),
                default=0,
            )
            + 1
        )
        for message in snapshot.messages:
            if message.role == "engineer":
                self.escalation_agent.chat_history.add_user_message(message.content)
            elif message.role == "agent":
                self.escalation_agent.chat_history.add_ai_message(message.content)

    def apply_to_snapshot(self, snapshot: ConversationSnapshot) -> None:
        self.task_agent.apply_to_snapshot(snapshot)
        snapshot.escalation_context = EscalationContext.from_legacy_dict(
            self.escalation_agent._build_snapshot()
        )
        known_event_ids = {event.event_id for event in snapshot.events}
        snapshot.events.extend(
            event for event in self.pending_events if event.event_id not in known_event_ids
        )
        if self.postmortem_agent.generated_draft:
            existing = {
                (draft.source_incident_id, draft.version): draft
                for draft in snapshot.postmortem_context.drafts
            }
            key = (
                self.postmortem_agent.generated_draft.source_incident_id,
                self.postmortem_agent.generated_draft.version,
            )
            existing[key] = self.postmortem_agent.generated_draft
            snapshot.postmortem_context.drafts = list(existing.values())


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


_in_memory_repository = InMemoryConversationRepository()
_redis_repository: RedisConversationRepository | None = None


async def get_conversation_repository() -> ConversationRepository:
    global _redis_repository
    if os.getenv("REDIS_STATE_ENABLED", "false").lower() != "true":
        return _in_memory_repository
    if _redis_repository is None:
        from config.redis_config import RedisClient

        client = await RedisClient.get_client()
        ttl = RedisClient.get_config().state_ttl
        _redis_repository = RedisConversationRepository(client, ttl_seconds=ttl)
    return _redis_repository


class ConversationCoordinator:
    """Load, execute on a fresh graph, and atomically persist one request."""

    def __init__(
        self,
        repository: ConversationRepository,
        *,
        agent_factory: Callable[[str], SessionAgents] = _build_session_agents,
        max_retries: int = MAX_CONVERSATION_RETRIES,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        self.repository = repository
        self.agent_factory = agent_factory
        self.max_retries = max_retries
        self.built_graphs: list[SessionAgents] = []

    async def _load_or_create(self, session_id: str) -> ConversationSnapshot:
        snapshot = await self.repository.load(session_id)
        if snapshot:
            return snapshot
        try:
            return await self.repository.create(
                ConversationSnapshot(session_id=session_id)
            )
        except ConversationAlreadyExists:
            snapshot = await self.repository.load(session_id)
            if snapshot is None:
                raise
            return snapshot

    async def process(
        self,
        message: str,
        session_id: str,
        request_id: str,
        *,
        request_payload: dict | None = None,
    ) -> str:
        idempotency_key = f"{session_id}:{request_id}"
        canonical_payload = request_payload or {"message": message}
        fingerprint = hashlib.sha256(
            json.dumps(
                canonical_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        prior_response = await self.repository.claim_request(
            idempotency_key, fingerprint
        )
        if prior_response is not None:
            return prior_response

        try:
            for attempt in range(self.max_retries):
                snapshot = await self._load_or_create(session_id)
                graph = self.agent_factory(session_id)
                self.built_graphs.append(graph)
                if hasattr(graph, "begin_request"):
                    graph.begin_request(request_id)
                graph.hydrate(snapshot)
                user_message = SessionMessage(role="engineer", content=message)
                snapshot.messages.append(user_message)
                graph.postmortem_agent.add_session_message(
                    role="engineer",
                    content=message,
                    timestamp=user_message.timestamp.isoformat(),
                )

                new_trace_id()
                tokens: list[str] = []
                with trace_step("classify_and_route", agent="TriageRouter"):
                    async for token in graph.task_agent.classify_task_stream(message):
                        tokens.append(token)
                response = "".join(tokens)

                graph.apply_to_snapshot(snapshot)
                snapshot.messages.append(SessionMessage(role="agent", content=response))
                snapshot.processed_requests[request_id] = response
                try:
                    await self.repository.save(snapshot, snapshot.revision)
                except ConcurrentConversationUpdate:
                    if attempt + 1 >= self.max_retries:
                        raise
                    continue
                await self.repository.complete_request(
                    idempotency_key, fingerprint, response
                )
                return response
        except Exception:
            await self.repository.abandon_request(idempotency_key, fingerprint)
            raise

        raise ConcurrentConversationUpdate(
            f"session={session_id} exceeded {self.max_retries} retries"
        )


async def reset_session(session_id: str) -> None:
    repository = await get_conversation_repository()
    await repository.delete(session_id)


async def ProcessUserInput_stream(
    user_input,
    state=None,
    context=None,
    session_id="default",
    request_id: str | None = None,
):
    """Process a turn without relying on a long-lived Python agent object."""
    repository = await get_conversation_repository()
    coordinator = ConversationCoordinator(repository)
    message = str(user_input)
    response = await coordinator.process(
        message,
        session_id,
        request_id or str(uuid.uuid4()),
        request_payload={
            "message": message,
            "state": state,
            "context": context or {},
        },
    )
    for token in response:
        yield token
