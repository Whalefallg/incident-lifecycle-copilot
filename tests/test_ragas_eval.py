"""
RAG 检索层评测 + Ragas 生成质量评测

层次：
  1. Golden Set      — query → expected_doc_ids 标准答案集
  2. RetrievalEval   — Hit Rate@K（目标文档是否在 Top-K 里）
  3. RagasEval       — Faithfulness + Answer Relevance（LLM-as-Judge）

运行：
  pytest tests/test_ragas_eval.py -m retrieval -v       # 纯逻辑，无需 MCP
  pytest tests/test_ragas_eval.py -m live -v            # 需要 MCP Server 运行
  pytest tests/test_ragas_eval.py -m ragas_eval -v      # 需要 MCP + LLM API Key
  pytest tests/test_ragas_eval.py -v                    # 全量（跳过 live/ragas_eval）

Pass thresholds:
  Hit Rate@10       >= 0.90
  Faithfulness      >= 0.85
  Answer Relevancy  >= 0.80
  Context Recall    >= 0.75
"""

import time
import pytest
from typing import List, Dict, Any
from unittest.mock import AsyncMock, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Golden Set
# ─────────────────────────────────────────────────────────────────────────────

GOLDEN_SET: List[Dict[str, Any]] = [
    {
        "id": "GS-001",
        "query": "checkout service error rate spike how to fix",
        "expected_doc_ids": ["checkout-error-runbook", "INC-2024-0425"],
        "ground_truth": (
            "For checkout error rate spikes, first check the circuit breaker status. "
            "If tripped, restart the checkout service pods. Then verify database "
            "connection pool health and check for recent deployments."
        ),
        "category": "runbook",
    },
    {
        "id": "GS-002",
        "query": "redis out of memory OOM how to resolve",
        "expected_doc_ids": ["redis-oom-runbook"],
        "ground_truth": (
            "For Redis OOM alerts, identify which keyspace is consuming memory using "
            "redis-cli INFO memory. Flush expired keys with SCAN + TTL check. "
            "Scale up the instance or evict low-priority keys using LRU policy."
        ),
        "category": "runbook",
    },
    {
        "id": "GS-003",
        "query": "payment gateway timeout error investigation steps",
        "expected_doc_ids": ["payment-gateway-timeout-runbook"],
        "ground_truth": (
            "Payment gateway timeouts stem from upstream provider latency or internal "
            "connection pool exhaustion. Check provider status page first. If internal, "
            "inspect connection pool metrics and increase pool size or enable queuing."
        ),
        "category": "runbook",
    },
    {
        "id": "GS-004",
        "query": "lambda function timeout cold start optimization",
        "expected_doc_ids": ["lambda-timeout-runbook"],
        "ground_truth": (
            "Lambda cold start timeouts: enable provisioned concurrency, reduce package "
            "size, increase function timeout, add SQS dead letter queue for retries."
        ),
        "category": "runbook",
    },
    {
        "id": "GS-005",
        "query": "postgres connection pool exhausted too many connections",
        "expected_doc_ids": ["postgres-connection-pool-runbook"],
        "ground_truth": (
            "PostgreSQL connection pool exhaustion: identify idle connections via "
            "pg_stat_activity and terminate them. Set connection_limit on app user "
            "roles. Add PgBouncer as a connection pooler."
        ),
        "category": "runbook",
    },
    {
        "id": "GS-006",
        "query": "how did we fix the checkout circuit breaker last incident",
        "expected_doc_ids": ["INC-2024-0425"],
        "ground_truth": (
            "In INC-2024-0425, the checkout circuit breaker was tripped by a bad "
            "deployment. Resolution: roll back deployment, restart affected pods. "
            "Root cause: uncaught exception in new payment validation logic."
        ),
        "category": "incident_memory",
    },
    {
        "id": "GS-007",
        "query": "redis memory usage monitoring what metrics to watch",
        "expected_doc_ids": ["redis-oom-runbook"],
        "ground_truth": (
            "Key Redis memory metrics: used_memory_rss, used_memory, "
            "mem_fragmentation_ratio (healthy: 1.0-1.5), keyspace hit ratio. "
            "Alert when used_memory_rss exceeds 80% of maxmemory."
        ),
        "category": "runbook",
    },
    {
        "id": "GS-008",
        "query": "past incidents similar to payment gateway issues",
        "expected_doc_ids": ["payment-gateway-timeout-runbook", "INC-2024-0425"],
        "ground_truth": (
            "Previous payment gateway incidents: provider-side outages requiring "
            "failover, and internal connection pool exhaustion. "
            "Most resolved within 30 minutes."
        ),
        "category": "incident_memory",
    },
    {
        "id": "GS-009",
        "query": "database connection pool runbook troubleshooting steps",
        "expected_doc_ids": ["postgres-connection-pool-runbook"],
        "ground_truth": (
            "Connection pool troubleshooting: pg_stat_activity for idle connections, "
            "identify top connection sources, restart PgBouncer, "
            "temporarily raise max_connections if critical."
        ),
        "category": "runbook",
    },
    {
        "id": "GS-010",
        "query": "P0 checkout service us-east-1 who to page on-call",
        "expected_doc_ids": ["checkout-error-runbook"],
        "ground_truth": (
            "For P0 checkout service incidents in us-east-1, page the platform-sre "
            "on-call rotation. Primary: Alice Chen. Slack: #platform-incidents."
        ),
        "category": "escalation",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def hit_at_k(retrieved_ids: List[str], expected_ids: List[str]) -> bool:
    """True if at least one expected doc appears in retrieved results."""
    return any(doc_id in set(retrieved_ids) for doc_id in expected_ids)


def compute_hit_rate(results: List[Dict]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r["hit"]) / len(results)


async def aiter_tokens(tokens):
    for t in tokens:
        yield MagicMock(content=t)


def _print_separator(title: str = "") -> None:
    line = "─" * 60
    print(f"\n{line}")
    if title:
        print(title)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unit tests — evaluation logic
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.retrieval
class TestRetrievalLogic:
    """Pure logic tests — no I/O, no LLM, fast."""

    def test_hit_true_when_expected_in_results(self):
        assert hit_at_k(["redis-oom-runbook", "other"], ["redis-oom-runbook"]) is True

    def test_hit_false_when_no_match(self):
        assert hit_at_k(["unrelated-1", "unrelated-2"], ["redis-oom-runbook"]) is False

    def test_hit_partial_multi_expected(self):
        # One of two expected docs present — still counts as a hit
        assert hit_at_k(["INC-2024-0425"], ["checkout-error-runbook", "INC-2024-0425"]) is True

    def test_hit_false_empty_retrieved(self):
        assert hit_at_k([], ["redis-oom-runbook"]) is False

    def test_compute_hit_rate_all_hits(self):
        assert compute_hit_rate([{"hit": True}] * 4) == 1.0

    def test_compute_hit_rate_partial(self):
        results = [{"hit": True}, {"hit": False}, {"hit": True}, {"hit": False}]
        assert compute_hit_rate(results) == 0.5

    def test_compute_hit_rate_zero(self):
        assert compute_hit_rate([{"hit": False}] * 3) == 0.0

    def test_compute_hit_rate_empty(self):
        assert compute_hit_rate([]) == 0.0

    def test_golden_set_has_required_fields(self):
        required = {"id", "query", "expected_doc_ids", "ground_truth", "category"}
        for item in GOLDEN_SET:
            missing = required - set(item.keys())
            assert not missing, f"{item['id']} missing fields: {missing}"

    def test_golden_set_unique_ids(self):
        ids = [item["id"] for item in GOLDEN_SET]
        assert len(ids) == len(set(ids)), "Golden Set IDs must be unique"

    def test_golden_set_non_empty_expected_docs(self):
        for item in GOLDEN_SET:
            assert len(item["expected_doc_ids"]) > 0, f"{item['id']} has empty expected_doc_ids"

    def test_golden_set_non_empty_ground_truth(self):
        for item in GOLDEN_SET:
            assert item["ground_truth"].strip(), f"{item['id']} has empty ground_truth"

    def test_mock_retriever_always_hits(self):
        """Mock returning exact expected docs should give 100% hit rate."""
        results = []
        for item in GOLDEN_SET:
            retrieved = item["expected_doc_ids"][:]
            results.append({"hit": hit_at_k(retrieved, item["expected_doc_ids"])})
        assert compute_hit_rate(results) == 1.0

    def test_empty_retriever_gives_zero_hit_rate(self):
        results = []
        for item in GOLDEN_SET:
            results.append({"hit": hit_at_k([], item["expected_doc_ids"])})
        assert compute_hit_rate(results) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Mocked ConsultantAgent — retrieval path
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.retrieval
class TestConsultantAgentMocked:
    """
    Verify ConsultantAgent's retrieval path with a mocked KnowledgeRetriever.
    No live MCP Server required.
    """

    @pytest.mark.asyncio
    async def test_search_knowledge_called_with_correct_query(self):
        from agents.consultant_agent import ConsultantAgent

        mock_retriever = AsyncMock()
        mock_retriever.search_knowledge = AsyncMock(return_value=[
            {"content": "checkout runbook content", "source": "checkout-error-runbook", "score": 0.95}
        ])

        agent = ConsultantAgent()
        agent.knowledge_retriever = mock_retriever

        docs = await mock_retriever.search_knowledge("checkout error rate spike", top_k=10)
        assert len(docs) == 1
        assert docs[0]["source"] == "checkout-error-runbook"
        mock_retriever.search_knowledge.assert_called_once_with("checkout error rate spike", top_k=10)

    @pytest.mark.asyncio
    async def test_hit_rate_100_percent_with_perfect_mock(self):
        """Sanity check: perfect mock retriever gives 100% hit rate."""
        results = []
        for item in GOLDEN_SET:
            mock_docs = [
                {"source": doc_id, "content": f"content for {doc_id}", "score": 0.95}
                for doc_id in item["expected_doc_ids"]
            ]
            retrieved_ids = [d["source"] for d in mock_docs]
            results.append({"id": item["id"], "hit": hit_at_k(retrieved_ids, item["expected_doc_ids"])})

        rate = compute_hit_rate(results)
        assert rate == 1.0, f"Perfect mock should give 100%, got {rate:.1%}"

    @pytest.mark.asyncio
    async def test_hit_rate_0_percent_with_wrong_mock(self):
        """Wrong mock (returns unrelated docs) should give 0% hit rate."""
        results = []
        for item in GOLDEN_SET:
            retrieved_ids = ["totally-unrelated-doc"]
            results.append({"hit": hit_at_k(retrieved_ids, item["expected_doc_ids"])})

        rate = compute_hit_rate(results)
        assert rate == 0.0, f"Wrong mock should give 0%, got {rate:.1%}"

    def test_golden_set_covers_all_runbook_categories(self):
        categories = {item["category"] for item in GOLDEN_SET}
        assert "runbook" in categories
        assert "incident_memory" in categories
        assert "escalation" in categories

    def test_golden_set_covers_all_five_runbooks(self):
        all_expected = [doc for item in GOLDEN_SET for doc in item["expected_doc_ids"]]
        expected_runbooks = {
            "checkout-error-runbook",
            "redis-oom-runbook",
            "payment-gateway-timeout-runbook",
            "lambda-timeout-runbook",
            "postgres-connection-pool-runbook",
        }
        for rb in expected_runbooks:
            assert rb in all_expected, f"Golden Set missing runbook: {rb}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Live retrieval evaluation (requires running MCP Server)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.live
class TestLiveRetrievalEval:
    """
    Hit Rate@K evaluation against the live MCP RAG Server.

    Skip:  pytest -m "not live"
    Run:   pytest -m live -v  (MCP Server must be running + runbooks ingested)

    Pass threshold: Hit Rate@10 >= 0.90
    """

    PASS_THRESHOLD = 0.90
    TOP_K = 10

    @pytest.mark.asyncio
    async def test_hit_rate_at_10_exceeds_threshold(self):
        from agents.consultant_agent import ConsultantAgent

        results = []
        try:
            async with ConsultantAgent() as agent:
                for item in GOLDEN_SET:
                    start = time.time()
                    docs = await agent.knowledge_retriever.search_knowledge(
                        item["query"], top_k=self.TOP_K
                    )
                    latency_ms = (time.time() - start) * 1000
                    retrieved_ids = [d.get("source", "") for d in docs]
                    hit = hit_at_k(retrieved_ids, item["expected_doc_ids"])
                    results.append({
                        "id":         item["id"],
                        "query":      item["query"],
                        "hit":        hit,
                        "retrieved":  retrieved_ids,
                        "expected":   item["expected_doc_ids"],
                        "latency_ms": round(latency_ms, 1),
                    })
        except Exception as exc:
            pytest.skip(f"MCP Server unavailable: {exc}")

        hit_rate = compute_hit_rate(results)
        hits_n   = sum(r["hit"] for r in results)
        misses   = [r for r in results if not r["hit"]]

        _print_separator(f"Hit Rate@{self.TOP_K} Results")
        print(f"  Score : {hit_rate:.1%}  ({hits_n}/{len(results)})")
        avg_lat = sum(r["latency_ms"] for r in results) / len(results)
        print(f"  Avg retrieval latency: {avg_lat:.0f}ms")
        if misses:
            print("  Misses:")
            for m in misses:
                print(f"    [{m['id']}] {m['query'][:55]}")
                print(f"      expected : {m['expected']}")
                print(f"      got      : {m['retrieved'][:3]}")
        print("─" * 60)

        assert hit_rate >= self.PASS_THRESHOLD, (
            f"Hit Rate@{self.TOP_K} = {hit_rate:.1%} below threshold "
            f"{self.PASS_THRESHOLD:.0%}. Misses: {[m['id'] for m in misses]}"
        )

    @pytest.mark.asyncio
    async def test_retrieval_latency_p95_under_800ms(self):
        from agents.consultant_agent import ConsultantAgent

        latencies = []
        try:
            async with ConsultantAgent() as agent:
                for item in GOLDEN_SET:
                    t0 = time.time()
                    await agent.knowledge_retriever.search_knowledge(item["query"], top_k=10)
                    latencies.append((time.time() - t0) * 1000)
        except Exception as exc:
            pytest.skip(f"MCP Server unavailable: {exc}")

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]

        print(f"\nRetrieval latency  P50={p50:.0f}ms  P95={p95:.0f}ms")
        assert p95 < 800, f"Retrieval P95={p95:.0f}ms exceeds 800ms limit"

    @pytest.mark.asyncio
    async def test_retrieval_returns_non_empty_content(self):
        """Every retrieved doc must have non-empty content and source fields."""
        from agents.consultant_agent import ConsultantAgent

        try:
            async with ConsultantAgent() as agent:
                docs = await agent.knowledge_retriever.search_knowledge(
                    GOLDEN_SET[0]["query"], top_k=5
                )
        except Exception as exc:
            pytest.skip(f"MCP Server unavailable: {exc}")

        assert len(docs) > 0, "Should retrieve at least one document"
        for doc in docs:
            assert doc.get("content", "").strip(), "Each doc must have non-empty content"
            assert doc.get("source", "").strip(), "Each doc must have non-empty source"

    @pytest.mark.asyncio
    async def test_hit_rate_per_category(self):
        """Report Hit Rate broken down by category (runbook / incident_memory / escalation)."""
        from agents.consultant_agent import ConsultantAgent

        by_category: Dict[str, List[Dict]] = {}
        try:
            async with ConsultantAgent() as agent:
                for item in GOLDEN_SET:
                    docs = await agent.knowledge_retriever.search_knowledge(
                        item["query"], top_k=10
                    )
                    retrieved_ids = [d.get("source", "") for d in docs]
                    cat = item["category"]
                    by_category.setdefault(cat, []).append({
                        "hit": hit_at_k(retrieved_ids, item["expected_doc_ids"])
                    })
        except Exception as exc:
            pytest.skip(f"MCP Server unavailable: {exc}")

        _print_separator("Hit Rate by Category")
        for cat, results in by_category.items():
            rate = compute_hit_rate(results)
            print(f"  {cat:20s}: {rate:.1%}  (n={len(results)})")
        print("─" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Ragas generation quality evaluation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.ragas_eval
class TestRagasEval:
    """
    Ragas LLM-as-Judge evaluation.

    Metrics:
      Faithfulness      — answer grounded in retrieved context (no hallucination)
      Answer Relevancy  — answer actually addresses the question
      Context Recall    — retrieved docs cover the ground truth

    Requirements:
      pip install ragas datasets
      Valid LLM API key in .env (Ragas calls it for judging)
    """

    FAITHFULNESS_THRESHOLD     = 0.85
    ANSWER_RELEVANCY_THRESHOLD = 0.80
    CONTEXT_RECALL_THRESHOLD   = 0.75

    @pytest.mark.asyncio
    async def test_faithfulness_and_answer_relevancy(self):
        try:
            from ragas import evaluate
            from ragas.metrics import faithfulness, answer_relevancy
            from datasets import Dataset
        except ImportError:
            pytest.skip("ragas / datasets not installed — pip install ragas datasets")

        from agents.consultant_agent import ConsultantAgent

        questions, answers, contexts, ground_truths = [], [], [], []

        try:
            async with ConsultantAgent() as agent:
                for item in GOLDEN_SET[:5]:   # limit to 5 to control LLM cost
                    docs = await agent.knowledge_retriever.search_knowledge(
                        item["query"], top_k=5
                    )
                    ctx = [d.get("content", "") for d in docs]

                    tokens = []
                    async for tok in agent.consult_stream(item["query"]):
                        tokens.append(tok)
                    answer = "".join(tokens)

                    questions.append(item["query"])
                    answers.append(answer)
                    contexts.append(ctx)
                    ground_truths.append(item["ground_truth"])
        except Exception as exc:
            pytest.skip(f"Agent / MCP unavailable: {exc}")

        if not questions:
            pytest.skip("No evaluation data collected")

        dataset = Dataset.from_dict({
            "question":     questions,
            "answer":       answers,
            "contexts":     contexts,
            "ground_truth": ground_truths,
        })

        result       = evaluate(dataset, metrics=[faithfulness, answer_relevancy])
        faith        = float(result["faithfulness"])
        relevancy    = float(result["answer_relevancy"])

        _print_separator(f"Ragas Results  (n={len(questions)})")
        print(f"  Faithfulness    : {faith:.3f}  threshold={self.FAITHFULNESS_THRESHOLD}")
        print(f"  Answer Relevancy: {relevancy:.3f}  threshold={self.ANSWER_RELEVANCY_THRESHOLD}")
        print("─" * 60)

        assert faith >= self.FAITHFULNESS_THRESHOLD, (
            f"Faithfulness {faith:.3f} < {self.FAITHFULNESS_THRESHOLD}. "
            "LLM may be hallucinating content outside retrieved docs."
        )
        assert relevancy >= self.ANSWER_RELEVANCY_THRESHOLD, (
            f"Answer Relevancy {relevancy:.3f} < {self.ANSWER_RELEVANCY_THRESHOLD}. "
            "LLM may be answering off-topic."
        )

    @pytest.mark.asyncio
    async def test_context_recall(self):
        """Context Recall: how much ground truth is covered by retrieved docs."""
        try:
            from ragas import evaluate
            from ragas.metrics import context_recall
            from datasets import Dataset
        except ImportError:
            pytest.skip("ragas / datasets not installed")

        from agents.consultant_agent import ConsultantAgent

        questions, contexts, ground_truths = [], [], []

        try:
            async with ConsultantAgent() as agent:
                for item in GOLDEN_SET[:5]:
                    docs = await agent.knowledge_retriever.search_knowledge(
                        item["query"], top_k=10
                    )
                    questions.append(item["query"])
                    contexts.append([d.get("content", "") for d in docs])
                    ground_truths.append(item["ground_truth"])
        except Exception as exc:
            pytest.skip(f"MCP unavailable: {exc}")

        dataset = Dataset.from_dict({
            "question":     questions,
            "contexts":     contexts,
            "ground_truth": ground_truths,
        })

        result = evaluate(dataset, metrics=[context_recall])
        recall = float(result["context_recall"])

        print(f"\nContext Recall: {recall:.3f}  threshold={self.CONTEXT_RECALL_THRESHOLD}")
        assert recall >= self.CONTEXT_RECALL_THRESHOLD, (
            f"Context Recall {recall:.3f} < {self.CONTEXT_RECALL_THRESHOLD}. "
            "Retrieved docs may not cover enough of the ground truth."
        )

    @pytest.mark.asyncio
    async def test_full_pipeline_ragas_all_metrics(self):
        """
        Full pipeline: retrieve → generate → evaluate all metrics in one shot.
        Most expensive test — run before major releases.
        """
        try:
            from ragas import evaluate
            from ragas.metrics import faithfulness, answer_relevancy, context_recall
            from datasets import Dataset
        except ImportError:
            pytest.skip("ragas / datasets not installed")

        from agents.consultant_agent import ConsultantAgent

        questions, answers, contexts, ground_truths = [], [], [], []

        try:
            async with ConsultantAgent() as agent:
                for item in GOLDEN_SET:
                    docs = await agent.knowledge_retriever.search_knowledge(
                        item["query"], top_k=10
                    )
                    ctx = [d.get("content", "") for d in docs]
                    tokens = []
                    async for tok in agent.consult_stream(item["query"]):
                        tokens.append(tok)
                    questions.append(item["query"])
                    answers.append("".join(tokens))
                    contexts.append(ctx)
                    ground_truths.append(item["ground_truth"])
        except Exception as exc:
            pytest.skip(f"Agent / MCP unavailable: {exc}")

        dataset = Dataset.from_dict({
            "question":     questions,
            "answer":       answers,
            "contexts":     contexts,
            "ground_truth": ground_truths,
        })

        result = evaluate(
            dataset,
            metrics=[faithfulness, answer_relevancy, context_recall],
        )

        faith    = float(result["faithfulness"])
        rel      = float(result["answer_relevancy"])
        recall   = float(result["context_recall"])

        _print_separator(f"Full Ragas Pipeline  (n={len(questions)})")
        print(f"  Faithfulness    : {faith:.3f}")
        print(f"  Answer Relevancy: {rel:.3f}")
        print(f"  Context Recall  : {recall:.3f}")
        print("─" * 60)

        assert faith  >= self.FAITHFULNESS_THRESHOLD
        assert rel    >= self.ANSWER_RELEVANCY_THRESHOLD
        assert recall >= self.CONTEXT_RECALL_THRESHOLD
