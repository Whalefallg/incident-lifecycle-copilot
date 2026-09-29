import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import type { StreamEvent } from "../../api/stream";
import { refreshIncidentQueries } from "./ConversationPanel";

describe("refreshIncidentQueries", () => {
  it("refreshes every incident workspace query after durable completion", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();
    const event = {
      event_id: "event-1",
      incident_id: "INC-1",
      request_id: "request-1",
      sequence: 4,
      timestamp: "2026-09-29T09:00:00Z",
      type: "request.completed",
      payload: { revision: 2 },
    } satisfies StreamEvent;

    await refreshIncidentQueries(queryClient, "INC-1", event);

    expect(invalidate).toHaveBeenCalledOnce();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["incidents", "INC-1"] });
  });
});
