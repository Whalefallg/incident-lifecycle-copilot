"""Strict adapter for rag-as-mcp's current Markdown citation response."""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Any

from .retrieval import RetrievalResult


class McpMalformedResponse(RuntimeError):
    pass


class McpToolError(RuntimeError):
    pass


_ERROR_PREFIXES = ("错误：", "检索组件初始化失败", "检索时发生错误：", "Error:")
_NO_RESULTS_PREFIX = "未找到相关内容。"
_HIT = re.compile(
    r"\*\*\[(?P<index>\d+)\]\*\*\s+`(?P<source>[^`]+)`"
    r"(?:，第\s*(?P<page>[^（]+?)\s*页)?（相关度:\s*(?P<score>N/A|-?\d+(?:\.\d+)?)）\s*\n"
    r"(?P<body>.*?)(?=\n\*\*\[\d+\]\*\*|\n---|\Z)",
    re.MULTILINE | re.DOTALL,
)


def normalize_document_id(source_path: str) -> str:
    """Incident-side normalization; rag-as-mcp does not return document_id."""
    filename = PurePath(source_path.replace("\\", "/")).name
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    normalized = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    if not normalized:
        raise McpMalformedResponse(f"cannot normalize source path: {source_path!r}")
    return normalized


class McpQueryResponseParser:
    def parse(self, result: dict[str, Any]) -> list[RetrievalResult]:
        if result.get("isError") is True:
            raise McpToolError(self._text(result) or "rag-as-mcp returned isError=true")
        text = self._text(result)
        if not text:
            raise McpMalformedResponse("rag-as-mcp response has no text content")
        stripped = text.strip()
        if stripped.startswith(_ERROR_PREFIXES):
            # Upstream currently puts several failures in TextContent with isError=false.
            raise McpToolError(stripped)
        if stripped.startswith(_NO_RESULTS_PREFIX):
            return []

        matches = list(_HIT.finditer(text))
        if not matches:
            raise McpMalformedResponse("response does not match rag-as-mcp citation Markdown")
        results: list[RetrievalResult] = []
        for match in matches:
            source = match.group("source")
            body_lines = match.group("body").strip().splitlines()
            if body_lines and body_lines[0].startswith(">"):
                body_lines[0] = body_lines[0][1:].lstrip()
            body = "\n".join(
                line[1:].lstrip() if line.startswith(">") else line for line in body_lines
            ).strip()
            if not body:
                raise McpMalformedResponse(f"citation {match.group('index')} has empty content")
            raw_score = match.group("score")
            metadata: dict[str, Any] = {
                "citation_index": int(match.group("index")),
                "document_id_normalization": "incident-source-path-stem",
            }
            if match.group("page"):
                metadata["page"] = match.group("page").strip()
            results.append(
                RetrievalResult(
                    document_id=normalize_document_id(source),
                    content=body,
                    source=source,
                    score=None if raw_score == "N/A" else float(raw_score),
                    metadata=metadata,
                )
            )
        return results

    @staticmethod
    def _text(result: dict[str, Any]) -> str:
        items = result.get("content")
        if not isinstance(items, list):
            return ""
        return "\n".join(
            item.get("text", "")
            for item in items
            if isinstance(item, dict) and item.get("type") == "text"
        )
