import { describe, expect, it } from "vitest";

import { allowedDraftActions } from "./KnowledgePage";

describe("allowedDraftActions", () => {
  it("only exposes transitions allowed by the knowledge lifecycle", () => {
    expect(allowedDraftActions("draft")).toEqual(["review", "reject"]);
    expect(allowedDraftActions("reviewed")).toEqual(["approve", "reject"]);
    expect(allowedDraftActions("approved")).toEqual([]);
    expect(allowedDraftActions("ingested")).toEqual([]);
    expect(allowedDraftActions("rejected")).toEqual([]);
  });
});
