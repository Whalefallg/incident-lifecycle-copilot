# Production Deployment Guide

> **Status:** This document describes the target multi-service architecture,
> not a completed concurrency benchmark. The resume-demo profile is the tested
> one-worker configuration in [DEMO_DEPLOYMENT.md](DEMO_DEPLOYMENT.md). Do not
> claim the figures below as measured results until load-test artifacts are
> checked into the repository.

## Overview

This guide sketches a future horizontally scalable deployment. Capacity and
savings must be measured against representative traffic before publication.

---

## Architecture Components

### 1. FastAPI Application (Target: Stateless)

Multiple Uvicorn workers require the complete agent conversation payload to be
stored in Redis. The current tested demo profile uses one worker; persisting
only the state enum is not sufficient for multi-worker correctness.

```bash
# Start with multiple workers
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

### 2. Redis (State & Cache)

- **Agent State Store**: Shared state machine storage for horizontal scaling
- **Semantic Cache**: Vector similarity-based LLM response caching
- **Session Management**: User session persistence

### 3. Celery Workers (Async Tasks)

- **Postmortem Generation**: Long-running tasks decoupled from API
- **Vector DB Writes**: Batch embedding computation
- **Alert Storm Handling**: Batch processing for high-volume scenarios

### 4. Optional: Vector Database

For production RAG over runbooks and postmortems (Chroma, Qdrant, or Pinecone).

---

## Installation

### Prerequisites

- Python 3.10+
- Redis 6.0+
- (Optional) Vector database instance

### Install Dependencies

```bash
# Production dependencies
pip install -r requirements-production.txt

# Download embedding model for Semantic Cache
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

### Environment Configuration

Copy and configure production environment:

```bash
cp .env.production .env
```

Edit `.env` with your settings:

```bash
# LLM API Keys
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Redis Connection
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your-password

# Enable Production Features
SEMANTIC_CACHE_ENABLED=true
MODEL_ROUTING_ENABLED=true
REDIS_STATE_ENABLED=true

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

---

## Deployment Steps

### Step 1: Start Redis

```bash
# Using Docker
docker run -d \
  --name incident-redis \
  -p 6379:6379 \
  redis:7-alpine redis-server --appendonly yes

# Verify connection
redis-cli ping
# Expected: PONG
```

### Step 2: Start Celery Workers

```bash
# Start Celery worker
celery -A config.celery_tasks worker \
  --loglevel=info \
  --concurrency=4

# Optional: Start Celery Beat (scheduled tasks)
celery -A config.celery_tasks beat --loglevel=info

# Optional: Start Flower (monitoring UI)
celery -A config.celery_tasks flower --port=5555
```

### Step 3: Start FastAPI Application

```bash
# Development
uvicorn app:app --host 0.0.0.0 --port 8000 --reload

# Production with multiple workers
uvicorn app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --log-level info
```

### Step 4: Verify Deployment

```bash
# Health check
curl http://localhost:8000/api/monitoring/health

# Cache statistics
curl http://localhost:8000/api/monitoring/stats/cache

# Model routing statistics
curl http://localhost:8000/api/monitoring/stats/model-routing

# Celery worker status
curl http://localhost:8000/api/monitoring/celery/status
```

---

## Production Features

### 1. Semantic Caching

**How it works:**
- Query text is embedded using `sentence-transformers`
- Cosine similarity computed against cached queries
- If similarity > threshold (default 0.85), return cached response
- Avoids expensive LLM API calls

**Configuration:**

```bash
SEMANTIC_CACHE_ENABLED=true
SEMANTIC_CACHE_THRESHOLD=0.85
REDIS_CACHE_TTL=7200  # 2 hours
```

**Potential benefits:**
- Fewer repeated LLM calls when real traffic has high semantic overlap
- Savings proportional to the measured cache hit rate
- Cache lookup latency and memory usage must be benchmarked in deployment

**Monitoring:**

```bash
curl http://localhost:8000/api/monitoring/stats/cache
```

Illustrative output shape (not a recorded benchmark):
```json
{
  "status": "ok",
  "cache_stats": {
    "enabled": true,
    "hits": 1250,
    "misses": 1850,
    "total_queries": 3100,
    "hit_rate_percent": 40.32,
    "threshold": 0.85,
    "ttl": 7200
  }
}
```

---

### 2. Model Routing

**How it works:**
- Automatically selects cost-appropriate model based on task complexity
- **SIMPLE** (classify, yes/no): `gpt-3.5-turbo` or `claude-haiku`
- **MEDIUM** (RAG, templates): `gpt-4o-mini` or `claude-sonnet`
- **COMPLEX** (postmortem, RCA): `gpt-4` or `claude-opus`

**Configuration:**

```bash
MODEL_ROUTING_ENABLED=true
MODEL_PROVIDER=openai  # or anthropic
```

**Potential benefits:**
- Avoids using expensive models for simple tasks
- Savings depend on current provider prices and the observed task distribution
- Quality gates are required before routing complex work to smaller models

**Usage in Code:**

```python
from config.model_router import model_router, classify_task_complexity, TaskComplexity

# Option 1: Automatic classification
complexity = classify_task_complexity("Is this a P0 incident?")
model = model_router.get_model(complexity)  # Returns gpt-3.5-turbo

# Option 2: Manual specification
model = model_router.get_model(TaskComplexity.COMPLEX)  # Returns gpt-4
```

---

### 3. Redis State Store

**How it works:**
- Agent state machine serialized to Redis
- FastAPI nodes remain stateless
- Horizontal scaling without session affinity

**Configuration:**

```bash
REDIS_STATE_ENABLED=true
REDIS_STATE_TTL=3600  # 1 hour
```

**Usage:**

```python
from config.redis_config import redis_state_store

# Save state
await redis_state_store.save_state(
    session_id="session_123",
    state_data={"current_state": "ESCALATION", "incident_data": {...}},
)

# Load state
state = await redis_state_store.load_state("session_123")

# Extend TTL (keep-alive)
await redis_state_store.extend_ttl("session_123", ttl=3600)
```

**Benefits:**
- Stateless FastAPI nodes
- Horizontal scaling behind load balancer
- Automatic cleanup via TTL

---

### 4. Celery Async Queue

**How it works:**
- Long-running tasks offloaded to Celery workers
- FastAPI returns immediately with task ID
- Client polls for completion or uses webhooks

**Tasks:**
- `generate_postmortem_async`: Multi-step postmortem generation
- `write_to_vector_db_async`: Batch vector embedding
- `process_alert_batch_async`: Alert storm batch processing

**Usage:**

```python
from config.celery_tasks import generate_postmortem_async

# Trigger async task
task = generate_postmortem_async.delay(
    incident_id="INC-12345",
    alert_data={...},
)

# Get task ID
task_id = task.id

# Check status later
from celery.result import AsyncResult
result = AsyncResult(task_id)
if result.ready():
    postmortem = result.get()
```

**Benefits:**
- Non-blocking API responses
- Handles alert storms (100+ concurrent alerts)
- Retry logic for transient failures

---

## Scaling Guide

### Horizontal Scaling

#### Add More FastAPI Workers

```bash
# Increase worker count
uvicorn app:app --workers 8
```

Or use Gunicorn:

```bash
gunicorn app:app \
  -k uvicorn.workers.UvicornWorker \
  --workers 8 \
  --bind 0.0.0.0:8000
```

#### Add More Celery Workers

```bash
# Start additional workers on different machines
celery -A config.celery_tasks worker --concurrency=8
```

### Load Balancing

Use Nginx or AWS ALB to distribute traffic:

```nginx
upstream fastapi_backend {
    server 10.0.1.10:8000;
    server 10.0.1.11:8000;
    server 10.0.1.12:8000;
    server 10.0.1.13:8000;
}

server {
    listen 80;

    location / {
        proxy_pass http://fastapi_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## Monitoring

### Health Checks

```bash
# Application health
curl http://localhost:8000/api/monitoring/health

# Redis connection
curl http://localhost:8000/api/monitoring/redis/info

# Celery workers
curl http://localhost:8000/api/monitoring/celery/status
```

### Performance Metrics

```bash
# Comprehensive system stats
curl http://localhost:8000/api/monitoring/stats/system
```

Expected output:
```json
{
  "status": "ok",
  "cache": {
    "hit_rate_percent": 42.5
  },
  "model_routing": {
    "cost_savings": {
      "savings_percent": 38.7
    }
  },
  "estimated_total_savings_percent": 40.0
}
```

### Celery Flower UI

Access at `http://localhost:5555` for visual task monitoring.

---

## Troubleshooting

### Cache Not Working

```bash
# Check if Redis is accessible
redis-cli ping

# Verify cache is enabled
curl http://localhost:8000/api/monitoring/stats/cache

# Clear cache if needed
curl -X POST http://localhost:8000/api/monitoring/cache/clear
```

### Celery Tasks Not Processing

```bash
# Check worker logs
celery -A config.celery_tasks worker --loglevel=debug

# Verify Redis broker connection
celery -A config.celery_tasks inspect active
```

### High Memory Usage

```bash
# Check Redis memory
redis-cli info memory

# Clear expired keys
redis-cli --scan --pattern "agent:state:*" | xargs redis-cli del
```

---

## Hypothetical Cost Model

The numbers below are an example calculation only. Model names and prices age
quickly; replace them with the selected provider's current prices and measured
traffic before using this section externally.

### Baseline (No Optimization)

- 10,000 API calls/day
- All using GPT-4 ($30/1M tokens)
- Average 1,000 tokens/call
- **Daily cost**: $300

### With Optimizations

- 40% cache hits (no API call): 4,000 requests
- 40% simple tasks (GPT-3.5-turbo, $0.50/1M): 2,400 requests = $1.20
- 40% medium tasks (GPT-4o-mini, $0.15/1M): 2,400 requests = $0.36
- 20% complex tasks (GPT-4, $30/1M): 1,200 requests = $36

**Daily cost**: $37.56
**Savings**: $262.44/day (87.5%)

---

## Security Considerations

1. **Secrets Management**: Never commit `.env` files
2. **Redis Authentication**: Use `REDIS_PASSWORD` in production
3. **API Rate Limiting**: Implement per-user rate limits
4. **Input Validation**: Sanitize all user inputs
5. **Network Security**: Use VPC/private networks for Redis

---

## Backup & Recovery

### Redis Backup

```bash
# Enable AOF persistence
redis-cli CONFIG SET appendonly yes

# Manual snapshot
redis-cli BGSAVE
```

### State Recovery

Agent states auto-expire via TTL. For long-lived sessions, implement periodic `extend_ttl` calls.

---

## Next Steps

1. Set up monitoring dashboards (Grafana + Prometheus)
2. Implement distributed tracing (Jaeger)
3. Add metrics export for cost tracking
4. Configure log aggregation (ELK stack)
5. Set up alerting for system health
