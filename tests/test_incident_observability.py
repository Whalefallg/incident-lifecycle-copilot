from types import SimpleNamespace

from config.request_trace import (
    MAX_RESULT_CONTENT_CHARS,
    MAX_RETRIEVAL_RESULTS,
    capture_request_trace,
    record_retrieval,
    trace_step,
)
from conversation.models import ConversationSnapshot
from conversation.repository import InMemoryConversationRepository
from services.incidents import IncidentService


def test_request_trace_captures_safe_steps_and_structured_retrieval():
    result = SimpleNamespace(
        document_id="redis-oom-runbook",
        content="Restart replicas one at a time.",
        source="redis-oom.yaml",
        score=0.87,
        metadata={"backend": "local", "filename": "redis-oom.yaml"},
    )
    with capture_request_trace("request-1") as request_trace:
        with trace_step("knowledge_search", agent="ConsultantAgent") as step:
            pass
        record_retrieval(
            query="redis oom",
            collection="default",
            duration_ms=step.duration_ms,
            results=[result],
        )

    assert request_trace.steps[0].action == "knowledge_search"
    assert request_trace.steps[0].status == "completed"
    assert request_trace.retrievals[0].results[0].document_id == "redis-oom-runbook"
    assert request_trace.model_dump_json().find("reasoning") == -1


def test_retrieval_trace_keeps_only_bounded_result_excerpts():
    results = [
        SimpleNamespace(
            document_id=f"runbook-{index}",
            content="x" * (MAX_RESULT_CONTENT_CHARS + 100),
            source="fixture",
            score=1.0,
            metadata={},
        )
        for index in range(MAX_RETRIEVAL_RESULTS + 2)
    ]
    with capture_request_trace("request-bounded") as request_trace:
        record_retrieval(
            query="bounded evidence",
            collection="default",
            duration_ms=1,
            results=results,
        )

    captured = request_trace.retrievals[0].results
    assert len(captured) == MAX_RETRIEVAL_RESULTS
    assert all(len(item.content) == MAX_RESULT_CONTENT_CHARS for item in captured)


async def test_incident_service_exposes_trace_and_runbook_resources():
    repository = InMemoryConversationRepository()
    with capture_request_trace("request-1") as request_trace:
        with trace_step("knowledge_search", agent="ConsultantAgent") as step:
            pass
        record_retrieval(
            query="redis oom",
            collection="production-runbooks",
            duration_ms=step.duration_ms,
            results=[
                SimpleNamespace(
                    document_id="redis-oom-runbook",
                    content="Recovery steps",
                    source="redis-oom.yaml",
                    score=0.87,
                    metadata={"page": "4"},
                )
            ],
        )
    await repository.create(
        ConversationSnapshot(session_id="INC-1", request_traces=[request_trace])
    )
    service = IncidentService(repository)
    trace = await service.get_trace("INC-1")
    runbooks = await service.get_runbooks("INC-1")

    assert trace.items[0].visibility == "execution_metadata"
    assert trace.items[0].retrievals[0].result_count == 1
    assert runbooks.items[0].collection == "production-runbooks"
    assert runbooks.items[0].results[0].score == 0.87
