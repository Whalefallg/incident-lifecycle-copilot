import uuid
import logging
from config.model_provider import create_chat_model
from .consultant import (
    Retriever,
    ConsultationClassifier,
    ResponseGenerator,
    ConsultationProcessor
)

logger = logging.getLogger(__name__)


class ConsultantAgent:
    """
    Runbook & Incident Memory Agent.

    Retrieval is injected as a backend-neutral Retriever. The application,
    not this request-scoped Agent, owns any MCP subprocess lifecycle.
    """

    def __init__(self, session_id=None, retriever: Retriever | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.shared_state = None
        self.unrelated_callback = None

        self.llm = self._initialize_llm()

        if retriever is None:
            from .consultant.retrieval_runtime import get_retriever
            retriever = get_retriever()
        self.retriever = retriever
        self.consultation_classifier = ConsultationClassifier(self.llm)
        self.response_generator = ResponseGenerator(self.llm)
        self.consultation_processor = ConsultationProcessor(
            self.retriever,
            self.consultation_classifier,
            self.response_generator,
        )

    def _initialize_llm(self):
        return create_chat_model(temperature=0.3)

    def set_shared_state(self, shared_state):
        """设置共享状态"""
        self.shared_state = shared_state

    def set_unrelated_callback(self, callback):
        """设置处理非相关任务的回调函数"""
        self.unrelated_callback = callback

    async def consult(self, user_input: str) -> str:
        """
        基础咨询功能

        用于非流式的简单咨询场景
        """
        return await self.consultation_processor.process_consultation(user_input)

    async def consult_stream(self, user_input: str):
        """
        流式输出咨询结果

        这是主要的咨询入口点，协调各个组件完成咨询流程
        """
        # 1. 检查是否与咨询相关
        is_consultation = await self.consultation_classifier.is_consultation_related(user_input)

        if not is_consultation:
            # 2. 处理与咨询无关的请求
            async for token in self.consultation_processor.handle_unrelated_request(
                user_input, self.unrelated_callback, self.shared_state
            ):
                yield token
            return

        # 3. 处理咨询相关的请求
        async for token in self.consultation_processor.process_consultation_stream(
            user_input, self.session_id
        ):
            yield token

        # 4. 重置状态
        self._reset_state_after_consultation()

    def _reset_state_after_consultation(self):
        """咨询完成后重置状态"""
        if self.shared_state:
            from config.constants import StateEnum
            self.shared_state.value = StateEnum.CLASSIFY
