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

  it("tracks public agent status and workflow transitions", () => {
    const started = reduceStreamState(initialStreamState, {
      event_id: "agent-started",
      incident_id: "INC-1",
      request_id: "request-1",
      sequence: 1,
      timestamp: "2026-01-01T00:00:00Z",
      type: "agent.started",
      payload: { agent: "TriageRouter" },
    });
    const transitioned = reduceStreamState(started, {
      event_id: "transition",
      incident_id: "INC-1",
      request_id: "request-1",
      sequence: 2,
      timestamp: "2026-01-01T00:00:01Z",
      type: "workflow.state_changed",
      payload: { from: "classify", to: "escalation" },
    });
    expect(transitioned.agents.TriageRouter?.status).toBe("running");
    expect(transitioned.workflowState).toBe("escalation");
  });
});
