// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

describe("WeekChecklist as the flow's navigation (v2)", () => {
  it("marks a warned row with ! and a rose tone", () => {
    const warned = rows.map((r) => (r.key === "captain" ? { ...r, done: false, warn: true, value: "Captain is on the bench" } : r));
    render(<WeekChecklist decisions={warned} />);
    const item = screen.getAllByRole("listitem")[1];
    expect(item.getAttribute("data-warn")).toBe("true");
    expect(item.textContent).toContain("!");
    expect(item.textContent).not.toContain("✓");
  });

  it("rows (and Squad overview) are buttons that open their step, with the active one lit", () => {
    const onSelect = vi.fn();
    render(<WeekChecklist decisions={rows} onSelect={onSelect} activeStep="captain" />);
    fireEvent.click(screen.getByRole("button", { name: /squad overview/i }));
    expect(onSelect).toHaveBeenCalledWith("squad");
    fireEvent.click(screen.getByRole("button", { name: /bench order/i }));
    expect(onSelect).toHaveBeenCalledWith("bench");
    const items = screen.getAllByRole("listitem");
    expect(items[1].getAttribute("data-active")).toBe("true");
    expect(items[0].getAttribute("data-active")).toBe("false");
  });

  it("offers Reset plan only when the plan is dirty", () => {
    const onReset = vi.fn();
    const { rerender } = render(<WeekChecklist decisions={rows} onReset={onReset} dirty={false} />);
    expect(screen.queryByRole("button", { name: /reset plan/i })).toBeNull();
    rerender(<WeekChecklist decisions={rows} onReset={onReset} dirty />);
    fireEvent.click(screen.getByRole("button", { name: /reset plan/i }));
    expect(onReset).toHaveBeenCalled();
  });

  it("renders plain rows (no buttons) without onSelect", () => {
    render(<WeekChecklist decisions={rows} />);
    expect(within(screen.getAllByRole("listitem")[0]).queryByRole("button")).toBeNull();
  });
});
