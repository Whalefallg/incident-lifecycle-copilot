"""
Communication processor — orchestrates the multi-stakeholder status update flow.
"""

from typing import AsyncGenerator, Optional
from .stakeholder_formatter import StakeholderFormatter


class CommsProcessor:
    """Processes communication drafting requests."""

    def __init__(self, stakeholder_formatter: StakeholderFormatter):
        self.formatter = stakeholder_formatter

    async def draft_updates_stream(
        self,
        user_request: str,
        incident_context: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream multi-stakeholder status updates.

        Args:
            user_request: Engineer's request (e.g., "draft an update for execs")
            incident_context: Current incident summary or session history

        Yields:
            Formatted updates for different stakeholder groups.
        """
        incident_summary = incident_context or user_request

        yield "[THOUGHT][Communication Agent] Parsing request and identifying target stakeholders...\n"

        target = self._identify_target_stakeholders(user_request)

        if target == "all":
            yield "[THOUGHT][Communication Agent] Generating updates for all stakeholder groups...\n"
            all_updates = await self.formatter.format_all_stakeholders(incident_summary)
            yield "[REPLY][Communication Agent]\n"
            yield "=== Engineer Bridge Update ===\n"
            yield all_updates["engineers"] + "\n\n"
            yield "=== Customer Support Update ===\n"
            yield all_updates["support"] + "\n\n"
            yield "=== Executive Summary ===\n"
            yield all_updates["executives"] + "\n"

        elif target == "engineers":
            yield "[THOUGHT][Communication Agent] Generating technical bridge update...\n"
            update = await self.formatter.format_for_engineers(incident_summary)
            yield "[REPLY][Communication Agent]\n"
            yield "=== Engineer Bridge Update ===\n"
            yield update + "\n"

        elif target == "support":
            yield "[THOUGHT][Communication Agent] Generating customer support update...\n"
            update = await self.formatter.format_for_support(incident_summary)
            yield "[REPLY][Communication Agent]\n"
            yield "=== Customer Support Update ===\n"
            yield update + "\n"

        elif target == "executives":
            yield "[THOUGHT][Communication Agent] Generating executive summary...\n"
            update = await self.formatter.format_for_executives(incident_summary)
            yield "[REPLY][Communication Agent]\n"
            yield "=== Executive Summary ===\n"
            yield update + "\n"

        else:
            yield "[REPLY][Communication Agent]\n"
            yield "Could not determine target stakeholder group. Please specify: engineers, support, executives, or all.\n"

    def _identify_target_stakeholders(self, user_request: str) -> str:
        """
        Identify which stakeholder group(s) the engineer wants to target.

        Returns: "engineers" | "support" | "executives" | "all"
        """
        req_lower = user_request.lower()

        if any(kw in req_lower for kw in ["all", "everyone", "every group", "three"]):
            return "all"
        elif any(kw in req_lower for kw in ["exec", "leadership", "vp", "management", "ceo"]):
            return "executives"
        elif any(kw in req_lower for kw in ["support", "customer", "cs team", "cx"]):
            return "support"
        elif any(kw in req_lower for kw in ["engineer", "bridge", "technical", "oncall", "sre"]):
            return "engineers"
        else:
            return "all"
