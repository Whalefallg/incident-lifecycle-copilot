"""Postmortem generation from recorded facts, never transcript keyword guesses."""

from langchain_core.language_models.chat_models import BaseChatModel

from conversation.events import IncidentEvent, format_timeline
from conversation.models import EscalationContext


class PostmortemGenerator:
    POSTMORTEM_TEMPLATE = """
You are writing a blameless post-incident review.

=== RECORDED INCIDENT CONTEXT ===
{incident_data}

=== RECORDED FACTUAL TIMELINE ===
{timeline_summary}

=== ENGINEER'S ADDITIONAL CONTEXT ===
{engineer_context}

Generate EXACTLY these sections:

## Incident Summary
## Impact
## Timeline
## Observed Facts
Only facts present in the context or recorded event ledger.
## Inferred Root Cause
Clearly label every inference. Use "To be determined" when unsupported.
## Open Questions
## Resolution
## Action Items
| Priority | Action | Owner | Due |
|----------|--------|-------|-----|

Never present an inference as an observed fact. Never invent a notification,
mitigation, dispatch, timestamp, owner, customer impact, or root cause.
"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    def _prompt(
        self,
        events: list[IncidentEvent],
        context: EscalationContext,
        engineer_context: str,
    ) -> str:
        incident_data = (
            f"Severity: {context.severity or 'unknown'}\n"
            f"Service: {context.service or 'unknown'}\n"
            f"Impact scope: {context.impact_scope or 'unknown'}\n"
            f"Symptoms: {context.symptoms or ['unknown']}\n"
            f"Suspected cause (unverified): {context.suspected_cause or 'unknown'}\n"
            f"Recent changes: {context.recent_changes or ['unknown']}\n"
        )
        return self.POSTMORTEM_TEMPLATE.format(
            incident_data=incident_data,
            timeline_summary=format_timeline(events),
            engineer_context=engineer_context or "No additional context provided.",
        )

    async def generate(
        self,
        events: list[IncidentEvent],
        context: EscalationContext,
        engineer_context: str = "",
    ) -> str:
        response = await self.llm.ainvoke(self._prompt(events, context, engineer_context))
        return response.content.strip() if hasattr(response, "content") else str(response)

    async def generate_stream(
        self,
        events: list[IncidentEvent],
        context: EscalationContext,
        engineer_context: str = "",
    ):
        async for chunk in self.llm.astream(self._prompt(events, context, engineer_context)):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                yield token
