"""FastAPI router registration without import-time application coupling."""


def get_api_routers():
    from .incidents import router as incidents_router
    from .knowledge import router as knowledge_router
    from .knowledge_lifecycle import router as knowledge_lifecycle_router
    from .monitoring import router as monitoring_router

    return [
        incidents_router,
        knowledge_lifecycle_router,
        knowledge_router,
        monitoring_router,
    ]
