#!/bin/bash

# 生产环境停止脚本

set -e

echo "======================================"
echo "Stopping Incident Lifecycle Copilot"
echo "======================================"

# 停止 FastAPI
echo ""
echo "Stopping FastAPI..."
pkill -f "uvicorn app:app" && echo "✅ FastAPI stopped" || echo "⚠️  No FastAPI process found"

# 停止 Celery Worker
echo ""
echo "Stopping Celery worker..."
if [ -f /tmp/celery_worker.pid ]; then
    kill $(cat /tmp/celery_worker.pid) 2>/dev/null && echo "✅ Celery worker stopped" || echo "⚠️  Celery worker not running"
    rm -f /tmp/celery_worker.pid
else
    pkill -f "celery.*worker" && echo "✅ Celery worker stopped" || echo "⚠️  No Celery worker found"
fi

# 停止 Celery Beat
echo ""
echo "Stopping Celery Beat..."
if [ -f /tmp/celery_beat.pid ]; then
    kill $(cat /tmp/celery_beat.pid) 2>/dev/null && echo "✅ Celery Beat stopped" || echo "⚠️  Celery Beat not running"
    rm -f /tmp/celery_beat.pid
else
    pkill -f "celery.*beat" && echo "✅ Celery Beat stopped" || echo "⚠️  No Celery Beat found"
fi

# 停止 Flower
echo ""
echo "Stopping Flower..."
pkill -f "celery.*flower" && echo "✅ Flower stopped" || echo "⚠️  No Flower process found"

echo ""
echo "======================================"
echo "All services stopped"
echo "======================================"
