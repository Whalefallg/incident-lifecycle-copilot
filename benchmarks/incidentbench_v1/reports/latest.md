# IncidentBench v1

Commit: `85b6ff6a886e482963191f113bc70f579a90159d`
Working tree dirty: `false`
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
| p95 Scenario Latency (ms) | 0.387 |

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

- `basic-escalation-001`: **PASSED** (0.770 ms)
- `basic-runbook-002`: **PASSED** (0.111 ms)
- `basic-comms-003`: **PASSED** (0.163 ms)
- `basic-postmortem-004`: **PASSED** (0.094 ms)
- `basic-severity-005`: **PASSED** (0.116 ms)
- `basic-impact-006`: **PASSED** (0.109 ms)
- `basic-mitigation-007`: **PASSED** (0.181 ms)
- `basic-resolution-008`: **PASSED** (0.106 ms)
- `concurrency-checkout-001`: **PASSED** (0.122 ms)
- `concurrency-payment-002`: **PASSED** (0.118 ms)
- `concurrency-redis-003`: **PASSED** (0.117 ms)
- `degraded-startup-auto-001`: **PASSED** (0.091 ms)
- `degraded-runtime-002`: **PASSED** (0.090 ms)
- `degraded-malformed-003`: **PASSED** (0.090 ms)
- `idempotency-escalation-001`: **PASSED** (0.103 ms)
- `idempotency-runbook-002`: **PASSED** (0.097 ms)
- `idempotency-comms-003`: **PASSED** (0.109 ms)
- `idempotency-postmortem-004`: **PASSED** (0.094 ms)
- `postmortem-checkout-001`: **PASSED** (0.387 ms)
- `postmortem-redis-002`: **PASSED** (0.344 ms)
- `postmortem-payment-003`: **PASSED** (0.183 ms)
- `retrieval-redis-001`: **PASSED** (0.141 ms)
- `retrieval-postgres-002`: **PASSED** (0.141 ms)
- `retrieval-checkout-003`: **PASSED** (0.143 ms)
- `retrieval-payment-004`: **PASSED** (0.138 ms)
- `retrieval-lambda-005`: **PASSED** (0.148 ms)
- `suspend-redis-001`: **PASSED** (0.366 ms)
- `suspend-postgres-002`: **PASSED** (0.330 ms)
- `suspend-comms-003`: **PASSED** (0.253 ms)
- `suspend-lifo-004`: **PASSED** (0.166 ms)

## Evaluation layers

| Layer | Cases | Passed | Status |
|---|---:|---:|---|
| deterministic_contract | 30 | 30 | PASSED |
| live_mcp | 9 | 9 | PASSED |
| redis_recovery | 3 | 3 | PASSED |
