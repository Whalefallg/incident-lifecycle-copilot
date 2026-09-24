"""
Incident Triage Classifier — determines the type of incoming request and routes
it to the appropriate specialist agent.

Categories:
    escalation    — P0/P1 alert or active incident needing on-call dispatch
    query         — runbook lookup or historical incident search
    comms_update  — request to draft a stakeholder status update
    postmortem    — incident resolved; generate postmortem draft
    statistics    — incident metrics query (MTTR, P1 counts, etc.)
    other         — unrelated input
"""

from langchain_core.prompts import PromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel


class TaskClassifier:
    """LLM-powered incident triage classifier."""

    VALID_CATEGORIES = {
        'escalation', 'query', 'comms_update', 'postmortem', 'statistics', 'other'
    }

    CATEGORY_DESCRIPTIONS = {
        'escalation':   'Active P0/P1 incident — escalation & on-call dispatch required',
        'query':        'Runbook or historical incident lookup via RAG',
        'comms_update': 'Draft stakeholder status update (engineer / support / executive)',
        'postmortem':   'Incident resolved — generate postmortem draft from session history',
        'statistics':   'Incident metrics query (MTTR, weekly P1 count, alert trends)',
        'other':        'Out-of-scope request',
    }

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self._initialize_prompt()
        self.chain = self.prompt | self.llm

    def _initialize_prompt(self):
        self.prompt = PromptTemplate(
            input_variables=["task"],
            template=(
                "You are an intelligent triage router for an internal Site Reliability / Support Engineering team.\n"
                "Your only job is to classify the incoming message into exactly one category.\n\n"
                "Category definitions:\n"
                "  escalation    — An active or suspected P0/P1 production incident that requires "
                "on-call engineer involvement, impact assessment, or immediate escalation. "
                "Examples: alert payloads from Datadog/PagerDuty, messages like 'checkout is down', "
                "'payment gateway error rate spiked', 'users cannot log in'.\n"
                "  query         — A request to look up a runbook, past incident resolution, "
                "or operational knowledge base. Examples: 'how did we fix the Redis OOM last week?', "
                "'show me the runbook for lambda timeouts', 'what causes checkout-service high latency?'.\n"
                "  comms_update  — A request to draft a status update for one or more stakeholder groups "
                "(engineering, customer support, management/executives). Examples: 'write an update for the "
                "exec team', 'draft a customer-facing message about the outage', 'give me the engineer "
                "summary for the bridge'.\n"
                "  postmortem    — The incident has been resolved and the engineer wants a postmortem "
                "document generated from the conversation history. Examples: 'the incident is resolved, "
                "write the postmortem', 'generate post-incident report', 'incident closed, create RCA'.\n"
                "  statistics    — A query about aggregate incident metrics or trends. Examples: "
                "'how many P1s this week?', 'what is our MTTR for checkout incidents?', "
                "'show alert frequency for redis-memory-high'.\n"
                "  other         — Anything not covered above.\n\n"
                "Rules:\n"
                "- Output ONLY the single category name in lowercase. No explanation, no punctuation.\n"
                "- When in doubt between escalation and query, prefer escalation if urgency is implied.\n\n"
                "Examples:\n"
                "  Input: '[PagerDuty] CRITICAL: checkout-service error rate 8.2%'  → escalation\n"
                "  Input: 'what happened last time redis ran out of memory?'         → query\n"
                "  Input: 'write a summary for the VP'                              → comms_update\n"
                "  Input: 'incident resolved, please generate the postmortem'       → postmortem\n"
                "  Input: 'how many P0s did we have last month?'                    → statistics\n"
                "  Input: 'what is the weather today?'                              → other\n\n"
                "Message to classify:\n"
                "{task}"
            )
        )

    async def classify_task(self, task: str) -> str:
        """
        Classify an incoming message.

        Returns one of: 'escalation', 'query', 'comms_update', 'postmortem',
        'statistics', 'other'.
        """
        try:
            result = await self.chain.ainvoke({"task": task})
            category = result.content.strip().lower()
            if category not in self.VALID_CATEGORIES:
                return 'other'
            return category
        except Exception as e:
            print(f"[TaskClassifier] classification failed: {e}")
            return 'other'

    def get_category_description(self, category: str) -> str:
        return self.CATEGORY_DESCRIPTIONS.get(category, 'Unknown category')
