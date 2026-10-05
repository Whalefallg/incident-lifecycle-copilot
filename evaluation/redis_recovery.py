"""Real Redis-backed cross-worker recovery evaluation."""

import hashlib
import json
import os
import time
from uuid import uuid4

from redis.asyncio import Redis

from agents.task_classification.state_manager import StateManager
from config.constants import StateEnum
from conversation.events import IncidentEvent, IncidentEventType
from conversation.models import ConversationSnapshot, EscalationContext
from conversation.observability import RequestTrace, RetrievalTrace, RunbookResult
from conversation.repository import (
    ConcurrentConversationUpdate,
    IdempotencyKeyMismatch,
    RedisConversationRepository,
)


async def run_redis_recovery() -> dict:
    url = os.getenv("INCIDENTBENCH_REDIS_URL", "redis://127.0.0.1:6379/15")
    client = Redis.from_url(url, decode_responses=False, socket_connect_timeout=1)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        return {"status": "skipped", "reason": f"Redis unavailable: {type(exc).__name__}", "cases": []}

    run_id = uuid4().hex
    cases: list[dict] = []
    try:
        cases.append(await _cross_worker_resume(client, run_id))
        cases.append(await _stale_write(client, run_id))
        cases.append(await _cross_worker_idempotency(client, run_id))
    finally:
        async for key in client.scan_iter(match=f"incident:*:incidentbench-{run_id}*"):
            await client.delete(key)
        await client.aclose()
    passed = sum(case["passed"] for case in cases)
    return {
        "status": "passed" if passed == len(cases) else "failed",
        "passed": passed,
        "total": len(cases),
        "cases": cases,
        "metrics": {
            "passed": passed,
            "total": len(cases),
            "cross_worker_resume": f"{int(cases[0]['passed'])}/1",
            "stale_write_rejection": f"{int(cases[1]['passed'])}/1",
            "cross_worker_idempotency": f"{int(cases[2]['passed'])}/1",
            "duplicate_event_rate": 0.0 if cases[2]["passed"] else None,
        },
    }


def _repo(client: Redis) -> RedisConversationRepository:
    return RedisConversationRepository(client, ttl_seconds=300, request_ttl_seconds=300)


async def _cross_worker_resume(client: Redis, run_id: str) -> dict:
    started = time.perf_counter()
    session = f"incidentbench-{run_id}-resume"
    worker_a = _repo(client)
    snapshot = ConversationSnapshot(
        session_id=session,
        current_state=StateEnum.ESCALATION,
        escalation_context=EscalationContext(service="checkout", severity="SEV-1"),
        events=[IncidentEvent(
            incident_id=session, type=IncidentEventType.ALERT_RECEIVED,
            actor="worker-a", source="incidentbench", request_id="r1",
        )],
    )
    await worker_a.create(snapshot)
    manager_a = StateManager(session_id=session)
    manager_a.hydrate(snapshot)
    manager_a.suspend_current(snapshot.escalation_context.to_legacy_dict())
    manager_a.apply_to_snapshot(snapshot)
    suspended = await worker_a.save(snapshot, 0)

    worker_b = _repo(client)
    restored = await worker_b.load(session)
    assert restored is not None
    manager_b = StateManager(session_id=session)
    manager_b.hydrate(restored)
    frame = manager_b.resume_suspended()
    if frame:
        restored.escalation_context = EscalationContext.from_legacy_dict(frame.agent_snapshot)
    manager_b.apply_to_snapshot(restored)
    resumed = await worker_b.save(restored, suspended.revision)
    passed = (
        resumed.session_id == session and resumed.revision == 2
        and resumed.current_state is StateEnum.ESCALATION and not resumed.suspend_stack
        and resumed.escalation_context.service == "checkout" and len(resumed.events) == 1
        and worker_a is not worker_b and manager_a is not manager_b
    )
    return {"id": "redis-cross-worker-resume", "passed": passed, "latency_ms": (time.perf_counter() - started) * 1000}


async def _stale_write(client: Redis, run_id: str) -> dict:
    started = time.perf_counter()
    session = f"incidentbench-{run_id}-cas"
    seed = _repo(client)
    await seed.create(ConversationSnapshot(session_id=session))
    worker_a, worker_b = _repo(client), _repo(client)
    a, b = await worker_a.load(session), await worker_b.load(session)
    assert a is not None and b is not None
    a.escalation_context.service = "checkout"
    saved = await worker_a.save(a, a.revision)
    rejected = False
    try:
        b.escalation_context.service = "payments"
        await worker_b.save(b, b.revision)
    except ConcurrentConversationUpdate:
        rejected = True
    final = await seed.load(session)
    passed = bool(rejected and final and final.revision == saved.revision == 1 and final.escalation_context.service == "checkout")
    return {"id": "redis-stale-write", "passed": passed, "latency_ms": (time.perf_counter() - started) * 1000}


async def _cross_worker_idempotency(client: Redis, run_id: str) -> dict:
    started = time.perf_counter()
    session = f"incidentbench-{run_id}-idem"
    request_id = f"{session}:req-X"
    payload = {"message": "find redis runbook"}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    worker_a = _repo(client)
    snapshot = ConversationSnapshot(session_id=session)
    snapshot.events.append(IncidentEvent(
        incident_id=session, type=IncidentEventType.RUNBOOK_RETRIEVED,
        actor="worker-a", source="incidentbench", request_id="req-X",
    ))
    snapshot.request_traces.append(RequestTrace(
        trace_id="trace-X", request_id="req-X", retrievals=[RetrievalTrace(
            query=payload["message"], collection="opsbench_v1", duration_ms=1,
            results=[RunbookResult(document_id="redis-oom-runbook", content="evidence", source="redis-oom.pdf")],
        )],
    ))
    await worker_a.claim_request(request_id, fingerprint)
    await worker_a.create(snapshot)
    await worker_a.complete_request(request_id, fingerprint, "completed result")

    worker_b = _repo(client)
    reused = await worker_b.claim_request(request_id, fingerprint)
    mismatch = False
    try:
        await worker_b.claim_request(request_id, hashlib.sha256(b"different-P").hexdigest())
    except IdempotencyKeyMismatch:
        mismatch = True
    final = await worker_b.load(session)
    passed = bool(reused == "completed result" and mismatch and final and len(final.events) == 1 and len(final.request_traces) == 1)
    return {"id": "redis-cross-worker-idempotency", "passed": passed, "latency_ms": (time.perf_counter() - started) * 1000}
