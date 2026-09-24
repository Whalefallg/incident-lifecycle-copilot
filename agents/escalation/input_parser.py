"""
Input parser for the Escalation & On-call Dispatch Agent.

Extracts structured incident information from engineer input:
- severity (P0/P1/P2)
- affected service
- impact scope (user count, regions, revenue impact)
- suspected root cause
- recent changes (deploy, config, traffic spike)
- preferred on-call engineer (if specified)
"""

import json
from typing import Dict, Any, Generator
from langchain_core.prompts import PromptTemplate
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage
from config.domain_knowledge import get_severity_guide


class InputParser:
    """Parses engineer input to extract incident escalation context."""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.prompt = self._create_prompt_template()
        self.chain = self.prompt | self.llm

    def _create_prompt_template(self) -> PromptTemplate:
        from config.time_config import time_config
        current_datetime = time_config.current_datetime_str()
        severity_guide = get_severity_guide()

        return PromptTemplate(
            input_variables=["history", "user_input"],
            template=(
                "You are an incident escalation parser. Extract structured information from engineer input.\n"
                f"Current time: {current_datetime}\n\n"
                f"{severity_guide}\n\n"
                "Context from conversation history:\n{history}\n\n"
                "Engineer input: {user_input}\n\n"
                "CRITICAL: Output ONLY valid JSON. No markdown fences, no explanations, just JSON:\n"
                "{{\n"
                '  "severity": "P0 | P1 | P2 | unknown",\n'
                '  "service": "affected service name (e.g. checkout-service, redis-cache) or unknown",\n'
                '  "impact_scope": "brief description of blast radius: user count, regions, revenue impact. unknown if not specified",\n'
                '  "symptoms": "observed symptoms: error rate, latency, timeout count, etc. unknown if not specified",\n'
                '  "suspected_cause": "engineer hypothesis if mentioned (deploy, config, traffic spike, upstream), otherwise unknown",\n'
                '  "recent_changes": "any mentioned recent changes: deploy hash, config change, time of change. unknown if none",\n'
                '  "oncall_preference": "if engineer specifies a preferred on-call engineer or team (e.g. Alice, platform-sre), otherwise unknown",\n'
                '  "confirmation": "if this is a confirmation response to a previous question (yes/no/ok/proceed), extract it here, otherwise unknown",\n'
                '  "info_complete": "true if severity + service are both not unknown, otherwise false",\n'
                '  "unrelated": "true if input is completely unrelated to incident escalation (e.g. weather, small talk), otherwise false. Confirmation responses are NOT unrelated.",\n'
                '  "missing_info": "list of critical missing fields if info_complete is false, e.g. [severity, service]"\n'
                "}}\n\n"
                "Parsing rules:\n"
                "1. Severity inference: if input mentions customer-facing outage / no workaround → P0; "
                "degraded but functional → P1; capacity warning → P2\n"
                "2. Service name: extract from alert name or engineer description (checkout-service, payment-gateway, etc.)\n"
                "3. Impact: parse user count, revenue loss, affected regions if mentioned\n"
                "4. info_complete = true ONLY if both severity and service are identified (not unknown)\n"
                "5. Confirmation responses (yes/no/proceed) should NOT be marked unrelated\n\n"
                "Output ONLY the JSON object. No other text."
            )
        )

    def parse_stream(self, user_input: str, chat_history: InMemoryChatMessageHistory) -> Generator[str, None, str]:
        """Stream-parse engineer input into structured incident context."""
        chat_history.add_message(HumanMessage(content=user_input))

        history_str = "\n".join(
            [f"Engineer: {m.content}" if m.type == "human" else f"Agent: {m.content}"
             for m in chat_history.messages]
        )

        response_stream = self.chain.stream({"history": history_str, "user_input": user_input})
        ai_content = ""

        for chunk in response_stream:
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            ai_content += token
            yield token

        chat_history.add_message(AIMessage(content=ai_content))
        return ai_content

    def parse_data(self, ai_content: str) -> Dict[str, Any]:
        """Parse LLM JSON output into structured dict."""
        try:
            return json.loads(ai_content)
        except json.JSONDecodeError:
            return {
                "severity": "unknown",
                "service": "unknown",
                "impact_scope": "unknown",
                "symptoms": "unknown",
                "suspected_cause": "unknown",
                "recent_changes": "unknown",
                "oncall_preference": "unknown",
                "confirmation": "unknown",
                "info_complete": False,
                "unrelated": False,
                "missing_info": ["severity", "service", "impact_scope"],
            }
