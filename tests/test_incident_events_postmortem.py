from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.escalation.incident_processor import IncidentProcessor
from agents.postmortem.postmortem_generator import PostmortemGenerator
from agents.postmortem.timeline_extractor import LegacyTranscriptTimelineExtractor
from agents.task_classification.agent_router import AgentRouter
from agents.task_classification.state_manager import StateManager
from conversation.events import (
    IncidentEvent,
    IncidentEventType,
    build_timeline,
    format_timeline,
)
from conversation.models import ConversationSnapshot, EscalationContext


def event(event_id, event_type, minute, **payload):
    return IncidentEvent(
        event_id=event_id,
        incident_id="INC-1",
        type=event_type,
        timestamp=datetime(2026, 1, 1, 10, minute, tzinfo=timezone.utc),
        actor="system",
        source="test",
        payload=payload,
    )


def test_event_timeline_is_sorted_and_deduplicated():
    later = event("b", IncidentEventType.ONCALL_DISPATCHED, 5, team="platform")
    earlier = event("a", IncidentEventType.ALERT_RECEIVED, 1, service="checkout")
    ordered = build_timeline([later, earlier, later])
    assert [item.event_id for item in ordered] == ["a", "b"]
    summary = format_timeline([later, earlier, later])
    assert summary.count("ONCALL_DISPATCHED") == 1
    assert summary.index("ALERT_RECEIVED") < summary.index("ONCALL_DISPATCHED")


def test_snapshot_round_trip_preserves_typed_events():
    snapshot = ConversationSnapshot(
        session_id="s",
        events=[event("a", IncidentEventType.ALERT_RECEIVED, 1)],
    )
    restored = ConversationSnapshot.from_json_payload(snapshot.json_payload())
    assert restored.events[0].type is IncidentEventType.ALERT_RECEIVED


@pytest.mark.asyncio
async def test_postmortem_prompt_separates_fact_from_inference():
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content="draft"))
    generator = PostmortemGenerator(llm)
    result = await generator.generate(
        [event("a", IncidentEventType.ALERT_RECEIVED, 1, service="checkout")],
        EscalationContext(service="checkout", severity="P1"),
        "Please prepare the review",
    )
    prompt = llm.ainvoke.await_args.args[0]
    assert result == "draft"
    assert "## Observed Facts" in prompt
    assert "## Inferred Root Cause" in prompt
    assert "Never present an inference as an observed fact" in prompt
    assert "ALERT_RECEIVED" in prompt


def test_transcript_extractor_is_explicitly_legacy_only():
    extractor = LegacyTranscriptTimelineExtractor()
    events = extractor.extract_timeline(
        [{"role": "engineer", "content": "P1 checkout down", "timestamp": "t"}]
    )
    assert events[0]["event_type"] == "triage"


@pytest.mark.asyncio
async def test_successful_dispatch_emits_factual_event():
    processor = IncidentProcessor(MagicMock(), MagicMock(), MagicMock(), None)
    processor.message_builder.create_escalation_dispatched_message.return_value = "done"
    recorded = []
    processor.event_sink = lambda event_type, **kwargs: recorded.append(
        (event_type, kwargs)
    )
    await processor._process_successful_escalation(
        {"team": "platform-sre"},
        {"service": "checkout", "severity": "P1"},
        "session",
    )
    assert recorded[0][0] is IncidentEventType.ONCALL_DISPATCHED
    assert recorded[0][1]["payload"]["team"] == "platform-sre"


@pytest.mark.asyncio
async def test_resolution_confirmation_is_recorded_before_postmortem_generation():
    state = StateManager()
    postmortem = MagicMock()
    seen = []

    async def generate_stream(_):
        assert seen[0][0] is IncidentEventType.INCIDENT_RESOLVED
        yield "draft"

    postmortem.generate_stream = generate_stream
    router = AgentRouter(MagicMock(), MagicMock(), state, postmortem_agent=postmortem)
    router.event_sink = lambda event_type, **kwargs: seen.append((event_type, kwargs))
    output = [token async for token in router.route_to_postmortem(
        "incident resolved, generate postmortem"
    )]
    assert "draft" in output
    assert state.should_classify()
