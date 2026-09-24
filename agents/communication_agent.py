"""
CommunicationAgent — Multi-Stakeholder Status Update Agent.

Generates incident status updates tailored for different audiences:
- Engineers: technical details, runbooks, metrics
- Customer Support: customer-facing language, workarounds, ETA
- Executives: business impact, revenue risk, mitigation status
"""

import uuid
from config.model_provider import create_chat_model
from .communication import CommsProcessor, StakeholderFormatter


class CommunicationAgent:
    """
    Communication Agent — drafts multi-stakeholder incident status updates.
    """

    def __init__(self, session_id=None):
        self.session_id = session_id or str(uuid.uuid4())
        self.llm = self._initialize_llm()
        self.formatter = StakeholderFormatter(self.llm)
        self.processor = CommsProcessor(self.formatter)

    def _initialize_llm(self):
        return create_chat_model(temperature=0.3)

    async def draft_stream(self, user_input: str, incident_context: str = None):
        """
        Main streaming entry point for drafting status updates.

        Args:
            user_input: Engineer's request (e.g., "write an exec update")
            incident_context: Optional incident summary from session history

        Yields:
            Streaming response tokens with formatted updates.
        """
        async for token in self.processor.draft_updates_stream(user_input, incident_context):
            yield token
