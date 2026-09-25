"""Long-lived stdio JSON-RPC client for the current rag-as-mcp contract."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from config.rag_mcp import RagMcpSettings

from .mcp_response_parser import McpQueryResponseParser
from .retrieval import RetrievalResult

logger = logging.getLogger(__name__)


class McpError(RuntimeError):
    pass


class McpNotConfigured(McpError):
    pass


class McpStartupError(McpError):
    pass


class McpProtocolError(McpError):
    pass


class McpCapabilityError(McpError):
    pass


class McpTimeoutError(McpError):
    pass


class McpProcessExited(McpError):
    pass


@dataclass(frozen=True)
class McpCapabilities:
    server_name: str
    server_version: str
    tools: tuple[str, ...]


class McpRagClient:
    """Owns one reusable rag-as-mcp process for an application worker."""

    REQUIRED_TOOL = "query_knowledge_hub"

    def __init__(self, settings: RagMcpSettings | None = None) -> None:
        self.settings = settings or RagMcpSettings.from_env()
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._req_id = 0
        self._stderr_task: asyncio.Task[None] | None = None
        self.capabilities: McpCapabilities | None = None
        self.parser = McpQueryResponseParser()

    @property
    def server_path(self):
        return self.settings.server_path

    async def start(self) -> McpCapabilities:
        async with self._lifecycle_lock:
            if self._process and self._process.returncode is None and self.capabilities:
                return self.capabilities
            path = self.settings.server_path
            if path is None:
                raise McpNotConfigured("RAG_MCP_SERVER_PATH is not configured")
            if not path.is_dir():
                raise McpNotConfigured(f"rag-as-mcp server path does not exist: {path}")
            command = self.settings.server_command()
            env = os.environ.copy()
            if self.settings.settings_path:
                env["MCP_SETTINGS_PATH"] = str(self.settings.settings_path)
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(path),
                    env=env,
                )
                self._stderr_task = asyncio.create_task(self._drain_stderr(self._process))
                initialized = await self._request(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "clientInfo": {"name": "incident-lifecycle-copilot", "version": "1.0"},
                    },
                    timeout=self.settings.startup_timeout_seconds,
                )
                await self._notify("notifications/initialized", {})
                tools_result = await self._request(
                    "tools/list", {}, timeout=self.settings.startup_timeout_seconds
                )
                self.capabilities = self._validate_capabilities(initialized, tools_result)
                return self.capabilities
            except McpError:
                await self._stop_unlocked()
                raise
            except OSError as exc:
                await self._stop_unlocked()
                raise McpStartupError(str(exc)) from exc

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            await self._stop_unlocked()

    async def _stop_unlocked(self) -> None:
        process, self._process = self._process, None
        stderr_task, self._stderr_task = self._stderr_task, None
        self.capabilities = None
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if stderr_task:
            try:
                await asyncio.wait_for(stderr_task, timeout=1)
            except asyncio.TimeoutError:
                stderr_task.cancel()

    @staticmethod
    async def _drain_stderr(process: asyncio.subprocess.Process) -> None:
        if not process.stderr:
            return
        while line := await process.stderr.readline():
            logger.debug("[rag-as-mcp] %s", line.decode(errors="replace").rstrip())

    async def ping(self) -> None:
        self._require_started()
        await self._request("ping", {})

    async def query(
        self, query: str, *, top_k: int = 10, collection: str | None = None
    ) -> list[RetrievalResult]:
        if not 1 <= top_k <= 50:
            raise ValueError("top_k must be in range 1..50")
        arguments = {
            "query": query,
            "top_k": top_k,
            "collection": collection or self.settings.collection,
        }
        for attempt in range(self.settings.max_retries + 1):
            try:
                self._require_started()
                response = await self._request(
                    "tools/call", {"name": self.REQUIRED_TOOL, "arguments": arguments}
                )
                return self.parser.parse(response)
            except (McpTimeoutError, McpProcessExited, ConnectionError):
                if attempt >= self.settings.max_retries:
                    raise
                await self.stop()
                await self.start()
        raise AssertionError("bounded retry loop exhausted")

    async def search(
        self, query: str, *, top_k: int = 10, collection: str = "default"
    ) -> list[RetrievalResult]:
        """Implement the backend-neutral Retriever protocol."""
        return await self.query(query, top_k=top_k, collection=collection)

    def _require_started(self) -> None:
        if not self._process or self._process.returncode is not None or not self.capabilities:
            raise McpProcessExited("rag-as-mcp process is not running and ready")

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise McpProcessExited("cannot notify a stopped rag-as-mcp process")
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
        self._process.stdin.write(payload.encode())
        await self._process.stdin.drain()

    async def _request(
        self, method: str, params: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        async with self._lock:
            process = self._process
            if (
                not process
                or not process.stdin
                or not process.stdout
                or process.returncode is not None
            ):
                raise McpProcessExited("rag-as-mcp process is not running")
            self._req_id += 1
            request_id = self._req_id
            payload = (
                json.dumps(
                    {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                    ensure_ascii=False,
                )
                + "\n"
            )
            try:
                process.stdin.write(payload.encode())
                await process.stdin.drain()
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=timeout or self.settings.request_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise McpTimeoutError(f"rag-as-mcp timed out during {method}") from exc
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise McpProcessExited(f"rag-as-mcp transport failed during {method}") from exc
            if not line:
                raise McpProcessExited(f"rag-as-mcp exited during {method}")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise McpProtocolError("rag-as-mcp emitted non-JSON stdout") from exc
            if response.get("id") != request_id:
                raise McpProtocolError(f"unexpected response id during {method}")
            if "error" in response:
                error = response["error"]
                raise McpProtocolError(error.get("message", str(error)))
            result = response.get("result")
            if not isinstance(result, dict):
                raise McpProtocolError(f"missing object result during {method}")
            return result

    @classmethod
    def _validate_capabilities(
        cls, initialized: dict[str, Any], tools_result: dict[str, Any]
    ) -> McpCapabilities:
        server = initialized.get("serverInfo")
        if not isinstance(server, dict) or not server.get("name") or not server.get("version"):
            raise McpCapabilityError("initialize response lacks serverInfo name/version")
        tools = tools_result.get("tools")
        if not isinstance(tools, list):
            raise McpCapabilityError("tools/list response lacks tools array")
        query_tool = next((tool for tool in tools if tool.get("name") == cls.REQUIRED_TOOL), None)
        if query_tool is None:
            raise McpCapabilityError(f"required tool missing: {cls.REQUIRED_TOOL}")
        schema = query_tool.get("inputSchema", {})
        properties = schema.get("properties", {})
        if not {"query", "top_k", "collection"}.issubset(properties):
            raise McpCapabilityError("query_knowledge_hub schema lacks required properties")
        if "query" not in schema.get("required", []):
            raise McpCapabilityError("query_knowledge_hub.query must be required")
        if properties["top_k"].get("maximum") != 50:
            raise McpCapabilityError("query_knowledge_hub.top_k maximum must be 50")
        return McpCapabilities(
            str(server["name"]), str(server["version"]), tuple(str(t.get("name")) for t in tools)
        )
