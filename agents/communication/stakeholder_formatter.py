"""
Stakeholder formatter — generates different versions of incident status updates
for different audiences (engineers, customer support, executives).
"""

from typing import Dict, Any, Optional
from langchain_core.language_models.chat_models import BaseChatModel


class StakeholderFormatter:
    """Formats incident updates for different stakeholder groups."""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def format_for_engineers(self, incident_summary: str) -> str:
        """
        Generate technical status update for engineering bridge channel.

        Includes: symptoms, suspected root cause, mitigation steps,
        runbook references, deployment hashes, metrics.
        """
        prompt = (
            "You are drafting a technical status update for engineers on an incident bridge.\n\n"
            f"Incident context:\n{incident_summary}\n\n"
            "Generate a concise technical update (under 150 words) that includes:\n"
            "- Current symptoms and affected metrics\n"
            "- Suspected root cause or active hypotheses\n"
            "- Mitigation steps in progress or completed\n"
            "- Relevant runbook references, deploy hashes, or config changes\n"
            "- Next investigation steps\n\n"
            "Use engineering terminology. Be precise and actionable."
        )
        response = await self.llm.ainvoke(prompt)
        return response.content.strip() if hasattr(response, 'content') else str(response)

    async def format_for_support(self, incident_summary: str) -> str:
        """
        Generate customer-facing update for support team.

        Non-technical language, includes: impact, workarounds, ETA, what
        customers should tell users.
        """
        prompt = (
            "You are drafting a status update for the customer support team during an incident.\n\n"
            f"Incident context:\n{incident_summary}\n\n"
            "Generate a non-technical update (under 100 words) that includes:\n"
            "- What customers are experiencing (in plain language)\n"
            "- Which features or flows are affected\n"
            "- Any available workarounds customers can use\n"
            "- Estimated time to resolution (if known) or 'investigating'\n"
            "- Recommended messaging for customer inquiries\n\n"
            "Avoid jargon. Focus on customer impact and workarounds."
        )
        response = await self.llm.ainvoke(prompt)
        return response.content.strip() if hasattr(response, 'content') else str(response)

    async def format_for_executives(self, incident_summary: str) -> str:
        """
        Generate executive summary for leadership.

        High-level: business impact, revenue/reputation risk, mitigation
        status, escalation path.
        """
        prompt = (
            "You are drafting an executive summary for leadership during a production incident.\n\n"
            f"Incident context:\n{incident_summary}\n\n"
            "Generate a high-level summary (under 80 words) that includes:\n"
            "- Business impact (revenue, customer experience, reputation)\n"
            "- Severity level and scope (regional / global / single service)\n"
            "- Current mitigation status (investigating / mitigated / resolved)\n"
            "- Estimated customer impact duration\n"
            "- Whether external communication (status page, social media) is needed\n\n"
            "Use business language. Focus on impact and mitigation, not technical details."
        )
        response = await self.llm.ainvoke(prompt)
        return response.content.strip() if hasattr(response, 'content') else str(response)

    async def format_all_stakeholders(self, incident_summary: str) -> Dict[str, str]:
        """Generate all three versions in parallel."""
        import asyncio

        results = await asyncio.gather(
            self.format_for_engineers(incident_summary),
            self.format_for_support(incident_summary),
            self.format_for_executives(incident_summary),
        )

        return {
            "engineers": results[0],
            "support": results[1],
            "executives": results[2],
        }
