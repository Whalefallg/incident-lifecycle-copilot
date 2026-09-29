import { describe, expect, it } from "vitest";

import type { StreamEvent } from "../api/stream";
import { initialStreamState, reduceStreamState } from "./workspaceStore";

function delta(sequence: number, text: string): StreamEvent {
  return {
    event_id: `event-${sequence}`,
    incident_id: "INC-1",
    request_id: "request-1",
    sequence,
    timestamp: "2026-01-01T00:00:00Z",
    type: "message.delta",
    payload: { text },
  };
}

describe("reduceStreamState", () => {
  it("appends ordered deltas and ignores duplicate sequences", () => {
    const first = reduceStreamState(initialStreamState, delta(1, "hello "));
    const second = reduceStreamState(first, delta(2, "world"));
    expect(second.text).toBe("hello world");
    expect(reduceStreamState(second, delta(2, "duplicate"))).toBe(second);
  });
});
