import { ApiError, type ErrorResponse } from "./client";

interface StreamEnvelope<TType extends string, TPayload> {
  event_id: string;
  incident_id: string;
  request_id: string;
  sequence: number;
  timestamp: string;
  type: TType;
  payload: TPayload;
}

export type StreamEvent =
  | StreamEnvelope<"request.started", Record<string, never>>
  | StreamEnvelope<"workflow.state_changed", { from: string; to: string }>
  | StreamEnvelope<"agent.started" | "agent.completed", { agent: string; duration_ms?: number | null }>
  | StreamEnvelope<"retrieval.started", { query: string }>
  | StreamEnvelope<"retrieval.completed", { query: string; result_count: number; duration_ms: number }>
  | StreamEnvelope<"incident.event", { event: Record<string, unknown> }>
  | StreamEnvelope<"message.delta", { text: string }>
  | StreamEnvelope<"message.completed", { message_id: string; text: string }>
  | StreamEnvelope<"postmortem.generated", { draft_id: string; version: number }>
  | StreamEnvelope<"request.completed", { revision: number }>
  | StreamEnvelope<"error", { code: string; message: string; details: Record<string, unknown> }>;

function parseBlock(block: string): StreamEvent | null {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  return data ? (JSON.parse(data) as StreamEvent) : null;
}

export async function parseSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = parseBlock(block);
      if (event) onEvent(event);
    }
    if (done) break;
  }

  const finalEvent = parseBlock(buffer);
  if (finalEvent) onEvent(finalEvent);
}

type Fetcher = typeof fetch;

export async function consumeIncidentStream(
  incidentId: string,
  message: string,
  requestId: string,
  onEvent: (event: StreamEvent) => void,
  fetcher: Fetcher = fetch,
): Promise<void> {
  const response = await fetcher(
    `/api/incidents/${encodeURIComponent(incidentId)}/messages`,
    {
      method: "POST",
      headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
      body: JSON.stringify({ message, request_id: requestId }),
    },
  );
  if (!response.ok) {
    throw new ApiError(response.status, (await response.json()) as ErrorResponse);
  }
  if (!response.body) throw new Error("Streaming response body is unavailable");
  await parseSseStream(response.body, onEvent);
}

export interface MessageOperation {
  readonly requestId: string;
  run: () => Promise<void>;
}

export function createMessageOperation(
  incidentId: string,
  message: string,
  onEvent: (event: StreamEvent) => void,
  options: { requestId?: string; fetcher?: Fetcher } = {},
): MessageOperation {
  const requestId = options.requestId ?? crypto.randomUUID();
  return {
    requestId,
    run: () =>
      consumeIncidentStream(
        incidentId,
        message,
        requestId,
        onEvent,
        options.fetcher,
      ),
  };
}
