# Full-Stack Demo

## Local production-shaped run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-production.txt

cd frontend
npm ci
npm run build
cd ..

RAG_MODE=local REDIS_STATE_ENABLED=false uvicorn app:app --port 8000
```

Open `http://127.0.0.1:8000`, create a demo incident, then use the workspace to request a runbook, draft a stakeholder update, resolve the incident, and inspect the postmortem. Direct routes such as `/incidents/INC-DEMO` are handled by the SPA fallback. The legacy interface remains available at `/legacy`.

## 3–5 minute walkthrough

1. Open the Incident Workspace and create a checkout incident. Point out its severity, workflow state, and recorded alert in the timeline.
2. Ask for the checkout timeout runbook. Open Runbooks to show the source, excerpt, score, and metadata; then open Agent Trace to show the actual `ConsultantAgent` retrieval and response steps.
3. Ask for a stakeholder update and explain that communication is generated from the durable incident context rather than a separate browser-only state.
4. Resolve the incident and generate a postmortem. Contrast **Recorded Facts** from the event ledger with **Generated Analysis** from the model.
5. Open Knowledge Review and advance the draft through review and approval. Explain that it stops at `APPROVED` without an upstream ingestion tool.
6. Close with the implementation boundaries: `ConversationSnapshot` is the recovery source of truth, Redis uses revision CAS, retries reuse a stable request ID, and the retriever is isolated behind the MCP-compatible contract.

During a request, the UI consumes typed SSE. The current implementation reports request progress and committed results; it does not promise live token-by-token output. When `request.completed` arrives, the workspace refreshes all incident resources from REST so the displayed messages, timeline, evidence, trace, and postmortem match durable state.

## CI coverage

- Backend tests exercise APIs, domain behavior, snapshots, concurrency, idempotency, and SSE serialization without requiring `frontend/dist`.
- Frontend unit tests cover parsing, reducers, stable retry IDs, and query refresh behavior.
- Playwright runs the browser lifecycle against a mocked API and fixture RAG data. It validates frontend behavior, not a live model or full backend integration.
- The Docker job builds the production image, starts FastAPI, and smoke-checks `/`, `/incidents`, `/incidents/INC-SPA`, `/api/monitoring/health`, and `/legacy`.

Use `RAG_MODE=mcp` only when a compatible `rag-as-mcp` checkout and Python environment are configured. The upstream interface currently supports querying but not ingestion, so an approved knowledge draft remains `APPROVED` unless a real `KnowledgeIngestor` is supplied.
