"""Central configuration for the query-only rag-as-mcp integration."""

from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


@dataclass(frozen=True)
class RagMcpSettings:
    mode: Literal["auto", "mcp", "local"] = "auto"
    server_path: Path | None = None
    python_executable: str | None = None
    command: tuple[str, ...] | None = None
    settings_path: Path | None = None
    collection: str = "default"
    startup_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 30.0
    max_retries: int = 1

    @classmethod
    def from_env(cls) -> "RagMcpSettings":
        mode = os.getenv("RAG_MODE", "auto").lower()
        if mode not in {"auto", "mcp", "local"}:
            raise ValueError("RAG_MODE must be one of: auto, mcp, local")
        raw_path = os.getenv("RAG_MCP_SERVER_PATH")
        raw_settings = os.getenv("RAG_MCP_SETTINGS_PATH")
        raw_command = os.getenv("RAG_MCP_COMMAND")
        command = None
        if raw_command:
            try:
                decoded = json.loads(raw_command)
                command = tuple(decoded) if isinstance(decoded, list) else None
            except json.JSONDecodeError:
                command = tuple(shlex.split(raw_command))
            if not command or not all(isinstance(part, str) and part for part in command):
                raise ValueError("RAG_MCP_COMMAND must be a non-empty JSON array or shell command")
        max_retries = int(os.getenv("RAG_MCP_MAX_RETRIES", "1"))
        if max_retries < 0:
            raise ValueError("RAG_MCP_MAX_RETRIES must be non-negative")
        return cls(
            mode=cast(Literal["auto", "mcp", "local"], mode),
            server_path=Path(raw_path).expanduser() if raw_path else None,
            python_executable=os.getenv("RAG_MCP_PYTHON") or sys.executable,
            command=command,
            settings_path=Path(raw_settings).expanduser() if raw_settings else None,
            collection=os.getenv("RAG_MCP_COLLECTION", "default"),
            startup_timeout_seconds=float(os.getenv("RAG_MCP_STARTUP_TIMEOUT_SECONDS", "10")),
            request_timeout_seconds=float(os.getenv("RAG_MCP_REQUEST_TIMEOUT_SECONDS", "30")),
            max_retries=max_retries,
        )

    def server_command(self) -> tuple[str, ...]:
        return self.command or (self.python_executable or sys.executable, "main.py")
