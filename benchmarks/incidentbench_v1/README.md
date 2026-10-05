# IncidentBench v1

IncidentBench is a static, deterministic scenario suite for the incident workflow boundary. It evaluates the real `ConversationSnapshot`, FSM state manager, event ledger, retrieval trace models, request-id repository contract, and optimistic-concurrency contract. It does not treat unit-test pass rate as retrieval quality, and it does not use an LLM judge.

The committed dataset contains exactly 30 scenarios: 8 basic workflows, 5 retrieval integrations, 4 suspend/resume cases, 4 idempotency cases, 3 stale-write cases, 3 degraded-path cases, and 3 postmortem evidence cases.

Run all memory-backed scenarios:

```bash
python scripts/benchmark_incidents.py \
  --dataset benchmarks/incidentbench_v1 \
  --backend memory \
  --retriever local \
  --output benchmarks/incidentbench_v1/reports/latest.json
```

Run integration profiles when their dependencies are available:

```bash
# Three real Redis recovery cases. Starts no fallback backend.
docker compose up -d redis
python scripts/benchmark_incidents.py --backend redis --retriever local

# Nine live scenarios through McpRagClient -> stdio -> rag-as-mcp.
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp \
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python \
RAG_MCP_COLLECTION=opsbench_v1 \
python scripts/benchmark_incidents.py --backend memory --retriever mcp

# Both integration layers.
python scripts/benchmark_incidents.py --backend redis --retriever mcp
```

Filter with `--scenario ID` or `--category CATEGORY`. The command writes JSON and Markdown reports. The deterministic retrieval scenarios use fixed evidence fixtures and validate persistence/integration; retrieval quality belongs to the upstream OpsBench suite. Live MCP claims require a separately executed run against the collection and commit pinned in `benchmarks/opsbench_dependency.json`.

IncidentBench separates deterministic contract validation from live integration validation. The memory-backed baseline validates workflow invariants and does not represent retrieval quality, production availability, or Redis cross-worker recovery. Live MCP and Redis results are reported as separate layers only when those dependencies are actually exercised.

The Redis layer creates fresh repository and FSM objects for workers A and B, sharing only Redis. It verifies suspend/resume recovery, stale-write rejection, and completed-request idempotency. Unavailable Redis is reported as `SKIPPED`; there is no memory fallback.

The MCP layer validates the configured path and Python executable, starts the real stdio server, performs initialize, tools/list, ping and list_collections, and requires `opsbench_v1`. It runs only the nine scenarios marked `live_mcp`. Missing prerequisites or collections are reported as `SKIPPED`; there is no local fallback in this profile.

Current measured combined status on this checkout: all **3/3 Redis recovery scenarios passed** against an isolated local Redis process, and **9/9 live MCP scenarios passed** through `McpRagClient -> stdio -> rag-as-mcp -> opsbench_v1`. The live layer recorded 100% retrieval success, 100% evidence persistence, p50 2.273 ms, and p95 15.608 ms against pinned rag commit `74fd31d57bce8275c72d79c3d8590d0be42333fa`.

No result artifact is committed until the benchmark has actually been executed. Regression gates may be added only after a stable baseline exists; they are not product SLAs.
