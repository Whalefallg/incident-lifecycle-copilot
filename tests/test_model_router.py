"""
测试 Model Router 功能
"""

import pytest
from config.model_router import (
    ModelRouter,
    TaskComplexity,
    ModelProvider,
    classify_task_complexity,
)


def test_model_routing_openai():
    """测试 OpenAI 模型路由"""
    router = ModelRouter(provider=ModelProvider.OPENAI, enabled=True)

    simple_model = router.get_model(TaskComplexity.SIMPLE)
    assert simple_model == "gpt-3.5-turbo"

    medium_model = router.get_model(TaskComplexity.MEDIUM)
    assert medium_model == "gpt-4o-mini"

    complex_model = router.get_model(TaskComplexity.COMPLEX)
    assert complex_model == "gpt-4"


def test_model_routing_anthropic():
    """测试 Anthropic 模型路由"""
    router = ModelRouter(provider=ModelProvider.ANTHROPIC, enabled=True)

    simple_model = router.get_model(TaskComplexity.SIMPLE)
    assert "haiku" in simple_model

    medium_model = router.get_model(TaskComplexity.MEDIUM)
    assert "sonnet" in medium_model

    complex_model = router.get_model(TaskComplexity.COMPLEX)
    assert "opus" in complex_model


def test_task_complexity_classification():
    """测试任务复杂度分类"""

    simple_query = "Is this a P0 incident?"
    assert classify_task_complexity(simple_query) == TaskComplexity.SIMPLE

    complex_query = "Generate a detailed postmortem with root cause analysis"
    assert classify_task_complexity(complex_query) == TaskComplexity.COMPLEX

    medium_query = "Find relevant runbooks for this alert"
    assert classify_task_complexity(medium_query) == TaskComplexity.MEDIUM


def test_router_stats():
    """测试路由统计"""
    router = ModelRouter(enabled=True)

    router.get_model(TaskComplexity.SIMPLE)
    router.get_model(TaskComplexity.SIMPLE)
    router.get_model(TaskComplexity.COMPLEX)

    stats = router.get_stats()

    assert stats["enabled"] is True
    assert stats["complexity_distribution"]["simple"] == 2
    assert stats["complexity_distribution"]["complex"] == 1
    assert stats["complexity_distribution"]["total"] == 3


def test_cost_tracking():
    """测试成本追踪"""
    router = ModelRouter(enabled=True)

    router.record_usage(TaskComplexity.SIMPLE, tokens=1000)
    router.record_usage(TaskComplexity.COMPLEX, tokens=1000)

    stats = router.get_stats()
    cost_stats = stats["cost_savings"]

    assert cost_stats["actual_cost_usd"] >= 0
    assert cost_stats["baseline_cost_usd"] >= 0
    assert cost_stats["savings_usd"] >= 0


def test_disabled_router():
    """测试禁用路由时的行为"""
    router = ModelRouter(enabled=False)

    model = router.get_model(TaskComplexity.SIMPLE)
    # 应该返回默认模型
    assert model in ["gpt-4", "claude-3-5-sonnet-20241022"]
