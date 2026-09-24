"""
EscalationAgent 测试

覆盖：
  - 多轮字段收集（必填字段追问）
  - InputParser 字段抽取准确率（Golden Set）
  - awaiting_confirmation 保护机制
  - suspend/resume 快照完整性
  - on-call 字典派单确定性
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# InputParser 字段抽取 Golden Set
# 每条记录：原始告警文本 → 期望抽取的字段值
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_CASES = [
    {
        "id": "EX-001",
        "input": "[PagerDuty] CRITICAL: checkout-service error rate 8.2% | us-east-1 | 03:14 UTC",
        "expected": {"severity": "P0", "service": "checkout-service", "impact_scope": "us-east-1"},
        "info_complete": True,
    },
    {
        "id": "EX-002",
        "input": "checkout P1 error rate spike",
        "expected": {"severity": "P1", "service": "checkout"},
        "info_complete": True,
    },
    {
        "id": "EX-003",
        "input": "redis OOM out of memory",
        "expected": {"service": "redis"},
        "info_complete": False,  # severity missing → should trigger follow-up
    },
    {
        "id": "EX-004",
        "input": "how do I fix this?",
        "expected": {"unrelated": True},
        "info_complete": False,
    },
    {
        "id": "EX-005",
        "input": "P0 payment-gateway timeout affecting all regions",
        "expected": {"severity": "P0", "service": "payment-gateway"},
        "info_complete": True,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. OnCallMatcher — 字典派单确定性
# ─────────────────────────────────────────────────────────────────────────────

class TestOnCallMatcher:

    def test_checkout_service_maps_to_platform_sre(self):
        from agents.escalation.oncall_matcher import OnCallMatcher
        matcher = OnCallMatcher()
        result = matcher.find_oncall_for_incident({"service": "checkout-service"})
        assert result is not None
        assert "team" in result or "primary" in result

    def test_unknown_service_returns_none_not_raises(self):
        from agents.escalation.oncall_matcher import OnCallMatcher
        matcher = OnCallMatcher()
        # Must not raise regardless of whether it returns None or a fallback
        try:
            result = matcher.find_oncall_for_incident({"service": "totally-unknown-xyz-service"})
            assert result is None or isinstance(result, dict)
        except Exception as exc:
            pytest.fail(f"find_oncall_for_incident raised unexpectedly: {exc}")

    def test_same_service_always_returns_same_team(self):
        """Deterministic: same input → same output."""
        from agents.escalation.oncall_matcher import OnCallMatcher
        matcher = OnCallMatcher()
        result_a = matcher.find_oncall_for_incident({"service": "checkout-service"})
        result_b = matcher.find_oncall_for_incident({"service": "checkout-service"})
        assert result_a == result_b

    def test_different_services_return_valid_dicts_or_none(self):
        from agents.escalation.oncall_matcher import OnCallMatcher
        matcher = OnCallMatcher()
        for svc in ["checkout-service", "redis", "payment-gateway"]:
            result = matcher.find_oncall_for_incident({"service": svc})
            assert result is None or isinstance(result, dict)


# ─────────────────────────────────────────────────────────────────────────────
# 2. EscalationAgent — 多轮收集 & 状态行为
# ─────────────────────────────────────────────────────────────────────────────

class TestEscalationAgentMultiTurn:

    def _mock_parse_result(self, severity=None, service=None, complete=False, unrelated=False):
        """Build a fake InputParser parse result dict."""
        import json
        data = {
            "severity": severity, "service": service,
            "impact_scope": None, "symptoms": None,
            "suspected_cause": None, "recent_changes": None,
            "oncall_preference": None, "confirmation": None,
            "info_complete": complete, "unrelated": unrelated,
            "missing_info": [],
        }
        return json.dumps(data), data

    @pytest.mark.asyncio
    async def test_complete_alert_triggers_dispatch_path(self):
        from agents.escalation_agent import EscalationAgent

        _, data = self._mock_parse_result(severity="P0", service="checkout-service", complete=True)

        agent = EscalationAgent()
        agent.input_parser.parse_stream = MagicMock(return_value=iter(['{"severity":"P0"}']*1))
        agent.input_parser.parse_data   = MagicMock(return_value=data)

        with patch.object(agent.incident_processor, "handle_complete_incident",
                          return_value=aiter_str(["[REPLY]on-call dispatched"])):
            tokens = []
            async for tok in agent.run_stream("checkout P0 error"):
                tokens.append(tok)

        assert len(tokens) > 0

    @pytest.mark.asyncio
    async def test_incomplete_alert_triggers_follow_up(self):
        from agents.escalation_agent import EscalationAgent

        _, data = self._mock_parse_result(service="redis", complete=False)

        agent = EscalationAgent()
        agent.input_parser.parse_stream = MagicMock(return_value=iter(['{"service":"redis"}']))
        agent.input_parser.parse_data   = MagicMock(return_value=data)

        with patch.object(agent.incident_processor, "handle_incomplete_info",
                          return_value=aiter_str(["[REPLY]What is the severity?"])):
            tokens = []
            async for tok in agent.run_stream("redis OOM"):
                tokens.append(tok)

        assert len(tokens) > 0

    @pytest.mark.asyncio
    async def test_second_turn_accumulates_context(self):
        from agents.escalation_agent import EscalationAgent
        import json

        agent = EscalationAgent()

        # Turn 1 — service known, severity missing → incomplete, no reset
        data1 = {
            "severity": None, "service": "checkout-service",
            "impact_scope": None, "symptoms": None, "suspected_cause": None,
            "recent_changes": None, "oncall_preference": None, "confirmation": None,
            "info_complete": False, "unrelated": False, "missing_info": ["severity"],
        }
        agent.input_parser.parse_stream = MagicMock(return_value=iter([json.dumps(data1)]))
        agent.input_parser.parse_data   = MagicMock(return_value=data1)

        with patch.object(agent.incident_processor, "handle_incomplete_info",
                          return_value=aiter_str(["[REPLY]severity?"])):
            async for _ in agent.run_stream("checkout error"):
                pass

        # After Turn 1: service should be set, no reset because info_complete=False
        assert agent.incident_history.get("service") == "checkout-service", (
            "Service from Turn 1 should persist after incomplete turn"
        )

    @pytest.mark.asyncio
    async def test_reset_clears_incident_history(self):
        from agents.escalation_agent import EscalationAgent

        agent = EscalationAgent()
        agent.incident_history["severity"] = "P1"
        agent.incident_history["service"]  = "checkout"

        agent.reset()

        for key, val in agent.incident_history.items():
            if key != "awaiting_confirmation":
                assert val is None, f"After reset, {key} should be None, got {val}"


async def aiter_str(items):
    for item in items:
        yield item


# ─────────────────────────────────────────────────────────────────────────────
# 3. awaiting_confirmation 保护机制
# ─────────────────────────────────────────────────────────────────────────────

class TestAwaitingConfirmationGuard:

    def test_awaiting_confirmation_initially_false(self):
        from agents.escalation_agent import EscalationAgent
        agent = EscalationAgent()
        assert not agent.incident_history.get("awaiting_confirmation", False)

    @pytest.mark.asyncio
    async def test_unrelated_input_blocked_when_awaiting_confirmation(self):
        """
        When awaiting_confirmation=True, an unrelated message must NOT
        trigger the suspend/reroute path.
        """
        from agents.escalation_agent import EscalationAgent
        import json

        suspend_called = []

        async def mock_suspend(user_input, snapshot):
            suspend_called.append(user_input)
            return
            yield  # make it an async generator

        agent = EscalationAgent(suspend_callback=mock_suspend)
        agent.incident_history["awaiting_confirmation"] = True

        # Mock parse result: unrelated=True but awaiting_confirmation is set
        data = {
            "severity": None, "service": None, "impact_scope": None,
            "symptoms": None, "suspected_cause": None, "recent_changes": None,
            "oncall_preference": None, "confirmation": "yes",
            "info_complete": False, "unrelated": True, "missing_info": [],
        }
        agent.input_parser.parse_stream = MagicMock(return_value=iter([json.dumps(data)]))
        agent.input_parser.parse_data   = MagicMock(return_value=data)

        with patch.object(agent.incident_processor, "handle_incomplete_info",
                          return_value=aiter_str(["[REPLY]ok"])):
            async for _ in agent.run_stream("ok confirmed"):
                pass

        assert len(suspend_called) == 0, (
            "suspend_callback must not fire when awaiting_confirmation=True"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Suspend / Resume 快照完整性
# ─────────────────────────────────────────────────────────────────────────────

class TestSnapshotIntegrity:

    def test_build_snapshot_captures_all_incident_history_keys(self):
        from agents.escalation_agent import EscalationAgent

        agent = EscalationAgent()
        agent.incident_history["severity"]    = "P1"
        agent.incident_history["service"]     = "checkout-service"
        agent.incident_history["impact_scope"] = "us-east-1"

        snapshot = agent._build_snapshot()

        assert snapshot["severity"]     == "P1"
        assert snapshot["service"]      == "checkout-service"
        assert snapshot["impact_scope"] == "us-east-1"

    def test_build_snapshot_is_a_copy_not_reference(self):
        """Mutating the snapshot must not affect incident_history."""
        from agents.escalation_agent import EscalationAgent

        agent = EscalationAgent()
        agent.incident_history["severity"] = "P1"

        snapshot = agent._build_snapshot()
        snapshot["severity"] = "P0"

        assert agent.incident_history["severity"] == "P1", (
            "_build_snapshot must return a copy, not a reference"
        )

    def test_restore_snapshot_writes_back_all_fields(self):
        from agents.escalation_agent import EscalationAgent

        agent = EscalationAgent()
        snapshot = {
            "severity":    "P0",
            "service":     "payment-gateway",
            "impact_scope": "eu-west-1",
            "symptoms":    "timeout errors",
            "suspected_cause": None,
            "recent_changes":  None,
            "oncall_preference": None,
        }

        agent.restore_snapshot(snapshot)

        assert agent.incident_history["severity"]    == "P0"
        assert agent.incident_history["service"]     == "payment-gateway"
        assert agent.incident_history["impact_scope"] == "eu-west-1"
        assert agent.incident_history["symptoms"]    == "timeout errors"

    def test_restore_snapshot_does_not_add_unknown_keys(self):
        from agents.escalation_agent import EscalationAgent

        agent = EscalationAgent()
        original_keys = set(agent.incident_history.keys())

        agent.restore_snapshot({"severity": "P1", "__unknown_key": "should not appear"})

        assert set(agent.incident_history.keys()) == original_keys

    @pytest.mark.asyncio
    async def test_prompt_resume_stream_yields_non_empty_string(self):
        from agents.escalation_agent import EscalationAgent

        agent = EscalationAgent()
        agent.incident_history["severity"] = "P1"
        agent.incident_history["service"]  = "checkout-service"

        tokens = []
        async for tok in agent.prompt_resume_stream():
            tokens.append(tok)

        result = "".join(tokens)
        assert len(result) > 0
        assert "P1" in result or "checkout" in result, (
            "Resume prompt should mention the incident context"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. 字段抽取准确率 (mocked InputParser)
# ─────────────────────────────────────────────────────────────────────────────

class TestFieldExtractionAccuracy:
    """
    Validate that InputParser.parse_data correctly maps LLM JSON output
    to incident_history fields.

    Uses mocked LLM responses — no live API call required.
    """

    @pytest.mark.parametrize("case", EXTRACTION_CASES, ids=[c["id"] for c in EXTRACTION_CASES])
    def test_parse_data_extracts_expected_fields(self, case):
        from agents.escalation.input_parser import InputParser

        # Simulate what the LLM would return as structured JSON
        mock_llm_json = {
            "severity":        case["expected"].get("severity"),
            "service":         case["expected"].get("service"),
            "impact_scope":    case["expected"].get("impact_scope"),
            "symptoms":        None,
            "suspected_cause": None,
            "recent_changes":  None,
            "oncall_preference": None,
            "unrelated":       case["expected"].get("unrelated", False),
            "info_complete":   case["info_complete"],
        }

        mock_llm = MagicMock()
        parser = InputParser(mock_llm)

        # parse_data receives the raw AI content string and deserialises it
        import json
        parsed = parser.parse_data(json.dumps(mock_llm_json))

        for field, expected_val in case["expected"].items():
            assert parsed.get(field) == expected_val, (
                f"[{case['id']}] field '{field}': expected {expected_val!r}, "
                f"got {parsed.get(field)!r}"
            )
