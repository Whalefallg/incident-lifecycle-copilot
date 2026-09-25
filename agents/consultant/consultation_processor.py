"""
咨询流程处理器

负责协调整个咨询流程
"""

from typing import AsyncGenerator

from config.request_trace import trace_step

from .consultation_classifier import ConsultationClassifier
from .response_generator import ResponseGenerator
from .retrieval import Retriever


class ConsultationProcessor:
    """咨询流程处理器"""

    def __init__(
        self,
        retriever: Retriever,
        consultation_classifier: ConsultationClassifier,
        response_generator: ResponseGenerator,
    ):
        self.retriever = retriever
        self.consultation_classifier = consultation_classifier
        self.response_generator = response_generator

    async def process_consultation(self, user_input: str) -> str:
        """处理标准咨询"""
        with trace_step("knowledge_search", agent="ConsultantAgent"):
            knowledge_docs = await self.retriever.search(user_input, top_k=3)

        with trace_step("response_generation", agent="ConsultantAgent"):
            response = await self.response_generator.generate_response(user_input, knowledge_docs)

        return response

    async def process_consultation_stream(
        self, user_input: str, session_id: str
    ) -> AsyncGenerator[str, None]:
        """处理流式咨询"""
        with trace_step("knowledge_search", agent="ConsultantAgent"):
            knowledge_docs = await self.retriever.search(user_input, top_k=3)

        with trace_step("response_generation_stream", agent="ConsultantAgent"):
            async for token in self.response_generator.generate_response_stream(
                user_input, knowledge_docs
            ):
                yield token

    async def handle_unrelated_request(
        self, user_input: str, unrelated_callback, shared_state
    ) -> AsyncGenerator[str, None]:
        """处理与咨询无关的请求"""
        yield self.response_generator.create_unrelated_message()

        # 转给回调处理
        if unrelated_callback:
            async for token in unrelated_callback(user_input):
                yield token
