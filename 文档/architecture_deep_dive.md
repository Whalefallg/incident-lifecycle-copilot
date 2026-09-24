# Incident Lifecycle Copilot — 架构深度解析

> 面试前速览：设计决策、数据流、状态机、RAG/MCP细节、失败模式与追问应答。
> 配套走查文档：`code_walkthrough.md`（单 Agent 链路）、`multi_agent_walkthrough.md`（多 Agent 协同）、`incident_lifecycle_walkthrough.md`（完整事件演练）。

---

## 一、项目是什么？

**一句话**：面向工程团队的 **Multi-Agent 事件响应副驾驶** —— 工程师用自然语言描述情况，系统自动判断意图，分发给专用 Agent 完成告警分诊、on-call 升级、多受众沟通更新或事后复盘生成。

**业务价值**（面试开场可用）：

| 传统痛点 | 本系统如何解决 |
|---|---|
| 告警来了手动判断严重等级，查 on-call 名单 | EscalationAgent 自动抽取 severity/service，`domain_knowledge.py` 字典匹配 on-call |
| Runbook 分散多系统，检索靠关键词 | Modular RAG MCP Server：混合检索（Dense + BM25 + RRF + Rerank）|
| 面向工程师、客服、高管要写三份沟通稿 | CommunicationAgent + StakeholderFormatter 三类受众差异化输出 |
| 事后 Postmortem 靠人工整理时间线 | PostmortemAgent 从会话历史自动重建时间线，无需外部集成 |

**技术栈速览**：FastAPI · LangChain · Modular RAG MCP Server (Hybrid Search) · SQLite · AsyncGenerator 流式输出 · 多 Provider LLM。

---

## 二、五层架构：为什么这样分？

```text
Web/Application  →  API  →  Agents  →  Services  →  DB
```

| 层 | 目录 | 职责 | 禁止做的事 |
|---|---|---|---|
| Web | `web/`, `app.py` | 页面渲染、流式 HTTP | 绕过 API 直接调 Services/DB |
| API | `api/` | 请求校验、响应封装、路由编排 | 写业务逻辑 |
| Agents | `agents/` | 意图理解、多轮对话、Agent 编排 | 绕过 Services 直接访问 DB |
| Services | `services/` | 行为记录、embedding 工具函数 | 反向调用 Agents/API |
| DB | `db/` | ORM 模型、Repository 数据访问 | 包含业务判断 |

> **注意**：RAG 检索不再在 Services 层，已迁移到独立的 **Modular RAG MCP Server** 进程。`KnowledgeRetriever` 通过 `McpRagClient`（subprocess stdio）调用它；仓库仍保留 `KnowledgeService` 的旧实现，但它不在当前 Runbook 查询热路径上。

---

## 三、Multi-Agent 编排：中心化 Hub-and-Spoke

```text
                    TaskClassificationAgent（TriageRouter）
                   /          |           |            \
         EscalationAgent  ConsultantAgent  CommunicationAgent  PostmortemAgent
```

- **入口**：`api/chat_handler.py` 实例化所有 Agent，交给 `TaskClassificationAgent` 统一调度。
- **路由逻辑**：`agents/task_classification/agent_router.py`
- **状态管理**：`agents/task_classification/state_manager.py` + `config/constants.py` 的 `StateEnum`

### 状态机设计

```text
CLASSIFY ──(escalation)──→ ESCALATION
   │                             │
   │(query)          (完成/无关回流)
   ▼                             ▼
RUNBOOK_LOOKUP ──────────→ CLASSIFY
   │
   │(comms_update)
   ▼
COMMS_DRAFTING ──────────→ CLASSIFY
   │
   │(postmortem)
   ▼
POSTMORTEM ──────────────→ CLASSIFY
```

**关键设计**：

1. **多轮不重新分类**：进入 `ESCALATION` 后，后续补充信息直接交给 `EscalationAgent` 继续收集，不重新走 LLM 分类。
2. **无关请求回流**：工程师在升级流程中问 runbook → `unrelated_callback` → 重置为 `CLASSIFY` → 重新路由到 `ConsultantAgent`。
3. **确认等待不过早 reset**：`awaiting_confirmation` 标志位让 EscalationAgent 在等用户确认 on-call 推荐时保持状态。

---

## 四、RAG 流水线（Modular RAG MCP Server）

### 4.1 架构变化

原来 RAG 逻辑嵌在 `services/knowledge_service.py`（SQLite + FAISS IndexFlatIP，仅 Dense 检索）。

**现在**：RAG 迁移到独立的 **Modular RAG MCP Server** 进程：

```
ConsultantAgent
  └─ KnowledgeRetriever
      └─ McpRagClient  (agents/consultant/mcp_rag_client.py)
          └─ subprocess: python -m src.mcp_server.server  [MODULAR-RAG-MCP-SERVER]
              └─ tools/query_knowledge_hub
                  └─ HybridSearch: Dense + BM25 + RRF Fusion
                      └─ Reranker (Cross-Encoder / LLM / none)
```

### 4.2 为什么迁移到 MCP？

| 关注点 | 嵌入式 FAISS | Modular RAG MCP Server |
|---|---|---|
| 检索质量 | 仅 Dense | Dense + BM25 + Rerank |
| 可观测性 | 无 | 全链路 ingestion + query trace |
| 评估 | 无 | Ragas + Golden Test Set |
| 职责分离 | RAG 逻辑混在 Agent 层 | Agent 编排；RAG Server 检索 |
| 独立迭代 | 改 RAG 要改 Agent | 两个进程独立演进 |

### 4.3 McpRagClient 工作原理

- **启动**：`ConsultantAgent.__aenter__` 调用 `KnowledgeRetriever.initialize()` → `McpRagClient.start()` spawn subprocess
- **请求**：JSON-RPC 2.0 over stdin/stdout，`asyncio.Lock` 保证并发安全
- **响应解析**：`_parse_query_response()` 将 MCP `content[]` 转为 `{content, source, score, category}` 列表
- **重连**：进程意外退出时自动重启
- **超时**：30 秒 timeout，出错返回空列表，ConsultantAgent 降级处理

### 4.4 RAG 评估指标（面试必答）

| 指标 | 含义 |
|---|---|
| Hit Rate@K | Top-K 是否包含正确文档 |
| MRR | 正确文档的平均倒数排名 |
| Context Precision | 检索结果中有用片段的比例 |
| Faithfulness | 回答是否忠于检索内容 |
| Answer Relevance | 回答是否针对问题 |

Modular RAG MCP Server 内置 Ragas 评估框架 + Golden Test Set 回归测试。

---

## 五、EscalationAgent：结构化抽取 + 字典匹配

### 5.1 核心流程

```
InputParser（LLM 结构化抽取）
  → 更新 incident_history（severity / service / impact_scope / symptoms / suspected_cause / recent_changes）
  → 判断必填字段完整性（severity + service 必填）
  → 完整 → OnCallMatcher（字典规则匹配）→ 升级确认消息
  → 不完整 → MessageBuilder 追问缺失字段
```

### 5.2 on-call 匹配（不走 FAISS）

```python
# config/domain_knowledge.py
SERVICE_CATALOGUE["checkout-service"]["owner"]  →  "platform-sre"
ON_CALL_ROSTER["platform-sre"]["primary"]        →  "Alice Chen"
```

`agents/escalation/oncall_matcher.py` 纯字典查找，与 RAG 完全独立。

### 5.3 awaiting_confirmation 状态机

```
收到告警
  → info_complete=True
  → yield [SIGNAL]recommendation_pending
  → awaiting_confirmation = True（等用户确认 on-call）
  → 用户确认
  → _reset_state_after_escalation()
  → state = CLASSIFY
```

---

## 六、CommunicationAgent：三类受众差异化

文件：`agents/communication/stakeholder_formatter.py`

| 受众 | 内容重点 |
|---|---|
| 工程师 | 技术细节、runbook 步骤、APM 链接 |
| 客服 | 面向客户的语言、预计恢复时间（ETA）、影响范围 |
| 高管 | 业务影响、营收风险、关键决策点 |

温度设置 `temperature=0.3` 保证输出格式稳定。

---

## 七、PostmortemAgent：无需外部集成的时间线重建

1. **会话记录**：`api/chat_handler.py` 中 `_postmortem_agent.add_session_message()` 在每条消息收发时调用
2. **TimelineExtractor**：关键词分类事件类型（triage / escalation / mitigation / resolution）
3. **PostmortemGenerator + PostmortemBuilder**：结构化 prompt → LLM 生成完整 RCA 文档
4. **知识写回**（设计目标）：生成的 postmortem 可 ingest 进 RAG MCP Server，供未来查询

---

## 八、可观测性

`config/request_trace.py` 的 `trace_step` 上下文管理器覆盖关键路径：

```text
INFO trace_id=a3f8b2c1 step=[TaskClassificationAgent] intent_classification elapsed_ms=342
INFO trace_id=a3f8b2c1 step=[ConsultantAgent] mcp_rag_query elapsed_ms=680
INFO trace_id=a3f8b2c1 step=[ConsultantAgent] response_generation_stream elapsed_ms=1820
```

**First-token latency** = 意图分类 + MCP RAG 查询 + LLM 首 token。

---

## 九、失败模式与降级策略

| 场景 | 当前处理 | 可改进方向 |
|---|---|---|
| LLM 分类超时 | `other` fallback + force_reset | 重试 + 超时配置 |
| MCP RAG Server 未启动 | `McpRagClient` 返回空列表，LLM 说明无结果 | 启动时健康检查告警 |
| MCP RAG Server 崩溃 | 自动重启（`_ensure_running`） | 重启次数上限 + 告警 |
| on-call 字典无匹配 | `"Unknown team"` | 增加 fuzzy match fallback |
| Postmortem 会话历史为空 | LLM 说明无法生成 | 要求最少 N 条消息才触发 |

---

## 十、扩展路径

### 数据层
- SQLite → PostgreSQL
- MCP Server 的 ChromaDB → Pinecone / Weaviate（百万级文档）

### Agent 层
- 当前顺序路由 → Event-driven（Redis Pub/Sub）
- 增加 Reflection Agent 做回答质量自评
- PostmortemAgent 写回直接对接 MCP Server ingestion pipeline

### 工程化
- `global_session_id` 单用户 → per-user session pool
- MCP Server 独立部署为 Docker 服务（当前 subprocess）
- LLM 分类步骤增加规则前置过滤（降低 LLM 调用成本）

---

## 十一、高频面试题速查

### Q1: 为什么 RAG 用独立的 MCP Server 而不是嵌在 Agent 里？

> 职责分离。Agent 负责业务编排，RAG 负责知识检索。独立进程意味着可以单独升级检索策略（加 Rerank、改 chunk size）而不动 Agent 代码。MCP 协议标准化了工具调用接口，也可以直接接入 Claude Desktop / GitHub Copilot 使用同一个知识库。

### Q2: on-call 匹配为什么不用 RAG？

> on-call 名单是强结构化数据（team → primary → slack_channel 的映射关系），查的是精确匹配，不是语义相似度。用 FAISS 做这个是过度工程。`domain_knowledge.py` 里的字典查找更快、更可靠、更易维护。

### Q3: PostmortemAgent 怎么在没有 Slack/PagerDuty API 的情况下重建时间线？

> 每条工程师输入和 Agent 回复都在 `ProcessUserInput_stream` 里被记录到 `PostmortemAgent` 的 `session_messages`。`TimelineExtractor` 用关键词分类这些消息（triage/escalation/mitigation/resolution），再交给 LLM 生成结构化文档。不依赖外部集成，开发和演示零基础设施即可工作。

### Q4: CommunicationAgent 为什么要三类受众？

> 工程师需要技术细节和 APM 链接；客服需要用客户能理解的语言解释影响和 ETA；高管需要业务影响和营收风险的摘要。同一份通稿给三类受众会同时让三类人都不满意。`StakeholderFormatter` 用三套独立 prompt 分别生成。

### Q5: 这个系统最大的技术亮点是什么？

> 1. **MCP 解耦的 RAG**：Hybrid Search + Rerank，独立进程，可单独评估和迭代
> 2. **完整事件生命周期**：分诊→升级→沟通→复盘，一套系统覆盖全流程
> 3. **domain_knowledge.py 集中注入**：P0-P3 定义、on-call 名单、service catalogue 全在一处，业务规则修改不需要动 Agent 代码
> 4. **无外部集成的 Postmortem**：从会话历史重建时间线，演示零依赖
> 5. **流式体验**：`[THOUGHT]`/`[REPLY]`/`[SIGNAL]` 标记协议让 Agent 思考过程对用户可见
