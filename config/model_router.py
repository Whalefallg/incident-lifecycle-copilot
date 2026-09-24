"""
模型分层路由策略

根据任务复杂度自动选择成本最优的 LLM 模型：
- SIMPLE: GPT-3.5-turbo / Claude Haiku
- MEDIUM: GPT-4o-mini / Claude Sonnet
- COMPLEX: GPT-4 / Claude Opus
"""

import os
import logging
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """任务复杂度枚举"""
    SIMPLE = "simple"      # 分类、是否判断、简单提取
    MEDIUM = "medium"      # RAG查询、模板填充、结构化输出
    COMPLEX = "complex"    # RCA分析、Postmortem生成、复杂推理


class ModelProvider(Enum):
    """模型提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass
class ModelConfig:
    """模型配置"""
    name: str
    cost_per_1k_tokens: float  # 输入+输出平均成本（美元）
    context_window: int


class ModelRouter:
    """模型路由器 - 根据任务复杂度选择最优模型"""

    # OpenAI 模型配置
    OPENAI_MODELS = {
        TaskComplexity.SIMPLE: ModelConfig("gpt-3.5-turbo", 0.0015, 16385),
        TaskComplexity.MEDIUM: ModelConfig("gpt-4o-mini", 0.0003, 128000),
        TaskComplexity.COMPLEX: ModelConfig("gpt-4", 0.03, 8192),
    }

    # Anthropic 模型配置
    ANTHROPIC_MODELS = {
        TaskComplexity.SIMPLE: ModelConfig("claude-3-haiku-20240307", 0.00125, 200000),
        TaskComplexity.MEDIUM: ModelConfig("claude-3-5-sonnet-20241022", 0.003, 200000),
        TaskComplexity.COMPLEX: ModelConfig("claude-3-opus-20240229", 0.015, 200000),
    }

    def __init__(
        self,
        provider: Optional[ModelProvider] = None,
        enabled: Optional[bool] = None,
    ):
        self.enabled = enabled if enabled is not None else os.getenv("MODEL_ROUTING_ENABLED", "true").lower() == "true"

        provider_str = provider.value if provider else os.getenv("MODEL_PROVIDER", "openai").lower()
        self._configured_provider = provider_str
        try:
            self.provider = ModelProvider(provider_str)
        except ValueError:
            # Generic OpenAI-compatible providers use their configured model;
            # tier routing is only meaningful for the two explicit catalogs.
            self.provider = ModelProvider.OPENAI
            self.enabled = False
            logger.warning(
                "Model routing disabled for OpenAI-compatible provider %s",
                provider_str,
            )

        self.models = self.OPENAI_MODELS if self.provider == ModelProvider.OPENAI else self.ANTHROPIC_MODELS

        # 统计信息
        self._stats = {
            "complexity_distribution": {
                "simple": 0,
                "medium": 0,
                "complex": 0,
                "total": 0,
            },
            "cost_tracking": {
                "actual_cost_usd": 0.0,
                "baseline_cost_usd": 0.0,  # 如果全部使用最贵模型
            }
        }

        if self.enabled:
            logger.info(f"✅ Model Routing enabled (provider={self.provider.value})")
        else:
            logger.info("⚠️  Model Routing disabled, using default model")

    def get_model(self, complexity: TaskComplexity) -> str:
        """根据复杂度获取模型名称"""
        if not self.enabled:
            # 禁用时返回默认最强模型
            return self.models[TaskComplexity.COMPLEX].name

        model_config = self.models[complexity]

        # 更新统计
        self._stats["complexity_distribution"][complexity.value] += 1
        self._stats["complexity_distribution"]["total"] += 1

        logger.debug(f"📍 Routing: {complexity.value} -> {model_config.name}")
        return model_config.name

    def get_model_config(self, complexity: TaskComplexity) -> ModelConfig:
        """获取模型配置"""
        return self.models[complexity]

    def route(
        self,
        task_name: str,
        temperature: float = 0,
        complexity: Optional[TaskComplexity] = None,
    ):
        """Create a LangChain chat model for the selected complexity tier."""
        complexity = complexity or classify_task_complexity(task_name)

        if self._configured_provider not in {provider.value for provider in ModelProvider}:
            from langchain_openai import ChatOpenAI
            from pydantic import SecretStr

            return ChatOpenAI(
                model=os.getenv("LLM_MODEL", "qwen-plus"),
                api_key=SecretStr(os.getenv("LLM_API_KEY", "")),
                base_url=os.getenv("LLM_BASE_URL") or None,
                temperature=temperature,
            )

        model_name = self.get_model(complexity)
        if self.provider == ModelProvider.OPENAI:
            from langchain_openai import ChatOpenAI
            from pydantic import SecretStr

            return ChatOpenAI(
                model=model_name,
                api_key=SecretStr(
                    os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY", "")
                ),
                base_url=os.getenv("LLM_BASE_URL") or None,
                temperature=temperature,
            )

        from langchain_anthropic import ChatAnthropic
        from pydantic import SecretStr

        return ChatAnthropic(
            model=model_name,
            api_key=SecretStr(os.getenv("ANTHROPIC_API_KEY", "")),
            temperature=temperature,
        )

    def record_usage(self, complexity: TaskComplexity, tokens: int):
        """记录使用量并计算成本"""
        model_config = self.models[complexity]
        actual_cost = (tokens / 1000) * model_config.cost_per_1k_tokens

        # 计算如果使用最贵模型的成本
        baseline_model = self.models[TaskComplexity.COMPLEX]
        baseline_cost = (tokens / 1000) * baseline_model.cost_per_1k_tokens

        self._stats["cost_tracking"]["actual_cost_usd"] += actual_cost
        self._stats["cost_tracking"]["baseline_cost_usd"] += baseline_cost

        logger.debug(
            f"💰 Cost: ${actual_cost:.4f} (baseline: ${baseline_cost:.4f})"
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        cost_stats = self._stats["cost_tracking"]
        actual = cost_stats["actual_cost_usd"]
        baseline = cost_stats["baseline_cost_usd"]

        savings = baseline - actual
        savings_percent = (savings / baseline * 100) if baseline > 0 else 0.0

        return {
            "enabled": self.enabled,
            "provider": self.provider.value,
            "complexity_distribution": self._stats["complexity_distribution"],
            "cost_savings": {
                "actual_cost_usd": round(actual, 4),
                "baseline_cost_usd": round(baseline, 4),
                "savings_usd": round(savings, 4),
                "savings_percent": round(savings_percent, 2),
            }
        }


def classify_task_complexity(query: str) -> TaskComplexity:
    """
    自动分类任务复杂度

    规则（可扩展为 LLM 分类器）：
    - SIMPLE: 包含 "is", "classify", "yes/no", "extract" 等关键词
    - COMPLEX: 包含 "postmortem", "root cause", "analyze", "generate detailed" 等
    - MEDIUM: 其他情况
    """
    query_lower = query.lower()

    # SIMPLE 模式
    simple_keywords = [
        "is this", "classify", "yes or no", "true or false",
        "severity level", "extract", "parse", "simple",
    ]

    # COMPLEX 模式
    complex_keywords = [
        "postmortem", "root cause", "rca", "detailed analysis",
        "generate report", "comprehensive", "investigate",
        "timeline", "incident report",
    ]

    # MEDIUM 模式
    medium_keywords = [
        "runbook", "find relevant", "search", "lookup",
        "template", "format", "structure",
    ]

    if any(keyword in query_lower for keyword in complex_keywords):
        return TaskComplexity.COMPLEX

    if any(keyword in query_lower for keyword in simple_keywords):
        return TaskComplexity.SIMPLE

    if any(keyword in query_lower for keyword in medium_keywords):
        return TaskComplexity.MEDIUM

    # 默认 MEDIUM
    return TaskComplexity.MEDIUM


# 全局实例
model_router = ModelRouter()
