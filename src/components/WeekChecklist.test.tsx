// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { WeekChecklist } from "./WeekChecklist";
import type { WeekDecision } from "@/lib/weekDecisions";

afterEach(cleanup);

const rows: WeekDecision[] = [
  { key: "transfers", label: "Transfers", value: "1 free move worth +2.4 xPts", done: false },
  { key: "captain", label: "Captain", value: "Saka (C) · Palmer (VC)", done: true },
  { key: "bench", label: "Bench order", value: "Mbeumo first sub", done: true },
  { key: "chip", label: "Chip", value: "Save", done: false },
];

describe("WeekChecklist", () => {
  it("counts the decisions made and fills the progress bar to match", () => {
    render(<WeekChecklist decisions={rows} />);
    expect(screen.getByText("2 of 4 decisions made")).toBeTruthy();
    expect((screen.getByTestId("week-progress") as HTMLElement).style.width).toBe("50%");
  });

  it("renders a tick on done rows and leaves pending rows unmarked", () => {
    render(<WeekChecklist decisions={rows} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[1].textContent).toContain("✓");
    expect(items[0].textContent).not.toContain("✓");
    expect(items[0].getAttribute("data-done")).toBe("false");
    expect(items[1].getAttribute("data-done")).toBe("true");
    expect(items[0].textContent).toContain("1 free move worth +2.4 xPts");
  });
});
