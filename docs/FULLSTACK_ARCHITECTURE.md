# Full-Stack Architecture

## Request and persistence boundary

```text
React workspace
  ├─ typed REST ────────────────┐
  └─ typed SSE request stream ──┤
                                v
FastAPI → IncidentService / IncidentStreamingService
                                |
                                v
                    ConversationCoordinator
                                |
                                v
                    ConversationSnapshot (revisioned)
                                |
                InMemory development / Redis CAS
```

Each request hydrates a disposable agent graph from the latest snapshot. The coordinator executes it, applies domain changes, and saves with the expected revision. A repeated request ID with the same canonical payload returns the prior result; reuse with a different payload is rejected.

## SSE semantics

The stream is a typed projection of request progress and durable coordinator output. It is not real-time token streaming: the current agent execution completes before committed workflow, ledger, retrieval, message, and postmortem events are emitted. The service therefore does not synthesize `message.delta`, agent timing, or retrieval-start events after execution.

`request.started` is ephemeral. Events describing workflow state, the incident ledger, retrieval evidence, the completed message, and generated postmortems reflect the saved snapshot. `request.completed` includes the saved revision and tells the UI to invalidate the incident query prefix. An `error` before completion means no successful durable completion was observed.

TanStack Query owns server state: incidents, messages, timeline events, runbooks, traces, and postmortems. Zustand owns transient UI state: the active tab and in-flight stream presentation. The durable revision is returned by `request.completed`, but the browser refreshes server queries instead of treating Zustand as an authoritative snapshot.

The browser creates one request ID per submitted operation and retains that operation for retry. A retry reuses the same request ID and payload. This matches coordinator idempotency: an identical retry returns the completed result, while a changed payload under the same ID returns `IDEMPOTENCY_MISMATCH`.

## API and observability

Official APIs live below `/api/incidents`, `/api/knowledge/drafts`, and `/api/monitoring`. Failures use the common `{ "error": { "code", "message", "request_id", "details" } }` envelope. Remaining compatibility routes are explicitly under `/api/legacy`; the old Jinja UI is at `/legacy`.

Request traces record execution metadata for actual participants: classification, specialist work, retrieval, and response generation. They do not expose model reasoning. Snapshot trace retention is bounded, retrievals retain at most five results, and each saved content excerpt is capped at 2,000 characters.

## Delivery and known limits

The production image builds the React application in a Node stage and serves its assets through FastAPI. CI separates fixture-backed browser E2E from Docker runtime smoke coverage, so mocked product behavior and production delivery are not conflated.

Redis CAS supports safe multi-worker writes, but cross-incident listings currently scan lists and are suitable only for demo-scale data. The upstream MCP integration is query-only today; it does not expose ingestion. Consequently, knowledge review can durably reach `APPROVED` but does not claim `INGESTED` without a real ingestor.
