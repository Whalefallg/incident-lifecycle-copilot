import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceTabs } from "./WorkspaceTabs";

describe("WorkspaceTabs", () => {
  it("announces the selected view and timeline count", () => {
    const onSelect = vi.fn();
    render(<WorkspaceTabs selected="conversation" timelineCount={3} runbookCount={1} traceCount={2} onSelect={onSelect} />);
    expect(screen.getByRole("tab", { name: "Conversation" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Timeline (3)" }));
    expect(onSelect).toHaveBeenCalledWith("timeline");
    expect(screen.getByRole("tab", { name: "Runbooks (1)" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Agent Trace (2)" })).toBeVisible();
  });
});
