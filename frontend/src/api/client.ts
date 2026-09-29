import type { components } from "./generated/schema";

export type Incident = components["schemas"]["IncidentResponse"];
export type IncidentList = components["schemas"]["IncidentListResponse"];
export type IncidentTimeline = components["schemas"]["IncidentTimelineResponse"];
export type IncidentEvent = components["schemas"]["IncidentEventResponse"];
export type CreateIncidentInput = components["schemas"]["CreateIncidentRequest"];
export type MessageList = components["schemas"]["MessageListResponse"];
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
  createIncident: (input: CreateIncidentInput) =>
    requestJson<Incident>("/api/incidents", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};
