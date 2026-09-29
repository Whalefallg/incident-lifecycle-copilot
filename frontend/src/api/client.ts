import type { components } from "./generated/schema";

export type Incident = components["schemas"]["IncidentResponse"];
export type IncidentList = components["schemas"]["IncidentListResponse"];
export type IncidentTimeline = components["schemas"]["IncidentTimelineResponse"];
export type IncidentEvent = components["schemas"]["IncidentEventResponse"];
export type CreateIncidentInput = components["schemas"]["CreateIncidentRequest"];
export type MessageList = components["schemas"]["MessageListResponse"];
export type TraceList = components["schemas"]["TraceListResponse"];
export type RunbookList = components["schemas"]["RunbookListResponse"];
export type Postmortem = components["schemas"]["PostmortemResponse"];
export type KnowledgeDraft = components["schemas"]["KnowledgeDraftResponse"];
export type KnowledgeDraftList = components["schemas"]["KnowledgeDraftListResponse"];
export type Health = components["schemas"]["HealthResponse"];
export type SystemStats = components["schemas"]["SystemStatsResponse"];
export type RedisInfo = components["schemas"]["RedisInfoResponse"];
export type ErrorResponse = components["schemas"]["ErrorResponse"];

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;

  constructor(status: number, response: ErrorResponse) {
    super(response.error.message);
    this.name = "ApiError";
    this.status = status;
    this.code = response.error.code;
    this.requestId = response.error.request_id;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  const body: unknown = await response.json();
  if (!response.ok) {
    throw new ApiError(response.status, body as ErrorResponse);
  }
  return body as T;
}

export const api = {
  listIncidents: () => requestJson<IncidentList>("/api/incidents"),
  getIncident: (incidentId: string) =>
    requestJson<Incident>(`/api/incidents/${encodeURIComponent(incidentId)}`),
  getIncidentTimeline: (incidentId: string) =>
    requestJson<IncidentTimeline>(
      `/api/incidents/${encodeURIComponent(incidentId)}/events`,
    ),
  getIncidentMessages: (incidentId: string) =>
    requestJson<MessageList>(
      `/api/incidents/${encodeURIComponent(incidentId)}/messages`,
    ),
  getIncidentTrace: (incidentId: string) =>
    requestJson<TraceList>(`/api/incidents/${encodeURIComponent(incidentId)}/trace`),
  getIncidentRunbooks: (incidentId: string) =>
    requestJson<RunbookList>(
      `/api/incidents/${encodeURIComponent(incidentId)}/runbooks`,
    ),
  getIncidentPostmortem: (incidentId: string) =>
    requestJson<Postmortem>(
      `/api/incidents/${encodeURIComponent(incidentId)}/postmortem`,
    ),
  listKnowledgeDrafts: () =>
    requestJson<KnowledgeDraftList>("/api/knowledge/drafts"),
  transitionKnowledgeDraft: (
    draftId: string,
    action: "review" | "approve" | "reject",
    actor: string,
    adminToken: string,
  ) =>
    requestJson<KnowledgeDraft>(
      `/api/knowledge/drafts/${encodeURIComponent(draftId)}/${action}`,
      {
        method: "POST",
        headers: { "X-Admin-Token": adminToken },
        body: JSON.stringify({ actor }),
      },
    ),
  getHealth: () => requestJson<Health>("/api/monitoring/health"),
  getSystemStats: () => requestJson<SystemStats>("/api/monitoring/stats/system"),
  getRedisInfo: () => requestJson<RedisInfo>("/api/monitoring/redis/info"),
  createIncident: (input: CreateIncidentInput) =>
    requestJson<Incident>("/api/incidents", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};
