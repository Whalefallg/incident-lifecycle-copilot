import json
from collections import Counter
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agents.consultant.mcp_rag_client import McpRagClient
from agents.consultant.retrieval import RetrievalResult
from evaluation.deterministic_judges import fact_coverage, normalize_text
from evaluation.incident_scenario import FactExpectation, load_scenarios
from evaluation.incident_scenario_runner import IncidentScenarioRunner
from evaluation.report import aggregate, nearest_rank, render_markdown

DATASET = Path(__file__).resolve().parents[1] / "benchmarks" / "incidentbench_v1"


def test_dataset_has_exact_static_distribution_and_unique_ids():
    scenarios = load_scenarios(DATASET)
    assert len(scenarios) == 30
    assert len({row.id for row in scenarios}) == 30
    assert Counter(row.category for row in scenarios) == {
        "basic": 8,
        "retrieval": 5,
        "suspend_resume": 4,
        "idempotency": 4,
        "concurrency": 3,
        "degraded": 3,
        "postmortem": 3,
    }


def test_fact_coverage_normalizes_case_whitespace_and_percent():
    required = [
        FactExpectation(id="rate", any_of=["18% error rate", "error rate reached 18%"]),
        FactExpectation(id="pool", any_of=["postgres pool exhausted"]),
    ]
    assert normalize_text("ERROR   RATE reached 18 percent") == "error rate reached 18%"
    assert fact_coverage("Error rate reached 18 percent; postgres pool exhausted", required) == (
        2,
        2,
    )


def test_nearest_rank_percentile_is_well_defined():
    assert nearest_rank([1, 2, 3, 4], 0.50) == 2
    assert nearest_rank([1, 2, 3, 4], 0.95) == 4
    assert nearest_rank([], 0.95) == 0


@pytest.mark.asyncio
async def test_runner_covers_assertions_and_report_serialization():
    scenarios = load_scenarios(DATASET)
    selected = [
        next(row for row in scenarios if row.category == category)
        for category in (
            "basic",
            "retrieval",
            "suspend_resume",
            "idempotency",
            "concurrency",
            "degraded",
            "postmortem",
        )
    ]
    runner = IncidentScenarioRunner()
    results = [await runner.run(row) for row in selected]
    assert all(row["status"] == "passed" for row in results)
    payload = {
        "metadata": {
            "incident_repo_commit": "test",
            "state_backend": "memory",
            "retrieval_backend": "local",
            "execution_mode": "deterministic_contract",
        },
        "metrics": aggregate(results),
        "scenarios": results,
    }
    assert payload["metrics"]["scenario_success_rate"] == 1
    assert "IncidentBench v1" in render_markdown(payload)
    json.dumps(payload)


@pytest.mark.asyncio
async def test_live_runner_uses_injected_retriever_and_persists_identity():
    class FakeRetriever:
        calls = []

        async def search(self, query, *, top_k, collection):
            self.calls.append((query, top_k, collection))
            return [
                RetrievalResult(
                    document_id="redis-oom-runbook",
                    content="[KB_ID: redis-oom#mitigation]",
                    source="data/documents/opsbench_v1/redis-oom.pdf",
                )
            ]

    scenario = next(row for row in load_scenarios(DATASET) if row.id == "retrieval-redis-001")
    retriever = FakeRetriever()
    result = await IncidentScenarioRunner(retriever=retriever).run(scenario)
    assert result["status"] == "passed"
    assert retriever.calls == [("Redis maxmemory mitigation", 10, "opsbench_v1")]


@pytest.mark.asyncio
async def test_mcp_collection_preflight_uses_tool_boundary():
    client = McpRagClient()
    client._require_started = lambda: None
    client._request = AsyncMock(
        return_value={
            "content": [
                {"type": "text", "text": "- **default**：2 个片段\n- **opsbench_v1**：24 个片段"}
            ]
        }
    )
    assert await client.list_collections() == {"default", "opsbench_v1"}
    client._request.assert_awaited_once_with(
        "tools/call", {"name": "list_collections", "arguments": {}}
    )
