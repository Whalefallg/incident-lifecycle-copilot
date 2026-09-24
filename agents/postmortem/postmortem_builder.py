"""
Postmortem builder — orchestrates the full postmortem generation flow,
including session history retrieval and knowledge base write-back.
"""

from typing import List, Dict, Any, AsyncGenerator, Optional
from .postmortem_generator import PostmortemGenerator


class PostmortemBuilder:
    """Orchestrates postmortem generation and knowledge base write-back."""

    def __init__(self, postmortem_generator: PostmortemGenerator):
        self.generator = postmortem_generator

    async def build_stream(
        self,
        user_request: str,
        session_messages: List[Dict[str, Any]],
        knowledge_service=None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream postmortem generation from session history.

        Args:
            user_request: Engineer's postmortem request message.
            session_messages: Full session conversation history.
            knowledge_service: Optional — if provided, write postmortem back to KB.

        Yields:
            Stream of formatted postmortem content.
        """
        yield "[THOUGHT][Postmortem Agent] Extracting timeline from session history...\n"

        if not session_messages:
            yield "[REPLY][Postmortem Agent]\n"
            yield (
                "No session history found. Please provide incident details:\n"
                "- What service was affected?\n"
                "- What was the severity?\n"
                "- What was the root cause?\n"
                "- How was it resolved?\n"
            )
            return

        metadata = self.generator.extractor.extract_incident_metadata(session_messages)
        yield (
            f"[THOUGHT][Postmortem Agent] Identified: {metadata['severity']} incident on "
            f"{metadata['service']} — reconstructing timeline from "
            f"{metadata['message_count']} session messages...\n"
        )

        yield "[REPLY][Postmortem Agent]\n"

        postmortem_content = ""
        async for token in self.generator.generate_stream(session_messages, user_request):
            postmortem_content += token
            yield token

        # Write back to knowledge base so future RAG queries can find this incident
        if knowledge_service and postmortem_content:
            try:
                service_name = metadata.get("service", "unknown")
                severity = metadata.get("severity", "unknown")
                keywords = [service_name, severity, "postmortem", "incident", "rca"]

                await knowledge_service.add_document(
                    content=postmortem_content,
                    category=f"postmortem:{service_name}",
                    keywords=keywords,
                )
                yield (
                    f"\n\n---\n*Postmortem saved to incident knowledge base "
                    f"(service: {service_name}, severity: {severity}). "
                    "Future runbook lookups can reference this incident.*\n"
                )
            except Exception as e:
                yield f"\n\n*Note: Could not save to knowledge base: {e}*\n"
