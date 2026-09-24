"""
Repositories Module

数据访问对象模块，包含：
- 知识库数据仓库（Runbook & Incident Memory）
- 用户行为数据仓库（Triage Pattern Learning）
"""

from .knowledge_repository import KnowledgeRepository
from .user_behavior_repository import UserBehaviorRepository

__all__ = [
    'KnowledgeRepository',
    'UserBehaviorRepository'
]
