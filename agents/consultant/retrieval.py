"""Backend-neutral retrieval contract used by runbook agents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field


class RetrievalUnavailable(RuntimeError):
    """The configured retrieval backend could not serve the request."""


class RetrievalResult(BaseModel):
    document_id: str
    content: str
    source: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Retriever(Protocol):
    async def search(
        self, query: str, *, top_k: int = 10, collection: str = "default"
    ) -> list[RetrievalResult]: ...


class LocalRunbookRetriever:
    """Deterministic keyword baseline used explicitly in local/degraded startup mode."""

    def __init__(self, runbook_path: Path | None = None) -> None:
        self.runbook_path = (
            runbook_path or Path(__file__).resolve().parents[2] / "data" / "runbooks"
        )

    async def search(
        self, query: str, *, top_k: int = 10, collection: str = "default"
    ) -> list[RetrievalResult]:
        del collection
        terms = {
            term
            for term in re.findall(r"[a-z0-9_-]+", query.lower())
            if len(term) > 1
            and term
            not in {"a", "an", "and", "for", "how", "in", "is", "of", "the", "to", "what", "with"}
        }
        scored: list[tuple[int, Path, str]] = []
        if not self.runbook_path.exists():
            return []
        for path in sorted(self.runbook_path.glob("*.yaml")):
            content = path.read_text(encoding="utf-8")
            score = sum(term in f"{path.stem} {content}".lower() for term in terms)
            if score:
                scored.append((score, path, content))
        scored.sort(key=lambda row: (-row[0], row[1].name))
        aliases = {
            "checkout-error.yaml": "checkout-error-runbook",
            "db-connection.yaml": "postgres-connection-pool-runbook",
            "lambda-timeout.yaml": "lambda-timeout-runbook",
            "payment-gateway.yaml": "payment-gateway-timeout-runbook",
            "redis-oom.yaml": "redis-oom-runbook",
        }
        return [
            RetrievalResult(
                document_id=aliases.get(path.name, path.stem),
                content=content,
                source=str(path),
                score=round(score / max(len(terms), 1), 3),
                metadata={"backend": "local", "filename": path.name},
            )
            for score, path, content in scored[:top_k]
        ]
