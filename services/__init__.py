"""
业务服务层模块

包含：
- 知识库服务（Runbook & Past Incident RAG）
- 文本嵌入工具
"""

from .text_embedding import (
    embed_input,
    find_best_match_indices,
)
from .knowledge_service import KnowledgeService

__all__ = [
    'embed_input',
    'find_best_match_indices',
    'KnowledgeService',
]
