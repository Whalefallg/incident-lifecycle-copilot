"""
PostmortemAgent — generates post-incident review drafts from recorded events.

The runtime path consumes ConversationSnapshot.events. Transcript keyword
extraction is retained only for explicit legacy imports.

Production features:
- Model routing: uses complex-tier model for postmortem generation
- Semantic caching: caches similar postmortem requests
"""

import uuid
import os
from typing import Dict, Any
from config.model_provider import create_chat_model
from conversation.events import IncidentEvent, build_timeline
from conversation.models import EscalationContext
from knowledge.approval import KnowledgeDraft
from .postmortem import PostmortemGenerator, PostmortemBuilder


class PostmortemAgent:
    """
    Generates a draft from the factual event ledger. It never ingests knowledge.
    """

    def __init__(self, session_id=None, knowledge_service=None):
        self.session_id = session_id or str(uuid.uuid4())
        self.llm = self._initialize_llm()
        self.generator = PostmortemGenerator(self.llm)
        self.builder = PostmortemBuilder(self.generator)

        self.session_messages = []
        self.incident_events: list[IncidentEvent] = []
        self.escalation_context = EscalationContext()
        self.generated_draft: KnowledgeDraft | None = None
        self.next_draft_version = 1

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
                    self._capture_draft(cached)
                    return cached
            except Exception:
                pass

        report_chunks: list[str] = []
        async for token in self.builder.build_stream(
            prompt,
            self.incident_events,
            self.escalation_context,
        ):
            report_chunks.append(token)

        report = "".join(report_chunks)
        self._capture_draft(self._draft_content(report))

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
                    self._capture_draft(self._draft_content(cached))
                    for char in cached:
                        yield char
                    return
            except Exception:
                pass

        collected = []
        async for token in self.builder.build_stream(
            user_input,
            self.incident_events,
            self.escalation_context,
        ):
            collected.append(token)
            yield token

        self._capture_draft(self._draft_content("".join(collected)))

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
        """Return factual ledger metadata for debugging."""
        return {
            "session_id": self.session_id,
            "event_count": len(self.incident_events),
            "event_types": [event.type.value for event in build_timeline(self.incident_events)],
            "service": self.escalation_context.service,
            "severity": self.escalation_context.severity,
        }

    def _capture_draft(self, content: str) -> None:
        if not content or not self.incident_events:
            return
        self.generated_draft = KnowledgeDraft.create(
            source_incident_id=self.session_id,
            version=self.next_draft_version,
            content=content,
        )

    @staticmethod
    def _draft_content(output: str) -> str:
        marker = "[REPLY][Postmortem Agent]\n"
        return output.split(marker, 1)[1].strip() if marker in output else output.strip()
