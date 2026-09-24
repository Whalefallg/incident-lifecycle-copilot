#!/bin/bash

# 生产环境启动脚本

set -e

echo "======================================"
echo "Incident Lifecycle Copilot - Production Startup"
echo "======================================"

# 检查环境变量
if [ ! -f .env ]; then
    echo "⚠️  .env file not found, copying from .env.production"
    cp .env.production .env
fi

# 检查 Redis 连接
echo ""
echo "Checking Redis connection..."
redis-cli -h ${REDIS_HOST:-localhost} -p ${REDIS_PORT:-6379} ping > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✅ Redis is running"
else
    echo "❌ Redis is not accessible"
    echo "   Start Redis with: docker run -d -p 6379:6379 redis:7-alpine"
    exit 1
fi

# 安装依赖
echo ""
echo "Installing dependencies..."
pip install -r requirements-production.txt

# 下载 embedding 模型
echo ""
echo "Downloading embedding model for Semantic Cache..."
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ Embedding model ready"
else
    echo "⚠️  Embedding model download failed, cache may not work"
fi

# 启动 Celery Worker (后台)
echo ""
echo "Starting Celery worker..."
celery -A config.celery_tasks worker \
    --loglevel=info \
    --concurrency=${CELERY_WORKER_CONCURRENCY:-4} \
    --detach \
    --pidfile=/tmp/celery_worker.pid \
    --logfile=logs/celery_worker.log

if [ $? -eq 0 ]; then
    echo "✅ Celery worker started (PID: $(cat /tmp/celery_worker.pid))"
else
    echo "⚠️  Celery worker failed to start"
fi

# 可选：启动 Celery Beat (定时任务)
if [ "${CELERY_BEAT_ENABLED:-false}" = "true" ]; then
    echo ""
    echo "Starting Celery Beat..."
    celery -A config.celery_tasks beat \
        --loglevel=info \
        --detach \
        --pidfile=/tmp/celery_beat.pid \
        --logfile=logs/celery_beat.log

    if [ $? -eq 0 ]; then
        echo "✅ Celery Beat started"
    fi
fi

# 可选：启动 Flower (监控)
if [ "${FLOWER_ENABLED:-false}" = "true" ]; then
    echo ""
    echo "Starting Flower monitoring UI..."
    celery -A config.celery_tasks flower \
        --port=${FLOWER_PORT:-5555} \
        --detach \
        --logfile=logs/flower.log

    if [ $? -eq 0 ]; then
        echo "✅ Flower started at http://localhost:${FLOWER_PORT:-5555}"
    fi
fi

# 启动 FastAPI
echo ""
echo "Starting FastAPI application..."
echo "Workers: ${FASTAPI_WORKERS:-4}"
echo "Port: ${FASTAPI_PORT:-8000}"
echo ""

uvicorn app:app \
    --host ${FASTAPI_HOST:-0.0.0.0} \
    --port ${FASTAPI_PORT:-8000} \
    --workers ${FASTAPI_WORKERS:-4} \
    --log-level ${LOG_LEVEL:-info}
