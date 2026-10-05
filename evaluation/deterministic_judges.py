"""Pure deterministic assertions used by IncidentBench."""

import re
from collections import Counter

from conversation.models import ConversationSnapshot

from .incident_scenario import FactExpectation, IncidentScenario


def normalize_text(value: str) -> str:
    value = value.lower().replace("％", "%")
    value = re.sub(r"(?<=\d)\s*percent\b", "%", value)
    return " ".join(re.sub(r"[^\w%.-]+", " ", value).split())


def fact_coverage(text: str, required: list[FactExpectation]) -> tuple[int, int]:
    normalized = normalize_text(text)
    matched = sum(
        any(normalize_text(alias) in normalized for alias in fact.any_of)
        for fact in required
    )
    return matched, len(required)


def duplicate_event_count(snapshot: ConversationSnapshot) -> int:
    keys = [(event.request_id, event.type.value, normalize_text(str(event.payload))) for event in snapshot.events]
    return sum(count - 1 for count in Counter(keys).values() if count > 1)


def judge_scenario(
    scenario: IncidentScenario,
    snapshot: ConversationSnapshot,
    observed_states: list[str],
    response_text: str,
    flags: dict[str, object],
) -> list[dict[str, object]]:
    exp = scenario.expectations
    event_types = {event.type.value for event in snapshot.events}
    documents = {
        result.document_id
        for trace in snapshot.request_traces
        for retrieval in trace.retrievals
        for result in retrieval.results
    }
    checks: list[tuple[str, bool, object]] = []
    if exp.final_state:
        checks.append(("final_state", snapshot.current_state.value == exp.final_state, snapshot.current_state.value))
    for state in exp.required_states:
        checks.append((f"state:{state}", state in observed_states, observed_states))
    for event_type in exp.required_event_types:
        checks.append((f"event:{event_type}", event_type in event_types, sorted(event_types)))
    for event_type in exp.forbidden_event_types:
        checks.append((f"forbidden_event:{event_type}", event_type not in event_types, sorted(event_types)))
    for document_id in exp.required_document_ids:
        checks.append((f"document:{document_id}", document_id in documents, sorted(documents)))
    if exp.duplicate_event_count is not None:
        actual = duplicate_event_count(snapshot)
        checks.append(("duplicate_event_count", actual == exp.duplicate_event_count, actual))
    for name in ("idempotency_required", "mismatch_rejected", "stale_write_rejected"):
        expected = getattr(exp, name)
        if expected:
            checks.append((name, flags.get(name) is True, flags.get(name)))
    if exp.degraded_outcome:
        checks.append(("degraded_outcome", flags.get("degraded_outcome") == exp.degraded_outcome, flags.get("degraded_outcome")))
    matched, total = fact_coverage(response_text, exp.required_facts)
    if total:
        checks.append(("required_facts", matched == total, {"matched": matched, "total": total}))
    normalized = normalize_text(response_text)
    for claim in exp.forbidden_claims:
        checks.append((f"forbidden_claim:{claim}", normalize_text(claim) not in normalized, claim))
    return [{"name": name, "passed": passed, "actual": actual} for name, passed, actual in checks]
