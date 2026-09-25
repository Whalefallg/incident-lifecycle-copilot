"""
Consultation classifier for the Runbook & Incident Memory Agent.
Determines whether an incoming query is in-scope for runbook / incident lookup.
"""

from langchain_core.language_models.chat_models import BaseChatModel

from .prompt_builder import PromptBuilder


class ConsultationClassifier:
    """Classifier for runbook / incident memory queries."""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.prompt_builder = PromptBuilder()

    async def is_consultation_related(self, user_input: str) -> bool:
        """
        Determine if the input is a runbook / incident memory query.

        Returns True if the query is about:
        - Looking up a runbook
        - Asking about a past incident
        - Investigating a service issue
        - Service metadata (dependencies, SLO, on-call)

        Returns False for active escalations, comms requests, postmortem
        generation, or out-of-scope queries.
        """
        try:
            prompt = self.prompt_builder.build_classification_prompt(user_input)
            response = await self.llm.ainvoke([{"role": "user", "content": prompt}])
            result = response.content.strip().upper()
            return result == "YES"
        except Exception as e:
            print(f"[ConsultationClassifier] Classification failed: {e}")
            return True
