from types import SimpleNamespace

import pytest

from api.chat_handler import ConversationCoordinator
from agents.task_classification.state_manager import StateManager
from config.constants import StateEnum
from conversation.models import ConversationSnapshot, EscalationContext
from conversation.repository import (
    ConcurrentConversationUpdate,
    IdempotencyKeyMismatch,
    InMemoryConversationRepository,
)


class FakePostmortemAgent:
    def add_session_message(self, **kwargs):
        return None


class FakeTaskAgent:
    def __init__(self, graph):
        self.graph = graph

    async def classify_task_stream(self, message):
        normalized = message.lower()
        if "checkout" in normalized:
            self.graph.state.transition_to_escalation()
            self.graph.context.service = "checkout"
            self.graph.context.severity = "P1"
            self.graph.context.impact_scope = "eu-west-1"
            yield "escalation started"
        elif "runbook" in normalized:
            self.graph.state.suspend_current(self.graph.context.to_legacy_dict())
            yield "Redis OOM runbook"
        elif normalized == "continue":
            frame = self.graph.state.resume_suspended()
            assert frame is not None
            self.graph.context = EscalationContext.from_legacy_dict(
                frame.agent_snapshot
            )
            yield "escalation resumed"


class FakeGraph:
    def __init__(self, session_id):
        self.session_id = session_id
        self.state = StateManager(session_id=session_id)
        self.context = EscalationContext()
        self.task_agent = FakeTaskAgent(self)
        self.postmortem_agent = FakePostmortemAgent()

    def hydrate(self, snapshot):
        self.state.hydrate(snapshot)
        self.context = snapshot.escalation_context.model_copy(deep=True)

    def apply_to_snapshot(self, snapshot):
        self.state.apply_to_snapshot(snapshot)
        snapshot.escalation_context = self.context.model_copy(deep=True)


@pytest.mark.asyncio
async def test_cross_worker_recovery_and_request_idempotency():
    repository = InMemoryConversationRepository()
    session_id = "cross-worker-session"

    worker_a = ConversationCoordinator(repository, agent_factory=FakeGraph)
    assert await worker_a.process(
        "checkout is failing in eu-west-1, severity P1", session_id, "request-a"
    ) == "escalation started"
    after_a = await repository.load(session_id)
    assert after_a.revision == 1
    assert after_a.current_state == StateEnum.ESCALATION

    worker_b = ConversationCoordinator(repository, agent_factory=FakeGraph)
    assert await worker_b.process(
        "what is the Redis OOM runbook?", session_id, "request-b"
    ) == "Redis OOM runbook"
    after_b = await repository.load(session_id)
    assert after_b.revision == 2
    assert after_b.current_state == StateEnum.CLASSIFY
    assert len(after_b.suspend_stack) == 1
    assert after_b.suspend_stack[0].state == StateEnum.ESCALATION

    worker_c = ConversationCoordinator(repository, agent_factory=FakeGraph)
    first_response = await worker_c.process("continue", session_id, "request-c")
    duplicate_response = await worker_c.process("continue", session_id, "request-c")
    after_c = await repository.load(session_id)

    graphs = [worker_a.built_graphs[0], worker_b.built_graphs[0], worker_c.built_graphs[0]]
    assert len({id(graph) for graph in graphs}) == 3
    assert first_response == duplicate_response == "escalation resumed"
    assert after_c.revision == 3
    assert after_c.current_state == StateEnum.ESCALATION
    assert after_c.suspend_stack == []
    assert after_c.escalation_context.service == "checkout"
    assert after_c.escalation_context.severity == "P1"
    assert len(after_c.messages) == 6
    assert len(worker_c.built_graphs) == 1

    with pytest.raises(IdempotencyKeyMismatch):
        await worker_c.process("different payload", session_id, "request-c")
    unchanged = await repository.load(session_id)
    assert unchanged.revision == 3
    assert len(unchanged.messages) == 6


@pytest.mark.asyncio
async def test_stale_revision_is_rejected_without_overwrite():
    repository = InMemoryConversationRepository()
    original = await repository.create(ConversationSnapshot(session_id="s"))
    first = original.model_copy(deep=True)
    stale = original.model_copy(deep=True)
    first.escalation_context.service = "checkout"
    saved = await repository.save(first, expected_revision=0)

    stale.escalation_context.service = "payments"
    with pytest.raises(ConcurrentConversationUpdate):
        await repository.save(stale, expected_revision=0)

    current = await repository.load("s")
    assert saved.revision == 1
    assert current.revision == 1
    assert current.escalation_context.service == "checkout"


@pytest.mark.asyncio
async def test_in_progress_request_id_rejects_payload_mismatch():
    repository = InMemoryConversationRepository()
    await repository.claim_request("request", "fingerprint-a")
    with pytest.raises(IdempotencyKeyMismatch):
        await repository.claim_request("request", "fingerprint-b")


def test_snapshot_json_round_trip_preserves_typed_state():
    snapshot = ConversationSnapshot(
        session_id="round-trip",
        current_state=StateEnum.ESCALATION,
        escalation_context=EscalationContext(service="checkout", severity="P1"),
    )
    restored = ConversationSnapshot.from_json_payload(snapshot.json_payload())
    assert restored == snapshot
    assert restored.current_state is StateEnum.ESCALATION


class AlwaysConflictingRepository(InMemoryConversationRepository):
    def __init__(self):
        super().__init__()
        self.save_attempts = 0

    async def save(self, snapshot, expected_revision):
        self.save_attempts += 1
        raise ConcurrentConversationUpdate("forced conflict")


@pytest.mark.asyncio
async def test_concurrent_update_retry_is_bounded():
    repository = AlwaysConflictingRepository()
    coordinator = ConversationCoordinator(
        repository, agent_factory=FakeGraph, max_retries=2
    )
    with pytest.raises(ConcurrentConversationUpdate):
        await coordinator.process(
            "checkout is failing in eu-west-1, severity P1", "bounded", "request"
        )
    assert repository.save_attempts == 2
