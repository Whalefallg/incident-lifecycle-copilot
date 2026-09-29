import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SeverityBadge } from "./SeverityBadge";

describe("SeverityBadge", () => {
  it("renders a classified severity", () => {
    render(<SeverityBadge severity="p0" />);
    expect(screen.getByText("P0")).toHaveClass("severity-p0");
  });

  it("makes an unclassified severity explicit", () => {
    render(<SeverityBadge severity={null} />);
    expect(screen.getByText("UNSET")).toHaveClass("severity-unset");
  });
});
