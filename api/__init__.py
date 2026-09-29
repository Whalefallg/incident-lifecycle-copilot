"""FastAPI router registration without import-time application coupling."""


def get_api_routers():
    from .consultation import router as consultation_router
    from .incident import router as incident_router
    from .incidents import router as incidents_router
    from .knowledge import router as knowledge_router
    from .knowledge_lifecycle import router as knowledge_lifecycle_router
    from .monitoring import router as monitoring_router
    from .task import router as task_router

    return [
        incident_router,
        incidents_router,
        consultation_router,
        task_router,
        knowledge_lifecycle_router,
        knowledge_router,
        monitoring_router,
    ]
