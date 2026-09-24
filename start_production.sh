#!/bin/bash

# ==============================================
# 生产环境启动脚本
# ==============================================

set -e

echo "🚀 Starting Incident Lifecycle Copilot (Production Mode)"
echo "=========================================================="

# 检查依赖
echo "📦 Checking dependencies..."
if ! command -v redis-cli &> /dev/null; then
    echo "❌ Redis CLI not found. Please install Redis first."
    exit 1
fi

if ! command -v celery &> /dev/null; then
    echo "❌ Celery not found. Installing dependencies..."
    pip install -r requirements-production.txt
fi

# 检查 Redis 连接
echo "🔍 Checking Redis connection..."
if ! redis-cli ping &> /dev/null; then
    echo "❌ Redis is not running. Please start Redis first:"
    echo "   docker run -d --name redis -p 6379:6379 redis:7.2-alpine"
    exit 1
fi
echo "✅ Redis is running"

# 检查环境变量
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Copying from .env.production..."
    cp .env.production .env
    echo "⚠️  Please edit .env and fill in your API keys!"
    exit 1
fi

# 创建日志目录
mkdir -p logs

# 启动 Celery Worker
echo ""
echo "🔧 Starting Celery Worker..."
celery -A config.celery_tasks worker \
    --loglevel=info \
    --concurrency=4 \
    --logfile=logs/celery_worker.log \
    --detach

sleep 2

# 检查 Celery Worker 状态
if celery -A config.celery_tasks inspect active &> /dev/null; then
    echo "✅ Celery Worker started"
else
    echo "❌ Celery Worker failed to start"
    exit 1
fi

# 启动 FastAPI
echo ""
echo "🌐 Starting FastAPI server..."
echo "=========================================================="
echo "📊 Monitoring endpoints:"
echo "   - Health Check: http://localhost:8000/api/monitoring/health"
echo "   - Cache Stats:  http://localhost:8000/api/monitoring/stats/cache"
echo "   - Model Stats:  http://localhost:8000/api/monitoring/stats/model-routing"
echo "   - API Docs:     http://localhost:8000/docs"
echo "=========================================================="
echo ""

# 使用 4 个 worker 启动（可根据 CPU 核心数调整）
uvicorn app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --log-level info

# 清理
trap "echo '🛑 Stopping services...'; celery -A config.celery_tasks control shutdown; exit" INT TERM
