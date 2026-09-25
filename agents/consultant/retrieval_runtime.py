"""Application/worker ownership for the shared retrieval backend."""
from __future__ import annotations

import logging

from config.rag_mcp import RagMcpSettings
from .mcp_rag_client import McpError, McpRagClient
from .retrieval import LocalRunbookRetriever, Retriever

logger = logging.getLogger(__name__)
_retriever: Retriever | None = None
_client: McpRagClient | None = None
_degraded_reason: str | None = None


async def initialize_retrieval(settings: RagMcpSettings | None = None) -> Retriever:
    global _retriever, _client, _degraded_reason
    settings = settings or RagMcpSettings.from_env()
    _degraded_reason = None
    if settings.mode == "local":
        _retriever = LocalRunbookRetriever()
        return _retriever
    client = McpRagClient(settings)
    try:
        await client.start()
    except McpError as exc:
        if settings.mode == "mcp":
            raise
        _degraded_reason = str(exc)
        logger.warning("rag-as-mcp unavailable at startup; using local baseline: %s", exc)
        _retriever = LocalRunbookRetriever()
        _client = None
        return _retriever
    _client = client
    _retriever = client
    return client


def get_retriever() -> Retriever:
    return _retriever or LocalRunbookRetriever()


def degraded_reason() -> str | None:
    return _degraded_reason


async def shutdown_retrieval() -> None:
    global _retriever, _client
    if _client:
        await _client.stop()
    _client = None
    _retriever = None
