"""Build a postmortem draft from the authoritative structured event ledger."""

from typing import AsyncGenerator

from conversation.events import IncidentEvent
from conversation.models import EscalationContext
from .postmortem_generator import PostmortemGenerator


class PostmortemBuilder:
    def __init__(self, postmortem_generator: PostmortemGenerator):
        self.generator = postmortem_generator

    async def build_stream(
        self,
        user_request: str,
        events: list[IncidentEvent],
        escalation_context: EscalationContext,
    ) -> AsyncGenerator[str, None]:
        yield "[THOUGHT][Postmortem Agent] Building timeline from recorded incident events...\n"
        if not events:
            yield "[REPLY][Postmortem Agent]\n"
            yield "No structured incident events are available for this session."
            return

        yield (
            f"[THOUGHT][Postmortem Agent] Using {len(events)} recorded events for "
            f"{escalation_context.severity or 'unknown severity'} / "
            f"{escalation_context.service or 'unknown service'}.\n"
        )
        yield "[REPLY][Postmortem Agent]\n"
        async for token in self.generator.generate_stream(
            events, escalation_context, user_request
        ):
            yield token
