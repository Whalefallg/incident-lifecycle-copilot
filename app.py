"""
FastAPI application entry point.

Configures middleware, registers routes, and runs startup checks.
RAG retrieval is handled by the configured Retriever (`rag-as-mcp` or local baseline);
see agents/consultant/mcp_rag_client.py for the client implementation.

Production enhancements:
- Redis 状态管理（支持无状态水平扩展）
- Semantic Caching（降低 LLM API 成本）
- 会话中间件与性能监控
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import logging
import os
from contextlib import asynccontextmanager

from api import api_routers
from api.core.exceptions import api_exception_handler, general_exception_handler, BusinessException
from api.middleware import (
    DemoRateLimitMiddleware,
    SessionMiddleware,
    PerformanceMiddleware,
    RequestLogMiddleware,
)
from web import router as web_router
from config.redis_config import RedisClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def initialize_system():
    """
    System startup initialization.

    Initialize the worker-level retrieval backend. In MCP mode this starts,
    initializes, and validates one reusable rag-as-mcp subprocess.

    Production: Initialize Redis connection pool.
    """
    logger.info("🚀 Initializing Incident Lifecycle Copilot...")
    from agents.consultant.retrieval_runtime import initialize_retrieval
    await initialize_retrieval()

    redis_enabled = os.getenv("REDIS_STATE_ENABLED", "false").lower() == "true"
    if redis_enabled:
        try:
            await RedisClient.get_client()
            logger.info("✅ Redis connection pool initialized")
        except Exception as e:
            logger.error(f"❌ Redis initialization failed: {e}")
            logger.warning("Continuing without Redis state management")

    logger.info("System initialization complete")

async def shutdown_system():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down system...")
    from agents.consultant.retrieval_runtime import shutdown_retrieval
    await shutdown_retrieval()
    await RedisClient.close()
    logger.info("✅ Cleanup complete")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await initialize_system()
    try:
        yield
    finally:
        await shutdown_system()

def create_app() -> FastAPI:
    """创建FastAPI应用实例"""

    app = FastAPI(
        title="Incident Lifecycle Copilot",
        description="Multi-Agent AI system covering the complete incident lifecycle — from alert triage to postmortem generation.",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    allowed_origins = [
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "X-Session-ID", "X-Admin-Token"],
        )

    app.add_middleware(PerformanceMiddleware)
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(DemoRateLimitMiddleware)
    # Starlette wraps middleware in reverse registration order. Session must
    # be outermost so downstream logging and route handlers see the same ID.
    app.add_middleware(SessionMiddleware)

    app.add_exception_handler(BusinessException, api_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    for router in api_routers:
        app.include_router(router)

    app.include_router(web_router)

    app.mount("/static", StaticFiles(directory="web/static"), name="static")

    return app

# 创建应用实例
app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
