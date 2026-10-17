// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WildcardCard } from "./WildcardCard";
import type { ChipOutlookRow } from "@/lib/fplAssistantApi";

afterEach(cleanup);

const row: ChipOutlookRow = {
  chip: "wildcard",
  event_id: 31,
  ev_gain: 18.4,
  bar: 120,
  status: "hold",
  reasons: [],
  guidance: "Hold for now. GW31 is the best week so far (+18.4 pts).",
};

describe("WildcardCard", () => {
  it("shows the best week, its gain and the engine's guidance", () => {
    render(<WildcardCard row={row} previewing={false} onToggle={() => {}} />);
    expect(screen.getByText(/best week GW31/)).toBeTruthy();
    expect(screen.getByText("+18.4 xPts")).toBeTruthy();
    expect(screen.getByText(row.guidance as string)).toBeTruthy();
  });

  it("previews the wildcard draft", () => {
    const onToggle = vi.fn();
    render(<WildcardCard row={row} previewing={false} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole("button", { name: /wildcard draft/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("while previewing, says where to play it and offers the way back", () => {
    const onToggle = vi.fn();
    render(<WildcardCard row={row} previewing onToggle={onToggle} />);
    expect(screen.getByText(/play it from the chip step/i)).toBeTruthy();
    expect(screen.queryByText(/window above/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /back to my squad/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("says the gain is net of planned transfers", () => {
    render(<WildcardCard row={row} previewing={false} onToggle={() => {}} />);
    expect(screen.getByText(/beyond what your planned transfers already gain/)).toBeTruthy();
  });

  it("names the GW the preview drafts for, and says when that isn't the best week", () => {
    const { rerender } = render(<WildcardCard row={row} draftGw={7} previewing={false} onToggle={() => {}} />);
    expect(screen.getByRole("button", { name: "See GW7 wildcard draft" })).toBeTruthy();
    rerender(<WildcardCard row={row} draftGw={7} previewing onToggle={() => {}} />);
    expect(
      screen.getByText("The pitch shows a wildcard for GW7, drafted on your horizon setting — not the GW31 window above. Play it from the Chip step."),
    ).toBeTruthy();
  });

  it("waits while ZN Pick is running", () => {
    render(<WildcardCard row={row} previewing={false} busy onToggle={() => {}} />);
    expect((screen.getByRole("button", { name: /wildcard draft/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("still offers the draft when no week stands out", () => {
    render(<WildcardCard row={{ ...row, event_id: null, ev_gain: null, guidance: undefined }} previewing={false} onToggle={() => {}} />);
    expect(screen.getByText(/no wildcard week stands out/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /wildcard draft/i })).toBeTruthy();
  });

  it("renders nothing without an outlook row", () => {
    const { container } = render(<WildcardCard row={undefined} previewing={false} onToggle={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});
