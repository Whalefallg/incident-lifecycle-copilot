"""Benchmark retrieval only through the public rag-as-mcp stdio boundary."""
import argparse, asyncio, json, statistics, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.consultant.mcp_rag_client import McpRagClient
from config.rag_mcp import RagMcpSettings


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * fraction), len(ordered) - 1)]


async def run(dataset_path, output_path, top_k):
    settings = RagMcpSettings.from_env()
    if settings.server_path is None:
        raise SystemExit("RAG_MCP_SERVER_PATH is required")
    client = McpRagClient(settings)
    await client.start()
    rows, latencies = [], []
    try:
        for line in dataset_path.read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            started = time.perf_counter()
            hits = await client.query(case["query"], top_k=top_k, collection=settings.collection)
            latency = (time.perf_counter() - started) * 1000
            latencies.append(latency)
            got, expected = [hit.document_id for hit in hits], set(case["relevant_document_ids"])
            ranks = [i for i, doc_id in enumerate(got, 1) if doc_id in expected]
            rows.append({**case, "retrieved_document_ids": got, "latency_ms": round(latency, 2), "hit": bool(ranks), "reciprocal_rank": 1 / min(ranks) if ranks else 0.0, "recall": len(set(got) & expected) / len(expected)})
        caps = client.capabilities
        payload = {
            "metadata": {"timestamp": datetime.now(timezone.utc).isoformat(), "incident_repo_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(), "server_name": caps.server_name, "server_version": caps.server_version, "collection": settings.collection, "top_k": top_k, "query_count": len(rows)},
            "metrics": {"hit_rate_at_k": statistics.mean(row["hit"] for row in rows), "mrr": statistics.mean(row["reciprocal_rank"] for row in rows), "recall_at_k": statistics.mean(row["recall"] for row in rows), "p50_ms": percentile(latencies, .50), "p95_ms": percentile(latencies, .95)},
            "queries": rows,
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        await client.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("benchmarks/retrieval_dataset.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/latest_retrieval_results.json"))
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(run(args.dataset, args.output, args.top_k))
