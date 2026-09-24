# 完整流程演示：Runbook 查询（/chat 流式接口）

## 场景：工程师问 "what's the runbook for checkout errors?"

---

## 请求入口

```
POST /chat
{
  "message": "what's the runbook for checkout errors?",
  "session_id": "engineer-001"
}
```

---

## ① API Layer（api/chat_handler.py）

```python
async def ProcessUserInput_stream(user_input, state=None, context=None):
    # 记录进 PostmortemAgent 会话历史
    _postmortem_agent.add_session_message(role="engineer", content=user_input)

    new_trace_id()
    async for token in task_agent.classify_task_stream(user_input):
        yield token
```

---

## ② TaskClassificationAgent — 意图分类

```python
# agents/task_classification/task_classifier.py
category = await self.chain.ainvoke({"task": user_input})
# "what's the runbook for checkout errors?" → "query"
```

LLM 输出 `"query"` → `ClassificationProcessor` 路由到 `route_to_runbook()`。

---

## ③ AgentRouter → ConsultantAgent

```python
# agents/task_classification/agent_router.py
async def route_to_runbook(self, task):
    self.state_manager.transition_to_runbook_lookup()
    yield "[THOUGHT][Triage Router] Knowledge query — routing to Runbook Agent."

    async with self.consultant_agent as agent:
        async for token in agent.consult_stream(task):
            yield token
```

`async with consultant_agent` 触发 `__aenter__` → `KnowledgeRetriever.initialize()` → `McpRagClient.start()` 启动 MCP Server subprocess。

---

## ④ McpRagClient — MCP stdio 通信

```python
# agents/consultant/mcp_rag_client.py
results = await self._call_tool(
    "query_knowledge_hub",
    {"query": "checkout errors runbook", "top_k": 5, "collection": "default"},
)
```

JSON-RPC 请求（写入 subprocess stdin）：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "query_knowledge_hub",
    "arguments": {
      "query": "checkout errors runbook",
      "top_k": 5,
      "collection": "default"
    }
  }
}
```

---

## ⑤ MODULAR-RAG-MCP-SERVER 内部（独立进程）

```
HybridSearch.search("checkout errors runbook", top_k=5)
  ├─ DenseRetriever: 向量相似度检索（当前 MCP Server 配置为 Chroma）
  ├─ SparseRetriever: BM25 关键词检索
  ├─ RRF Fusion: 倒数排名融合两路结果
  └─ Reranker: Cross-Encoder 精排（backend=none 时透传）

ResponseBuilder.build(results, query, image_contents)
  → Markdown 格式内容 + 来源引用
```

JSON-RPC 响应（写入 subprocess stdout）：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "## checkout-error-rate-high Runbook\n\n**Alert:** checkout-service error rate > 5%\n**Severity:** P0\n\n### Symptoms\n- Error rate spike above 5% threshold\n- Payment failures in us-east-1\n\n### Resolution Steps\n1. Check Datadog APM for error breakdown\n2. Verify payment-gateway health: `curl https://payment-gateway.internal/healthz`\n3. Review recent deploys in Spinnaker\n4. If circuit breaker tripped: restart with `kubectl rollout restart deployment/checkout-service`\n\n### Past Incidents\n- INC-2024-0425 (28 min): Payment gateway circuit breaker tripped\n- INC-2024-0301 (12 min): Bad deploy, rolled back\n\n**Source:** checkout-error.yaml"
      }
    ],
    "isError": false
  }
}
```

---

## ⑥ ConsultationProcessor → ResponseGenerator

```python
# agents/consultant/consultation_processor.py
knowledge_docs = await self.knowledge_retriever.search_knowledge(
    user_input, top_k=5
)
# knowledge_docs = [
#   {
#     "content": "## checkout-error-rate-high Runbook\n...",
#     "source": "modular-rag-mcp-server",
#     "score": 1.0,
#     "category": "runbook"
#   }
# ]

async for token in self.response_generator.generate_response_stream(
    user_input, knowledge_docs
):
    yield token
```

`PromptBuilder.build_consultation_prompt()` 将检索到的 runbook 内容注入 system prompt：

```
[System] You are the Runbook & Incident Memory Agent...
[Context]
=== Retrieved Runbooks & Incident Memory ===
[1] (score=1.000, category=runbook)
## checkout-error-rate-high Runbook
...
=== End of Retrieved Context ===

Engineer query: what's the runbook for checkout errors?
Provide your answer:
```

LLM 基于检索内容流式生成回答。

---

## 完整层级调用链

```
HTTP 请求
  ↓
API Layer (chat_handler.py)
  → 会话历史记录
  → task_agent.classify_task_stream()
  ↓
TaskClassificationAgent
  → TaskClassifier (LLM) → "query"
  → AgentRouter.route_to_runbook()
  ↓
ConsultantAgent (async with → MCP Server 启动)
  → ConsultationClassifier → is in scope
  → ConsultationProcessor
      → KnowledgeRetriever.search_knowledge()
          → McpRagClient.query()             [JSON-RPC over stdio]
          → MODULAR-RAG-MCP-SERVER           [独立进程]
              → HybridSearch + RRF + Reranker
              → ResponseBuilder
          ← content[]
      → ResponseGenerator.generate_response_stream()
          → PromptBuilder (注入检索内容)
          → LLM 流式生成
  ↓
StreamingResponse → 逐 token 推送浏览器
```

---

## 响应示例（流式 token 时间线）

```
T=0.0s  [THOUGHT][Triage Router] Knowledge query — routing to Runbook Agent.
T=0.3s  [THOUGHT][RunbookAgent] Querying MCP RAG Server...
T=0.9s  [REPLY][RunbookAgent] Based on the checkout-error-rate-high runbook:

T=1.0s  **Immediate Steps:**
T=1.1s  1. Check Datadog APM for error breakdown — look for payment-gateway timeouts
T=1.2s  2. Verify payment-gateway health...
...
T=3.5s  **Past Incidents:** INC-2024-0425 (circuit breaker, 28 min resolution)...
T=3.6s  (流结束)
```

---

## 关键设计原则

| 层级 | 职责 | 禁止 |
|---|---|---|
| API | 入口 + 会话历史 | 写业务逻辑 |
| TaskClassificationAgent | 分类 + 路由 | 直接访问 DB |
| ConsultantAgent | RAG 流程编排 | 绕过 McpRagClient 直接调 FAISS |
| McpRagClient | MCP 通信抽象 | 业务逻辑 |
| MODULAR-RAG-MCP-SERVER | 检索 + 排序 | 感知 Agent 业务状态 |

**扩展性**：替换检索后端（ChromaDB → Pinecone）只需修改 MCP Server 配置，`McpRagClient` 和 `ConsultantAgent` 无需改动。
