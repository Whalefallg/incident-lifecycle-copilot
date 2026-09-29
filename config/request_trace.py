"""Request-scoped, safe execution observability without model reasoning."""

import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator

from conversation.observability import (
    AgentTraceStep,
    RequestTrace,
    RetrievalTrace,
    RunbookResult,
)

logger = logging.getLogger(__name__)

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_request_trace: ContextVar[RequestTrace | None] = ContextVar("request_trace", default=None)


def get_trace_id() -> str:
    trace_id = _trace_id.get()
    if trace_id is None:
        trace_id = uuid.uuid4().hex[:8]
        _trace_id.set(trace_id)
    return trace_id


def set_trace_id(trace_id: str) -> None:
    _trace_id.set(trace_id)


def new_trace_id() -> str:
    trace_id = uuid.uuid4().hex[:8]
    _trace_id.set(trace_id)
    return trace_id


@contextmanager
def capture_request_trace(request_id: str) -> Iterator[RequestTrace]:
    trace = RequestTrace(trace_id=new_trace_id(), request_id=request_id)
    token = _request_trace.set(trace)
    try:
        yield trace
    finally:
        trace.completed_at = datetime.now(timezone.utc)
        _request_trace.reset(token)


@contextmanager
def trace_step(step: str, *, agent: str = "") -> Iterator[AgentTraceStep]:
    trace_id = get_trace_id()
    started_at = time.perf_counter()
    record = AgentTraceStep(agent=agent or "system", action=step, duration_ms=0)
    try:
        yield record
    except Exception as exc:
        record.status = "failed"
        record.error_type = type(exc).__name__
        raise
    finally:
        record.duration_ms = round((time.perf_counter() - started_at) * 1000)
        active = _request_trace.get()
        if active is not None:
            active.steps.append(record)
        logger.info(
            "trace_id=%s step=[%s] %s elapsed_ms=%d status=%s",
            trace_id,
            record.agent,
            step,
            record.duration_ms,
            record.status,
        )


def record_retrieval(
    *,
    query: str,
    collection: str,
    duration_ms: int,
    results: list[Any],
) -> None:
    active = _request_trace.get()
    if active is None:
        return
    active.retrievals.append(
        RetrievalTrace(
            query=query,
            collection=collection,
            duration_ms=duration_ms,
            results=[RunbookResult.model_validate(result, from_attributes=True) for result in results],
        )
    )
