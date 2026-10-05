# IncidentBench v1

Commit: `c2c65fab109dfa5058af8c691485b9b1448e3eaf`
Working tree dirty: `true`
State backend: `redis`
Retrieval backend: `mcp`
Execution mode: `layered_incidentbench`

> The metric table below covers the deterministic contract harness only. Integration evidence is reported separately under Evaluation layers.

| Metric | Result |
|---|---:|
| Scenario Success Rate | 1.000 |
| Retrieval Success Rate | 1.000 |
| FSM Assertion Pass Rate | 1.000 |
| Suspend/Resume Success Rate | 1.000 |
| Idempotent Retry Success | 1.000 |
| Duplicate Event Rate | 0.000 |
| Stale Write Rejection Rate | 1.000 |
| Postmortem Fact Coverage | 1.000 |
| Unsupported Claim Rate | 0.000 |
| p95 Scenario Latency (ms) | 0.391 |

## Categories

| Category | Cases | Success |
|---|---:|---:|
| basic | 8 | 1.000 |
| concurrency | 3 | 1.000 |
| degraded | 3 | 1.000 |
| idempotency | 4 | 1.000 |
| postmortem | 3 | 1.000 |
| retrieval | 5 | 1.000 |
| suspend_resume | 4 | 1.000 |

## Scenario details

- `basic-escalation-001`: **PASSED** (0.628 ms)
- `basic-runbook-002`: **PASSED** (0.112 ms)
- `basic-comms-003`: **PASSED** (0.164 ms)
- `basic-postmortem-004`: **PASSED** (0.094 ms)
- `basic-severity-005`: **PASSED** (0.128 ms)
- `basic-impact-006`: **PASSED** (0.112 ms)
- `basic-mitigation-007`: **PASSED** (0.183 ms)
- `basic-resolution-008`: **PASSED** (0.109 ms)
- `concurrency-checkout-001`: **PASSED** (0.124 ms)
- `concurrency-payment-002`: **PASSED** (0.123 ms)
- `concurrency-redis-003`: **PASSED** (0.118 ms)
- `degraded-startup-auto-001`: **PASSED** (0.092 ms)
- `degraded-runtime-002`: **PASSED** (0.090 ms)
- `degraded-malformed-003`: **PASSED** (0.090 ms)
- `idempotency-escalation-001`: **PASSED** (0.100 ms)
- `idempotency-runbook-002`: **PASSED** (0.098 ms)
- `idempotency-comms-003`: **PASSED** (0.111 ms)
- `idempotency-postmortem-004`: **PASSED** (0.095 ms)
- `postmortem-checkout-001`: **PASSED** (0.391 ms)
- `postmortem-redis-002`: **PASSED** (0.348 ms)
- `postmortem-payment-003`: **PASSED** (0.183 ms)
- `retrieval-redis-001`: **PASSED** (0.147 ms)
- `retrieval-postgres-002`: **PASSED** (0.146 ms)
- `retrieval-checkout-003`: **PASSED** (0.139 ms)
- `retrieval-payment-004`: **PASSED** (0.141 ms)
- `retrieval-lambda-005`: **PASSED** (0.142 ms)
- `suspend-redis-001`: **PASSED** (0.356 ms)
- `suspend-postgres-002`: **PASSED** (0.331 ms)
- `suspend-comms-003`: **PASSED** (0.259 ms)
- `suspend-lifo-004`: **PASSED** (0.166 ms)

## Evaluation layers

| Layer | Cases | Passed | Status |
|---|---:|---:|---|
| deterministic_contract | 30 | 30 | PASSED |
| live_mcp | 9 | 9 | PASSED |
| redis_recovery | 3 | 3 | PASSED |
