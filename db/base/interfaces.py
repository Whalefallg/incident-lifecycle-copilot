from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime


class BaseKnowledgeRepository(ABC):
    """
    Knowledge base data access interface.
    Stores runbooks, past incident reports, and postmortems.
    """

    @abstractmethod
    def add_document(self, content: str, category: str, keywords: Optional[List[str]] = None,
                     embedding: Optional[List[float]] = None) -> int:
        pass

    @abstractmethod
    def get_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_all_documents(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def update_document(self, doc_id: int, content: Optional[str] = None, category: Optional[str] = None,
                        keywords: Optional[List[str]] = None, embedding: Optional[List[float]] = None) -> bool:
        pass

    @abstractmethod
    def delete_document(self, doc_id: int, soft_delete: bool = True) -> bool:
        pass

    @abstractmethod
    def search_documents_by_category(self, category: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def search_documents_by_keywords(self, keywords: List[str]) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_all_categories(self) -> List[str]:
        pass

    @abstractmethod
    def get_documents_count(self) -> int:
        pass


class BaseUserBehaviorRepository(ABC):
    """
    User behavior data access interface.
    Tracks incident triage patterns and engineer preferences for pattern learning.
    """

    @abstractmethod
    def record_behavior(self, user_id: str, action_type: str, action_data: Optional[Dict[str, Any]] = None,
                        session_id: Optional[str] = None) -> int:
        pass

    @abstractmethod
    def get_user_behaviors(self, user_id: str, action_type: Optional[str] = None,
                           days_back: Optional[int] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def update_user_preference(self, user_id: str, preference_type: str, preference_value: str) -> bool:
        pass

    @abstractmethod
    def get_user_preferences(self, user_id: str, preference_type: Optional[str] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def create_recommendation(self, user_id: str, recommendation_type: str, content: str) -> int:
        pass

    @abstractmethod
    def get_pending_recommendations(self, user_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def mark_recommendation_sent(self, recommendation_id: int) -> bool:
        pass

    @abstractmethod
    def get_user_statistics(self, user_id: str, days_back: int = 30) -> Dict[str, Any]:
        pass
