"""
Prompt builder for the Runbook & Incident Memory Agent.
Constructs prompts for runbook retrieval, incident lookup, and
classification of whether a query is within scope.
"""

from typing import List, Dict, Any
from .retrieval import RetrievalResult
from config.domain_knowledge import get_domain_context, get_severity_guide


class PromptBuilder:
    """Builds prompts for the Runbook & Incident Memory Agent."""

    def __init__(self):
        self.system_prompt = self._create_system_prompt()
        self.classification_prompt_template = self._create_classification_prompt_template()

    def _create_system_prompt(self) -> str:
        domain_ctx = get_domain_context(include_roster=True)
        return (
            "You are the Runbook & Incident Memory Agent in an Incident Lifecycle Copilot.\n"
            "Your job is to help on-call support engineers find relevant runbooks, past incident "
            "resolutions, and operational knowledge — quickly and accurately.\n\n"
            "Behaviour rules:\n"
            "- Answer based ONLY on the retrieved runbook/incident context provided below.\n"
            "- If the context is insufficient, say so honestly and suggest escalation steps.\n"
            "- Always surface the most relevant runbook steps in numbered format.\n"
            "- If a past incident matches the query, summarise: date, root cause, resolution time, action items.\n"
            "- Do NOT hallucinate step numbers, commands, or service names not present in the context.\n"
            "- Respond concisely. Engineers are under time pressure during incidents.\n\n"
            f"{domain_ctx}"
        )

    def _create_classification_prompt_template(self) -> str:
        return (
            "You are a classifier. Determine whether the input is an operational knowledge query "
            "that should be handled by the Runbook & Incident Memory Agent.\n\n"
            "IN-SCOPE queries (return YES):\n"
            "- Looking up a runbook or resolution steps for a known alert\n"
            "- Asking about a past incident (root cause, resolution, timeline)\n"
            "- Asking how to diagnose or investigate a service issue\n"
            "- Asking about a service's dependencies, SLO, or on-call owner\n\n"
            "OUT-OF-SCOPE queries (return NO):\n"
            "- Active P0/P1 escalation requests ('checkout is down, need on-call')\n"
            "- Requests to draft a stakeholder status update\n"
            "- Requests to generate a postmortem\n"
            "- Incident metrics / statistics queries\n"
            "- Completely unrelated topics\n\n"
            "Reply with YES or NO only.\n\n"
            "Input: {user_input}"
        )

    def build_consultation_prompt(self, user_input: str, knowledge_docs: list[RetrievalResult]) -> str:
        context = self._build_knowledge_context(knowledge_docs)
        return f"{self.system_prompt}\n\n{context}\nEngineer query: {user_input}\n\nProvide your answer:"

    def build_classification_prompt(self, user_input: str) -> str:
        return self.classification_prompt_template.format(user_input=user_input)

    def _build_knowledge_context(self, knowledge_docs: list[RetrievalResult]) -> str:
        if not knowledge_docs:
            return (
                "No matching runbooks or past incidents found in the knowledge base.\n"
                "Advise the engineer to check Datadog APM, CloudWatch logs, and recent deploys. "
                "If the issue is urgent, escalate to the appropriate on-call rotation."
            )

        context = "=== Retrieved Runbooks & Incident Memory ===\n"
        for i, doc in enumerate(knowledge_docs, 1):
            score = "N/A" if doc.score is None else f"{doc.score:.3f}"
            context += f"\n[{i}] (score={score}, source={doc.source})\n"
            context += doc.content + "\n"
        context += "\n=== End of Retrieved Context ===\n"
        context += "\nBase your answer strictly on the above. Cite the incident ID or runbook name when relevant.\n"
        return context
