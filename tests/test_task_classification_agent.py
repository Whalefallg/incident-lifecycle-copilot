"""
TaskClassificationAgent / StateManager 测试

覆盖：
  - 意图分类准确率（Golden Set，mocked LLM）
  - 状态机转换规则
  - 多轮续话不重复分类
  - suspend / resume 全链路
  - 确认态保护
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# 意图分类 Golden Set
# ─────────────────────────────────────────────────────────────────────────────

INTENT_CASES = [
    # (id, input_text, expected_category)
    ("IC-001", "[PagerDuty] CRITICAL: checkout-service error rate 8.2%", "escalation"),
    ("IC-002", "P0 redis OOM out of memory us-east-1",                    "escalation"),
    ("IC-003", "how do I fix checkout circuit breaker",                   "query"),
    ("IC-004", "what does the redis OOM runbook say",                     "query"),
    ("IC-005", "write a status update for the exec team",                 "comms_update"),
    ("IC-006", "draft an engineering status update",                      "comms_update"),
    ("IC-007", "incident resolved generate postmortem",                   "postmortem"),
    ("IC-008", "create the post-incident review",                         "postmortem"),
    ("IC-009", "what's the weather today",                                "other"),
    ("IC-010", "book me a restaurant",                                    "other"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. StateManager 单元测试
# ─────────────────────────────────────────────────────────────────────────────

class TestStateManager:

    def _make_manager(self):
        from agents.task_classification.state_manager import StateManager
        return StateManager()

    def test_initial_state_is_classify(self):
        from config.constants import StateEnum
        sm = self._make_manager()
        assert sm.get_current_state() == StateEnum.CLASSIFY

    def test_should_classify_true_initially(self):
        sm = self._make_manager()
        assert sm.should_classify() is True

    def test_transition_to_escalation(self):
        from config.constants import StateEnum
        sm = self._make_manager()
        sm.transition_to_escalation()
        assert sm.get_current_state() == StateEnum.ESCALATION
        assert sm.should_classify() is False

    def test_transition_to_runbook_lookup(self):
        from config.constants import StateEnum
        sm = self._make_manager()
        sm.transition_to_runbook_lookup()
        assert sm.get_current_state() == StateEnum.RUNBOOK_LOOKUP

    def test_reset_to_classify(self):
        from config.constants import StateEnum
        sm = self._make_manager()
        sm.transition_to_escalation()
        sm.reset_to_classify()
        assert sm.get_current_state() == StateEnum.CLASSIFY

    def test_force_reset_clears_suspend_stack(self):
        sm = self._make_manager()
        sm.transition_to_escalation()
        sm.suspend_current({"severity": "P1"})
        assert sm.has_suspended_context() is True

        sm.force_reset()
        assert sm.has_suspended_context() is False
        assert sm.should_classify() is True

    # ── Suspend / Resume ──────────────────────────────────────────────────

    def test_suspend_current_pushes_frame_and_resets_to_classify(self):
        from config.constants import StateEnum
        sm = self._make_manager()
        sm.transition_to_escalation()

        result = sm.suspend_current({"severity": "P1", "service": "checkout"})

        assert result is True
        assert sm.has_suspended_context() is True
        assert sm.get_current_state() == StateEnum.CLASSIFY

    def test_resume_suspended_restores_state(self):
        from config.constants import StateEnum
        sm = self._make_manager()
        sm.transition_to_escalation()
        sm.suspend_current({"severity": "P1"})

        frame = sm.resume_suspended()

        assert frame is not None
        assert frame.state == StateEnum.ESCALATION
        assert frame.agent_snapshot["severity"] == "P1"
        assert sm.get_current_state() == StateEnum.ESCALATION
        assert sm.has_suspended_context() is False

    def test_resume_returns_none_when_stack_empty(self):
        sm = self._make_manager()
        frame = sm.resume_suspended()
        assert frame is None

    def test_peek_does_not_pop(self):
        sm = self._make_manager()
        sm.transition_to_escalation()
        sm.suspend_current({"key": "val"})

        peek1 = sm.peek_suspended()
        peek2 = sm.peek_suspended()

        assert peek1 is peek2
        assert sm.has_suspended_context() is True

    def test_suspend_stack_max_depth_respected(self):
        from agents.task_classification.state_manager import MAX_SUSPEND_DEPTH
        sm = self._make_manager()

        for i in range(MAX_SUSPEND_DEPTH):
            sm.transition_to_escalation()
            sm.suspend_current({"depth": i})

        # One more push should be rejected
        sm.transition_to_escalation()
        result = sm.suspend_current({"depth": MAX_SUSPEND_DEPTH})
        assert result is False

    def test_clear_suspend_stack(self):
        sm = self._make_manager()
        sm.transition_to_escalation()
        sm.suspend_current({})
        sm.clear_suspend_stack()
        assert sm.has_suspended_context() is False

    def test_snapshot_contents_preserved_in_frame(self):
        sm = self._make_manager()
        sm.transition_to_escalation()
        snapshot = {"severity": "P0", "service": "payment-gateway", "impact_scope": "eu-west-1"}
        sm.suspend_current(snapshot)

        frame = sm.resume_suspended()
        assert frame.agent_snapshot == snapshot


# ─────────────────────────────────────────────────────────────────────────────
# 2. TaskClassifier 意图分类准确率（mocked LLM）
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskClassifierAccuracy:
    """
    Validates classification logic with a mocked LLM that returns
    the expected category.  Does not make real API calls.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case_id,text,expected", INTENT_CASES)
    async def test_classify_returns_expected_category(self, case_id, text, expected):
        from agents.task_classification.task_classifier import TaskClassifier

        mock_llm = MagicMock()
        classifier = TaskClassifier(mock_llm)
        classifier.chain = AsyncMock()
        classifier.chain.ainvoke = AsyncMock(return_value=MagicMock(content=expected))

        result = await classifier.classify_task(text)

        assert result == expected, (
            f"[{case_id}] input={text!r}: expected {expected!r}, got {result!r}"
        )

    @pytest.mark.asyncio
    async def test_classify_strips_whitespace_and_lowercases(self):
        from agents.task_classification.task_classifier import TaskClassifier

        mock_llm = MagicMock()
        classifier = TaskClassifier(mock_llm)
        classifier.chain = AsyncMock()
        classifier.chain.ainvoke = AsyncMock(return_value=MagicMock(content="  Escalation\n"))

        result = await classifier.classify_task("P0 checkout down")
        assert result == "escalation"

    @pytest.mark.asyncio
    async def test_classify_handles_unexpected_llm_output(self):
        """Unknown category should pass through without raising."""
        from agents.task_classification.task_classifier import TaskClassifier

        mock_llm = MagicMock()
        classifier = TaskClassifier(mock_llm)
        classifier.chain = AsyncMock()
        classifier.chain.ainvoke = AsyncMock(return_value=MagicMock(content="statistics"))

        result = await classifier.classify_task("show me incident metrics")
        assert isinstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# 3. ClassificationProcessor — 状态机路由逻辑
# ─────────────────────────────────────────────────────────────────────────────

class TestClassificationProcessor:

    def _make_processor(self, classify_return="query"):
        from agents.task_classification.state_manager import StateManager
        from agents.task_classification.agent_router import AgentRouter
        from agents.task_classification.task_classifier import TaskClassifier
        from agents.task_classification.unrelated_handler import UnrelatedHandler
        from agents.task_classification.classification_processor import ClassificationProcessor

        mock_classifier = AsyncMock()
        mock_classifier.classify_task = AsyncMock(return_value=classify_return)

        state_manager = StateManager()

        mock_router = MagicMock()
        mock_router.route_to_escalation = MagicMock(side_effect=lambda _: aiter(["[THOUGHT]routing"]))
        mock_router.route_to_runbook    = MagicMock(side_effect=lambda _: aiter(["[REPLY]runbook answer"]))
        mock_router.route_to_comms      = MagicMock(side_effect=lambda _: aiter(["[REPLY]comms draft"]))
        mock_router.route_to_postmortem = MagicMock(side_effect=lambda _: aiter(["[REPLY]postmortem"]))
        mock_router.route_by_state      = MagicMock(side_effect=lambda _: aiter(["[REPLY]continued"]))
        mock_router.handle_unsupported_task = MagicMock(side_effect=lambda _: aiter(["[REPLY]unsupported"]))

        unrelated_handler = UnrelatedHandler(state_manager)

        processor = ClassificationProcessor(
            mock_classifier, state_manager, mock_router, unrelated_handler
        )
        return processor, state_manager, mock_classifier, mock_router

    @pytest.mark.asyncio
    async def test_classify_state_calls_classifier(self):
        processor, sm, classifier, _ = self._make_processor("query")
        tokens = []
        async for tok in processor.process_task_stream("redis OOM fix"):
            tokens.append(tok)
        classifier.classify_task.assert_called_once_with("redis OOM fix")

    @pytest.mark.asyncio
    async def test_non_classify_state_skips_classifier(self):
        from config.constants import StateEnum
        processor, sm, classifier, router = self._make_processor()

        sm.set_state(StateEnum.ESCALATION)

        async def fake_route_by_state(task):
            yield "[REPLY]continued"

        router.route_by_state = fake_route_by_state

        tokens = []
        async for tok in processor.process_task_stream("P1"):
            tokens.append(tok)

        classifier.classify_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_fires_after_inserted_task_completes(self):
        """
        When suspend stack is non-empty after a CLASSIFY-state task,
        ClassificationProcessor must call resume_suspended() and
        restore_snapshot() on the EscalationAgent.
        """
        from config.constants import StateEnum
        from agents.task_classification.state_manager import StateManager
        from agents.task_classification.task_classifier import TaskClassifier
        from agents.task_classification.agent_router import AgentRouter
        from agents.task_classification.unrelated_handler import UnrelatedHandler
        from agents.task_classification.classification_processor import ClassificationProcessor

        sm = StateManager()

        # Pre-load a suspended ESCALATION frame
        sm.transition_to_escalation()
        sm.suspend_current({"severity": "P1", "service": "checkout-service"})
        # State is now CLASSIFY with a pending frame

        mock_classifier = AsyncMock()
        mock_classifier.classify_task = AsyncMock(return_value="query")

        mock_escalation_agent = MagicMock()
        mock_escalation_agent.restore_snapshot = MagicMock()

        async def fake_prompt_resume():
            yield "[REPLY]resuming P1/checkout"

        mock_escalation_agent.prompt_resume_stream = fake_prompt_resume

        mock_router = MagicMock()
        mock_router.escalation_agent = mock_escalation_agent

        async def fake_runbook(task):
            yield "[REPLY]runbook answer"

        mock_router.route_to_runbook = fake_runbook

        unrelated_handler = UnrelatedHandler(sm)
        processor = ClassificationProcessor(mock_classifier, sm, mock_router, unrelated_handler)

        tokens = []
        async for tok in processor.process_task_stream("redis OOM runbook"):
            tokens.append(tok)

        full = "".join(tokens)

        # State should be restored to ESCALATION
        assert sm.get_current_state() == StateEnum.ESCALATION
        # Snapshot should have been restored
        mock_escalation_agent.restore_snapshot.assert_called_once_with(
            {"severity": "P1", "service": "checkout-service"}
        )
        # Resume prompt should appear in output
        assert "resuming" in full.lower() or "P1" in full


# ─────────────────────────────────────────────────────────────────────────────
# 4. End-to-end intent routing (mocked agents)
# ─────────────────────────────────────────────────────────────────────────────

class TestEndToEndRouting:

    def _make_agent(self, classify_return: str):
        """Build a TaskClassificationAgent with mocked sub-agents and LLM."""
        from agents.task_classification_agent import TaskClassificationAgent

        mock_escalation = MagicMock()
        mock_escalation.run_stream = AsyncMock(return_value=aiter(["[REPLY]escalation"]))
        mock_escalation.unrelated_callback = None
        mock_escalation.suspend_callback   = None
        mock_escalation.set_shared_state   = MagicMock()

        mock_consultant = MagicMock()
        mock_consultant.__aenter__ = AsyncMock(return_value=mock_consultant)
        mock_consultant.__aexit__  = AsyncMock(return_value=False)
        mock_consultant.consult_stream = AsyncMock(return_value=aiter(["[REPLY]runbook"]))
        mock_consultant.set_unrelated_callback = MagicMock()

        agent = TaskClassificationAgent(mock_escalation, mock_consultant)

        # Override the internal LLM classifier
        agent.task_classifier.classify_task = AsyncMock(return_value=classify_return)
        return agent, mock_escalation, mock_consultant

    @pytest.mark.asyncio
    async def test_escalation_intent_routes_to_escalation_agent(self):
        agent, mock_escalation, _ = self._make_agent("escalation")

        async def fake_run_stream(user_input):
            yield "[REPLY]escalation dispatched"

        mock_escalation.run_stream = fake_run_stream

        tokens = []
        async for tok in agent.classify_task_stream("P0 checkout down"):
            tokens.append(tok)

        assert len(tokens) > 0

    @pytest.mark.asyncio
    async def test_other_intent_returns_unsupported_message(self):
        agent, _, _ = self._make_agent("other")
        tokens = []
        async for tok in agent.classify_task_stream("what's the weather"):
            tokens.append(tok)
        response = "".join(tokens)
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_reset_conversation_resets_state(self):
        from config.constants import StateEnum
        agent, _, _ = self._make_agent("escalation")
        agent.state_manager.transition_to_escalation()
        agent.reset_conversation()
        assert agent.state_manager.get_current_state() == StateEnum.CLASSIFY


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

async def aiter(items):
    for item in items:
        yield item
