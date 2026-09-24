"""
Postmortem generator — uses the LLM to produce a structured postmortem
document from extracted timeline events and incident metadata.
"""

from typing import List, Dict, Any
from langchain_core.language_models.chat_models import BaseChatModel
from .timeline_extractor import TimelineExtractor


class PostmortemGenerator:
    """Generates structured postmortem documents from session history."""

    POSTMORTEM_TEMPLATE = """
You are writing a formal post-incident review (postmortem) for an engineering team.
Use the incident data below to generate a complete, structured postmortem document.

=== INCIDENT DATA ===
{incident_data}

=== TIMELINE SUMMARY ===
{timeline_summary}

=== ENGINEER'S ADDITIONAL CONTEXT ===
{engineer_context}

Generate a postmortem document with EXACTLY these sections:

## Incident Summary
One sentence: what broke, when, severity level.

## Impact
- Affected service(s)
- Estimated user/revenue impact
- Duration (detected → resolved)
- Customer-facing effect

## Timeline
Format each event as:
  HH:MM — Event description

## Root Cause
Concise technical explanation of why the incident occurred.

## Contributing Factors
Bullet list of conditions that made the incident worse or harder to detect.

## Resolution
What was done to restore service.

## Action Items
| Priority | Action | Owner | Due |
|----------|--------|-------|-----|
| P0       | ...    | ...   | ... |

## Lessons Learned
2-3 key takeaways for the team.

Be specific and factual. If information is not available, write "To be determined" rather than hallucinating.
"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.extractor = TimelineExtractor()

    async def generate(
        self,
        session_messages: List[Dict[str, Any]],
        engineer_context: str = "",
    ) -> str:
        """
        Generate a postmortem document from session history.

        Args:
            session_messages: Full conversation history from the session.
            engineer_context: Additional context from the engineer's request.

        Returns:
            Formatted postmortem markdown string.
        """
        events = self.extractor.extract_timeline(session_messages)
        metadata = self.extractor.extract_incident_metadata(session_messages)
        timeline_summary = self.extractor.build_timeline_summary(events)

        incident_data = (
            f"Severity: {metadata['severity']}\n"
            f"Service: {metadata['service']}\n"
            f"Detected at: {metadata['detected_at']}\n"
            f"Resolved at: {metadata['resolved_at']}\n"
            f"Session messages: {metadata['message_count']}\n"
        )

        prompt = self.POSTMORTEM_TEMPLATE.format(
            incident_data=incident_data,
            timeline_summary=timeline_summary,
            engineer_context=engineer_context or "No additional context provided.",
        )

        response = await self.llm.ainvoke(prompt)
        return response.content.strip() if hasattr(response, "content") else str(response)

    async def generate_stream(
        self,
        session_messages: List[Dict[str, Any]],
        engineer_context: str = "",
    ):
        """
        Stream postmortem generation token by token.

        Yields:
            Response tokens from the LLM.
        """
        events = self.extractor.extract_timeline(session_messages)
        metadata = self.extractor.extract_incident_metadata(session_messages)
        timeline_summary = self.extractor.build_timeline_summary(events)

        incident_data = (
            f"Severity: {metadata['severity']}\n"
            f"Service: {metadata['service']}\n"
            f"Detected at: {metadata['detected_at']}\n"
            f"Resolved at: {metadata['resolved_at']}\n"
            f"Session messages: {metadata['message_count']}\n"
        )

        prompt = self.POSTMORTEM_TEMPLATE.format(
            incident_data=incident_data,
            timeline_summary=timeline_summary,
            engineer_context=engineer_context or "No additional context provided.",
        )

        async for chunk in self.llm.astream(prompt):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                yield token
