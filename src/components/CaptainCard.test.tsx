// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CaptainCard } from "./CaptainCard";
import type { CaptainCandidate } from "@/lib/captainLab";

afterEach(cleanup);

const saka: CaptainCandidate = {
  id: 2, name: "Saka", team: "ARS", xpts: 7.4, doubled: 14.8, p10: 2, p90: 16, pHaul: 0.31,
  eoTop10k: 38, rankGainIfHaul: 41000, bigGain: true, fixture: { opponent: "BHA", isHome: true, difficulty: 1 }, suggested: false, benched: false,
};

describe("CaptainCard", () => {
  it("shows the headline number, doubled value, range bar and the two stat tiles", () => {
    render(<CaptainCard c={saka} role={null} znPick onMakeCaptain={() => {}} onMakeVice={() => {}} />);
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

  it("has separate Make captain / Make vice buttons and shows the role badge", () => {
    const onMakeCaptain = vi.fn();
    const onMakeVice = vi.fn();
    const { rerender } = render(<CaptainCard c={saka} role={null} znPick={false} onMakeCaptain={onMakeCaptain} onMakeVice={onMakeVice} />);
    fireEvent.click(screen.getByRole("button", { name: "Make captain" }));
    expect(onMakeCaptain).toHaveBeenCalledWith(2);
    fireEvent.click(screen.getByRole("button", { name: "Make vice" }));
    expect(onMakeVice).toHaveBeenCalledWith(2);
    rerender(<CaptainCard c={saka} role="C" znPick={false} onMakeCaptain={onMakeCaptain} onMakeVice={onMakeVice} />);
    expect(screen.getByTestId("captain-card").getAttribute("data-role")).toBe("C");
    expect(screen.getByText("Captain ✓")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Make vice" }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<CaptainCard c={saka} role="VC" znPick={false} onMakeCaptain={onMakeCaptain} onMakeVice={onMakeVice} />);
    expect(screen.getByText("Vice ✓")).toBeTruthy();
    expect(screen.getByText("VC")).toBeTruthy();
  });

  it("dims a benched candidate, disables both buttons and says why", () => {
    render(<CaptainCard c={{ ...saka, benched: true }} role={null} znPick={false} onMakeCaptain={() => {}} onMakeVice={() => {}} />);
    const card = screen.getByTestId("captain-card");
    expect(card.getAttribute("data-benched")).toBe("true");
    expect((screen.getByRole("button", { name: "Make captain" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Make vice" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Saka is on your bench. Bring him on in the Bench step first.")).toBeTruthy();
  });

  it("labels the ownership tile by its basis", () => {
    render(<CaptainCard c={{ ...saka, eoTop10k: undefined, ownershipPct: 38 }} role={null} znPick={false} onMakeCaptain={() => {}} onMakeVice={() => {}} ownershipBasis="overall" />);
    expect(screen.getByText("Ownership")).toBeTruthy();
    expect(screen.getByText("38%")).toBeTruthy();
    expect(screen.queryByText("Top 10k EO")).toBeNull();
  });

  it("shows dashes for missing ownership and rank data", () => {
    render(<CaptainCard c={{ ...saka, eoTop10k: undefined, rankGainIfHaul: undefined, bigGain: false, p10: undefined, p90: undefined }} role={null} znPick={false} onMakeCaptain={() => {}} onMakeVice={() => {}} />);
    expect(screen.getAllByText("—")).toHaveLength(3); // EO, rank, range label
    expect(screen.queryByTestId("range-fill")).toBeNull();
  });
});
