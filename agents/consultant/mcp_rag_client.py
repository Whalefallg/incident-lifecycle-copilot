"""
MCP RAG Client — subprocess-based stdio transport client for Modular RAG MCP Server.

Architecture:
    ConsultantAgent / KnowledgeRetriever
        → McpRagClient.query()
        → subprocess (python -m src.mcp_server.server)  [MODULAR-RAG-MCP-SERVER]
        → JSON-RPC 2.0 over stdin/stdout
        → HybridSearch + Reranker + ResponseBuilder

The MCP Server uses stdio transport: we spawn it as a subprocess, write
JSON-RPC requests to its stdin, and read JSON-RPC responses from its stdout.

One subprocess is kept alive for the lifetime of the client (lazy-started on
first query, restarted automatically if the process dies).

Environment variable:
    RAG_MCP_SERVER_PATH   absolute path to MODULAR-RAG-MCP-SERVER project root
                          (must contain config/settings.yaml)
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── default path resolution ────────────────────────────────────────────────
_DEFAULT_SERVER_PATH = str(Path.home() / "Projects" / "MODULAR-RAG-MCP-SERVER")


class McpRagClient:
    """
    Async client for the Modular RAG MCP Server.

    Usage:
        client = McpRagClient()
        await client.start()

        results = await client.query("how to fix Redis OOM?", top_k=5)
        # results: list of {"content": str, "source": str, "score": float}

        await client.stop()

    Or as an async context manager:
        async with McpRagClient() as client:
            results = await client.query("...")
    """

    def __init__(self, server_path: Optional[str] = None):
        self._server_path = Path(
            server_path
            or os.environ.get("RAG_MCP_SERVER_PATH", _DEFAULT_SERVER_PATH)
        )
        self._process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._initialized = False

    @property
    def server_path(self) -> Path:
        return self._server_path

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the MCP Server subprocess and run the MCP initialize handshake."""
        if self._process and self._process.returncode is None:
            return  # already running

        python = sys.executable
        cmd = [python, "-m", "src.mcp_server.server"]
        env = {**os.environ, "MCP_SETTINGS_PATH": "config/settings.yaml"}

        logger.info(f"[McpRagClient] Starting MCP Server at {self._server_path}")
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._server_path),
            env=env,
        )
        self._initialized = False
        await self._initialize()
        logger.info("[McpRagClient] MCP Server ready")

    async def stop(self) -> None:
        """Terminate the subprocess gracefully."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
        self._process = None
        self._initialized = False

    async def __aenter__(self) -> "McpRagClient":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.stop()

    # ── public API ─────────────────────────────────────────────────────────

    async def query(
        self,
        query: str,
        top_k: int = 5,
        collection: str = "default",
    ) -> List[Dict[str, Any]]:
        """
        Query the RAG knowledge base via the MCP Server.

        Returns a list of result dicts, each with:
            content  (str)   — the retrieved text chunk
            source   (str)   — document name / citation
            score    (float) — relevance score (if available)
        """
        await self._ensure_running()

        response = await self._call_tool(
            "query_knowledge_hub",
            {"query": query, "top_k": top_k, "collection": collection},
        )
        return self._parse_query_response(response)

    async def is_healthy(self) -> bool:
        """Return True if the subprocess is alive and initialized."""
        try:
            await self._ensure_running()
            return True
        except Exception as e:
            logger.warning(f"[McpRagClient] Health check failed: {e}")
            return False

    # ── internal ───────────────────────────────────────────────────────────

    async def _ensure_running(self) -> None:
        """Restart the subprocess if it has died."""
        if self._process is None or self._process.returncode is not None:
            logger.warning("[McpRagClient] Process not running — restarting")
            await self.start()

    async def _initialize(self) -> None:
        """Send MCP initialize handshake."""
        response = await self._send_request(
            "initialize",
            {"protocolVersion": "2024-11-05", "clientInfo": {"name": "incident-copilot", "version": "1.0"}},
        )
        server_info = response.get("result", {}).get("serverInfo", {})
        logger.info(f"[McpRagClient] Server info: {server_info}")
        self._initialized = True

    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Send a tools/call request and return the result dict."""
        response = await self._send_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        if "error" in response:
            raise RuntimeError(
                f"MCP tool error [{tool_name}]: {response['error'].get('message', response['error'])}"
            )
        return response.get("result", {})

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send one JSON-RPC 2.0 request and await the corresponding response.

        Uses a mutex so concurrent callers don't interleave reads/writes.
        """
        async with self._lock:
            if self._process is None:
                raise RuntimeError("MCP Server subprocess is not running")

            self._req_id += 1
            req_id = self._req_id
            request = json.dumps(
                {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
                ensure_ascii=False,
            ) + "\n"

            # Write to subprocess stdin
            self._process.stdin.write(request.encode())
            await self._process.stdin.drain()

            # Read response lines until we get one with matching id
            # (MCP Server may emit log lines to stderr; stdout is JSON only)
            while True:
                try:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(), timeout=30.0
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(f"MCP Server did not respond within 30s (method={method})")

                if not line:
                    # EOF — subprocess exited
                    stderr_output = ""
                    try:
                        stderr_output = (await self._process.stderr.read()).decode(errors="replace")
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"MCP Server subprocess exited unexpectedly. stderr: {stderr_output[:500]}"
                    )

                try:
                    msg = json.loads(line.decode())
                except json.JSONDecodeError:
                    # Ignore non-JSON lines (shouldn't happen with correct server)
                    logger.debug(f"[McpRagClient] Non-JSON stdout line: {line!r}")
                    continue

                if msg.get("id") == req_id:
                    return msg

    @staticmethod
    def _parse_query_response(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert MCP tools/call result into a flat list of retrieval dicts.

        The RAG Server returns:
            {
                "content": [
                    {"type": "text", "text": "## Results\n\n[1] ..."},
                    {"type": "image", ...}   # optional
                ],
                "isError": false
            }

        We extract the text block and parse it into individual result entries.
        """
        if result.get("isError"):
            logger.error(f"[McpRagClient] Server returned isError=true: {result.get('content')}")
            return []

        content_items = result.get("content", [])
        parsed: List[Dict[str, Any]] = []

        for item in content_items:
            if item.get("type") != "text":
                continue

            text = item.get("text", "")
            # Return the raw text as a single context block so PromptBuilder
            # can use it directly.  For score / source metadata we do a
            # best-effort parse; the raw text is always available as "content".
            parsed.append({
                "content": text,
                "source": "modular-rag-mcp-server",
                "score": 1.0,   # server already ranked results; treat as top
                "category": "runbook",
            })

        return parsed
