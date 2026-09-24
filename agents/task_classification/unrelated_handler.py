"""Handle requests outside the incident-response domain."""

from typing import AsyncGenerator
from .state_manager import StateManager


class UnrelatedHandler:
    """Reset the router and guide users back to supported incident workflows."""

    def __init__(self, state_manager: StateManager):
        """
        初始化无关请求处理器

        Args:
            state_manager: 状态管理器
        """
        self.state_manager = state_manager
        self._default_replies = [
            "This request is outside the Incident Lifecycle Copilot scope. I can help triage an incident, find a runbook, draft a stakeholder update, or generate a postmortem.",
            "I support incident-response workflows. Paste an alert or ask for a runbook, status update, or postmortem.",
            "I cannot complete that request, but I can help investigate and coordinate an active production incident.",
        ]
        self._reply_index = 0

    async def handle_unrelated_sync(self, user_input: str) -> str:
        """
        同步处理无关请求（返回字符串）

        Args:
            user_input: 用户输入内容

        Returns:
            str: 处理结果
        """
        print("归类机器人接管处理 unrelated user_input")

        # 重置状态为分类状态，准备处理下一个输入
        self.state_manager.reset_to_classify()

        # 返回友好的拒绝回复
        return self._get_next_reply()

    async def handle_unrelated_async(self, user_input: str) -> AsyncGenerator[str, None]:
        """
        异步处理无关请求（返回流式响应）

        Args:
            user_input: 用户输入内容

        Yields:
            str: 流式响应内容
        """
        print("归类机器人接管处理 unrelated user_input (async stream)")

        # 重置状态为分类状态
        self.state_manager.reset_to_classify()

        # 生成流式回复
        reply = self._get_next_reply()
        yield "[REPLY][归类机器人]"
        for char in reply:
            yield char

    def _get_next_reply(self) -> str:
        """获取下一个回复内容（轮换使用不同回复）"""
        reply = self._default_replies[self._reply_index]
        self._reply_index = (self._reply_index + 1) % len(self._default_replies)
        return reply

    def add_custom_reply(self, reply: str) -> None:
        """添加自定义回复"""
        if reply and reply not in self._default_replies:
            self._default_replies.append(reply)

    def set_business_context(self, service_name: str = "incident response") -> None:
        """Customize the domain name used by the fallback replies."""
        self._default_replies = [
            f"This request is outside {service_name}. I can help triage incidents, retrieve runbooks, draft updates, or generate postmortems.",
            f"I specialize in {service_name}. Paste an alert or ask for incident-response guidance.",
            f"I cannot complete that request, but I can assist with {service_name} workflows.",
        ]

    def get_available_replies(self) -> list:
        """获取所有可用的回复模板"""
        return self._default_replies.copy()

    def reset_reply_rotation(self) -> None:
        """重置回复轮换索引"""
        self._reply_index = 0
