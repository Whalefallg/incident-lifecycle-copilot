import { describe, expect, it, vi } from "vitest";

import { createMessageOperation, parseSseStream, type StreamEvent } from "./stream";

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

const completed = {
  event_id: "event-1",
  incident_id: "INC-1",
  request_id: "request-1",
  sequence: 0,
  timestamp: "2026-01-01T00:00:00Z",
  type: "request.completed",
  payload: { revision: 2 },
} satisfies StreamEvent;

describe("parseSseStream", () => {
  it("parses events split across arbitrary network chunks", async () => {
    const payload = `id: event-1\nevent: request.completed\ndata: ${JSON.stringify(completed)}\n\n`;
    const events: StreamEvent[] = [];
    await parseSseStream(
      streamFrom([payload.slice(0, 17), payload.slice(17, 43), payload.slice(43)]),
      (event) => events.push(event),
    );
    expect(events).toEqual([completed]);
  });
});

describe("createMessageOperation", () => {
  it("reuses its stable request ID when the same operation is retried", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(() =>
      Promise.resolve(
        new Response(
          `data: ${JSON.stringify(completed)}\n\n`,
          { status: 200, headers: { "Content-Type": "text/event-stream" } },
        ),
      ),
    );
    const operation = createMessageOperation("INC-1", "status", () => undefined, {
      requestId: "stable-request",
      fetcher,
    });
    await operation.run();
    await operation.run();
    const bodies: unknown[] = fetcher.mock.calls.map((call) => {
      const body = call[1]?.body;
      if (typeof body !== "string") throw new Error("expected a JSON request body");
      return JSON.parse(body) as unknown;
    });
    expect(bodies).toEqual([
      { message: "status", request_id: "stable-request" },
      { message: "status", request_id: "stable-request" },
    ]);
  });
});
