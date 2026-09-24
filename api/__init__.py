"""
API模块

核心功能API：
- Incident escalation & on-call dispatch
- Runbook & past incident consultation
- Task classification & routing
- Knowledge base management
- User behavior analysis
- Production monitoring & statistics (NEW)
"""

from .incident import router as incident_router
from .consultation import router as consultation_router
from .task import router as task_router
from .knowledge import router as knowledge_router
from .user_behavior_analysis import router as user_behavior_analysis_router
from .user_behavior_analysis import router_underscore as user_behavior_analysis_underscore_router
from .monitoring import router as monitoring_router

api_routers = [
    incident_router,
    consultation_router,
    task_router,
    knowledge_router,
    user_behavior_analysis_router,
    user_behavior_analysis_underscore_router,
    monitoring_router,  # 生产级监控 API
]
