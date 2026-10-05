"""IncidentBench JSON payload aggregation and Markdown rendering."""

import math
from collections import defaultdict


def nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def aggregate(results: list[dict]) -> dict:
    passed = sum(row["status"] == "passed" for row in results)
    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        by_category[row["category"]].append(row)
    assertions = [item for row in results for item in row["assertions"]]
    named = lambda name: [item for item in assertions if item["name"] == name]
    rate = lambda items: (sum(item["passed"] for item in items) / len(items)) if items else None
    fact_values = [row["metrics"]["fact_coverage"] for row in results if row["metrics"]["fact_coverage"] is not None]
    unsupported = [row["metrics"]["unsupported_claim_rate"] for row in results if row["metrics"]["unsupported_claim_rate"] is not None]
    return {
        "scenario_success_rate": passed / len(results) if results else 0,
        "retrieval_success_rate": rate([item for item in assertions if item["name"].startswith("document:")]),
        "fsm_assertion_pass_rate": rate([item for item in assertions if item["name"].startswith("state:") or item["name"] == "final_state"]),
        "suspend_resume_success_rate": sum(r["status"] == "passed" for r in by_category["suspend_resume"]) / len(by_category["suspend_resume"]) if by_category["suspend_resume"] else None,
        "idempotent_retry_success_rate": rate(named("idempotency_required")),
        "duplicate_event_rate": 1 - rate(named("duplicate_event_count")) if named("duplicate_event_count") else None,
        "stale_write_rejection_rate": rate(named("stale_write_rejected")),
        "postmortem_fact_coverage": sum(fact_values) / len(fact_values) if fact_values else None,
        "unsupported_claim_rate": sum(unsupported) / len(unsupported) if unsupported else None,
        "p95_scenario_latency_ms": nearest_rank([r["latency_ms"] for r in results], .95),
        "categories": {name: {"cases": len(rows), "success_rate": sum(r["status"] == "passed" for r in rows) / len(rows)} for name, rows in sorted(by_category.items())},
    }


def render_markdown(payload: dict) -> str:
    def display(value):
        if value is None: return "N/A"
        if isinstance(value, float): return f"{value:.3f}"
        return str(value)
    metrics = payload["metrics"]
    labels = {
        "scenario_success_rate": "Scenario Success Rate", "retrieval_success_rate": "Retrieval Success Rate",
        "fsm_assertion_pass_rate": "FSM Assertion Pass Rate", "suspend_resume_success_rate": "Suspend/Resume Success Rate",
        "idempotent_retry_success_rate": "Idempotent Retry Success", "duplicate_event_rate": "Duplicate Event Rate",
        "stale_write_rejection_rate": "Stale Write Rejection Rate", "postmortem_fact_coverage": "Postmortem Fact Coverage",
        "unsupported_claim_rate": "Unsupported Claim Rate", "p95_scenario_latency_ms": "p95 Scenario Latency (ms)",
    }
    lines = [
        "# IncidentBench v1", "",
        f"Commit: `{payload['metadata']['incident_repo_commit']}`",
        f"Working tree dirty: `{str(payload['metadata'].get('git_dirty', False)).lower()}`",
        f"State backend: `{payload['metadata'].get('state_backend', 'memory')}`",
        f"Retrieval backend: `{payload['metadata'].get('retrieval_backend', 'local')}`",
        f"Execution mode: `{payload['metadata'].get('execution_mode', 'unknown')}`",
        "",
        "> The metric table below covers the deterministic contract harness only. Integration evidence is reported separately under Evaluation layers.",
        "", "| Metric | Result |", "|---|---:|",
    ]
    lines += [f"| {label} | {display(metrics[key])} |" for key, label in labels.items()]
    lines += ["", "## Categories", "", "| Category | Cases | Success |", "|---|---:|---:|"]
    lines += [f"| {name} | {row['cases']} | {display(row['success_rate'])} |" for name, row in metrics["categories"].items()]
    lines += ["", "## Scenario details", ""]
    lines += [f"- `{row['id']}`: **{row['status'].upper()}** ({row['latency_ms']:.3f} ms)" for row in payload["scenarios"]]
    layers = payload.get("layers", {})
    if layers:
        lines += ["", "## Evaluation layers", "", "| Layer | Cases | Passed | Status |", "|---|---:|---:|---|"]
        reasons = []
        for name in ("deterministic_contract", "live_mcp", "redis_recovery"):
            layer = layers.get(name, {})
            lines.append(f"| {name} | {layer.get('total', len(layer.get('cases', [])))} | {layer.get('passed', 'N/A')} | {str(layer.get('status', 'not_requested')).upper()} |")
            if layer.get("reason"):
                reasons.append(f"> {name}: {layer['reason']}")
        if reasons:
            lines += ["", *reasons]
    return "\n".join(lines) + "\n"
