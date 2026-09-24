# 完整事件升级流程 Walkthrough（Mock 数据 + 真实代码）

## 场景设定

PagerDuty 在 03:14 UTC 告警：checkout-service 错误率 8.2%（阈值 5%），us-east-1 地区。追踪这个告警从进入系统到生成事后报告的完整流程。

### Mock 告警输入
```
[PagerDuty Alert] CRITICAL: checkout-service
Error rate 8.2% (threshold 5%) | us-east-1 | Since 03:14 UTC
```

---

## 第 1-3 步：API 到分类

**第 1 步：API 层** (`api/chat_handler.py`)

```99:115:api/chat_handler.py
async def ProcessUserInput_stream(user_input, state=None, context=None):
    if context is None:
        context = {}
    _postmortem_agent.add_session_message(role="engineer", content=user_input)
    new_trace_id()
    with trace_step("classify_and_route", agent="TriageRouter"):
        response_tokens = []
        async for token in task_agent.classify_task_stream(user_input):
            response_tokens.append(token)
            yield token
```

**第 2 步：分类 Agent** (`agents/task_classification_agent.py`)

```5:40:agents/task_classification_agent.py
class TaskClassificationAgent:
    def __init__(
        self,
        escalation_agent,
        consultant_agent,
        communication_agent=None,
        postmortem_agent=None,
    ):
        self.escalation_agent = escalation_agent
        self.consultant_agent = consultant_agent
        self.communication_agent = communication_agent
        self.postmortem_agent = postmortem_agent
        self.llm = self._initialize_llm()
        self.state_manager = StateManager(SharedState())
        self.task_classifier = TaskClassifier(self.llm)
        self.agent_router = AgentRouter(
            escalation_agent,
            consultant_agent,
            self.state_manager,
            communication_agent=communication_agent,
            postmortem_agent=postmortem_agent,
        )
```

**第 3 步：分类处理** (`agents/task_classification/classification_processor.py`)

```27:52:agents/task_classification/classification_processor.py
    async def process_task_stream(self, task: str) -> AsyncGenerator[str, None]:
        try:
            if self.state_manager.should_classify():
                with trace_step("intent_classification", agent="TriageRouter"):
                    category = await self.task_classifier.classify_task(task)

                if category == "escalation":
                    async for token in self.agent_router.route_to_escalation(task):
                        yield token
                elif category == "query":
                    async for token in self.agent_router.route_to_runbook(task):
                        yield token
                elif category == "comms_update":
                    async for token in self.agent_router.route_to_comms(task):
                        yield token
                elif category == "postmortem":
                    async for token in self.agent_router.route_to_postmortem(task):
                        yield token
```

**Mock LLM 分类输出：** `category = "escalation"`（P0 事件）

---

## 第 4-6 步：路由到升级 Agent

**第 4 步：路由** (`agents/task_classification/agent_router.py`)

```42:57:agents/task_classification/agent_router.py
    async def route_to_escalation(self, task: str) -> AsyncGenerator[str, None]:
        if not self.escalation_agent:
            yield "[ERROR] Escalation service unavailable"
            return
        self.state_manager.transition_to_escalation()
        yield "[THOUGHT][Triage Router] P0/P1 incident detected — routing to Escalation Agent for impact assessment and on-call dispatch."
        try:
            async for token in self.escalation_agent.run_stream(user_input=task):
                yield token
        except Exception as e:
            yield f"[ERROR] Escalation failed: {e}"
            self.state_manager.reset_to_classify()
```

**第 5 步：升级 Agent 初始化** (`agents/escalation_agent.py`)

```5:40:agents/escalation_agent.py
class EscalationAgent:
    def __init__(self, session_id=None, unrelated_callback=None):
        self.session_id = session_id or str(uuid.uuid4())
        self.unrelated_callback = unrelated_callback
        self.state = None

        self.llm = create_chat_model(temperature=0)

        self.input_parser = InputParser(self.llm)
        self.oncall_matcher = OnCallMatcher()
        self.message_builder = MessageBuilder()
        self.incident_processor = IncidentProcessor(
            self.input_parser,
            self.oncall_matcher,
            self.message_builder,
            self.llm,
        )

        self.chats_by_session_id = {}
        self.chat_history = self._get_chat_history(self.session_id)
        self.reset()
```

**第 6 步：待命工程师匹配** (`agents/escalation/oncall_matcher.py`)

```18:60:agents/escalation/oncall_matcher.py
    def find_oncall_for_incident(
        self,
        incident_context: Dict[str, Any],
        yield_func: Optional[Callable] = None,
    ) -> Optional[Dict]:
        service = incident_context.get("service", "unknown")
        severity = incident_context.get("severity", "unknown")
        oncall_preference = incident_context.get("oncall_preference", "unknown")

        if yield_func:
            yield_func(f"[THOUGHT][Escalation Agent] Looking up on-call for service: {service}\n")

        oncall = get_oncall_for_service(service)
        if oncall:
            if yield_func:
                yield_func(
                    f"[THOUGHT][Escalation Agent] Found on-call: {oncall['team']} "
                    f"(primary: {oncall['primary']}, channel: {oncall['slack_channel']})\n"
                )
            return oncall
```

---

## 第 7 步：Domain Knowledge 查询

**服务目录** (`config/domain_knowledge.py`)

```38:48:config/domain_knowledge.py
SERVICE_CATALOGUE = {
    "checkout-service": {
        "owner": "platform-sre",
        "tier": "T1",
        "description": "Core checkout flow — cart, order creation, payment orchestration",
        "slo_availability": "99.99%",
        "key_dependencies": ["payment-gateway", "redis-cache", "postgres-primary"],
        "runbook_tags": ["checkout", "order", "cart"],
    },
```

**待命花名册** (`config/domain_knowledge.py`)

```7:17:config/domain_knowledge.py
ON_CALL_ROSTER = {
    "platform-sre": {
        "team": "Platform SRE",
        "description": "Infrastructure, Kubernetes, networking, storage",
        "primary": "Alice Chen",
        "secondary": "Bob Martinez",
        "escalation_path": "platform-sre → VP Engineering",
        "slack_channel": "#platform-incidents",
        "services": ["checkout-service", "payment-gateway", "redis-cache", "postgres-primary"],
    },
```

**Mock 匹配结果：**
```json
{
  "team": "Platform SRE",
  "primary": "Alice Chen",
  "secondary": "Bob Martinez",
  "slack_channel": "#platform-incidents",
  "services": ["checkout-service", "payment-gateway", "redis-cache", "postgres-primary"]
}
```

---

## 第 8 步：生成升级消息

**消息构建器** (`agents/escalation/message_builder.py`)

```16:46:agents/escalation/message_builder.py
    def create_escalation_dispatched_message(self, incident_context: Dict[str, Any]) -> str:
        severity = incident_context.get("severity", "unknown")
        service = incident_context.get("service", "unknown service")
        impact = incident_context.get("impact_scope", "unknown")
        symptoms = incident_context.get("symptoms", "unknown")
        suspected_cause = incident_context.get("suspected_cause", "unknown")
        recent_changes = incident_context.get("recent_changes", "none reported")

        oncall = get_oncall_for_service(service)
        oncall_line = (
            f"On-call dispatched: {oncall['team']} | "
            f"Primary: {oncall['primary']} | Secondary: {oncall['secondary']} | "
            f"Bridge channel: {oncall['slack_channel']}"
        )

        lines = [
            f"Incident escalation initiated — {severity}",
            "",
            f"Service:         {service}",
            f"Impact:          {impact}",
            f"Symptoms:        {symptoms}",
            f"Suspected cause: {suspected_cause}",
            f"Recent changes:  {recent_changes}",
            "",
            oncall_line,
            "",
            "Next steps:",
            "  1. Open a bridge in the Slack channel above",
            "  2. Post status page acknowledgement if customer-facing",
            "  3. Check Datadog APM and recent deploy history",
            "  4. Update this thread with findings every 15 minutes",
            "",
            "When the incident is resolved, say 'incident resolved' to generate the postmortem.",
        ]
        return "\n".join(lines)
```

**Mock 生成消息：**
```
Incident escalation initiated — P0

Service:         checkout-service
Impact:          us-east-1 customer-facing checkout flow
Symptoms:        error rate 8.2%, exceeds 5% threshold
Suspected cause: unknown
Recent changes:  none reported

On-call dispatched: Platform SRE | Primary: Alice Chen | Secondary: Bob Martinez | Bridge channel: #platform-incidents

Next steps:
  1. Open a bridge in the Slack channel above
  2. Post status page acknowledgement if customer-facing
  3. Check Datadog APM and recent deploy history
  4. Update this thread with findings every 15 minutes

When the incident is resolved, say 'incident resolved' to generate the postmortem.
```

---

## 第 9 步：流式响应返回

API 通过 Server-Sent Events 返回：

```
data: [THOUGHT][Triage Router] P0/P1 incident detected — routing to Escalation Agent...
data: [THOUGHT][Escalation Agent] Parsing incident information...
data: [DATA] Severity extracted: P0
data: [DATA] Service identified: checkout-service
data: [DATA] Impact scope: us-east-1 customer-facing checkout flow
data: [DATA] Symptoms: error rate 8.2%, exceeds 5% threshold
data: [THOUGHT][Escalation Agent] Looking up on-call for service: checkout-service
data: [THOUGHT][Escalation Agent] Found on-call: Platform SRE (primary: Alice Chen, channel: #platform-incidents)
data: Incident escalation initiated — P0
```

---

## 关键特性

| 特性 | 实现 | 代码位置 |
|------|------|--------|
| **流式分类** | LLM 逐 token 返回分类结果 | `task_classifier.py` |
| **状态管理** | CLASSIFY → ESCALATION → POSTMORTEM | `state_manager.py` |
| **多轮对话** | ESCALATION 中可接收更多信息 | `classification_processor.py` |
| **待命匹配** | 查询 domain_knowledge 找工程师 | `oncall_matcher.py` |
| **消息生成** | 结构化升级消息模板 | `message_builder.py` |
| **域知识** | 服务目录和待命花名册 | `domain_knowledge.py` |

---

## 完整流程图

```
PagerDuty Alert
    ↓
ProcessUserInput_stream()
    ↓
TaskClassificationAgent (LLM 分类)
    ↓
ClassificationProcessor (检查 should_classify)
    ↓
TaskClassifier (分类: "escalation")
    ↓
AgentRouter.route_to_escalation()
    ↓
EscalationAgent:
  • InputParser: 提取 severity, service, symptoms
  • OnCallMatcher: 查询 domain_knowledge 找待命
  • MessageBuilder: 生成升级确认
    ↓
流式响应返回工程师
    ↓
工程师在 ESCALATION 状态提供更多信息
    ↓
说"incident resolved"
    ↓
状态转移: ESCALATION → POSTMORTEM
    ↓
PostmortemAgent 生成事后报告
```

---

## 设计决策

**为什么流式？**
事件是时间关键的。流式让工程师实时看到进度。

**为什么多个 Agent？**
每个 Agent 专注单一职责（分类、升级、咨询、通信、事后）。

**为什么 domain_knowledge？**
集中管理服务和待命信息，避免硬编码。
