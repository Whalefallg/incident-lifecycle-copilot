"""
业务服务层模块

包含：
- 知识库服务（Runbook & Past Incident RAG）
- 用户行为服务（Pattern Analysis）
- 文本嵌入工具
"""

from .text_embedding import (
    embed_input,
    find_best_match_indices,
)
from .knowledge_service import KnowledgeService
from .user_behavior_service import UserBehaviorService

__all__ = [
    'embed_input',
    'find_best_match_indices',
    'KnowledgeService',
    'UserBehaviorService',
]
