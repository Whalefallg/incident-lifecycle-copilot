# Incident Lifecycle Copilot

基于 React、TypeScript 与 FastAPI 的全栈 AI Incident Operations Workspace：以可恢复多 Agent 工作流、Redis CAS、请求幂等与 MCP-based RAG 覆盖完整事故生命周期。

**中文** · [English](#english)

---

# 中文

## 项目简介

Incident Lifecycle Copilot 是一个面向事故响应的 **全栈 AI Operations Workspace**，基于 React + TypeScript + FastAPI 构建，并结合可恢复多 Agent 工作流、Redis CAS / 幂等状态管理与 MCP-based RAG，覆盖告警分诊、升级、Runbook 检索、状态沟通、Postmortem 和知识审核。

它不是与后端脱节的 mock dashboard：Incident Workspace、Conversation、Timeline、Runbook Evidence、Agent Trace、Postmortem Review、Knowledge Review 与 Observability UI 分别映射真实的 `ConversationSnapshot`、Incident Event Ledger、Request Trace、Retrieval Evidence 和 Knowledge Draft Lifecycle。

与依赖进程内 Agent 状态的实现不同，系统将完整会话状态持久化为版本化 `ConversationSnapshot`，使任意 Worker 能够恢复工作流，并通过乐观并发控制与幂等机制保证重试和并发正确性。检索则通过 MCP 对接独立的 [`rag-as-mcp`](https://github.com/Whalefallg/rag-as-mcp)，保持 Agent 编排与 RAG 基础设施的清晰边界。

## 核心能力

- **Full-Stack Incident Workspace**：React + TypeScript 承载 Incident Workspace、Conversation、Timeline、Runbook Evidence、Agent Trace、Postmortem / Knowledge Review 与 Observability，并直接呈现后端持久化状态。
- **可恢复多 Agent 工作流**：请求级 Agent 为一次性对象；可中断 FSM 与业务上下文由 `ConversationSnapshot` 恢复。
- **Typed REST + SSE Delivery**：OpenAPI 生成 TypeScript 契约；typed SSE 传递请求进度与已提交结果，FastAPI 同时提供 API 和生产 SPA。
- **MCP-based RAG 集成**：稳定 `Retriever` 契约对接独立混合检索服务，并隔离 MCP 生命周期、协议与错误处理。
- **跨 Worker 恢复**：Redis revision compare-and-set 允许不同 Worker 安全恢复和更新同一事故会话。
- **并发与幂等保护**：CAS 拒绝 stale write，request ID + payload fingerprint 防止重复执行与幂等键误用。
- **结构化 Incident Event Ledger**：先持久化事实，再生成 Timeline、沟通内容和 Postmortem 草稿。
- **Agent Execution Trace**：展示实际参与请求的 Agent、动作、状态、耗时与有界 Retrieval Evidence，不暴露模型思维链。
- **知识审核闭环**：知识草稿经过 `DRAFT → REVIEWED → APPROVED → INGESTED / REJECTED` 生命周期；没有真实 ingestor 时停留在 `APPROVED`。

## 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | React 19、TypeScript、Vite、React Router、TanStack Query、Zustand |
| 后端 | FastAPI、Pydantic、Python |
| 状态与并发 | `ConversationSnapshot`、Redis CAS、request idempotency |
| AI 工作流 | Recoverable Multi-Agent Workflow、LangChain、OpenAI-compatible models |
| 检索 | MCP、`rag-as-mcp`、Hybrid RAG |
| 可观测性 | Agent Trace、Incident Event Ledger、typed SSE |
| 测试 | Pytest、Vitest、Playwright |
| 交付 | Multi-stage Docker、GitHub Actions |

## 架构

```text
React + TypeScript Incident Workspace
├── Incident List / Workspace     ├── Conversation / Timeline
├── Runbook Evidence / Agent Trace
└── Postmortem / Knowledge Review / Observability
                    |
                    | Typed REST + SSE
                    v
FastAPI → Incident Application Services
                    |
                    v
         ConversationCoordinator
                    |
                    v
         ConversationRepository
                    |
                    v
         ConversationSnapshot
      ├── Request Trace / Retrieval Evidence
      ├── Incident Event Ledger / Knowledge Lifecycle
      └── Redis CAS / Request Idempotency
                    |
                    v
       Disposable Multi-Agent Workflow
      ├── EscalationAgent      ├── ConsultantAgent
      ├── CommunicationAgent   └── PostmortemAgent
                    |
                    v
          Retriever / MCP → rag-as-mcp
```

SSE 提供类型化的请求进度与已提交结果，不宣称为实时 token streaming。`request.completed` 表示快照已经持久化，前端随后刷新该事故下的消息、时间线、检索证据、trace 与复盘查询。完整边界与演示步骤见 [`docs/FULLSTACK_ARCHITECTURE.md`](docs/FULLSTACK_ARCHITECTURE.md) 和 [`docs/FULLSTACK_DEMO.md`](docs/FULLSTACK_DEMO.md)。

Agent 名称表示职责边界，而不是长期持有状态的独立服务。每个请求都会根据当前 `ConversationSnapshot` 构建新的执行图，处理完成后再以 revision 为条件写回持久层。

## 关键工程设计

### 1. Snapshot 作为恢复 Source of Truth

`ConversationSnapshot` 保存恢复一次事故会话所需的完整状态，包括：

- schema version、session ID 与 revision
- 当前 FSM state 与 suspend stack
- escalation / postmortem context
- 消息历史与结构化 incident events
- 已完成 request 的结果与幂等信息
- 创建与更新时间

这使 Agent 本身可以保持 disposable，并避免将正确性绑定到单个进程或单个 Python 对象。

### 2. 乐观并发控制与请求幂等

`RedisConversationRepository.save(snapshot, expected_revision)` 使用原子 compare-and-set。

当两个 Worker 同时基于旧版本更新同一会话时，过期写入会触发 `ConcurrentConversationUpdate`，而不是覆盖较新的状态。

对于请求重试，系统使用稳定 request ID 和规范化 payload fingerprint：

- 相同 request ID + 相同 payload：返回已完成结果
- 相同 request ID + 不同 payload：抛出 `IdempotencyKeyMismatch`

因此网络重试不会重复追加事件，也不会重复推进工作流。

### 3. 可中断、可恢复的 FSM

FSM 只表示**工作流位置**，业务字段保存在类型化 context 中。

例如，正在执行的事故升级可以临时挂起：

```text
Escalation
    |
    | suspend
    v
Runbook Question
    |
    | resume
    v
Escalation
```

`suspend stack` 与 escalation context 都会持久化，因此回答 Runbook 的 Worker 和恢复升级流程的 Worker 可以完全不同。

### 4. Structured Incident Event Ledger

运行时事实被记录为类型化 `IncidentEvent`，包含稳定 ID、incident ID、timestamp、actor、source、request ID、event type 和 payload。

复盘时间线来自该事件账本，而不是重新从自然语言聊天记录中猜测事实。记录事实与模型生成的 root-cause analysis 保持分离。

### 5. RAG 与 Agent 编排解耦

Incident Lifecycle Copilot 只依赖抽象 `Retriever` 契约。

默认外部后端为 [`rag-as-mcp`](https://github.com/Whalefallg/rag-as-mcp)，当前已验证的 MCP 契约为：

```text
transport: stdio
entrypoint: python main.py

initialize
ping
tools/list
tools/call

required:
  query_knowledge_hub(query, top_k, collection)

optional:
  list_collections
  get_document_summary
```

Incident 项目负责 MCP client 生命周期、能力校验、失败策略与响应适配；`rag-as-mcp` 负责摄取、切分、Dense / BM25 检索、RRF 融合、rerank 和索引。

### 6. 显式知识审核流程

事故复盘中产生的候选知识不会直接写回知识库，而是经过版本化审核流程：

```text
DRAFT -> REVIEWED -> APPROVED -> INGESTED
                   -> REJECTED
```

当前上游 MCP 接口以查询为主，没有暴露 ingestion tool，因此写回能力保留为应用侧 `KnowledgeIngestor` 契约，而不是通过 shell 调用上游脚本绕过边界。

## Agent 职责

| Component | Responsibility |
|---|---|
| Triage Router | 判断请求属于事故、Runbook、沟通还是复盘流程 |
| EscalationAgent | 收集影响范围、严重级别与服务上下文，并推进升级流程 |
| ConsultantAgent | 通过注入的 `Retriever` 获取知识并生成答案 |
| CommunicationAgent | 基于已记录事实生成干系人更新 |
| PostmortemAgent | 基于结构化事件账本生成复盘草稿 |

## RAG 运行模式

```text
RAG_MODE=local
```

使用确定性的本地 `LocalRunbookRetriever`，适合离线测试和开发。

```text
RAG_MODE=auto
```

配置可用时优先启动 MCP；启动或配置失败时回退到本地检索。

```text
RAG_MODE=mcp
```

强制使用 MCP。初始化失败会使启动失败。

MCP 成功初始化后，运行时查询错误会显式暴露，不会静默切换到本地结果。

## 快速开始

完整产品由 FastAPI API 与 React + TypeScript workspace 组成。本地开发使用两个进程：

```bash
git clone https://github.com/Whalefallg/incident-lifecycle-copilot.git
cd incident-lifecycle-copilot

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements-production.txt
cp .env.example .env

# terminal 1
uvicorn app:app --reload --port 8000

# terminal 2
cd frontend
npm ci
npm run dev
```

访问 `http://localhost:5173`。Vite 会将 `/api` 代理到 FastAPI。生产构建由 FastAPI 在 `http://localhost:8000` 直接提供，旧 Jinja UI 保留在 `/legacy`。

单容器构建：

```bash
docker build -t incident-lifecycle-copilot .
docker run --rm -p 8000:8000 --env-file .env incident-lifecycle-copilot
```

镜像使用 Node 构建阶段生成前端静态资源，再复制进精简 Python runtime；生产 Compose 不运行 Vite dev server。

默认使用本地 RAG 时无需启动外部 MCP 服务。

如需接入 `rag-as-mcp`：

```bash
RAG_MODE=mcp
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python
```

## 测试与质量门

安装开发依赖：

```bash
pip install -r requirements-dev.txt
```

运行默认离线测试：

```bash
pytest -q

cd frontend
npm ci
npm run lint
npm run typecheck
npm run test
npx playwright install chromium
npm run test:e2e
npm run build
```

Redis 集成测试：

```bash
REDIS_URL=redis://localhost:6379/0 \
pytest -q -m redis_integration tests/test_redis_conversation_repository.py
```

Live MCP contract 测试：

```bash
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp \
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python \
pytest -q -m live tests/test_live_rag_mcp.py
```

静态质量检查：

```bash
ruff check .
ruff format --check .
mypy
```

GitHub Actions 分别运行 backend、frontend、浏览器 E2E 和 Docker production smoke。浏览器 E2E 使用 mocked API；Docker job 独立验证构建后的 React SPA、FastAPI、深层客户端路由、health 与 legacy 页面。

- **Backend**：Pytest、Ruff、format check、Mypy
- **Frontend**：ESLint、TypeScript typecheck、Vitest、production build、OpenAPI drift check
- **Browser**：Playwright fixture-backed E2E（mocked API / fixture data，不调用 live model）
- **Production Delivery**：Docker build + FastAPI runtime HTTP smoke

## 检索评估

项目提供真实 MCP 边界上的检索评估链路：

```text
dataset
   |
   v
McpRagClient / Retriever
   |
   v
stdio JSON-RPC
   |
   v
query_knowledge_hub
   |
   v
rag-as-mcp
```

运行：

```bash
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp \
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python \
python scripts/benchmark_retrieval.py
```

当前提交的 benchmark artifact 用于验证端到端协议链路；由于测试时上游 `default` collection 未包含对应 golden runbooks，现有结果不应被解释为检索质量结论。质量指标需要在完成固定语料摄取后重新执行。

## 当前限制

- 多 Worker 恢复依赖 Redis；内存 repository 仅适用于单进程开发与测试。
- Redis repository 的跨事故列表查询使用 list scan，适合 demo 规模而非大型生产索引。
- 当前 `rag-as-mcp` MCP surface 主要提供查询能力，尚未提供知识 ingestion tool。
- 知识草稿当前最多推进到 `APPROVED`；缺少上游 ingestion tool 时不会伪造 `INGESTED`。
- 请求 trace 采用有界保留，检索证据仅保存有限结果与正文摘录，不保存模型思维链。
- 上游部分工具错误可能以普通文本返回，因此 adapter 仍包含已验证的错误语义兼容逻辑。
- strict lint / type boundary 当前覆盖 correctness-critical 模块，而不是全部 legacy UI / service 代码。
- 当前 benchmark artifact 尚未使用包含 golden runbooks 的上游 collection。

## 仓库结构

```text
frontend/              React + TypeScript Incident Workspace
api/contracts/         Typed REST / SSE public contracts
services/incidents/    Incident application services 与 SSE 投影
conversation/          Snapshot、Event、Trace、Repository 与 Redis CAS
agents/                Recoverable multi-agent workflow
knowledge/             Knowledge draft 审核生命周期
config/                Runtime 与 RAG MCP 配置
benchmarks/            Golden dataset 与检索评估结果
scripts/               Benchmark 等工程脚本
tests/                 Unit / integration / live contract tests
```

## License

MIT License。详见 [LICENSE](LICENSE)。

---

# English

## Overview

Incident Lifecycle Copilot is a **full-stack AI incident operations workspace** built with React, TypeScript, FastAPI, recoverable multi-agent workflows, Redis CAS and request idempotency, and MCP-based RAG. It covers triage, escalation, runbook retrieval, stakeholder communication, postmortems, and knowledge review.

It is not a mock dashboard disconnected from the backend. The Incident Workspace, conversation, timeline, runbook evidence, agent trace, postmortem review, knowledge review, and observability UI map directly to persisted `ConversationSnapshot`, Incident Event Ledger, Request Trace, Retrieval Evidence, and Knowledge Draft Lifecycle state.

Recoverable state belongs in a versioned `ConversationSnapshot`, not a long-lived Python Agent object. This allows requests to move across workers while preserving correctness through optimistic concurrency control and idempotent request handling.

The project integrates with [`rag-as-mcp`](https://github.com/Whalefallg/rag-as-mcp) through MCP, keeping agent orchestration and retrieval infrastructure cleanly separated.

## Highlights

- **Full-stack Incident Workspace** — React and TypeScript provide the incident workspace, conversation, timeline, runbook evidence, agent trace, postmortem and knowledge review, and observability over real backend state.
- **Recoverable multi-agent workflows** — request-scoped Agents are disposable; the interruptible FSM and business context are rebuilt from `ConversationSnapshot`.
- **Typed REST + SSE delivery** — OpenAPI generates the TypeScript contract; typed SSE carries request progress and committed results, while FastAPI serves both the API and production SPA.
- **MCP-based RAG integration** — a backend-neutral `Retriever` contract isolates hybrid retrieval from MCP lifecycle, protocol, and failure handling.
- **Cross-worker recovery** — Redis revision compare-and-set allows independent workers to recover and update the same incident safely.
- **Concurrency and idempotency** — CAS rejects stale writes, while request IDs and payload fingerprints prevent duplicate execution and key misuse.
- **Structured Incident Event Ledger** — operational facts are persisted before timelines, communications, and postmortems are generated.
- **Agent execution trace** — the UI exposes actual participating Agents, actions, status, duration, and bounded retrieval evidence without model chain-of-thought.
- **Reviewed knowledge lifecycle** — drafts move through `DRAFT → REVIEWED → APPROVED → INGESTED / REJECTED`; without a real ingestor they stop at `APPROVED`.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, React Router, TanStack Query, Zustand |
| Backend | FastAPI, Pydantic, Python |
| State / Concurrency | `ConversationSnapshot`, Redis CAS, request idempotency |
| AI Workflow | Recoverable multi-agent workflow, LangChain, OpenAI-compatible models |
| Retrieval | MCP, `rag-as-mcp`, hybrid RAG |
| Observability | Agent Trace, Incident Event Ledger, typed SSE |
| Testing | Pytest, Vitest, Playwright |
| Delivery | Multi-stage Docker, GitHub Actions |

## Architecture

```text
React + TypeScript Incident Workspace
├── Incident List / Workspace     ├── Conversation / Timeline
├── Runbook Evidence / Agent Trace
└── Postmortem / Knowledge Review / Observability
                    |
                    | Typed REST + SSE
                    v
FastAPI → Incident Application Services
                    |
                    v
         ConversationCoordinator
                    |
                    v
         ConversationRepository
                    |
                    v
         ConversationSnapshot
      ├── Request Trace / Retrieval Evidence
      ├── Incident Event Ledger / Knowledge Lifecycle
      └── Redis CAS / Request Idempotency
                    |
                    v
       Disposable Multi-Agent Workflow
      ├── EscalationAgent      ├── ConsultantAgent
      ├── CommunicationAgent   └── PostmortemAgent
                    |
                    v
          Retriever / MCP → rag-as-mcp
```

SSE carries typed request progress and committed results; it is not presented as real-time token streaming. `request.completed` means the snapshot is durable, after which the frontend refreshes messages, timeline, retrieval evidence, trace, and postmortem queries for that incident. See [`docs/FULLSTACK_ARCHITECTURE.md`](docs/FULLSTACK_ARCHITECTURE.md) and [`docs/FULLSTACK_DEMO.md`](docs/FULLSTACK_DEMO.md).

Agent names represent responsibility boundaries, not long-lived stateful services. A fresh request graph is created from the latest `ConversationSnapshot`, executed, and then persisted with an expected revision.

## Key Engineering Decisions

### 1. Snapshot as the Recovery Source of Truth

`ConversationSnapshot` contains the complete state required to reconstruct an incident conversation:

- schema version, session ID, and revision
- current FSM state and suspend stack
- escalation and postmortem contexts
- messages and structured incident events
- completed request results used for idempotency
- creation and update timestamps

This keeps Agents disposable and prevents workflow correctness from depending on a specific process or object instance.

### 2. Optimistic Concurrency and Request Idempotency

`RedisConversationRepository.save(snapshot, expected_revision)` performs an atomic compare-and-set.

If multiple workers attempt to update the same conversation from an old revision, the stale writer receives `ConcurrentConversationUpdate` instead of overwriting newer state.

Stable request IDs are also bound to canonical payload fingerprints:

- same request ID + same payload → reuse the completed result
- same request ID + different payload → raise `IdempotencyKeyMismatch`

Retries therefore do not duplicate events or advance the workflow twice.

### 3. Interruptible and Recoverable FSM

The FSM represents **workflow position only**. Typed business data remains in dedicated contexts.

An escalation may be suspended for an inserted runbook question:

```text
Escalation
    |
    | suspend
    v
Runbook Question
    |
    | resume
    v
Escalation
```

Both the suspend stack and escalation context are persisted, so one worker can answer the runbook question and another worker can resume the original flow.

### 4. Structured Incident Event Ledger

Runtime facts are recorded as typed `IncidentEvent` entries with stable IDs, incident IDs, timestamps, actors, sources, request IDs, event types, and payloads.

Postmortem timelines are derived from this ledger instead of reconstructing facts from free-form chat history. Recorded observations remain separate from generated root-cause analysis.

### 5. Retrieval Is Decoupled from Agent Orchestration

Incident Lifecycle Copilot depends on an abstract `Retriever` contract.

The primary external backend is [`rag-as-mcp`](https://github.com/Whalefallg/rag-as-mcp), with the currently verified MCP contract:

```text
transport: stdio
entrypoint: python main.py

initialize
ping
tools/list
tools/call

required:
  query_knowledge_hub(query, top_k, collection)

optional:
  list_collections
  get_document_summary
```

This repository owns the MCP client lifecycle, capability validation, failure policy, and response adaptation. `rag-as-mcp` owns ingestion, chunking, dense and BM25 retrieval, RRF fusion, reranking, and indexes.

### 6. Explicit Knowledge Review

Knowledge derived from incident response is not written directly into the knowledge base.

Drafts follow a versioned review lifecycle:

```text
DRAFT -> REVIEWED -> APPROVED -> INGESTED
                   -> REJECTED
```

The current upstream MCP surface is query-oriented and does not expose an ingestion tool, so write-back remains behind the application-side `KnowledgeIngestor` contract rather than bypassing the boundary through shell execution.

## Agent Responsibilities

| Component | Responsibility |
|---|---|
| Triage Router | Route incident, runbook, communication, and postmortem requests |
| EscalationAgent | Collect impact and severity context and advance escalation |
| ConsultantAgent | Retrieve operational knowledge through an injected `Retriever` |
| CommunicationAgent | Draft stakeholder updates from persisted facts |
| PostmortemAgent | Build postmortem drafts from the structured event ledger |

## RAG Modes

```text
RAG_MODE=local
```

Uses the deterministic `LocalRunbookRetriever` for offline development and tests.

```text
RAG_MODE=auto
```

Uses MCP when configured and falls back to local retrieval if startup or configuration fails.

```text
RAG_MODE=mcp
```

Requires MCP. Initialization failure is fatal.

Once MCP has initialized successfully, runtime query failures are explicit and do not silently fall back to local results.

## Quick Start

The complete product consists of the FastAPI API and a React + TypeScript incident workspace. Local development uses two processes:

```bash
git clone https://github.com/Whalefallg/incident-lifecycle-copilot.git
cd incident-lifecycle-copilot

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements-production.txt
cp .env.example .env

# terminal 1
uvicorn app:app --reload --port 8000

# terminal 2
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`; Vite proxies `/api` to FastAPI. The production build is served by FastAPI at `http://localhost:8000`, while the former Jinja UI remains available at `/legacy`.

Single-container build:

```bash
docker build -t incident-lifecycle-copilot .
docker run --rm -p 8000:8000 --env-file .env incident-lifecycle-copilot
```

The image builds the frontend in a Node stage and copies only the compiled assets into the Python runtime. Production Compose does not run a Vite development server.

For MCP-backed retrieval:

```bash
RAG_MODE=mcp
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python
```

## Testing and Quality Gates

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the default offline suite:

```bash
pytest -q

cd frontend
npm ci
npm run lint
npm run typecheck
npm run test
npx playwright install chromium
npm run test:e2e
npm run build
```

Redis integration tests:

```bash
REDIS_URL=redis://localhost:6379/0 \
pytest -q -m redis_integration tests/test_redis_conversation_repository.py
```

Live MCP contract tests:

```bash
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp \
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python \
pytest -q -m live tests/test_live_rag_mcp.py
```

Static quality checks:

```bash
ruff check .
ruff format --check .
mypy
```

GitHub Actions runs independent backend, frontend, browser E2E, and Docker production-smoke jobs. Browser E2E uses a mocked API; the Docker job separately verifies the built React SPA, FastAPI API, deep client routes, health endpoint, and legacy page.

- **Backend:** Pytest, Ruff, format check, and Mypy
- **Frontend:** ESLint, TypeScript typecheck, Vitest, production build, and OpenAPI drift check
- **Browser:** Playwright fixture-backed E2E with mocked API and fixture data, not a live model
- **Production Delivery:** Docker build plus FastAPI runtime HTTP smoke

## Retrieval Evaluation

The benchmark exercises the real retrieval boundary:

```text
dataset
   |
   v
McpRagClient / Retriever
   |
   v
stdio JSON-RPC
   |
   v
query_knowledge_hub
   |
   v
rag-as-mcp
```

Run it with:

```bash
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp \
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python \
python scripts/benchmark_retrieval.py
```

The currently committed benchmark artifact demonstrates end-to-end protocol execution. The upstream `default` collection used in that run did not contain the Incident golden runbooks, so the stored result should not be interpreted as a retrieval-quality claim. Quality metrics should be rerun after ingesting the fixed benchmark corpus.

## Current Limitations

- Multi-worker recovery requires Redis; in-memory repositories are intended for single-process development and tests.
- Cross-incident Redis listings use list scans and are intended for demo-scale data, not large production indexes.
- The current `rag-as-mcp` MCP surface is primarily query-oriented and does not expose a knowledge-ingestion tool.
- Knowledge drafts stop at `APPROVED` when that upstream ingestion capability is absent; the system does not claim `INGESTED`.
- Request traces have bounded retention, and retrieval evidence stores bounded result excerpts rather than model chain-of-thought.
- Some upstream tool failures may still arrive as ordinary text, so the adapter contains compatibility logic for verified error messages.
- Strict lint and type checking currently targets correctness-critical modules rather than every legacy UI and service module.
- The committed retrieval benchmark has not yet been rerun against an upstream collection containing the golden runbooks.

## Repository Structure

```text
frontend/              React + TypeScript Incident Workspace
api/contracts/         typed REST / SSE public contracts
services/incidents/    incident application services and SSE projection
conversation/          snapshots, events, traces, repositories, and Redis CAS
agents/                recoverable multi-agent workflow
knowledge/             reviewed knowledge-draft lifecycle
config/                runtime and RAG MCP configuration
benchmarks/            golden retrieval dataset and result artifacts
scripts/               benchmark and engineering utilities
tests/                 unit, integration, and live contract coverage
```

## License

Licensed under the [MIT License](LICENSE).
