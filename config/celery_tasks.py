"""
Celery 异步任务配置

用于解耦长耗时任务：
1. Postmortem 生成（可能需要数十秒）
2. 向量数据库写入（批量嵌入计算）
3. 告警批量处理

优势：
- 不阻塞 API 响应
- 支持重试与容错
- 水平扩展 Worker
"""

import os
import logging
from celery import Celery
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "incident_copilot",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

logger.info(f"✅ Celery configured (broker={CELERY_BROKER_URL})")


@celery_app.task(name="tasks.generate_postmortem_async", bind=True, max_retries=3)
def generate_postmortem_async(self, incident_id: str, alert_data: dict):
    """
    异步生成 Postmortem

    Args:
        incident_id: 事件 ID
        alert_data: 告警数据

    Returns:
        dict: 生成的 Postmortem 内容
    """
    try:
        logger.info(f"Starting postmortem generation for incident {incident_id}")

        import asyncio
        from agents.postmortem_agent import PostmortemAgent

        async def _generate():
            agent = PostmortemAgent(session_id=incident_id)
            for event in alert_data.get("timeline", []):
                if isinstance(event, dict):
                    agent.add_session_message(
                        role=event.get("role", "system"),
                        content=event.get("content", str(event)),
                        timestamp=event.get("timestamp"),
                    )
                else:
                    agent.add_session_message(role="system", content=str(event))
            prompt = alert_data.get("summary") or f"Generate postmortem for {incident_id}"
            return await agent.generate_report(prompt)

        result = asyncio.run(_generate())
        logger.info(f"✅ Postmortem generated for incident {incident_id}")
        return result

    except Exception as e:
        logger.error(f"Failed to generate postmortem for {incident_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(name="tasks.write_to_vector_db_async", bind=True, max_retries=3)
def write_to_vector_db_async(self, documents: list[dict], collection_name: str = "postmortems"):
    """
    异步写入向量数据库

    Args:
        documents: 文档列表 [{"id": "...", "text": "...", "metadata": {...}}]
        collection_name: 集合名称

    Returns:
        dict: 写入结果
    """
    try:
        logger.info(f"Writing {len(documents)} documents to vector DB ({collection_name})")

        import asyncio
        from config.vector_store import vector_store

        async def _write():
            success_count = 0
            for doc in documents:
                success = await vector_store.add_document(
                    doc_id=doc["id"],
                    text=doc["text"],
                    metadata=doc.get("metadata", {}),
                    collection=collection_name,
                )
                if success:
                    success_count += 1
            return {"success": success_count, "total": len(documents)}

        result = asyncio.run(_write())
        logger.info(f"✅ Vector DB write complete: {result}")
        return result

    except Exception as e:
        logger.error(f"Failed to write to vector DB: {e}")
        raise self.retry(exc=e, countdown=30)


@celery_app.task(name="tasks.process_alert_batch_async", bind=True)
def process_alert_batch_async(self, alerts: list[dict]):
    """
    批量处理告警（告警风暴场景）

    Args:
        alerts: 告警列表

    Returns:
        dict: 处理结果统计
    """
    try:
        logger.info(f"Processing alert batch: {len(alerts)} alerts")

        import asyncio
        import json
        from agents.escalation_agent import EscalationAgent

        async def _process():
            results = {
                "processed": 0,
                "dispatched": 0,
                "failed": 0,
            }

            for alert in alerts:
                try:
                    incident_id = str(alert.get("id", f"batch-{results['processed']}"))
                    agent = EscalationAgent(session_id=incident_id)
                    tokens = []
                    async for token in agent.run_stream(json.dumps(alert)):
                        tokens.append(token)
                    response = "".join(tokens).lower()
                    results["processed"] += 1
                    if "dispatch" in response or "escalation initiated" in response:
                        results["dispatched"] += 1
                except Exception as e:
                    logger.error(f"Failed to process alert {alert.get('id')}: {e}")
                    results["failed"] += 1

            return results

        result = asyncio.run(_process())
        logger.info(f"✅ Alert batch processed: {result}")
        return result

    except Exception as e:
        logger.error(f"Failed to process alert batch: {e}")
        return {"error": str(e)}


@celery_app.task(name="tasks.cleanup_expired_states")
def cleanup_expired_states():
    """
    定期清理过期的 Redis 状态（由 Celery Beat 调度）
    """
    try:
        import asyncio
        from config.redis_config import RedisClient

        async def _cleanup():
            redis = await RedisClient.get_client()

            cursor = 0
            cleaned = 0

            while True:
                cursor, keys = await redis.scan(
                    cursor,
                    match="agent:state:*",
                    count=100
                )

                for key in keys:
                    ttl = await redis.ttl(key)
                    if ttl == -1:
                        await redis.delete(key)
                        cleaned += 1

                if cursor == 0:
                    break

            return {"cleaned": cleaned}

        result = asyncio.run(_cleanup())
        logger.info(f"✅ State cleanup complete: {result}")
        return result

    except Exception as e:
        logger.error(f"State cleanup failed: {e}")
        return {"error": str(e)}


celery_app.conf.beat_schedule = {
    "cleanup-expired-states": {
        "task": "tasks.cleanup_expired_states",
        "schedule": 3600.0,
    },
}
