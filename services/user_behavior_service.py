"""
用户行为服务层

职责：
1. 封装用户行为相关的数据库操作
2. 处理用户行为分析业务逻辑
3. 提供用户偏好管理服务
"""

from typing import Dict, Any, List
from datetime import datetime
from db.db_router import DatabaseRouter
import logging

logger = logging.getLogger(__name__)

class UserBehaviorService:
    """用户行为服务类"""

    def __init__(self, db_path: str = 'sqlite:///data/incident_copilot.db'):
        self.db_router = DatabaseRouter(db_path)
        self.user_behavior_repo = self.db_router.user_behavior

    def record_behavior(self, user_id: str, action_type: str, action_data: Dict[str, Any] = None,
                       session_id: str = "default_session") -> bool:
        """记录用户行为"""
        try:
            behavior_id = self.user_behavior_repo.record_behavior(
                user_id=user_id,
                action_type=action_type,
                action_data=action_data,
                session_id=session_id
            )

            if behavior_id:
                logger.info(f"用户行为记录成功：用户={user_id}, 行为={action_type}, ID={behavior_id}")
                return True
            return False

        except Exception as e:
            logger.error(f"记录用户行为失败：{e}")
            return False

    def get_user_behaviors(self, user_id: str, action_type: str = None,
                          days_back: int = None) -> List[Dict[str, Any]]:
        """获取用户行为记录"""
        try:
            return self.user_behavior_repo.get_user_behaviors(user_id, action_type, days_back)
        except Exception as e:
            logger.error(f"获取用户行为记录失败：{e}")
            return []

    def get_user_preferences(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户偏好"""
        try:
            return self.user_behavior_repo.get_user_preferences(user_id)
        except Exception as e:
            logger.error(f"获取用户偏好失败：{e}")
            return []

    def update_user_preference(self, user_id: str, preference_type: str,
                             preference_value: str, confidence_score: int = 1) -> bool:
        """更新用户偏好"""
        try:
            return self.user_behavior_repo.update_user_preference(
                user_id, preference_type, preference_value
            )
        except Exception as e:
            logger.error(f"更新用户偏好失败：{e}")
            return False

    def analyze_user_patterns(self, user_id: str) -> Dict[str, Any]:
        """分析用户行为模式"""
        try:
            behaviors = self.get_user_behaviors(user_id, days_back=30)

            if not behaviors:
                return {"pattern": "no_data", "recommendation": "需要更多数据"}

            incident_behaviors = [
                b for b in behaviors
                if b.get('action_type') in {'triage', 'escalation', 'runbook_lookup', 'postmortem'}
            ]
            freq_analysis = self._analyze_frequency(incident_behaviors)
            workflow_counts = self._analyze_workflow_usage(incident_behaviors)

            return {
                "pattern": "active_responder" if len(incident_behaviors) > 2 else "occasional_responder",
                "frequency_analysis": freq_analysis,
                "workflow_counts": workflow_counts,
                "total_incident_actions": len(incident_behaviors),
                "analysis_period_days": 30
            }

        except Exception as e:
            logger.error(f"分析用户行为模式失败：{e}")
            return {"pattern": "analysis_error", "error": str(e)}

    def _analyze_frequency(self, incident_behaviors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze how frequently the responder uses incident workflows."""
        if not incident_behaviors:
            return {"frequency": "no_activity", "days_between": 0}

        if len(incident_behaviors) < 2:
            return {"frequency": "single_action", "days_between": 0}

        # 计算平均间隔天数
        dates = []
        for behavior in incident_behaviors:
            if 'created_at' in behavior:
                try:
                    date = datetime.fromisoformat(behavior['created_at'].replace('Z', '+00:00'))
                    dates.append(date)
                except:
                    continue

        if len(dates) < 2:
            return {"frequency": "insufficient_data", "days_between": 0}

        dates.sort()
        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        avg_interval = sum(intervals) / len(intervals)

        if avg_interval < 7:
            frequency = "very_frequent"
        elif avg_interval < 14:
            frequency = "frequent"
        elif avg_interval < 30:
            frequency = "regular"
        else:
            frequency = "occasional"

        return {"frequency": frequency, "days_between": avg_interval}

    def _analyze_workflow_usage(self, incident_behaviors: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count usage by incident workflow."""
        from collections import Counter

        return dict(Counter(b.get('action_type', 'unknown') for b in incident_behaviors))
