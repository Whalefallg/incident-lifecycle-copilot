# Public Demo Deployment

This profile is designed for a resume link: one container, deterministic local
runbook retrieval, per-browser incident state, and bounded public usage. The
full MCP + Redis + Celery topology remains available for local architecture
demonstrations.

## Before deploying

1. Push the complete project to a GitHub repository. Include `data/runbooks/`
   but never commit `.env` or `.env.production`.
2. Create an LLM API key with a low project-level spending limit.
3. Choose a small, inexpensive chat model and confirm its model identifier.

## Deploy on Render

1. In Render, choose **New > Blueprint** and connect the GitHub repository.
2. Render detects `render.yaml` and builds the root `Dockerfile`.
3. Enter the secret `LLM_API_KEY` and the `LLM_MODEL` value when prompted.
4. After deployment, verify:

   ```bash
   curl https://YOUR-SERVICE.onrender.com/api/monitoring/health
   ```

5. Open the service URL and run all four guided buttons in order.

The Blueprint deliberately uses `RAG_MODE=local`, disables Redis-dependent
features, and keeps `WEB_CONCURRENCY=1`. This is required because the demo's
active agent objects live in process memory. Do not increase the worker count
until the complete conversation payload—not only the state enum—is persisted
and restored from a shared store.

To evaluate semantic caching separately, install `requirements-cache.txt`,
start Redis, and then enable `SEMANTIC_CACHE_ENABLED=true`. It is intentionally
excluded from the public image to reduce cold-start time and memory usage.

## Required secrets

| Variable | Example | Notes |
|---|---|---|
| `LLM_API_KEY` | provider key | Secret; never expose in client code |
| `LLM_MODEL` | provider model ID | Use a low-cost chat model |

For a non-OpenAI compatible endpoint, additionally change
`MODEL_PROVIDER` and add `LLM_BASE_URL` in the Render dashboard.

## Smoke-test checklist

- `/` loads over HTTPS and sets an `HttpOnly` session cookie.
- P0 Alert asks for or extracts impact details.
- Runbook Lookup cites one of the bundled runbook source IDs.
- Status Update produces audience-specific text.
- Postmortem uses messages from only the current browser session.
- New Incident clears both the UI and server-side conversation.
- An eleventh rapid chat request receives HTTP 429 with the default local
  configuration (the Render Blueprint limit is eight per minute).
- `POST /api/monitoring/cache/clear` returns HTTP 403 without `X-Admin-Token`.

## Resume packaging

Use three links when possible:

- **Live Demo** — the deployed service URL
- **Source Code** — the cleaned GitHub repository
- **90-second Walkthrough** — a short recording showing alert to postmortem

Do not claim a concurrency number or cost-reduction percentage until the
repository contains the load-test script, environment description, raw output,
and calculation method needed to reproduce it.
