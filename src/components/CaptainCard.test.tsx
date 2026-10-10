// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CaptainCard } from "./CaptainCard";
import type { CaptainCandidate } from "@/lib/captainLab";

afterEach(cleanup);

const saka: CaptainCandidate = {
  id: 2, name: "Saka", team: "ARS", xpts: 7.4, doubled: 14.8, p10: 2, p90: 16, pHaul: 0.31,
  eoTop10k: 38, rankGainIfHaul: 41000, bigGain: true, fixture: { opponent: "BHA", isHome: true, difficulty: 1 }, suggested: false,
};

describe("CaptainCard", () => {
  it("shows the headline number, doubled value, range bar and the two stat tiles", () => {
    render(<CaptainCard c={saka} selected={false} znPick onSelect={() => {}} />);
    expect(screen.getByTestId("cap-xpts").textContent).toBe("7.4");
    expect(screen.getByText("xPts (×2 = 14.8)")).toBeTruthy();
    expect(screen.getByText("2–16 pts")).toBeTruthy();
    const fill = screen.getByTestId("range-fill") as HTMLElement;
    expect(fill.style.left).toBe("10%");
    expect(fill.style.width).toBe("70%");
    expect((screen.getByTestId("range-median") as HTMLElement).style.left).toBe("calc(37% - 1px)");
    expect(screen.getByText("38%")).toBeTruthy();
    expect(screen.getByText("+41k").className).toContain("accent");
    expect(screen.getByText("ZN Pick")).toBeTruthy();
    expect(screen.getByText("H-BHA(D1)")).toBeTruthy();
  });

  it("selects on click and marks the selected card", () => {
    const onSelect = vi.fn();
    const { rerender } = render(<CaptainCard c={saka} selected={false} znPick={false} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /Saka/ }));
    expect(onSelect).toHaveBeenCalledWith(2);
    rerender(<CaptainCard c={saka} selected znPick={false} onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: /Saka/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("C")).toBeTruthy();
  });

  it("shows dashes for missing ownership and rank data", () => {
    render(<CaptainCard c={{ ...saka, eoTop10k: undefined, rankGainIfHaul: undefined, bigGain: false, p10: undefined, p90: undefined }} selected={false} znPick={false} onSelect={() => {}} />);
    expect(screen.getAllByText("—")).toHaveLength(3); // EO, rank, range label
    expect(screen.queryByTestId("range-fill")).toBeNull();
  });
});
