"""
Knowledge Retriever — delegates all RAG search to the Modular RAG MCP Server.

The retrieval path is:
    KnowledgeRetriever.search_knowledge()
        → McpRagClient.query()
        → subprocess: python -m src.mcp_server.server  (MODULAR-RAG-MCP-SERVER)
        → HybridSearch (Dense + BM25 + RRF) + Reranker + ResponseBuilder

The McpRagClient instance is injected at construction time so that the
ConsultantAgent can manage its lifecycle (start/stop with the agent).
"""

import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from .mcp_rag_client import McpRagClient

logger = logging.getLogger(__name__)


class KnowledgeRetriever:
    """
    Retrieves runbook and incident-memory context via the Modular RAG MCP Server.

    The client must be started before the first call to search_knowledge().
    ConsultantAgent.__aenter__ is responsible for starting it.
    """

    def __init__(self, mcp_client: Optional[McpRagClient] = None):
        self._client = mcp_client or McpRagClient()
        self._use_local = False
        self._local_path = Path(
            os.getenv(
                "LOCAL_RUNBOOK_PATH",
                str(Path(__file__).resolve().parents[2] / "data" / "runbooks"),
            )
        )

    @property
    def mcp_client(self) -> McpRagClient:
        return self._client

    async def initialize(self) -> None:
        """Start the MCP Server subprocess and run the initialize handshake."""
        mode = os.getenv("RAG_MODE", "auto").lower()
        if mode == "local":
            self._use_local = True
            logger.info("[KnowledgeRetriever] local runbook mode")
            return

        if mode == "auto" and not self._client.server_path.exists():
            self._use_local = True
            logger.info(
                "[KnowledgeRetriever] MCP server unavailable; using local runbooks"
            )
            return

        try:
            await self._client.start()
            logger.info("[KnowledgeRetriever] MCP RAG Server ready")
        except Exception:
            if mode == "mcp":
                raise
            self._use_local = True
            logger.exception(
                "[KnowledgeRetriever] MCP startup failed; using local runbooks"
            )

    async def search_knowledge(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search the RAG knowledge base.

        Returns a list of dicts with keys: content, source, score, category.
        Falls back to an empty list (with a warning) if the MCP Server is
        unreachable, so the ConsultantAgent can still generate a graceful reply.
        """
        if self._use_local:
            return self._search_local_runbooks(query, top_k)

        try:
            results = await self._client.query(query, top_k=top_k)
            self._log_results(query, results)
            return results
        except Exception as exc:
            logger.error(
                "[KnowledgeRetriever] MCP query failed for %r: %s", query, exc
            )
            return []

    async def close(self) -> None:
        """Stop the MCP Server subprocess."""
        if not self._use_local:
            await self._client.stop()

    def _search_local_runbooks(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Deterministic fallback used by the standalone public demo image."""
        if not self._local_path.exists():
            logger.warning("Local runbook directory not found: %s", self._local_path)
            return []

        stop_words = {
            "a", "an", "and", "did", "do", "for", "how", "i", "in", "is",
            "it", "last", "of", "on", "the", "this", "to", "we", "what",
            "when", "with",
        }
        query_terms = {
            term
            for term in re.findall(r"[a-z0-9_-]+", query.lower())
            if term not in stop_words and len(term) > 1
        }
        scored = []
        for path in sorted(self._local_path.glob("*.yaml")):
            content = path.read_text(encoding="utf-8")
            searchable = f"{path.stem} {content}".lower()
            score = sum(1 for term in query_terms if term in searchable)
            if score:
                scored.append((score, path, content))

        scored.sort(key=lambda item: (-item[0], item[1].name))
        source_ids = {
            "checkout-error.yaml": "checkout-error-runbook",
            "db-connection.yaml": "postgres-connection-pool-runbook",
            "lambda-timeout.yaml": "lambda-timeout-runbook",
            "payment-gateway.yaml": "payment-gateway-timeout-runbook",
            "redis-oom.yaml": "redis-oom-runbook",
        }
        results = [
            {
                "content": content,
                "source": source_ids.get(path.name, path.name),
                "score": round(score / max(len(query_terms), 1), 3),
                "category": "runbook",
            }
            for score, path, content in scored[:top_k]
        ]
        self._log_results(query, results)
        return results

    # ── internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _log_results(query: str, results: List[Dict[str, Any]]) -> None:
        if results:
            for i, doc in enumerate(results, 1):
                logger.debug(
                    "RAG hit #%d score=%.3f source=%s content=%s",
                    i,
                    doc.get("score", 0),
                    doc.get("source", "unknown"),
                    doc.get("content", "")[:80],
                )
            logger.info(
                "[KnowledgeRetriever] query=%r hits=%d", query, len(results)
            )
        else:
            logger.warning("[KnowledgeRetriever] no hits for query=%r", query)
