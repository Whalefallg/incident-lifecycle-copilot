import { expect, test, type Page, type Route } from "@playwright/test";

const now = "2026-09-29T09:00:00Z";

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installFixtureApi(page: Page) {
  let created = false;
  let resolved = false;
  let retrievalReady = false;
  let draftReady = false;
  const messages: Array<{ role: string; content: string; timestamp: string }> = [];
  const incident = () => ({ incident_id: "INC-E2E", title: "Checkout API elevated errors", service: "checkout-service", severity: "P0", status: resolved ? "resolved" : "open", workflow_state: resolved ? "postmortem" : "classify", revision: messages.length, created_at: now, updated_at: now });
  const events = () => [
    { event_id: "evt-alert", incident_id: "INC-E2E", type: "alert_received", timestamp: now, actor: "engineer", source: "incident_api", request_id: null, payload: { description: "Error rate reached 8%" }, provenance: "recorded_fact" },
    ...(resolved ? [{ event_id: "evt-resolved", incident_id: "INC-E2E", type: "incident_resolved", timestamp: now, actor: "engineer", source: "fixture_model", request_id: "req-resolve", payload: { summary: "Checkout recovered" }, provenance: "recorded_fact" }] : []),
  ];
  const draft = { draft_id: "draft-e2e", source_incident_id: "INC-E2E", version: 1, content: "Root cause: upstream timeout.\nCorrective action: tune circuit breaker.", content_hash: "fixture", status: "draft", created_at: now, reviewed_by: null, reviewed_at: null, approved_by: null, approved_at: null, ingested_at: null };

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/incidents" && request.method() === "GET") return json(route, { items: created ? [incident()] : [], total: created ? 1 : 0 });
    if (path === "/api/incidents" && request.method() === "POST") { created = true; return json(route, incident(), 201); }
    if (path === "/api/incidents/INC-E2E" && request.method() === "GET") return json(route, incident());
    if (path.endsWith("/events")) return json(route, { incident_id: "INC-E2E", items: events(), total: events().length });
    if (path.endsWith("/messages") && request.method() === "GET") return json(route, { incident_id: "INC-E2E", items: messages, total: messages.length });
    if (path.endsWith("/runbooks")) return json(route, { incident_id: "INC-E2E", items: retrievalReady ? [{ retrieval_id: "ret-1", request_id: "req-runbook", query: "checkout timeout runbook", collection: "fixture-runbooks", duration_ms: 8, results: [{ document_id: "checkout-timeout-runbook", source: "fixture", content: "Check upstream latency and circuit-breaker saturation.", score: 0.97, metadata: { backend: "fixture" } }] }] : [], total: retrievalReady ? 1 : 0 });
    if (path.endsWith("/trace")) return json(route, { incident_id: "INC-E2E", items: retrievalReady ? [{ trace_id: "trace-1", request_id: "req-runbook", started_at: now, completed_at: now, steps: [{ step_id: "step-1", agent: "ConsultantAgent", action: "retrieve_runbook", status: "completed", started_at: now, completed_at: now, duration_ms: 8, error_type: null }], retrievals: [{ retrieval_id: "ret-1", query: "checkout timeout runbook", collection: "fixture-runbooks", duration_ms: 8, result_count: 1 }] }] : [], total: retrievalReady ? 1 : 0 });
    if (path.endsWith("/postmortem")) return json(route, { incident_id: "INC-E2E", factual_timeline: events(), generated_analysis: draftReady ? draft : null });
    if (path.endsWith("/messages") && request.method() === "POST") {
      const payload = request.postDataJSON() as { message: string; request_id: string };
      const lower = payload.message.toLowerCase();
      retrievalReady ||= lower.includes("runbook");
      if (lower.includes("resolve")) { resolved = true; draftReady = true; }
      const reply = lower.includes("stakeholder") ? "Stakeholder update: checkout errors are contained." : lower.includes("resolve") ? "Incident resolved. Postmortem draft generated." : "Retrieved the checkout timeout runbook.";
      messages.push({ role: "engineer", content: payload.message, timestamp: now }, { role: "assistant", content: reply, timestamp: now });
      const envelope = (type: string, sequence: number, eventPayload: object) => `data: ${JSON.stringify({ event_id: `stream-${sequence}`, incident_id: "INC-E2E", request_id: payload.request_id, sequence, timestamp: now, type, payload: eventPayload })}\n\n`;
      const body = envelope("request.started", 1, {}) + envelope("agent.started", 2, { agent: "FixtureAgent" }) + envelope("message.delta", 3, { text: reply }) + (draftReady ? envelope("postmortem.generated", 4, { draft_id: draft.draft_id, version: 1 }) : "") + envelope("request.completed", draftReady ? 5 : 4, { revision: messages.length });
      return route.fulfill({ status: 200, contentType: "text/event-stream", body });
    }
    return json(route, { error: { code: "NOT_FOUND", message: path, request_id: "e2e", details: {} } }, 404);
  });
}

test("runs the incident lifecycle with fixture model and RAG data", async ({ page }) => {
  await installFixtureApi(page);
  await page.goto("/incidents");
  await page.getByRole("button", { name: "New demo incident" }).click();
  await page.getByRole("button", { name: "Create incident" }).click();
  await expect(page.getByRole("heading", { name: "Checkout API elevated errors" })).toBeVisible();

  await page.getByLabel("Message the Copilot").fill("Find the checkout timeout runbook");
  await page.getByRole("button", { name: "Send" }).click();
  await page.getByRole("tab", { name: /Runbooks/ }).click();
  await expect(page.getByText(/Check upstream latency/)).toBeVisible();
  await page.getByRole("tab", { name: /Agent Trace/ }).click();
  await expect(page.getByText("ConsultantAgent")).toBeVisible();

  await page.getByRole("tab", { name: "Conversation" }).click();
  await page.getByLabel("Message the Copilot").fill("Generate a stakeholder update");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/Stakeholder update/)).toBeVisible();
  await page.getByLabel("Message the Copilot").fill("Resolve the incident and generate postmortem");
  await page.getByRole("button", { name: "Send" }).click();
  await page.getByRole("tab", { name: /Postmortem/ }).click();
  await expect(page.getByText("RECORDED FACTS")).toBeVisible();
  await expect(page.getByText("GENERATED ANALYSIS")).toBeVisible();
  await expect(page.getByText(/Root cause: upstream timeout/)).toBeVisible();
});
