# Incident Lifecycle Copilot

面向生产事故生命周期的可恢复 Agent 协作系统：覆盖事故分诊、升级、Runbook 检索、干系人沟通、复盘生成与知识审核，并将跨请求、跨 Worker 的一致性作为核心设计目标。

**中文** · [English](#english)

---

# 中文

## 项目简介

Incident Lifecycle Copilot 将事故响应从一次性的 LLM 对话，建模为一组**可恢复、可验证、可审计的工作流**。

系统围绕事故处理中的关键环节组织多个职责明确的 Agent，包括分诊、升级、知识检索、沟通和复盘。与依赖进程内 Agent 状态的实现不同，本项目将完整会话状态持久化为版本化 `ConversationSnapshot`，使任意 Worker 都能够恢复当前工作流，并通过乐观并发控制与幂等机制保证重试和并发请求下的正确性。

项目同时通过 MCP 对接独立的 [`rag-as-mcp`](https://github.com/Whalefallg/rag-as-mcp) 检索服务，使 Agent 编排与 RAG 基础设施保持清晰边界。

## 核心能力

- **可恢复 Agent 工作流**：请求级 Agent 为一次性对象，状态由持久化快照恢复，而不是保存在 Python 对象中。
- **跨 Worker 会话恢复**：支持通过 Redis CAS 在多 Worker 环境中恢复、继续和更新同一事故会话。
- **可中断 FSM**：事故升级流程可被临时 Runbook 查询挂起，查询结束后恢复原工作流。
- **并发与幂等保护**：使用 revision compare-and-set 拒绝 stale write，并通过 request ID + payload fingerprint 防止重复执行和幂等键误用。
- **结构化 Incident Event Ledger**：先持久化事实，再基于事件生成时间线、沟通内容和复盘草稿。
- **MCP RAG 集成**：通过稳定 `Retriever` 契约接入独立的混合检索服务，并隔离 MCP 生命周期、协议与错误处理。
- **知识审核闭环**：知识草稿经过 `DRAFT → REVIEWED → APPROVED → INGESTED / REJECTED` 生命周期后才能进入知识库。

## 架构

```text
FastAPI / request_id
        |
        v
ConversationCoordinator
        |
        v
ConversationRepository ---------------- InMemory / Redis CAS
        |
        v
ConversationSnapshot
        |
        +---- Triage Router / FSM
        +---- EscalationAgent
        +---- ConsultantAgent ---------- Retriever ---------- rag-as-mcp
        +---- CommunicationAgent
        +---- PostmortemAgent
        |
        +---- Structured Incident Event Ledger
        |
        +---- Reviewed Knowledge Lifecycle
```

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

GitHub Actions 当前在 Python 3.11 上运行离线测试套件，并关闭外部 Redis、Semantic Cache 与 Model Routing 依赖，以保证 CI 可重复执行。

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
- 当前 `rag-as-mcp` MCP surface 主要提供查询能力，尚未提供知识 ingestion tool。
- 上游部分工具错误可能以普通文本返回，因此 adapter 仍包含已验证的错误语义兼容逻辑。
- strict lint / type boundary 当前覆盖 correctness-critical 模块，而不是全部 legacy UI / service 代码。
- 当前 benchmark artifact 尚未使用包含 golden runbooks 的上游 collection。

## 仓库结构

```text
agents/           Agent 与工作流职责
api/              HTTP API 与 ConversationCoordinator
conversation/     Snapshot、Event、Repository 与 Redis CAS
knowledge/        Knowledge draft 审核生命周期
config/           Runtime 与 RAG MCP 配置
benchmarks/       Golden dataset 与检索评估结果
scripts/          Benchmark 等工程脚本
tests/            Unit / integration / live contract tests
```

## License

MIT License。详见 [LICENSE](LICENSE)。

---

# English

## Overview

Incident Lifecycle Copilot models incident response as a set of **recoverable, testable, and auditable agent workflows** rather than a single stateful LLM conversation.

The system coordinates triage, escalation, runbook consultation, stakeholder communication, postmortem drafting, and reviewed knowledge promotion. Its central design principle is that recoverable state belongs in a versioned `ConversationSnapshot`, not inside a long-lived Python Agent object.

This allows requests to move across workers while preserving correctness through optimistic concurrency control and idempotent request handling.

The project integrates with [`rag-as-mcp`](https://github.com/Whalefallg/rag-as-mcp) through MCP, keeping agent orchestration and retrieval infrastructure cleanly separated.

## Highlights

- **Recoverable agent workflows** — request-scoped Agents are disposable and rebuilt from persisted snapshots.
- **Cross-worker recovery** — Redis CAS allows independent workers to continue the same incident conversation safely.
- **Interruptible FSM** — an active escalation can be suspended for a runbook question and resumed later.
- **Concurrency and idempotency** — revision checks reject stale writes, while request IDs and payload fingerprints protect retries.
- **Structured incident event ledger** — operational facts are persisted before timelines, communications, and postmortems are generated.
- **MCP-based RAG integration** — retrieval is isolated behind a backend-neutral `Retriever` contract.
- **Reviewed knowledge lifecycle** — generated knowledge must pass explicit review and approval before ingestion.

## Architecture

```text
FastAPI / request_id
        |
        v
ConversationCoordinator
        |
        v
ConversationRepository ---------------- InMemory / Redis CAS
        |
        v
ConversationSnapshot
        |
        +---- Triage Router / FSM
        +---- EscalationAgent
        +---- ConsultantAgent ---------- Retriever ---------- rag-as-mcp
        +---- CommunicationAgent
        +---- PostmortemAgent
        |
        +---- Structured Incident Event Ledger
        |
        +---- Reviewed Knowledge Lifecycle
```

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

GitHub Actions runs independent backend, frontend, fixture-backed Playwright, and Docker build jobs. The E2E scenario uses a fake model stream and fixture RAG data, so CI never depends on paid model APIs.

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
- The current `rag-as-mcp` MCP surface is primarily query-oriented and does not expose a knowledge-ingestion tool.
- Some upstream tool failures may still arrive as ordinary text, so the adapter contains compatibility logic for verified error messages.
- Strict lint and type checking currently targets correctness-critical modules rather than every legacy UI and service module.
- The committed retrieval benchmark has not yet been rerun against an upstream collection containing the golden runbooks.

## Repository Structure

```text
agents/           agent and workflow responsibilities
api/              HTTP API and conversation coordination
conversation/     snapshots, events, repositories, and Redis CAS
knowledge/        reviewed knowledge-draft lifecycle
config/           runtime and RAG MCP configuration
benchmarks/       golden retrieval dataset and result artifacts
scripts/          benchmark and engineering utilities
tests/            unit, integration, and live contract coverage
```

## License

Licensed under the [MIT License](LICENSE).
