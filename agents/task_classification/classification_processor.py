"""
Classification processor — orchestrates the full triage → routing → agent dispatch flow.

Flow:
    1. Determine if we need to classify (CLASSIFY state) or continue an active flow
    2. If classifying: invoke TaskClassifier LLM
    3. Route to the appropriate specialist agent based on category
    4. Handle errors and state resets
"""

from typing import AsyncGenerator
from config.request_trace import trace_step
from .task_classifier import TaskClassifier
from .state_manager import StateManager
from .agent_router import AgentRouter
from .unrelated_handler import UnrelatedHandler


class ClassificationProcessor:
    """Orchestrates the full incident triage and routing pipeline."""

    def __init__(
        self,
        task_classifier: TaskClassifier,
        state_manager: StateManager,
        agent_router: AgentRouter,
        unrelated_handler: UnrelatedHandler,
    ):
        self.task_classifier = task_classifier
        self.state_manager = state_manager
        self.agent_router = agent_router
        self.unrelated_handler = unrelated_handler

    async def process_task_stream(self, task: str) -> AsyncGenerator[str, None]:
        """
        Main streaming entry point for incident triage and routing.

        Args:
            task: User input (alert payload, engineer message, etc.)

        Yields:
            Streaming response tokens from the appropriate agent.
        """
        try:
            if self.state_manager.should_classify():
                with trace_step("intent_classification", agent="TriageRouter"):
                    category = await self.task_classifier.classify_task(task)

                if category == "escalation":
                    async for token in self.agent_router.route_to_escalation(task):
                        yield token

                elif category == "query":
                    async for token in self.agent_router.route_to_runbook(task):
                        yield token

                elif category == "comms_update":
                    async for token in self.agent_router.route_to_comms(task):
                        yield token

                elif category == "postmortem":
                    async for token in self.agent_router.route_to_postmortem(task):
                        yield token

                elif category == "statistics":
                    yield "[REPLY][Triage Router] Incident metrics queries are not yet implemented. Coming soon."

                else:
                    async for token in self.agent_router.handle_unsupported_task(category):
                        yield token

                # After any inserted task completes, check if there is a
                # suspended frame waiting to be resumed.
                if self.state_manager.has_suspended_context():
                    frame = self.state_manager.resume_suspended()
                    if frame:
                        yield (
                            f"[THOUGHT][Triage Router] Inserted task complete — "
                            f"resuming your {frame.state.value} flow."
                        )
                        if (
                            frame.state.value == "escalation"
                            and frame.agent_snapshot
                            and hasattr(self.agent_router.escalation_agent, "restore_snapshot")
                        ):
                            self.agent_router.escalation_agent.restore_snapshot(
                                frame.agent_snapshot
                            )
                        if (
                            frame.state.value == "escalation"
                            and hasattr(self.agent_router.escalation_agent, "prompt_resume_stream")
                        ):
                            async for token in self.agent_router.escalation_agent.prompt_resume_stream():
                                yield token

            else:
                # Active multi-turn flow — continue in current state
                async for token in self.agent_router.route_by_state(task):
                    yield token

        except Exception as e:
            yield f"[ERROR] Triage pipeline failed: {e}"
            self.state_manager.force_reset()

    async def process_task_sync(self, task: str) -> str:
        """
        Synchronous (non-streaming) processing — used for testing or simple calls.

        Returns:
            Complete response string.
        """
        try:
            if self.state_manager.should_classify():
                category = await self.task_classifier.classify_task(task)

                if category == "escalation" and self.agent_router.escalation_agent:
                    self.state_manager.transition_to_escalation()
                    return await self.agent_router.escalation_agent.run(user_input=task)

                elif category == "query" and self.agent_router.consultant_agent:
                    self.state_manager.transition_to_runbook_lookup()
                    async with self.agent_router.consultant_agent as agent:
                        return await agent.consult(task)

                elif category == "comms_update":
                    return "Communication agent not yet implemented in sync mode."

                elif category == "postmortem":
                    return "Postmortem agent not yet implemented in sync mode."

                elif category == "statistics":
                    return "Incident metrics queries not yet implemented."

                else:
                    return (
                        "This request is outside the scope of the Incident Lifecycle Copilot. "
                        "I can help with: incident escalation, runbook lookups, status updates, "
                        "postmortem generation, and incident metrics."
                    )

            else:
                # Continue active flow
                if self.state_manager.is_in_escalation_flow():
                    return await self.agent_router.escalation_agent.run(user_input=task)
                elif self.state_manager.is_in_runbook_flow():
                    async with self.agent_router.consultant_agent as agent:
                        return await agent.consult(task)
                else:
                    return "Multi-turn flow in sync mode not fully supported yet."

        except Exception as e:
            self.state_manager.force_reset()
            return f"[ERROR] {e}"

    def get_current_state_info(self) -> dict:
        return {
            'current_state': self.state_manager.get_current_state(),
            'state_description': self.state_manager.get_state_description(),
            'available_services': self.agent_router.get_available_services(),
            'can_classify': self.state_manager.should_classify(),
        }

    def reset_conversation(self) -> None:
        self.state_manager.force_reset()
        self.unrelated_handler.reset_reply_rotation()

    async def handle_unrelated_request(self, user_input: str, async_mode: bool = True):
        if async_mode:
            async for token in self.unrelated_handler.handle_unrelated_async(user_input):
                yield token
        else:
            result = await self.unrelated_handler.handle_unrelated_sync(user_input)
            yield result
