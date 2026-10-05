#!/usr/bin/env python3
"""Run the deterministic IncidentBench v1 scenario suite."""

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.consultant.mcp_rag_client import McpRagClient
from agents.consultant.retrieval import LocalRunbookRetriever
from agents.consultant.retrieval_runtime import (
    degraded_reason,
    initialize_retrieval,
    shutdown_retrieval,
)
from config.rag_mcp import RagMcpSettings
from evaluation.incident_scenario import load_scenarios
from evaluation.incident_scenario_runner import IncidentScenarioRunner
from evaluation.redis_recovery import run_redis_recovery
from evaluation.report import aggregate, render_markdown

REPO_ROOT = Path(__file__).resolve().parents[1]


def git_revision(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_dirty(path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def dataset_hash(dataset: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((dataset / "scenarios").glob("*.yaml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


async def run(args: argparse.Namespace) -> dict:
    scenarios = load_scenarios(args.dataset)
    if args.scenario:
        scenarios = [row for row in scenarios if row.id == args.scenario]
    if args.category:
        scenarios = [row for row in scenarios if row.category == args.category]
    if not scenarios:
        raise SystemExit("no scenarios matched the supplied filters")
    runner = IncidentScenarioRunner(backend="memory")
    results = [await runner.run(scenario) for scenario in scenarios]
    dependency = json.loads(
        (args.dataset.parent / "opsbench_dependency.json").read_text(encoding="utf-8")
    )
    if (
        dependency.get("dataset") != "opsbench-v1"
        or dependency.get("expected_collection") != "opsbench_v1"
    ):
        raise SystemExit("invalid benchmarks/opsbench_dependency.json")
    live_mcp = (
        await run_live_mcp(scenarios, dependency)
        if args.retriever == "mcp"
        else {"status": "not_requested", "reason": "run with --retriever mcp", "cases": []}
    )
    redis_recovery = (
        await run_redis_recovery()
        if args.backend == "redis"
        else {"status": "not_requested", "reason": "run with --backend redis", "cases": []}
    )
    rag_metadata = live_mcp.get("metadata", {})
    payload = {
        "metadata": {
            "dataset_version": "incidentbench-v1",
            "dataset_hash": dataset_hash(args.dataset),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_dirty": git_dirty(REPO_ROOT),
            "state_backend": args.backend,
            "retrieval_backend": args.retriever,
            "incident_repo_commit": git_revision(REPO_ROOT),
            "rag_repo_commit": rag_metadata.get("rag_repo_commit"),
            "rag_collection": rag_metadata.get("rag_collection"),
            "rag_server_version": rag_metadata.get("rag_server_version"),
            "execution_mode": "layered_incidentbench",
            "scenario_count": len(results),
            "filters": {"scenario": args.scenario, "category": args.category},
        },
        "metrics": aggregate(results),
        "scenarios": results,
        "layers": {
            "deterministic_contract": {
                "status": "passed"
                if all(row["status"] == "passed" for row in results)
                else "failed",
                "passed": sum(row["status"] == "passed" for row in results),
                "total": len(results),
            },
            "live_mcp": live_mcp,
            "redis_recovery": redis_recovery,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output.with_suffix(".md").write_text(render_markdown(payload), encoding="utf-8")
    return payload


async def run_live_mcp(scenarios, dependency: dict) -> dict:
    settings = RagMcpSettings.from_env()
    expected = dependency["expected_collection"]
    if settings.server_path is None:
        return {"status": "skipped", "reason": "RAG_MCP_SERVER_PATH is not configured", "cases": []}
    if not settings.server_path.is_dir():
        return {
            "status": "skipped",
            "reason": f"rag-as-mcp path does not exist: {settings.server_path}",
            "cases": [],
        }
    executable = settings.python_executable or ""
    if not executable_exists(executable):
        return {
            "status": "skipped",
            "reason": f"RAG_MCP_PYTHON does not exist: {executable}",
            "cases": [],
        }
    rag_commit = git_revision(settings.server_path)
    pinned = dependency.get("rag_commit")
    if pinned and pinned != rag_commit:
        return {
            "status": "skipped",
            "reason": f"rag commit mismatch: expected {pinned}, got {rag_commit}",
            "cases": [],
        }
    client = McpRagClient(
        RagMcpSettings(
            mode="mcp",
            server_path=settings.server_path,
            python_executable=settings.python_executable,
            command=settings.command,
            settings_path=settings.settings_path,
            collection=expected,
            startup_timeout_seconds=settings.startup_timeout_seconds,
            request_timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
        )
    )
    try:
        capabilities = await client.start()
        await client.ping()
        error_semantics = await check_mcp_error_semantics(settings)
        collections = await client.list_collections()
        if expected not in collections:
            return {
                "status": "skipped",
                "reason": f"required collection {expected!r} not found; available={sorted(collections)}",
                "cases": [],
                "error_semantics": error_semantics,
                "metadata": {
                    "rag_repo_commit": rag_commit,
                    "rag_collection": expected,
                    "rag_server_version": capabilities.server_version,
                },
            }
        subset = [scenario for scenario in scenarios if scenario.live_mcp]
        live_runner = IncidentScenarioRunner(retriever=client, collection=expected)
        rows = [await live_runner.run(scenario) for scenario in subset]
        passed = sum(row["status"] == "passed" for row in rows)
        latencies = [row["latency_ms"] for row in rows]
        from evaluation.report import nearest_rank

        retrieval_assertions = [
            item
            for row in rows
            for item in row["assertions"]
            if item["name"].startswith("document:")
        ]
        return {
            "status": "passed" if passed == len(rows) else "failed",
            "passed": passed,
            "total": len(rows),
            "cases": rows,
            "metrics": {
                "retrieval_success_rate": sum(item["passed"] for item in retrieval_assertions)
                / len(retrieval_assertions)
                if retrieval_assertions
                else None,
                "evidence_persistence_rate": sum(bool(row["assertions"]) for row in rows)
                / len(rows)
                if rows
                else None,
                "mcp_error_semantics_pass_rate": sum(error_semantics.values())
                / len(error_semantics),
                "p50_latency_ms": nearest_rank(latencies, 0.50),
                "p95_latency_ms": nearest_rank(latencies, 0.95),
            },
            "metadata": {
                "rag_repo_commit": rag_commit,
                "rag_collection": expected,
                "rag_server_version": capabilities.server_version,
            },
        }
    except Exception as exc:
        return {
            "status": "skipped",
            "reason": f"MCP precondition failed: {type(exc).__name__}: {exc}",
            "cases": [],
            "metadata": {
                "rag_repo_commit": rag_commit,
                "rag_collection": expected,
                "rag_server_version": None,
            },
        }
    finally:
        await client.stop()


async def check_mcp_error_semantics(settings: RagMcpSettings) -> dict[str, bool]:
    """Exercise the production startup, runtime, and auto-fallback semantics."""
    unavailable = McpRagClient(
        RagMcpSettings(mode="mcp", server_path=Path("/definitely/missing/rag-as-mcp"))
    )
    required_failed = False
    try:
        await unavailable.start()
    except Exception:
        required_failed = True

    runtime_surfaced = False
    runtime_client = McpRagClient(replace(settings, max_retries=0))
    try:
        await runtime_client.start()
        await runtime_client.stop()
        await runtime_client.query("incidentbench failure probe", collection=settings.collection)
    except Exception:
        runtime_surfaced = True

    fallback = await initialize_retrieval(
        RagMcpSettings(mode="auto", server_path=Path("/definitely/missing/rag-as-mcp"))
    )
    auto_fallback = isinstance(fallback, LocalRunbookRetriever) and bool(degraded_reason())
    await shutdown_retrieval()
    return {
        "required_startup_failure_surfaced": required_failed,
        "runtime_failure_surfaced": runtime_surfaced,
        "auto_startup_fallback_recorded": auto_fallback,
    }


def executable_exists(value: str) -> bool:
    return Path(value).is_file() or shutil.which(value) is not None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("benchmarks/incidentbench_v1"))
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/incidentbench_v1/reports/latest.json")
    )
    parser.add_argument("--scenario")
    parser.add_argument(
        "--category",
        choices=[
            "basic",
            "retrieval",
            "suspend_resume",
            "idempotency",
            "concurrency",
            "degraded",
            "postmortem",
        ],
    )
    parser.add_argument("--backend", choices=["memory", "redis"], default="memory")
    parser.add_argument("--retriever", choices=["local", "mcp"], default="local")
    parsed = parser.parse_args()
    report = asyncio.run(run(parsed))
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
