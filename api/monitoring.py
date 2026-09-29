"""
生产级监控与统计 API

提供系统运行状态、缓存命中率、模型路由统计等监控指标。
"""

import logging

from fastapi import APIRouter, Depends

from api.contracts.monitoring import HealthResponse, RedisInfoResponse, SystemStatsResponse
from api.core.security import require_admin

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """健康检查端点"""
    return HealthResponse(status="healthy", service="Incident Lifecycle Copilot")


@router.get("/stats/cache")
async def get_cache_stats() -> dict[str, object]:
    """获取 Semantic Cache 统计信息"""
    try:
        from config.semantic_cache import semantic_cache

        stats = await semantic_cache.get_stats()
        return {"status": "ok", "cache_stats": stats}
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/stats/model-routing")
async def get_model_routing_stats() -> dict[str, object]:
    """获取模型路由统计信息"""
    try:
        from config.model_router import model_router

        stats = model_router.get_stats()
        return {"status": "ok", "routing_stats": stats}
    except Exception as e:
        logger.error(f"Failed to get routing stats: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/cache/clear", dependencies=[Depends(require_admin)])
async def clear_cache() -> dict[str, str]:
    """清空 Semantic Cache"""
    try:
        from config.semantic_cache import semantic_cache

        success = await semantic_cache.clear()
        if success:
            return {"status": "ok", "message": "Cache cleared successfully"}
        return {"status": "error", "message": "Failed to clear cache"}
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/celery/status")
async def get_celery_status() -> dict[str, object]:
    """获取 Celery Worker 状态"""
    try:
        from config.celery_tasks import celery_app

        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        active = inspect.active()

        return {
            "status": "ok",
            "workers": stats or {},
            "active_tasks": active or {},
        }
    except Exception as e:
        logger.error(f"Failed to get Celery status: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/redis/info", response_model=RedisInfoResponse)
async def get_redis_info() -> RedisInfoResponse:
    """获取 Redis 连接信息"""
    try:
        from config.redis_config import RedisClient

        redis = await RedisClient.get_client()
        info = await redis.info("server")

        db_size = await redis.dbsize()
        memory_info = await redis.info("memory")

        return RedisInfoResponse(
            status="ok",
            redis_version=info.get("redis_version"),
            uptime_seconds=info.get("uptime_in_seconds"),
            db_size=db_size,
            used_memory_human=memory_info.get("used_memory_human"),
        )
    except Exception as e:
        logger.error(f"Failed to get Redis info: {e}")
        return RedisInfoResponse(status="error", error=str(e))


@router.get("/stats/system", response_model=SystemStatsResponse)
async def get_system_stats() -> SystemStatsResponse:
    """获取系统综合统计"""
    try:
        from config.model_router import model_router
        from config.semantic_cache import semantic_cache

        cache_stats = await semantic_cache.get_stats()
        routing_stats = model_router.get_stats()

        cost_savings = cache_stats.get("hit_rate_percent", 0) + routing_stats.get(
            "cost_savings", {}
        ).get("savings_percent", 0)

        return SystemStatsResponse(
            status="ok",
            cache=cache_stats,
            model_routing=routing_stats,
            estimated_total_savings_percent=round(min(cost_savings, 80), 2),
        )
    except Exception as e:
        logger.error(f"Failed to get system stats: {e}")
        return SystemStatsResponse(status="error", error=str(e))
