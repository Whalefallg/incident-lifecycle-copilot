from dotenv import load_dotenv
import os
from conversation.models import ConversationSnapshot
from config.model_provider import create_chat_model
from config.constants import SharedState, StateEnum
from .task_classification import (
    TaskClassifier,
    StateManager,
    AgentRouter,
    UnrelatedHandler,
    ClassificationProcessor
)

load_dotenv()


class TaskClassificationAgent:
    """
    Triage Router — the top-level orchestrator for the Incident Lifecycle Copilot.

    Routes incoming alerts and engineer messages to the appropriate specialist agent:
    - EscalationAgent (EscalationAgent) for P0/P1 incidents
    - RunbookAgent (ConsultantAgent) for knowledge lookups
    - CommunicationAgent for stakeholder updates
    - PostmortemAgent for post-incident report generation

    The request coordinator owns persistence; this object is disposable.
    """

    def __init__(
        self,
        escalation_agent,
        consultant_agent,
        communication_agent=None,
        postmortem_agent=None,
        session_id=None,
    ):
        self.escalation_agent = escalation_agent
        self.consultant_agent = consultant_agent
        self.communication_agent = communication_agent
        self.postmortem_agent = postmortem_agent
        self.session_id = session_id

        self.llm = self._initialize_llm()

        self.state_manager = StateManager(SharedState(), session_id=session_id)
        self.task_classifier = TaskClassifier(self.llm)
        self.agent_router = AgentRouter(
            escalation_agent,
            consultant_agent,
            self.state_manager,
            communication_agent=communication_agent,
            postmortem_agent=postmortem_agent,
        )
        self.unrelated_handler = UnrelatedHandler(self.state_manager)
        self.classification_processor = ClassificationProcessor(
            self.task_classifier,
            self.state_manager,
            self.agent_router,
            self.unrelated_handler,
        )

        self._setup_callbacks()
        self.agent_router.set_task_classifier(self.task_classifier)
        self.state = self.state_manager.state


    def _initialize_llm(self):
        routing_enabled = os.getenv("MODEL_ROUTING_ENABLED", "false").lower() == "true"

        if routing_enabled:
            try:
                from config.model_router import model_router, TaskComplexity
                return model_router.route(
                    task_name="classify",
                    temperature=0,
                    complexity=TaskComplexity.SIMPLE
                )
            except Exception:
                pass

        return create_chat_model(temperature=0)

    def _setup_callbacks(self):
        if self.escalation_agent and hasattr(self.escalation_agent, 'unrelated_callback'):
            self.escalation_agent.unrelated_callback = self.handle_unrelated

        if self.escalation_agent and hasattr(self.escalation_agent, 'suspend_callback'):
            self.escalation_agent.suspend_callback = self._handle_suspend

        if self.consultant_agent and hasattr(self.consultant_agent, 'set_unrelated_callback'):
            self.consultant_agent.set_unrelated_callback(self.handle_unrelated_async)

    async def _handle_suspend(self, user_input: str, snapshot: dict):
        """
        suspend_callback injected into EscalationAgent.

        Tells StateManager to push current state + snapshot onto the suspend
        stack, then routes the inserted task.  ClassificationProcessor will
        auto-resume after the inserted task yields its last token.
        """
        suspended = self.state_manager.suspend_current(snapshot)
        if not suspended:
            # Stack full — fall back to legacy discard-and-reroute
            async for token in self.classification_processor.process_task_stream(user_input):
                yield token
            return

        async for token in self.classification_processor.process_task_stream(user_input):
            yield token

    async def classify_task(self, task):
        return await self.classification_processor.process_task_sync(task)

    async def classify_task_stream(self, task):
        async for token in self.classification_processor.process_task_stream(task):
            yield token

    def hydrate(self, snapshot: ConversationSnapshot) -> None:
        self.state_manager.hydrate(snapshot)

    def apply_to_snapshot(self, snapshot: ConversationSnapshot) -> None:
        self.state_manager.apply_to_snapshot(snapshot)

    async def handle_unrelated(self, user_input):
        result = ""
        async for token in self.classification_processor.process_task_stream(user_input):
            result += token
        return result

    async def handle_unrelated_async(self, user_input):
        async for token in self.classification_processor.process_task_stream(user_input):
            yield token

    def get_classification_info(self):
        return self.classification_processor.get_current_state_info()

    def reset_conversation(self):
        self.classification_processor.reset_conversation()

    def set_business_context(self, service_name: str = "incident-ops"):
        self.unrelated_handler.set_business_context(service_name)
