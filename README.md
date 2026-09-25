# Incident Lifecycle Copilot

Incident Lifecycle Copilot coordinates incident triage, escalation, runbook lookup,
stakeholder communication, postmortem drafting, and reviewed knowledge promotion.
Its core design goal is correctness across requests and workers: recoverable state is
persisted as one versioned snapshot instead of being owned by a Python Agent object.

## Problem

During an incident, an on-call engineer must collect impact, preserve context across
interruptions, locate operational knowledge, notify stakeholders, and later reconstruct
what happened. This project models those steps as explicit workflows with recoverable
state and testable boundaries.

## Architecture

```text
FastAPI / request_id
        |
ConversationCoordinator
        |
ConversationRepository ---- InMemory / Redis CAS
        |
disposable request graph
        +---- Triage router / FSM
        +---- EscalationAgent
        +---- ConsultantAgent ---- Retriever
        +---- CommunicationAgent
        +---- PostmortemAgent
```

The specialist names describe responsibilities, not independently stateful services.
Agents are rebuilt for each request and hydrated from the current `ConversationSnapshot`.

## Design Goals

- Use the complete conversation snapshot as the recoverable source of truth.
- Keep workflow state separate from typed incident business context.
- Reject stale writes with optimistic revision checks.
- Make request retries idempotent and reject request-ID payload mismatches.
- Record typed incident facts before generating a postmortem.
- Require review and approval before knowledge ingestion.
- Keep retrieval behind a backend-neutral `Retriever` contract.

## Workflow and FSM

The FSM represents workflow position only. Incident fields such as severity, service,
impact scope, symptoms, and recent changes live in `EscalationContext`.

An inserted runbook question can suspend an active escalation. The snapshot persists the
suspend stack and escalation context, allowing a different worker to answer the question
and a later worker to resume the original flow.

State changes use `transition`, `suspend`, and `resume` through `StateManager` rather than
placing business data in `StateEnum`.

## Stateless Conversation Recovery

`ConversationSnapshot` includes:

- schema version, session ID, and revision;
- current FSM state and suspend stack;
- escalation and postmortem contexts;
- messages and typed incident events;
- completed request results used for idempotency;
- creation and update timestamps.

`RedisConversationRepository.save(snapshot, expected_revision)` performs an atomic
compare-and-set. A stale save raises `ConcurrentConversationUpdate`. Stable request IDs
are associated with a canonical payload fingerprint; reusing an ID with different input
raises `IdempotencyKeyMismatch`.

The cross-worker test creates three independent object graphs: worker A starts a P1
checkout incident, worker B suspends it for a runbook question, and worker C resumes it.

## Agent Responsibilities

| Component | Responsibility |
|---|---|
| Triage router | Classify and route incident, runbook, communication, or postmortem work |
| EscalationAgent | Collect impact context and select the on-call route |
| ConsultantAgent | Generate an answer using an injected `Retriever` |
| CommunicationAgent | Draft stakeholder updates |
| PostmortemAgent | Build a draft from persisted incident events |

There are no `PatternAgent` or `UserBehaviorAgent` placeholders in the active architecture.

## RAG MCP Integration

The primary external retrieval backend is
[`Whalefallg/rag-as-mcp`](https://github.com/Whalefallg/rag-as-mcp). The current verified
transport and capability contract is:

```text
transport: stdio
entrypoint: python main.py
protocol: initialize, ping, tools/list, tools/call
required tool: query_knowledge_hub(query, top_k, collection)
optional tools: list_collections, get_document_summary
```

Incident Lifecycle Copilot owns the retrieval contract, configuration, MCP client
lifecycle, capability validation, failure policy, and response adapter. `rag-as-mcp`
owns ingestion, chunking, sparse/dense retrieval, fusion, reranking, and its indexes.
This repository does not import those internals.

One `McpRagClient` subprocess is initialized and reused for the application lifespan of
each worker. Request-scoped Agents do not start or stop it. Health (`ping`), capability
validation (`initialize` plus `tools/list`), and a live retrieval query are separate tests.

The server currently returns citation Markdown. `McpQueryResponseParser` converts each
citation into a separate `RetrievalResult`. `document_id` is an Incident-side,
deterministic normalization of the citation `source_path`; it is not a native upstream
field. Upstream error text can currently arrive with `isError=false`, so the adapter also
recognizes the verified error messages and raises `McpToolError`.

Modes:

- `RAG_MODE=local`: deterministic `LocalRunbookRetriever`.
- `RAG_MODE=auto`: use MCP when configured; startup/configuration failure falls back to local.
- `RAG_MODE=mcp`: MCP is required and startup failure is fatal.

After MCP has initialized successfully, runtime query failures are explicit and do not
silently switch to the local retriever.

## Structured Incident Event Ledger

Runtime facts are persisted as typed `IncidentEvent` records with stable IDs, incident
IDs, timestamps, actors, sources, request IDs, event types, and payloads. Duplicate
requests do not append duplicate events.

## Postmortem and Knowledge Review

Postmortem timelines are built from the structured event ledger. Recorded observations
remain distinct from generated root-cause analysis. Knowledge drafts are versioned and
follow an explicit lifecycle:

```text
DRAFT -> REVIEWED -> APPROVED -> INGESTED
                   -> REJECTED
```

The application retains a `KnowledgeIngestor` contract and an in-memory implementation.
The current `rag-as-mcp` MCP surface is query-only and exposes no ingestion tool, so this
repository intentionally does not implement `McpKnowledgeIngestor` or shell out to the
upstream ingestion script.

## Running Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-production.txt
cp .env.example .env
python app.py
```

Use `RAG_MODE=local` for the bundled deterministic runbooks. For MCP mode, clone and
configure `rag-as-mcp`, then set:

```bash
RAG_MODE=mcp
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python
```

No developer-machine path is used as a default.

## Testing

Install the development tools:

```bash
pip install -r requirements-dev.txt
```

Run the default external-service-free suite:

```bash
pytest -q
```

Run Redis integration tests only after Redis is configured:

```bash
REDIS_URL=redis://localhost:6379/0 pytest -q -m redis_integration \
  tests/test_redis_conversation_repository.py
```

Run the live MCP contract suite:

```bash
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp \
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python \
pytest -q -m live tests/test_live_rag_mcp.py
```

Dependency absence is checked in integration fixture setup and may skip the suite. Once
setup succeeds, runtime failures fail the test. Unit tests do not start MCP or Redis.

Quality gates:

```bash
ruff check .
ruff format --check .
mypy
```

The configured strict lint/type boundary covers the conversation, approval, RAG MCP,
benchmark, and related critical tests. Legacy UI/service modules are not yet included in
that static-analysis boundary; the complete pytest suite still exercises the repository.

## Benchmarks

The retrieval harness follows the real boundary:

```text
dataset -> McpRagClient/Retriever -> stdio JSON-RPC
        -> query_knowledge_hub -> rag-as-mcp
```

Run it with:

```bash
RAG_MCP_SERVER_PATH=/path/to/rag-as-mcp \
RAG_MCP_PYTHON=/path/to/rag-as-mcp/.venv/bin/python \
python scripts/benchmark_retrieval.py
```

Targets and observed results are deliberately separate:

| Metric | Target | Latest observed result |
|---|---:|---:|
| Hit Rate@10 | >= 0.90 | 0.00 |
| MRR | >= 0.80 | 0.00 |
| Recall@10 | >= 0.80 | 0.00 |
| p95 latency | < 2000 ms | 315.41 ms |

The saved artifact is `benchmarks/latest_retrieval_results.json`. The run used five real
MCP queries, but the configured upstream `default` collection contained none of the
Incident golden documents. Therefore retrieval-quality targets were not met. The latency
value only proves protocol execution against that empty collection; it is not evidence of
production retrieval quality.

## Current Limitations

- The committed benchmark demonstrates the boundary but fails retrieval-quality targets
  until the golden runbooks are ingested into the configured upstream collection.
- `rag-as-mcp` currently reports some tool failures as ordinary text content with
  `isError=false`; the adapter must recognize those verified strings.
- The upstream MCP surface has no ingestion tool, so approved write-back remains an
  application-side contract.
- Local in-memory repositories are process-local; multi-worker recovery requires Redis.
- The strict lint/type gate currently covers correctness-critical modules rather than all
  legacy UI and service code.

## Repository Structure

```text
agents/           disposable workflow and specialist agents
api/              HTTP handlers and conversation coordination
conversation/     snapshots, events, repository contracts and Redis CAS
knowledge/        reviewed knowledge draft lifecycle
config/           runtime and RAG MCP configuration
benchmarks/       golden retrieval dataset and saved result artifact
scripts/          benchmark runner
tests/            unit and opt-in integration coverage
```

## License

Licensed under the repository's [MIT License](LICENSE). Legal attribution in the license
is retained; this README does not claim that third-party retrieval algorithms live in the
Incident Lifecycle Copilot repository.
