# 代码走查：完整请求链路

## 场景：工程师问 "checkout 的 runbook 是什么？"

---

## 第1站：API 层入口（api/chat_handler.py）

```python
# api/chat_handler.py

async def ProcessUserInput_stream(user_input, state=None, context=None):
    if context is None:
        context = {}

    # 每条消息都记录进 PostmortemAgent 的会话历史
    _postmortem_agent.add_session_message(role="engineer", content=user_input)

    new_trace_id()
    with trace_step("classify_and_route", agent="TriageRouter"):
        response_tokens = []
        async for token in task_agent.classify_task_stream(user_input):
            response_tokens.append(token)
            yield token

    # Agent 回复也记录进会话历史（供 PostmortemAgent 用）
    _postmortem_agent.add_session_message(
        role="agent", content="".join(response_tokens)
    )
```

用户输入 `"checkout 的 runbook 是什么？"` → `ProcessUserInput_stream` → `task_agent.classify_task_stream()`。

---

## 第2站：TaskClassificationAgent（TriageRouter）

```python
# agents/task_classification_agent.py
class TaskClassificationAgent:
    def __init__(self, escalation_agent, consultant_agent,
                 communication_agent, postmortem_agent):
        self.state_manager = StateManager(SharedState())
        self.task_classifier = TaskClassifier(self.llm)   # LLM 分类
        self.agent_router = AgentRouter(...)
        self.classification_processor = ClassificationProcessor(...)
```

`classify_task_stream` 调用 `ClassificationProcessor.process_task_stream()`：

```python
# agents/task_classification/classification_processor.py
async def process_task_stream(self, task):
    if self.state_manager.get_current_state() != StateEnum.CLASSIFY:
        # 已在某流程中，不重新分类，直接续
        async for token in self.agent_router.route_by_state(task):
            yield token
        return

    # 当前在 CLASSIFY 状态，LLM 分类意图
    category = await self.task_classifier.classify_task(task)
    # "checkout 的 runbook 是什么？" → category = "query"

    async for token in self.agent_router.route_to_runbook(task):
        yield token
```

---

## 第3站：AgentRouter 路由到 ConsultantAgent

```python
# agents/task_classification/agent_router.py
async def route_to_runbook(self, task):
    self.state_manager.transition_to_runbook_lookup()
    yield "[THOUGHT][Triage Router] Knowledge query — routing to Runbook Agent."

    async with self.consultant_agent as agent:
        async for token in agent.consult_stream(task):
            yield token
```

`async with consultant_agent` 触发 `__aenter__`，启动 MCP RAG Server subprocess。

---

## 第4站：ConsultantAgent → KnowledgeRetriever → McpRagClient

```python
# agents/consultant_agent.py
async def __aenter__(self):
    await self.knowledge_retriever.initialize()   # spawn MCP Server subprocess
    return self

async def consult_stream(self, user_input):
    is_consultation = await self.consultation_classifier.is_consultation_related(user_input)
    if not is_consultation:
        async for token in self.consultation_processor.handle_unrelated_request(...):
            yield token
        return

    async for token in self.consultation_processor.process_consultation_stream(
        user_input, self.session_id
    ):
        yield token
    self._reset_state_after_consultation()
```

```python
# agents/consultant/knowledge_retriever.py
async def initialize(self):
    await self._client.start()   # McpRagClient.start()

async def search_knowledge(self, query, top_k=5):
    results = await self._client.query(query, top_k=top_k)
    return results
```

---

## 第5站：McpRagClient — MCP stdio 通信

```python
# agents/consultant/mcp_rag_client.py
async def start(self):
    self._process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "src.mcp_server.server",
        stdin=PIPE, stdout=PIPE, stderr=PIPE,
        cwd=str(self._server_path),        # RAG_MCP_SERVER_PATH
    )
    await self._initialize()              # MCP handshake

async def query(self, query, top_k=5, collection="default"):
    return await self._call_tool(
        "query_knowledge_hub",
        {"query": query, "top_k": top_k, "collection": collection},
    )

async def _send_request(self, method, params):
    async with self._lock:
        req = json.dumps({"jsonrpc": "2.0", "id": self._req_id,
                          "method": method, "params": params}) + "\n"
        self._process.stdin.write(req.encode())
        await self._process.stdin.drain()

        while True:
            line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=30.0
            )
            msg = json.loads(line.decode())
            if msg.get("id") == self._req_id:
                return msg
```

**MCP Server 内部流程**（MODULAR-RAG-MCP-SERVER）：

```
tools/call: query_knowledge_hub
  → HybridSearch.search(query, top_k, collection)
      → DenseRetriever  (FAISS / ChromaDB embedding 检索)
      → SparseRetriever (BM25 关键词检索)
      → RRF Fusion      (倒数排名融合)
      → Reranker        (Cross-Encoder 精排，backend=none 时透传)
  → ResponseBuilder     (构建 Markdown + 引用来源)
  → 返回 content[]
```

---

## 第6站：ConsultationProcessor → ResponseGenerator

```python
# agents/consultant/consultation_processor.py
async def process_consultation_stream(self, user_input, session_id):
    with trace_step("mcp_rag_query", agent="ConsultantAgent"):
        knowledge_docs = await self.knowledge_retriever.search_knowledge(
            user_input, top_k=5
        )
    # knowledge_docs = [
    #   {"content": "## checkout-error-rate-high Runbook\n...", "source": "modular-rag-mcp-server", "score": 1.0}
    # ]

    with trace_step("response_generation_stream", agent="ConsultantAgent"):
        async for token in self.response_generator.generate_response_stream(
            user_input, knowledge_docs
        ):
            yield token
```

```python
# agents/consultant/prompt_builder.py
def build_consultation_prompt(self, user_input, knowledge_docs):
    context = self._build_knowledge_context(knowledge_docs)
    # context 包含从 MCP Server 检索回来的 Markdown 格式 runbook 内容
    return f"{self.system_prompt}\n\n{context}\nEngineer query: {user_input}\n\nProvide your answer:"
```

---

## 完整调用地图

```
① API 层
   ProcessUserInput_stream()
   ↓
② TaskClassificationAgent（TriageRouter）
   classify_task_stream()
   ↓ LLM 分类 → "query"
③ AgentRouter
   route_to_runbook()
   ↓
④ ConsultantAgent
   consult_stream()
   ↓
⑤ KnowledgeRetriever
   search_knowledge()
   ↓
⑥ McpRagClient
   query("checkout runbook", top_k=5)
   ↓ JSON-RPC 2.0 over stdio
⑦ MODULAR-RAG-MCP-SERVER（独立进程）
   HybridSearch → RRF → Reranker → ResponseBuilder
   ↓ content[]
⑧ ConsultationProcessor
   generate_response_stream()
   ↓ 用检索内容构建 prompt → LLM 流式生成
⑨ StreamingResponse
   逐 token 推送到浏览器
```

---

## 关键要点

| 层 | 职责 | 核心文件 |
|---|---|---|
| API | 请求入口、会话历史记录、流式响应 | `api/chat_handler.py` |
| TaskClassificationAgent | 意图分类 + 路由 | `agents/task_classification_agent.py` |
| ConsultantAgent | RAG 流程编排 + 回答生成 | `agents/consultant_agent.py` |
| McpRagClient | MCP subprocess 通信 | `agents/consultant/mcp_rag_client.py` |
| MODULAR-RAG-MCP-SERVER | Hybrid Search + Rerank | 独立进程 |

**与旧版的关键区别**：RAG 检索不再在 `services/knowledge_service.py` 内的 FAISS，而是通过 MCP 协议委托给独立进程，检索质量从 Dense-only 升级为 Hybrid + Rerank。
