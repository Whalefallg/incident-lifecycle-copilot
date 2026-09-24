"""
PostmortemAgent — generates post-incident review documents from session history.

This is the deepest component of the Incident Lifecycle Copilot. It reconstructs
incident timelines from local conversation logs and produces structured postmortem
documents without requiring external integrations (Slack, PagerDuty, etc.).

Key capability: timeline extraction from pure dialogue history.

Production features:
- Model routing: uses complex-tier model for postmortem generation
- Semantic caching: caches similar postmortem requests
"""

import uuid
import os
from typing import List, Dict, Any
from config.model_provider import create_chat_model
from .postmortem import TimelineExtractor, PostmortemGenerator, PostmortemBuilder


class PostmortemAgent:
    """
    Postmortem Agent — reconstructs incident timeline from session history
    and generates structured post-incident review documents.
    """

    def __init__(self, session_id=None, knowledge_service=None):
        self.session_id = session_id or str(uuid.uuid4())
        self.knowledge_service = knowledge_service
        self.llm = self._initialize_llm()

        self.extractor = TimelineExtractor()
        self.generator = PostmortemGenerator(self.llm)
        self.builder = PostmortemBuilder(self.generator)

        self.session_messages = []

        self._cache_enabled = os.getenv("SEMANTIC_CACHE_ENABLED", "false").lower() == "true"

    def _initialize_llm(self):
        routing_enabled = os.getenv("MODEL_ROUTING_ENABLED", "false").lower() == "true"

        if routing_enabled:
            try:
                from config.model_router import model_router, TaskComplexity
                return model_router.route(
                    task_name="postmortem_generation",
                    temperature=0.2,
                    complexity=TaskComplexity.COMPLEX
                )
            except Exception:
                pass

        return create_chat_model(temperature=0.2)

    def add_session_message(self, role: str, content: str, timestamp: str = None):
        """
        Record a message in the session history for later timeline extraction.

        In a production deployment, this would write to a session database.
        """
        from datetime import datetime
        self.session_messages.append({
            "role": role,
            "content": content,
            "timestamp": timestamp or datetime.utcnow().isoformat(),
        })

    async def generate_report(self, prompt: str) -> str:
        """
        Generate postmortem report (non-streaming).
        Used by Celery async tasks.

        Args:
            prompt: Postmortem generation prompt

        Returns:
            Complete postmortem document
        """
        if self._cache_enabled:
            try:
                from config.semantic_cache import semantic_cache
                cached = await semantic_cache.get(
                    query=prompt,
                    context={"agent": "postmortem", "session_id": self.session_id}
                )
                if cached:
                    return cached
            except Exception:
                pass

        report_chunks = []
        async for token in self.builder.build_stream(
            prompt,
            self.session_messages,
            self.knowledge_service,
        ):
            report_chunks.append(token)

        report = "".join(report_chunks)

        if self._cache_enabled:
            try:
                from config.semantic_cache import semantic_cache
                await semantic_cache.set(
                    query=prompt,
                    response=report,
                    context={"agent": "postmortem", "session_id": self.session_id}
                )
            except Exception:
                pass

        return report

    async def generate_stream(self, user_input: str):
        """
        Main streaming entry point for postmortem generation.

        Args:
            user_input: Engineer's request (e.g., "incident resolved, generate postmortem")

        Yields:
            Streaming postmortem document tokens.
        """
        if self._cache_enabled:
            try:
                from config.semantic_cache import semantic_cache
                cached = await semantic_cache.get(
                    query=user_input,
                    context={"agent": "postmortem", "session_id": self.session_id}
                )
                if cached:
                    for char in cached:
                        yield char
                    return
            except Exception:
                pass

        collected = []
        async for token in self.builder.build_stream(
            user_input,
            self.session_messages,
            self.knowledge_service,
        ):
            collected.append(token)
            yield token

        if self._cache_enabled:
            try:
                from config.semantic_cache import semantic_cache
                await semantic_cache.set(
                    query=user_input,
                    response="".join(collected),
                    context={"agent": "postmortem", "session_id": self.session_id}
                )
            except Exception:
                pass

    def get_session_summary(self) -> Dict[str, Any]:
        """Return metadata about the current session for debugging."""
        metadata = self.extractor.extract_incident_metadata(self.session_messages)
        return {
            "session_id": self.session_id,
            "message_count": len(self.session_messages),
            "metadata": metadata,
        }
