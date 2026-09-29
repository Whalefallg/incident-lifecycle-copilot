"""
API模块

核心功能API：
- Incident escalation & on-call dispatch
- Runbook & past incident consultation
- Task classification & routing
- Knowledge base management
- Production monitoring & statistics (NEW)
"""

from .consultation import router as consultation_router
from .incident import router as incident_router
from .incidents import router as incidents_router
from .knowledge import router as knowledge_router
from .monitoring import router as monitoring_router
from .task import router as task_router

api_routers = [
    incident_router,
    incidents_router,
    consultation_router,
    task_router,
    knowledge_router,
    monitoring_router,  # 生产级监控 API
]
