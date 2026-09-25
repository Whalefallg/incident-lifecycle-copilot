# Incident Lifecycle Copilot

A Multi-Agent AI system for internal support and site reliability engineering teams. Covers the complete incident lifecycle — from alert triage to postmortem generation — reducing mean time to acknowledge (MTTA) and eliminating repetitive manual work across the on-call workflow.

[![CI](https://github.com/Whalefallg/incident-lifecycle-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Whalefallg/incident-lifecycle-copilot/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Design Goals

- Make the complete conversation snapshot the only recoverable source of truth.
- Keep workflow state separate from typed incident business context.
- Treat agents as disposable computation units that can be rebuilt on every request.
- Support atomic multi-worker recovery and stable request idempotency.
- Generate postmortems only from recorded, typed incident events.
- Require explicit human review and approval before knowledge ingestion.

### What the demo shows

| Workflow | Example |
|---|---|
| Alert triage and escalation | Classify a P0/P1 alert, collect impact, and select the on-call rotation |
| Runbook retrieval | Retrieve bundled operational runbooks locally or through an MCP RAG server |
| Stakeholder communication | Draft engineering, customer-support, and executive updates |
| Postmortem generation | Reconstruct a session timeline and produce an RCA draft |

For the fastest local run, copy `.env.example`, set an OpenAI-compatible model, choose `RAG_MODE=local`, install `requirements-production.txt`, and run `python app.py`. The UI is available at `http://localhost:8001`.

---

## The Problem

When a P0/P1 alert fires at 3 AM, an on-call engineer has to simultaneously:

- Assess severity and determine blast radius
- Hunt through Slack, Grafana, runbooks, and past incidents across multiple tools
- Page the right team and open a bridge channel
- Draft status updates for engineering, customer support, and leadership
- Write a postmortem 48 hours later from memory

Each step is high-stakes, time-sensitive, and largely manual. This project addresses the full chain.

---

## Scalability Features

### High Concurrency & Cost Optimization

- **Semantic Caching**: Optional vector similarity-based LLM response caching with measurable hit-rate statistics
- **Model Routing**: Optional complexity-based model selection with usage statistics
- **Redis State Store**: Optional full-snapshot persistence with atomic revision checks
- **Celery Async Queue**: Optional workers for long-running Postmortem generation and vector DB writes
- **Public Demo Guardrails**: Per-browser sessions, input bounds, HTML escaping, rate limiting, and protected admin mutations

### Monitoring & Observability

- `/api/monitoring/health` - Health check endpoint
- `/api/monitoring/stats/cache` - Cache hit rate statistics
- `/api/monitoring/stats/model-routing` - Model usage and cost savings
- `/api/monitoring/celery/status` - Async worker status
- `/api/monitoring/redis/info` - Redis connection metrics

See [Production Deployment Guide](docs/PRODUCTION_DEPLOYMENT.md) for details.

---

## Architecture

Five-layer separation of concerns — no layer references a layer above it:

```
┌─────────────────────────────────────────────────────────┐
│  Web Layer      │  Server-rendered UI + incident console │
├─────────────────────────────────────────────────────────┤
│  API Layer      │  FastAPI streaming endpoints           │
├─────────────────────────────────────────────────────────┤
│  Agent Layer    │  5 specialist agents (see below)       │
├─────────────────────────────────────────────────────────┤
│  Service Layer  │  MCP client, messaging and utility code │
├─────────────────────────────────────────────────────────┤
│  DB Layer       │  SQLAlchemy business persistence        │
└─────────────────────────────────────────────────────────┘
```

### Five-Agent Architecture

```
Alert / Engineer Input
         │
         ▼
┌─────────────────────────┐
│  TriageRouter           │  TaskClassificationAgent
│  P0/P1/query/comms/     │  LLM classifier → state machine
│  postmortem routing     │
└──┬──────┬──────┬───┬───┘
   │      │      │   │
   ▼      ▼      ▼   ▼
┌──────┐ ┌───────┐ ┌──────────┐ ┌──────────┐
│Escal-│ │Runbook│ │Comms     │ │Postmortem│
│ation │ │Agent  │ │Agent     │ │Agent     │
│Agent │ │       │ │          │ │          │
└──┬───┘ └───┬───┘ └────┬─────┘ └────┬─────┘
```

| Agent | Implementation | Incident Ops Role |
|---|---|---|
| TriageRouter | `TaskClassificationAgent` | P0/P1/P2 classification + routing |
| EscalationAgent | `EscalationAgent` | Impact collection + on-call dispatch |
| RunbookAgent | `ConsultantAgent` | RAG over runbooks + past incidents |
| CommunicationAgent | `CommunicationAgent` | 3-audience status update generation |
| PostmortemAgent | `PostmortemAgent` | Timeline reconstruction + RCA draft |

---

## State Machine & Suspend / Resume

The Triage Router uses a deterministic FSM (`StateEnum`) to manage multi-turn context. When an agent detects an off-topic request mid-flow, it **suspends** the current context onto a stack rather than discarding it, handles the inserted task, then **automatically resumes** the original flow.

```
Engineer: "checkout P1, affecting us-east-1 payments"
  → state: ESCALATION (collecting severity, service ✓)

Engineer: "by the way, what's the runbook for redis OOM?"
  → EscalationAgent detects off-topic
  → suspend_callback fires:
      stack.push(ESCALATION + incident_history snapshot)
      state → CLASSIFY

  → inserted task routed: RunbookAgent answers redis OOM question
      state → RUNBOOK_LOOKUP → CLASSIFY

  → ClassificationProcessor detects non-empty suspend stack:
      stack.pop() → restore state = ESCALATION
      EscalationAgent.restore_snapshot(incident_history)

Engineer sees:
  "Resuming your P1 / checkout-service escalation.
   Still have: service, severity. Still needed: impact_scope. Please continue."
```

**Before (discard-and-reroute):** context lost, engineer must re-describe the incident.
**After (suspend+resume):** incident context preserved across the detour.

Suspend stack is capped at depth 2 (`MAX_SUSPEND_DEPTH`) to prevent runaway nesting. Legacy `unrelated_callback` is retained as fallback when stack is full.

---

① Alert fires       →  TriageRouter classifies P0/P1/P2
② Triage            →  EscalationAgent collects impact + dispatches on-call
③ Investigation     →  RunbookAgent retrieves relevant runbooks via RAG
④ Status updates    →  CommunicationAgent drafts 3 versions (eng / support / exec)
⑤ Resolution        →  PostmortemAgent reconstructs timeline from session history
⑥ Knowledge loop    →  PostmortemAgent writes back to runbook KB for future RAG
```

---

## Severity Model

| Level | Criteria | Response SLA |
|---|---|---|
| P0 | Customer-facing, no workaround, core transaction path | Bridge in 5 min, exec notify in 15 |
| P1 | Degraded with workaround, single-region | Ack in 15 min, plan in 30 min |
| P2 | Capacity warning, non-prod, known flaky alert | Ack in 1 hr, schedule fix |
| P3 | Cosmetic, low-impact hygiene | Backlog |

---

## Runbook Knowledge Base (Modular RAG MCP Server)

RAG retrieval is delegated to the **Modular RAG MCP Server** — an independent process that exposes `query_knowledge_hub`, `list_collections`, and `get_document_summary` tools via the MCP stdio protocol.

```
ConsultantAgent (RunbookAgent)
    → KnowledgeRetriever
    → McpRagClient  (agents/consultant/mcp_rag_client.py)
    → subprocess: python -m src.mcp_server.server
    → HybridSearch: Dense (default Chroma) + Sparse (BM25) + RRF Fusion + optional Reranker
```

**Why MCP instead of embedded FAISS?**

| Concern | Embedded FAISS | Modular RAG MCP Server |
|---|---|---|
| Search quality | Dense only | Hybrid (Dense + BM25) + Rerank |
| Observability | None | Full ingestion + query trace |
| Evaluation | Manual | Ragas + Golden Test Set |
| Separation of concerns | RAG logic inside Agent | Agent orchestrates; RAG server retrieves |

**Setup:** set `RAG_MCP_SERVER_PATH` in `.env` to the absolute path of the MODULAR-RAG-MCP-SERVER project, then ingest runbook documents once before starting the Copilot.

Five seed runbooks ship with the project (redis-oom, checkout-error, payment-gateway-timeout, lambda-timeout, postgres-connection-pool). Each contains symptoms, root cause, resolution steps, past incidents, and on-call mapping.

---

## PostmortemAgent — Technical Highlight

The `PostmortemAgent` reconstructs incident timelines without requiring external integrations (no Slack API, no PagerDuty webhook). It uses:

1. **Session message recording** — every engineer ↔ agent exchange is timestamped in memory
2. **`TimelineExtractor`** — keyword-based event classification (triage → escalation → mitigation → resolution)
3. **`PostmortemGenerator`** — LLM prompt with structured incident data + timeline summary
4. **Optional write-back hook** — `PostmortemBuilder` can write to an injected legacy knowledge service. The default Agent does not yet call an MCP ingest tool.

The current runtime generates an RCA draft from in-memory session history. Persisting and ingesting that draft into the MCP knowledge base remains an explicit follow-up step.

---

## Tech Stack

- **Python 3.11** + FastAPI (streaming SSE)
- **LangChain** for LLM orchestration
- **OpenAI / Qwen / DeepSeek** (pluggable via `model_provider.py`)
- **Modular RAG MCP Server** — subprocess-based hybrid retrieval (Dense + BM25 + RRF + Rerank)
- **SQLite** for persistence (swappable via DB layer)
- **Pydantic** for request/response models

---

## Quick Start

```bash
cp .env.example .env
# Set LLM_API_KEY and LLM_MODEL in .env.
# RAG_MODE=auto uses MCP when present and bundled runbooks otherwise.

pip install -r requirements.txt

# Ingest runbooks into the RAG MCP Server (one-time setup)
cd $RAG_MCP_SERVER_PATH
pip install -r requirements.txt
python scripts/ingest.py --path data/documents/default/ --collection default
cd -

python app.py
# open http://localhost:8001
```

### Public Demo Deployment

The repository includes a one-service `render.yaml` and a lightweight Docker
image. The public profile uses bundled runbooks, one worker, isolated browser
sessions, and no Redis/Celery dependency. See
[Demo Deployment Guide](docs/DEMO_DEPLOYMENT.md).

---

## Demo Scenarios

**P0 Escalation:**
```
Input:  [PagerDuty] CRITICAL: checkout-service error rate 8.2% | us-east-1 | 03:14 UTC
Output: P0 severity confirmed → EscalationAgent collects impact → on-call dispatched
```

**Runbook Lookup:**
```
Input:  how did we fix the Redis OOM last week?
Output: RunbookAgent RAG retrieves INC-2024-0891, surfaces resolution steps
```

**Multi-Stakeholder Update:**
```
Input:  write an update for the exec team
Output: CommunicationAgent generates business-impact executive summary
```

**Postmortem Generation:**
```
Input:  incident resolved, generate the postmortem
Output: PostmortemAgent reconstructs timeline from session, generates full RCA doc
```

---

## Background

This project evolved from internal support tooling experience. The core challenge — reducing MTTA and institutionalizing incident knowledge — is the same problem that motivated PayPal's internal Autotriage Tool. This system extends that single-step triage model into a full lifecycle orchestration layer with RAG-based memory and automated documentation.

The five-layer architecture and four original agent roles are preserved from the learning scaffold. `CommunicationAgent` and `PostmortemAgent` are net-new additions filling the gaps between active incident response and knowledge retention.

---

## Running the Project

This section covers every command needed to set up, run, and test the full system — including the MCP RAG Server that powers runbook retrieval.

---

### Prerequisites

- Python 3.11+
- A running MCP RAG Server (see below)
- An OpenAI-compatible LLM API key (Qwen / DeepSeek / OpenAI / Azure)

---

### 1. Environment Setup

```bash
# Clone and enter the project
git clone <repo-url>
cd "incident lifecycle copilot"

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill in the env file
cp .env.example .env
```

Open `.env` and fill in the required values:

```bash
# LLM (chat model)
MODEL_PROVIDER=qwen              # qwen | openai | deepseek | azure
LLM_API_KEY=your_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

# Embedding model (can be a different provider from LLM)
EMBEDDING_PROVIDER=qwen
EMBEDDING_API_KEY=your_key_here
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3

# Absolute path to the MODULAR-RAG-MCP-SERVER project root
RAG_MCP_SERVER_PATH=/Users/your_username/Projects/MODULAR-RAG-MCP-SERVER
```

---

### 2. Set Up the MCP RAG Server

The MCP RAG Server is a separate project that handles hybrid retrieval (BM25 + Dense + RRF + Rerank). The `ConsultantAgent` spawns it as a subprocess on demand.

#### 2a. Clone and install

```bash
git clone <mcp-server-repo-url> ~/Projects/MODULAR-RAG-MCP-SERVER
cd ~/Projects/MODULAR-RAG-MCP-SERVER

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2b. Configure the MCP Server

Open `config/settings.yaml` in the MCP Server project and fill in the same API keys:

```yaml
llm:
  provider: openai          # azure | openai | ollama | deepseek
  model: qwen-plus
  api_key: "your_key_here"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"

embedding:
  provider: openai
  model: text-embedding-v3
  api_key: "your_key_here"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"

vector_store:
  backend: chroma
  persist_path: ./data/db/chroma

retrieval:
  top_k_dense: 20
  top_k_sparse: 20
  top_k_final: 10
  fusion_algorithm: rrf

rerank:
  backend: none             # none | cross_encoder | llm
```

#### 2c. Ingest the five seed runbooks (one-time setup)

The project ships with five runbooks covering the most common incident types. Ingest them before starting the Copilot:

```bash
cd ~/Projects/MODULAR-RAG-MCP-SERVER
source .venv/bin/activate

# Ingest all runbooks in the default collection
python scripts/ingest.py --path data/documents/default/ --collection default

# Or ingest a single file
python scripts/ingest.py --path data/documents/default/redis-oom-runbook.pdf --collection default

# Verify ingestion
python scripts/query.py --query "redis OOM how to fix" --collection default
```

The five seed runbooks cover:
- `checkout-error` — checkout service error rate spikes
- `redis-oom` — Redis out-of-memory incidents
- `payment-gateway-timeout` — payment gateway timeouts
- `lambda-timeout` — Lambda function cold start timeouts
- `postgres-connection-pool` — PostgreSQL connection pool exhaustion

#### 2d. Verify the MCP Server works standalone

```bash
cd ~/Projects/MODULAR-RAG-MCP-SERVER
source .venv/bin/activate

# Test the JSON-RPC handshake
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m src.mcp_server.server
```

You should see a JSON response listing three tools: `query_knowledge_hub`, `list_collections`, `get_document_summary`.

#### 2e. (Optional) Start the RAG Dashboard

```bash
cd ~/Projects/MODULAR-RAG-MCP-SERVER
source .venv/bin/activate
python scripts/start_dashboard.py
# Open http://localhost:8501
```

The dashboard shows ingestion traces, query traces, chunk browser, and evaluation panel.

---

### 3. Run the Incident Lifecycle Copilot

```bash
cd "/path/to/incident lifecycle copilot"
source .venv/bin/activate

python app.py
# Open http://localhost:8001
```

The UI presents a chat console. Try these scenarios:

**P0 Escalation (multi-turn field collection):**
```
You:    [PagerDuty] CRITICAL: checkout-service error rate 8.2% | us-east-1 | 03:14 UTC
Agent:  P0 severity confirmed. Dispatching platform-sre on-call (Alice Chen) → #platform-incidents
```

**Runbook lookup mid-escalation (suspend/resume):**
```
You:    checkout P1 affecting eu-west-1
Agent:  Collecting impact... what is the blast radius?
You:    by the way, what does the redis OOM runbook say?
Agent:  [Suspending escalation context] Redis OOM: flush expired keys, scale instance...
        [Resuming P1/checkout escalation] I still have: severity, service. Still needed: impact_scope.
```

**Stakeholder update:**
```
You:    write a status update for the exec team
Agent:  CommunicationAgent drafts executive summary with business impact
```

**Postmortem generation:**
```
You:    incident resolved, generate the postmortem
Agent:  PostmortemAgent reconstructs timeline from session history → RCA document
```

---

### 4. Run Tests

```bash
cd "/path/to/incident lifecycle copilot"
source .venv/bin/activate

# Fast unit tests — no MCP Server or API key required
pytest tests/ -m "not live and not ragas_eval and not redis_integration" -q

# Verbose with test names
pytest tests/ -m "not live and not ragas_eval and not redis_integration" -v

# Run a specific test file
pytest tests/test_ragas_eval.py -m retrieval -v
pytest tests/test_escalation_agent.py -v
pytest tests/test_task_classification_agent.py -v
pytest tests/test_consultant_agent.py -v

# Live retrieval evaluation — MCP Server must be running with runbooks ingested
pytest tests/test_ragas_eval.py -m live -v

# Ragas generation quality evaluation — requires MCP Server + LLM API key
pytest tests/test_ragas_eval.py -m ragas_eval -v
```

**Test markers:**

| Marker | Requires | What it tests |
|--------|----------|---------------|
| _(no marker)_ | Nothing | Pure logic, state machine, snapshot integrity |
| `retrieval` | Nothing | Hit Rate logic, Golden Set structure, mock retrieval |
| `live` | Running MCP Server | Runs retrieval evaluation against configured acceptance thresholds |
| `ragas_eval` | MCP Server + LLM API key | Runs LLM-based quality evaluation against configured acceptance thresholds |
| `redis_integration` | Redis + sentence-transformers | State and semantic-cache integration tests |

**Configured acceptance thresholds (not recorded benchmark results):**

| Metric | Threshold |
|--------|-----------|
| Hit Rate@10 | ≥ 90% |
| Retrieval P95 latency | < 800ms |
| Ragas Faithfulness | ≥ 0.85 |
| Ragas Answer Relevancy | ≥ 0.80 |
| Ragas Context Recall | ≥ 0.75 |

---

### 5. Ingest a Postmortem into the Knowledge Base

After resolving an incident and generating a postmortem, ingest it into the MCP Server so future RAG queries can surface it:

```bash
cd ~/Projects/MODULAR-RAG-MCP-SERVER
source .venv/bin/activate

# Ingest a single postmortem document
python scripts/ingest.py --path /path/to/INC-2024-1201-postmortem.md --collection default

# Verify it's retrievable
python scripts/query.py --query "checkout circuit breaker past incident" --collection default
```

---

### 6. Add Custom Runbooks

To extend the knowledge base with your own runbooks:

```bash
cd ~/Projects/MODULAR-RAG-MCP-SERVER
source .venv/bin/activate

# Add a new runbook (PDF or Markdown)
python scripts/ingest.py --path /path/to/your-service-runbook.md --collection default

# Ingest an entire directory
python scripts/ingest.py --path /path/to/runbooks/ --collection default --verbose
```

---

### 7. Troubleshooting

**`ModuleNotFoundError: No module named 'config'`**
Run pytest from the project root with `python -m pytest`, not directly as `python tests/xxx.py`. A `conftest.py` at the project root adds the path automatically.

**MCP Server subprocess fails to start**
Verify `RAG_MCP_SERVER_PATH` in `.env` is the absolute path to the MCP Server project root. Test manually:
```bash
cd $RAG_MCP_SERVER_PATH && source .venv/bin/activate
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m src.mcp_server.server
```

**LLM API `AuthenticationError`**
Double-check `LLM_API_KEY` and `LLM_BASE_URL` in `.env`. For Qwen, the base URL is `https://dashscope.aliyuncs.com/compatible-mode/v1`.

**Retrieval returns empty results**
Runbooks have not been ingested yet. Run step 2c above. Then verify with `python scripts/query.py --query "redis OOM"`.

**`openai.APIConnectionError: 403 Forbidden` in tests**
Some tests require external services. The default `pytest` command skips them;
run their marker explicitly only after configuring MCP, Redis, and the required API key.
