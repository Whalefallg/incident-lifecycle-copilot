"""
轻量级请求追踪工具

在不改变分层架构的前提下，为 Multi-Agent 流水线提供可观测性：
- 为每次用户请求分配 trace_id
- 记录各处理阶段的耗时
- 便于面试中讲解 first-token latency 与全链路延迟拆解
"""

import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def get_trace_id() -> str:
    """获取当前请求的 trace_id，不存在则自动生成。"""
    tid = _trace_id.get()
    if tid is None:
        tid = uuid.uuid4().hex[:8]
        _trace_id.set(tid)
    return tid


def set_trace_id(trace_id: str) -> None:
    """为当前异步上下文设置 trace_id。"""
    _trace_id.set(trace_id)


def new_trace_id() -> str:
    """创建并绑定新的 trace_id，通常在请求入口调用。"""
    tid = uuid.uuid4().hex[:8]
    _trace_id.set(tid)
    return tid


@contextmanager
def trace_step(step: str, *, agent: str = ""):
    """
    记录单个处理阶段的耗时。

    Usage:
        with trace_step("knowledge_search", agent="ConsultantAgent"):
            docs = await retriever.search_knowledge(query)
    """
    trace_id = get_trace_id()
    label = f"[{agent}] {step}" if agent else step
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("trace_id=%s step=%s elapsed_ms=%.1f", trace_id, label, elapsed_ms)
