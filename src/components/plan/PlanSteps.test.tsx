// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { StepChips } from "./StepChips";
import { PlanFooter } from "./PlanFooter";
import { TransfersStep } from "./TransfersStep";
import { CaptainStep } from "./CaptainStep";
import { BenchStep } from "./BenchStep";
import { ChipStep } from "./ChipStep";
import { ReviewStep } from "./ReviewStep";
import { StepHeader } from "./StepHeader";
import type { WeekDecision } from "@/lib/weekDecisions";
import type { CaptainLab } from "@/lib/captainLab";
import type { ChipOption, TransferOptions } from "@/lib/planFlow";
import { buildPlayerLookup, resolvePlan, seedPlan } from "@/lib/gwPlan";
import { SAMPLE_SQUAD } from "@/lib/fplAssistantApi";

afterEach(cleanup);

const decisions: WeekDecision[] = [
  { key: "transfers", label: "Transfers", value: "Not decided · 1 FT", done: false },
  { key: "captain", label: "Captain", value: "Captain is on the bench", done: false, warn: true },
  { key: "bench", label: "Bench order", value: "Thiago first sub", done: true },
  { key: "chip", label: "Chip", value: "Save chips", done: true },
];

describe("StepChips", () => {
  it("lists the six steps with ✓/! marks, lights the active one, and navigates", () => {
    const onSelect = vi.fn();
    render(<StepChips decisions={decisions} step="captain" onSelect={onSelect} />);
    const chips = screen.getAllByRole("button");
    expect(chips.map((c) => c.textContent)).toEqual(["Squad", "Transfers", "! Captain", "✓ Bench", "✓ Chip", "Review"]);
    expect(chips[2].getAttribute("aria-current")).toBe("step");
    fireEvent.click(chips[5]);
    expect(onSelect).toHaveBeenCalledWith("confirm");
  });
});

describe("StepChips scroll", () => {
  it("scrolls the active chip into view so Review is never hidden off the right edge", () => {
    const spy = vi.fn();
    Element.prototype.scrollIntoView = spy;
    render(<StepChips decisions={decisions} step="confirm" onSelect={() => {}} />);
    expect(spy).toHaveBeenCalled();
    expect((spy.mock.instances[0] as HTMLElement).textContent).toContain("Review");
  });
});

describe("StepHeader", () => {
  it("renders the eyebrow, title and sub, plus the saved banner when locked", () => {
    const { rerender } = render(<StepHeader copy={{ eyebrow: "Overview", title: "Your GW29 squad", sub: "Work through…" }} savedBanner={false} />);
    expect(screen.getByRole("heading", { name: "Your GW29 squad" })).toBeTruthy();
    expect(screen.getByText("Overview")).toBeTruthy();
    expect(screen.queryByText(/Plan saved/)).toBeNull();
    rerender(<StepHeader copy={{ eyebrow: "Overview", title: "Your GW29 squad", sub: "Work through…" }} savedBanner />);
    expect(screen.getByText("Plan saved. Any edit reopens it until the deadline.")).toBeTruthy();
  });
});

describe("PlanFooter", () => {
  it("renders Back only when allowed, the hint, and a disabled Next", () => {
    const onBack = vi.fn();
    const onNext = vi.fn();
    const { rerender } = render(
      <PlanFooter spec={{ label: "Next: Captain", disabled: true, hint: "Pick an option to continue", variant: "primary", hasBack: true }} onBack={onBack} onNext={onNext} />,
    );
    expect(screen.getByText("Pick an option to continue")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Next: Captain" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(onBack).toHaveBeenCalled();
    rerender(<PlanFooter spec={{ label: "Save GW29 plan", disabled: false, hint: "", variant: "accent", hasBack: false }} onBack={onBack} onNext={onNext} />);
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save GW29 plan" }));
    expect(onNext).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save GW29 plan" }).className).toContain("bg-accent");
  });
});

const tOpts: TransferOptions = {
  make: {
    zn: true,
    gain: 2.4,
    meta: "xPts over GW29–31 · free transfer",
    why: "Newcastle face Liverpool next.",
    moves: [{ sell: { id: 1, name: "Isak", team: "NEW", price: 8 }, buy: { id: 2, name: "Solanke", team: "BOU", price: 7 }, this_gw_gain: 0.8, horizon_gain: 2.4 }],
  },
  roll: { zn: false, gain: 0, meta: "this week · 2 FTs in GW30", why: "Bank it.", moves: [] },
  alsoConsidered: [{ sell: "Gordon", buy: "Rogers", net: -2.9, hit: true, bar: 4 }],
};

describe("TransfersStep", () => {
  it("renders two radio cards with the ZN badge, the move, the gain, and the also-considered row", () => {
    const onPick = vi.fn();
    render(<TransfersStep options={tOpts} value={null} onPick={onPick} />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(2);
    expect(within(radios[0]).getByText("ZN Pick")).toBeTruthy();
    expect(within(radios[0]).getByText("Solanke")).toBeTruthy();
    expect(within(radios[0]).getByText("+2.4")).toBeTruthy();
    expect(within(radios[1]).getByText("+0.0")).toBeTruthy();
    fireEvent.click(radios[1]);
    expect(onPick).toHaveBeenCalledWith("roll");
    expect(screen.getByText(/Gordon → Rogers/).textContent).toContain("−4 hit");
    expect(screen.getByText("below the +4.0 bar")).toBeTruthy();
  });

  it("marks the chosen card checked and disables Make when there is no move", () => {
    render(<TransfersStep options={{ ...tOpts, make: null }} value="roll" onPick={() => {}} />);
    const radios = screen.getAllByRole("radio");
    expect(radios[1].getAttribute("aria-checked")).toBe("true");
    expect(radios[0].getAttribute("aria-disabled")).toBe("true");
    expect(within(radios[0]).getByText("No move clears the bar")).toBeTruthy();
  });

  it("asks for ZN Pick when no recommendation exists yet", () => {
    render(<TransfersStep options={null} value={null} onPick={() => {}} loading />);
    expect(screen.getByText(/working out your moves/i)).toBeTruthy();
  });
});

const lab: CaptainLab = {
  candidates: [
    { id: 1, name: "Haaland", team: "MCI", xpts: 8.6, doubled: 17.2, bigGain: false, suggested: true, benched: false },
    { id: 2, name: "Saka", team: "ARS", xpts: 7.4, doubled: 14.8, bigGain: true, suggested: false, benched: false },
    { id: 3, name: "Palmer", team: "CHE", xpts: 6.9, doubled: 13.8, bigGain: false, suggested: false, benched: true },
  ],
  znPickId: 2,
  captainId: 1,
  viceId: 2,
  headline: "Captain Saka to climb the ranks.",
  subcopy: "Haaland projects higher, but…",
  rankAware: true,
  ownershipBasis: "top10k",
  projected: 66,
};

describe("CaptainStep", () => {
  it("shows the goal toggle, three cards with roles, and wires both buttons", () => {
    const onMakeCaptain = vi.fn();
    const onMakeVice = vi.fn();
    const onGoal = vi.fn();
    render(<CaptainStep lab={lab} goal="chase" onGoal={onGoal} onMakeCaptain={onMakeCaptain} onMakeVice={onMakeVice} />);
    const cards = screen.getAllByTestId("captain-card");
    expect(cards).toHaveLength(3);
    expect(cards[0].getAttribute("data-role")).toBe("C");
    expect(cards[1].getAttribute("data-role")).toBe("VC");
    expect(cards[2].getAttribute("data-benched")).toBe("true");
    fireEvent.click(within(cards[1]).getByRole("button", { name: "Make captain" }));
    expect(onMakeCaptain).toHaveBeenCalledWith(2);
    fireEvent.click(screen.getByRole("radio", { name: "Protect rank" }));
    expect(onGoal).toHaveBeenCalledWith("safe");
  });

  it("explains the fallback when the backend sends no ownership data", () => {
    render(<CaptainStep lab={{ ...lab, rankAware: false }} goal="chase" onGoal={() => {}} onMakeCaptain={() => {}} onMakeVice={() => {}} />);
    expect(screen.getByText(/Rank-aware picks need ownership data/)).toBeTruthy();
  });
});

describe("BenchStep", () => {
  const seed = seedPlan(SAMPLE_SQUAD);
  const lookup = buildPlayerLookup(SAMPLE_SQUAD, undefined);
  const r = resolvePlan(seed, []); // bench: Dúbravka (GK), Thiago, Calvert-Lewin, Estève

  it("lists the bench with order badges, arrows bounded at the ends, and Swap", () => {
    const onMove = vi.fn();
    const onSwap = vi.fn();
    render(<BenchStep resolved={r} lookup={lookup} swapSelection={null} onSwapSelect={onSwap} onMoveBench={onMove} autoSub="No flagged starters." message={null} />);
    const rows = screen.getAllByTestId("bench-row");
    expect(rows.map((x) => within(x).getByTestId("bench-order").textContent)).toEqual(["GK", "1", "2", "3"]);
    expect(within(rows[0]).queryByRole("button", { name: "Move up" })).toBeNull();
    expect((within(rows[1]).getByRole("button", { name: "Move up" }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(rows[3]).getByRole("button", { name: "Move down" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(rows[2]).getByRole("button", { name: "Move up" }));
    expect(onMove).toHaveBeenCalledWith(2, -1);
    fireEvent.click(within(rows[1]).getByRole("button", { name: "Swap" }));
    expect(onSwap).toHaveBeenCalledWith(136);
    expect(screen.getByText("No flagged starters.")).toBeTruthy();
    expect(rows[1].textContent).toContain("Thiago");
    expect(rows[1].textContent).toContain("FWD · ");
  });

  it("shows Cancel on the selected row and the message box", () => {
    render(
      <BenchStep
        resolved={r}
        lookup={lookup}
        swapSelection={136}
        onSwapSelect={() => {}}
        onMoveBench={() => {}}
        autoSub=""
        message={{ text: "Tap a highlighted starter to bring Thiago on.", tone: "primary" }}
      />,
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(screen.getByText("Tap a highlighted starter to bring Thiago on.")).toBeTruthy();
    expect(screen.getAllByTestId("bench-row")[1].getAttribute("data-selected")).toBe("true");
  });
});

const chipOpts: ChipOption[] = [
  { chip: "none", title: "Save chips", zn: true, gain: 0, why: "Bench Boost is worth +15.1 in GW32.", used: false },
  { chip: "bench_boost", title: "Bench Boost", zn: false, gain: 7.4, why: "Adds your bench this week.", used: false },
  { chip: "free_hit", title: "Free Hit", zn: false, gain: null, why: "Hold it.", used: false },
  { chip: "triple_captain", title: "Triple Captain", zn: false, gain: 8.6, why: "On Haaland.", used: true },
];

describe("ChipStep", () => {
  it("renders four radio cards, dashes unknown gains, disables used chips, and picks", () => {
    const onPick = vi.fn();
    render(<ChipStep options={chipOpts} value="none" onPick={onPick} />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(4);
    expect(radios[0].getAttribute("aria-checked")).toBe("true");
    expect(within(radios[0]).getByText("ZN Pick")).toBeTruthy();
    expect(within(radios[1]).getByText("+7.4")).toBeTruthy();
    expect(within(radios[2]).getByText("—")).toBeTruthy();
    expect(radios[3].getAttribute("aria-disabled")).toBe("true");
    expect(within(radios[3]).getByText("Already played")).toBeTruthy();
    fireEvent.click(radios[1]);
    expect(onPick).toHaveBeenCalledWith("bench_boost");
    fireEvent.click(radios[3]);
    expect(onPick).not.toHaveBeenCalledWith("triple_captain");
  });
});

describe("ReviewStep", () => {
  const rows = [
    { key: "transfers" as const, label: "Transfers", value: "Isak → Solanke · +2.4", changed: true },
    { key: "captain" as const, label: "Captain", value: "Saka (C) · Palmer (VC)", changed: false },
    { key: "bench" as const, label: "Bench", value: "Mbeumo, Cunha, Mykolenko · Sels (GK)", changed: false },
    { key: "chip" as const, label: "Chip", value: "Not decided", changed: false },
  ];

  it("lists tappable rows with Changed badges, the projected points and delta", () => {
    const onRow = vi.fn();
    render(<ReviewStep rows={rows} onRow={onRow} warnings={[]} onFix={() => {}} projected={68.4} delta={2.4} locked={false} todo={[]} gw={29} countdown="1d 04:12:33" />);
    fireEvent.click(screen.getByRole("button", { name: /Captain/ }));
    expect(onRow).toHaveBeenCalledWith("captain");
    expect(screen.getAllByText("Changed")).toHaveLength(1);
    expect(screen.getByTestId("review-projected").textContent).toBe("68.4");
    expect(screen.getByTestId("review-delta").textContent).toBe("+2.4");
  });

  it("shows a warning with a Fix button", () => {
    const onFix = vi.fn();
    render(<ReviewStep rows={rows} onRow={() => {}} warnings={[{ text: "Your captain is on the bench. Pick a starter.", fixStep: "captain" }]} onFix={onFix} projected={66} delta={0} locked={false} todo={[]} gw={29} countdown="" />);
    expect(screen.getByText(/⚠ Your captain is on the bench/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Fix" }));
    expect(onFix).toHaveBeenCalledWith("captain");
  });

  it("once saved, lists exactly what to change in the FPL app before the deadline", () => {
    render(
      <ReviewStep rows={rows} onRow={() => {}} warnings={[]} onFix={() => {}} projected={68.4} delta={2.4} locked todo={["Transfer out Isak, bring in Solanke (free).", "Set Saka as captain and Palmer as vice."]} gw={29} countdown="1d 04:12:33" />,
    );
    expect(screen.getByText("GW29 plan saved")).toBeTruthy();
    expect(screen.getByText(/before the deadline \(1d 04:12:33\)/)).toBeTruthy();
    expect(screen.getByText("Transfer out Isak, bring in Solanke (free).")).toBeTruthy();
  });
});
