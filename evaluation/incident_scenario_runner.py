"""Deterministic runner over real snapshot, event, trace, FSM and repository types."""

import time
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from agents.task_classification.state_manager import StateManager
from config.constants import StateEnum
from conversation.events import IncidentEvent, IncidentEventType
from conversation.models import ConversationSnapshot, EscalationContext
from conversation.observability import RequestTrace, RetrievalTrace, RunbookResult
from conversation.repository import (
    ConcurrentConversationUpdate, IdempotencyKeyMismatch, InMemoryConversationRepository,
)

from .deterministic_judges import fact_coverage, judge_scenario
from .incident_scenario import IncidentScenario


class IncidentScenarioRunner:
    def __init__(self, backend: str = "memory", *, retriever=None, collection: str = "opsbench_v1") -> None:
        self.backend = backend
        self.retriever = retriever
        self.collection = collection

    async def run(self, scenario: IncidentScenario) -> dict:
        started = time.perf_counter()
        incident_id = scenario.initial_state.get("incident_id", scenario.id)
        repo = InMemoryConversationRepository()
        snapshot = ConversationSnapshot(
            session_id=incident_id,
            current_state=StateEnum(scenario.initial_state.get("state", "classify")),
            escalation_context=EscalationContext.model_validate(
                scenario.initial_state.get("escalation_context", {})
            ),
        )
        await repo.create(snapshot)
        observed_states = [snapshot.current_state.value]
        response_parts: list[str] = []
        flags: dict[str, object] = {}
        request_results: dict[str, str] = {}

        for ordinal, step in enumerate(scenario.steps):
            snapshot = await repo.load(incident_id)
            assert snapshot is not None
            action = step.action
            if action == "transition":
                snapshot.current_state = StateEnum(step.state)
                observed_states.append(step.state or "")
            elif action == "suspend":
                manager = StateManager(session_id=incident_id)
                manager.hydrate(snapshot)
                manager.suspend_current(snapshot.escalation_context.to_legacy_dict())
                manager.apply_to_snapshot(snapshot)
                observed_states.append(snapshot.current_state.value)
            elif action == "resume":
                manager = StateManager(session_id=incident_id)
                manager.hydrate(snapshot)
                frame = manager.resume_suspended()
                if frame and frame.agent_snapshot:
                    snapshot.escalation_context = EscalationContext.from_legacy_dict(frame.agent_snapshot)
                manager.apply_to_snapshot(snapshot)
                observed_states.append(snapshot.current_state.value)
            elif action == "event":
                event_type = IncidentEventType(step.event_type)
                event_id = str(uuid5(NAMESPACE_URL, f"{scenario.id}:{step.request_id}:{event_type.value}"))
                if all(event.event_id != event_id for event in snapshot.events):
                    snapshot.events.append(IncidentEvent(
                        event_id=event_id, incident_id=incident_id, type=event_type,
                        actor="incidentbench", source="scenario", request_id=step.request_id,
                        payload=step.facts,
                    ))
            elif action == "retrieve":
                if self.retriever is None:
                    results = [RunbookResult(document_id=doc, content=step.content or doc, source="incidentbench") for doc in step.document_ids]
                else:
                    live_results = await self.retriever.search(
                        step.content or "", top_k=10, collection=self.collection
                    )
                    results = [RunbookResult.model_validate(item, from_attributes=True) for item in live_results]
                snapshot.request_traces.append(RequestTrace(
                    trace_id=f"trace-{scenario.id}-{ordinal}", request_id=step.request_id or f"req-{ordinal}",
                    completed_at=datetime.now(timezone.utc), retrievals=[RetrievalTrace(
                        query=step.content or "", collection=self.collection, duration_ms=0, results=results,
                    )],
                ))
                snapshot.events.append(IncidentEvent(
                    incident_id=incident_id, type=IncidentEventType.RUNBOOK_RETRIEVED,
                    actor="consultant", source="retriever", request_id=step.request_id,
                    payload={"document_ids": step.document_ids},
                ))
                response_parts.append(step.content or " ".join(step.document_ids))
            elif action == "respond":
                response_parts.append(step.content or "")
            elif action == "idempotent_retry":
                request_id = f"{incident_id}:{step.request_id}"
                content = step.content or ""
                import hashlib
                fingerprint = hashlib.sha256(content.encode()).hexdigest()
                prior = await repo.claim_request(request_id, fingerprint)
                if prior is None:
                    await repo.complete_request(request_id, fingerprint, content)
                second = await repo.claim_request(request_id, fingerprint)
                flags["idempotency_required"] = second == content
                try:
                    await repo.claim_request(request_id, hashlib.sha256((content + "-changed").encode()).hexdigest())
                except IdempotencyKeyMismatch:
                    flags["mismatch_rejected"] = True
            elif action == "stale_write":
                first = snapshot.model_copy(deep=True)
                stale = snapshot.model_copy(deep=True)
                saved = await repo.save(first, snapshot.revision)
                try:
                    await repo.save(stale, snapshot.revision)
                except ConcurrentConversationUpdate:
                    flags["stale_write_rejected"] = True
                snapshot = saved
                continue
            elif action == "mcp_failure":
                if self.backend == "redis" and step.failure == "redis_unavailable":
                    flags["degraded_outcome"] = "skipped"
                else:
                    flags["degraded_outcome"] = "fallback" if step.failure == "startup_auto" else "surfaced"
            else:
                raise ValueError(f"unsupported action: {action}")
            snapshot = await repo.save(snapshot, snapshot.revision)

        snapshot = await repo.load(incident_id)
        assert snapshot is not None
        response_text = "\n".join(response_parts)
        assertions = judge_scenario(scenario, snapshot, observed_states, response_text, flags)
        matched, total = fact_coverage(response_text, scenario.expectations.required_facts)
        return {
            "id": scenario.id, "title": scenario.title, "category": scenario.category,
            "status": "passed" if all(item["passed"] for item in assertions) else "failed",
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "assertions": assertions,
            "metrics": {
                "fact_coverage": matched / total if total else None,
                "unsupported_claim_rate": (
                    sum(claim.lower() in response_text.lower() for claim in scenario.expectations.forbidden_claims)
                    / len(scenario.expectations.forbidden_claims)
                    if scenario.expectations.forbidden_claims else None
                ),
            },
        }
