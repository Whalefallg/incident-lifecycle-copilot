"""
生产级 API 中间件 - 支持会话管理与性能监控

包含：
1. 会话 ID 自动生成与传递
2. Redis 状态自动恢复
3. 请求耗时统计
4. 并发限流保护
"""

import time
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import uuid
import os
from collections import defaultdict, deque
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class SessionMiddleware(BaseHTTPMiddleware):
    """会话中间件 - 自动管理 session_id"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        session_id = request.headers.get("X-Session-ID") or request.cookies.get(
            "incident_session"
        )

        try:
            session_id = str(uuid.UUID(session_id)) if session_id else None
        except (ValueError, TypeError, AttributeError):
            session_id = None

        if session_id is None:
            session_id = str(uuid.uuid4())

        request.state.session_id = session_id

        response = await call_next(request)
        response.headers["X-Session-ID"] = session_id
        response.set_cookie(
            "incident_session",
            session_id,
            max_age=int(os.getenv("SESSION_TTL_SECONDS", "3600")),
            httponly=True,
            secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
            samesite="lax",
        )

        return response


class DemoRateLimitMiddleware(BaseHTTPMiddleware):
    """In-process guardrail for a single-instance public demo."""

    def __init__(self, app):
        super().__init__(app)
        self.limit = int(os.getenv("DEMO_RATE_LIMIT_PER_MINUTE", "10"))
        self.window_seconds = 60
        self.requests = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        metered_paths = {
            "/chat",
            "/chat/stream",
            "/api/consultation/ask",
            "/api/incident/escalate",
            "/api/task/classify",
            "/api/user-behavior/send-reminder",
        }
        if request.url.path not in metered_paths:
            return await call_next(request)

        forwarded_for = request.headers.get("x-forwarded-for", "")
        client_ip = forwarded_for.split(",", 1)[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        now = time.monotonic()
        history = self.requests[client_ip]
        while history and now - history[0] >= self.window_seconds:
            history.popleft()

        if len(history) >= self.limit:
            return JSONResponse(
                status_code=429,
                content={"error": "Demo rate limit reached. Please retry in a minute."},
                headers={"Retry-After": "60"},
            )

        history.append(now)
        return await call_next(request)


class PerformanceMiddleware(BaseHTTPMiddleware):
    """性能监控中间件 - 记录请求耗时"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        response = await call_next(request)

        duration = time.time() - start_time
        response.headers["X-Response-Time"] = f"{duration:.3f}s"

        if duration > 5.0:
            logger.warning(
                f"Slow request: {request.method} {request.url.path} "
                f"took {duration:.2f}s"
            )

        return response


class RequestLogMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        session_id = getattr(request.state, "session_id", "unknown")

        logger.info(
            f"→ {request.method} {request.url.path} | session={session_id[:8]}"
        )

        response = await call_next(request)

        logger.info(
            f"← {request.method} {request.url.path} | "
            f"status={response.status_code} | session={session_id[:8]}"
        )

        return response
