"""Compatibility facade over the backend-neutral Retriever contract."""

from __future__ import annotations

from .retrieval import RetrievalResult, Retriever


class KnowledgeRetriever:
    """Deprecated name retained for callers; it owns no backend lifecycle."""

    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever

    async def search_knowledge(
        self, query: str, top_k: int = 5, collection: str = "default"
    ) -> list[RetrievalResult]:
        return await self.retriever.search(query, top_k=top_k, collection=collection)
