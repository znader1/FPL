// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { DecisionCard, fmtGain, gwRange } from "./DecisionCard";
import type {
  FplTransferPlanHorizon,
  FplTransferRunnerUp,
  FplTransferVerdictDetail,
  FplTransferVerdictMove,
} from "@/lib/fplAssistantApi";

afterEach(cleanup);

const mv = (sellId: number, buyId: number, thisGw = 0.9, horizon = 2.8): FplTransferVerdictMove => ({
  sell: { id: sellId, name: `S${sellId}`, team: "LIV", price: 7.0 },
  buy: { id: buyId, name: `B${buyId}`, team: "BOU", price: 6.1 },
  position: "MID",
  this_gw_gain: thisGw,
  horizon_gain: horizon,
});

const ru = (sellId: number, buyId: number, clearsBar: boolean, thisGw = 1.0, horizon = 3.0): FplTransferRunnerUp => ({
  ...mv(sellId, buyId, thisGw, horizon),
  clears_bar: clearsBar,
});

const detail = (over: Partial<FplTransferVerdictDetail>): FplTransferVerdictDetail => ({
  action: "spend",
  horizon: { start_gw: 5, end_gw: 7, n: 3 },
  ft_before: 1,
  ft_after: 0,
  threshold: 2.0,
  moves: [mv(1, 2)],
  this_gw_gain: 0.9,
  horizon_gain: 2.8,
  hit_cost: 0,
  plan_net: 6.5,
  roll_alternative: { net: 0, gw: 6, moves: [] },
  next_move: null,
  ...over,
});

const plan = (d?: FplTransferVerdictDetail, extra: Partial<FplTransferPlanHorizon> = {}): FplTransferPlanHorizon => ({
  verdict: d?.action ?? "spend",
  reasoning: "legacy prose",
  verdict_detail: d,
  horizon_gws: 3,
  allow_hits: false,
  ...extra,
});

describe("helpers", () => {
  it("formats gains with sign and one decimal", () => {
    expect(fmtGain(0.94)).toBe("+0.9");
    expect(fmtGain(-1.25)).toBe("−1.3");
    expect(fmtGain(0)).toBe("+0.0");
  });
  it("formats GW ranges", () => {
    expect(gwRange({ start_gw: 5, end_gw: 7 })).toBe("GW5–7");
    expect(gwRange({ start_gw: 5, end_gw: 5 })).toBe("GW5");
    expect(gwRange({ start_gw: null, end_gw: null })).toBe("the horizon");
  });
});

describe("DecisionCard spend", () => {
  it("shows the move, both gains with the GW range, and the roll comparison", () => {
    render(<DecisionCard plan={plan(detail({}))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toMatch(/make the move/i);
    // Sibling spans, so textContent has no space between name and meta.
    expect(card.textContent).toContain("S1(LIV £7.0)");
    expect(card.textContent).toContain("B2(BOU £6.1)");
    expect(screen.getByTestId("decision-gains").textContent).toBe("+0.9 this GW · +2.8 over GW5–7");
    expect(card.textContent).toMatch(/Plan GW5–7 nets \+6\.5/);
    expect(card.textContent).toMatch(/rolling instead nets \+0\.0/);
    expect(card.textContent).toContain("FT 1→0");
    expect(card.textContent).not.toContain("legacy prose");
  });

  it("applies the plan's moves via onApplyTransferAtIndex(k-1)", () => {
    const onApply = vi.fn();
    render(<DecisionCard plan={plan(detail({ moves: [mv(1, 2), mv(3, 4)] }))} onApplyTransferAtIndex={onApply} appliedTransferCount={0} />);
    // Card 2's button applies the plan through that move: index k-1.
    fireEvent.click(screen.getByRole("button", { name: /apply moves 1–2/i }));
    expect(onApply).toHaveBeenCalledWith(1);
  });

  it("marks applied once appliedTransferCount covers the plan moves", () => {
    render(<DecisionCard plan={plan(detail({}))} onApplyTransferAtIndex={() => {}} appliedTransferCount={1} />);
    const btn = screen.getByRole("button", { name: /applied/i });
    expect(btn.hasAttribute("disabled")).toBe(true);
  });

  it("shows Undo next to Applied and calls onResetAppliedTransfers", () => {
    const onReset = vi.fn();
    render(
      <DecisionCard
        plan={plan(detail({}))}
        onApplyTransferAtIndex={() => {}}
        onResetAppliedTransfers={onReset}
        appliedTransferCount={1}
      />,
    );
    expect(screen.getByRole("button", { name: /applied/i })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /undo/i }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("shows ITB after when the plan carries bank_after", () => {
    render(<DecisionCard plan={plan(detail({}), { plan: [{ gw: 5, action: "transfer", free_transfers_before: 1, free_transfers_after: 0, hits: 0, hit_cost: 0, gw_gain: 2.8, net_gain: 2.8, bank_after: 1.2, moves: [], note: "" }] })} />);
    expect(screen.getByTestId("plan-verdict-banner").textContent).toMatch(/ITB after £1\.2m/);
  });

  it("hides the apply button when no handler is given", () => {
    render(<DecisionCard plan={plan(detail({}))} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the hit cost when hits were taken", () => {
    render(<DecisionCard plan={plan(detail({ hit_cost: 4, this_gw_gain: 3.2, horizon_gain: 9.1 }))} />);
    expect(screen.getByTestId("decision-gains").textContent).toContain("−4.0 hit");
  });

  it("uses the injury tone and flags the seller on a forced sell", () => {
    render(<DecisionCard plan={plan(detail({ action: "spend_forced_injury", moves: [{ ...mv(1, 2), forced_injury: true }], roll_alternative: null }))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toMatch(/injury: act now/i);
    expect(card.textContent).toMatch(/flagged/i);
    expect(card.className).toContain("destructive");
  });
});

describe("DecisionCard roll", () => {
  it("explains the bank and names the next planned move", () => {
    render(<DecisionCard plan={plan(detail({
      action: "roll", moves: [], this_gw_gain: 0, horizon_gain: 0, ft_before: 1, ft_after: 2,
      roll_alternative: null, plan_net: 3.7,
      next_move: { gw: 6, moves: [mv(5, 6, 3.7, 3.7)], horizon_gain: 3.7 },
    }))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toMatch(/roll it/i);
    expect(card.textContent).toMatch(/No move clears \+2\.0 over GW5–7/);
    expect(card.textContent).toMatch(/Next planned move: S5 → B6 in GW6 \(\+3\.7 over GW6–7\)/);
    expect(card.textContent).toContain("FT 1→2");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("quotes the rejected spend when the counterfactual flipped the verdict", () => {
    render(<DecisionCard plan={plan(detail({
      action: "roll", moves: [], this_gw_gain: 0, horizon_gain: 0, ft_before: 1, ft_after: 2,
      plan_net: 14, roll_alternative: { net: 13, gw: 5, moves: [mv(1, 3)] },
      next_move: { gw: 6, moves: [mv(1, 3), mv(2, 4)], horizon_gain: 14 },
    }))} />);
    expect(screen.getByTestId("plan-verdict-banner").textContent)
      .toMatch(/Moving now \(S1 → B3\) would net \+13\.0 over GW5–7; rolling nets \+14\.0/);
  });
});

describe("DecisionCard runner-ups", () => {
  it("wraps GW range strings in a non-wrapping span", () => {
    render(<DecisionCard plan={plan(detail({}))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    const spans = Array.from(card.querySelectorAll("span.whitespace-nowrap"));
    expect(spans.some((s) => s.textContent === "GW5–7")).toBe(true);
  });

  it("renders nothing when runner_ups is empty or absent", () => {
    render(<DecisionCard plan={plan(detail({ runner_ups: [] }))} />);
    expect(screen.queryByTestId("runner-ups")).toBeNull();
    render(<DecisionCard plan={plan(detail({}))} />);
    expect(screen.queryByTestId("runner-ups")).toBeNull();
  });

  it("shows the first 3 runner-ups and folds the rest behind show N more, numbered from 2 on spend", () => {
    const runner_ups = [
      ru(10, 11, true), ru(12, 13, true), ru(14, 15, false), ru(16, 17, false), ru(18, 19, false),
    ];
    render(<DecisionCard plan={plan(detail({ runner_ups }))} />);
    const block = screen.getByTestId("runner-ups");
    expect(block.textContent).toMatch(/Also considered/);
    expect(block.textContent).toContain("2. S10 → B11");
    expect(block.textContent).toContain("3. S12 → B13");
    expect(block.textContent).toContain("4. S14 → B15");
    const details = block.querySelector("details");
    expect(details).toBeTruthy();
    expect(details?.hasAttribute("open")).toBe(false);
    const inDetails = within(details as HTMLElement);
    expect(inDetails.getByText(/show 2 more/i)).toBeTruthy();
    expect(inDetails.getByText(/5\. S16 → B17/)).toBeTruthy();
    expect(inDetails.getByText(/6\. S18 → B19/)).toBeTruthy();
  });

  it("numbers runner-ups from 1 and uses the roll heading on a roll verdict", () => {
    const runner_ups = [ru(10, 11, false)];
    render(<DecisionCard plan={plan(detail({
      action: "roll", moves: [], this_gw_gain: 0, horizon_gain: 0, ft_before: 1, ft_after: 2,
      roll_alternative: null, plan_net: 0, next_move: null, runner_ups,
    }))} />);
    const block = screen.getByTestId("runner-ups");
    expect(block.textContent).toMatch(/Best available — all below the bar/);
    expect(block.textContent).toContain("1. S10 → B11");
  });

  it("shows this-GW and horizon gains per runner-up row", () => {
    const runner_ups = [ru(10, 11, true, 1.1, 3.4)];
    render(<DecisionCard plan={plan(detail({ runner_ups }))} />);
    expect(screen.getByTestId("runner-ups").textContent).toMatch(/\+1\.1 this GW · \+3\.4/);
  });

  it("shows a below-bar tag only on runner-ups that don't clear the bar", () => {
    const runner_ups = [ru(10, 11, true), ru(12, 13, false)];
    render(<DecisionCard plan={plan(detail({ runner_ups }))} />);
    const block = screen.getByTestId("runner-ups");
    expect(block.textContent).toMatch(/below bar/);
    const rows = within(block).getAllByRole("listitem");
    expect(rows[0].textContent).not.toMatch(/below bar/);
    expect(rows[1].textContent).toMatch(/below bar/);
  });
});

describe("DecisionCard fallback", () => {
  it("renders the legacy reasoning banner when verdict_detail is absent", () => {
    render(<DecisionCard plan={plan(undefined, { verdict: "spend", first_gw_ft_before: 1, first_gw_ft_after: 0 })} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toContain("legacy prose");
    expect(card.textContent).toMatch(/Planned across 3 GWs/);
  });

  it("renders nothing without a verdict", () => {
    const { container } = render(<DecisionCard plan={{}} />);
    expect(container.querySelector('[data-testid="plan-verdict-banner"]')).toBeNull();
  });
});

describe("DecisionCard head-to-head flag", () => {
  it("shows 'faces your X' on the pick and on a runner-up", () => {
    render(<DecisionCard plan={plan(detail({
      moves: [{ ...mv(1, 2), h2h_conflicts: ["Raya"] }],
      runner_ups: [{ ...mv(3, 4, 4.5, 4.5), clears_bar: true, h2h_conflicts: ["Woodman"] }],
    }))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toContain("faces your Raya");
    expect(screen.getByTestId("runner-ups").textContent).toContain("faces your Woodman");
  });

  it("renders no flag when there is no conflict", () => {
    render(<DecisionCard plan={plan(detail({}))} />);
    expect(screen.queryByText(/faces your/i)).toBeNull();
  });
});

describe("DecisionCard seller fitness chip", () => {
  it("shows '75% fit' on the pick and on a runner-up for a doubtful seller", () => {
    render(<DecisionCard plan={plan(detail({
      moves: [{ ...mv(1, 2), sell_availability: { status: "d", chance: 75 } }],
      runner_ups: [{ ...mv(3, 4, 4.5, 4.5), clears_bar: true,
                     sell_availability: { status: "d", chance: 60 } }],
    }))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toContain("75% fit");
    expect(screen.getByTestId("runner-ups").textContent).toContain("60% fit");
  });

  it("shows the status word when chance is unknown", () => {
    render(<DecisionCard plan={plan(detail({
      moves: [{ ...mv(1, 2), sell_availability: { status: "i", chance: null } }],
    }))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toContain("injured");
  });

  it("renders no chip when the seller is fit", () => {
    render(<DecisionCard plan={plan(detail({}))} />);
    expect(screen.queryByText(/% fit/i)).toBeNull();
  });
});

describe("DecisionCard single-week horizon", () => {
  it("shows one number when the plan covers only this GW", () => {
    render(<DecisionCard plan={plan(detail({
      horizon: { start_gw: 5, end_gw: 5, n: 1 }, this_gw_gain: 4.5, horizon_gain: 3.0,
      roll_alternative: null,
      runner_ups: [{ ...mv(3, 4, 3.8, 2.2), clears_bar: true }],
    }))} />);
    expect(screen.getByTestId("decision-gains").textContent).toBe("+3.0 this GW");
    expect(screen.getByTestId("runner-ups").textContent).toContain("+2.2 this GW");
    expect(screen.getByTestId("runner-ups").textContent).not.toContain("+3.8");
  });
});

describe("DecisionCard move cards (2026-10 Command Center)", () => {
  it("renders one card per move with both jerseys and the in-player's name leading", () => {
    render(<DecisionCard plan={plan(detail({}))} />);
    const cards = screen.getAllByTestId("move-card");
    expect(cards).toHaveLength(1);
    expect(cards[0].querySelectorAll("svg.drop-shadow-md")).toHaveLength(2);
    expect(cards[0].textContent).toMatch(/B2.*for S1/);
  });

  it("labels each move free or hit by position against the free transfers, and nets the hit", () => {
    render(<DecisionCard plan={plan(detail({ moves: [mv(1, 2, 0.9, 2.8), mv(3, 4, 1.0, 5.2)], ft_before: 1, hit_cost: 4, horizon_gain: 8.0 }))} />);
    const cards = screen.getAllByTestId("move-card");
    expect(cards[0].textContent).toContain("Free transfer");
    expect(cards[0].querySelector('[data-testid="move-net"]')?.textContent).toBe("+2.8");
    expect(cards[1].textContent).toContain("−4 hit");
    expect(cards[1].querySelector('[data-testid="move-net"]')?.textContent).toBe("+1.2");
  });

  it("colours a negative net rose", () => {
    render(<DecisionCard plan={plan(detail({ moves: [mv(1, 2, 0.5, 2.0), mv(3, 4, 0.2, 1.0)], ft_before: 1, hit_cost: 4 }))} />);
    const nets = screen.getAllByTestId("move-net");
    expect(nets[1].textContent).toBe("−3.0");
    expect(nets[1].className).toContain("fdr-4");
    expect(nets[0].className).toContain("accent");
  });

  it("draws the out/in comparison bars only when the seller's horizon xPts is known", () => {
    const { rerender } = render(<DecisionCard plan={plan(detail({}))} />);
    expect(screen.queryByTestId("xpts-bars")).toBeNull();
    rerender(<DecisionCard plan={plan(detail({}))} horizonXptsById={{ 1: 14.2 }} />);
    const bars = screen.getByTestId("xpts-bars");
    expect(bars.textContent).toContain("14.2");
    expect(bars.textContent).toContain("17.0");
    const fills = bars.querySelectorAll('[data-testid="xpts-bar-fill"]');
    expect((fills[0] as HTMLElement).style.width).toBe("79%");
    expect((fills[1] as HTMLElement).style.width).toBe("94%");
  });

  it("names the next fixtures in the reason line when the backend sends them", () => {
    const m = { ...mv(1, 2), sell: { ...mv(1, 2).sell, next_fixture: "LIV (A)" }, buy: { ...mv(1, 2).buy, next_fixture: "WHU (H)" } };
    render(<DecisionCard plan={plan(detail({ moves: [m] }))} />);
    expect(screen.getByTestId("move-card").textContent).toContain("S1 has LIV (A); B2 gets WHU (H)");
  });

  it("marks the applied card and offers Undo on it", () => {
    render(<DecisionCard plan={plan(detail({}))} onApplyTransferAtIndex={() => {}} onResetAppliedTransfers={() => {}} appliedTransferCount={1} />);
    const card = screen.getByTestId("move-card");
    expect(card.getAttribute("data-applied")).toBe("true");
    expect(within(card).getByRole("button", { name: /undo/i })).toBeTruthy();
  });

  it("offers 'Apply this move' on the next move in sequence", () => {
    const onApply = vi.fn();
    render(<DecisionCard plan={plan(detail({}))} onApplyTransferAtIndex={onApply} appliedTransferCount={0} />);
    fireEvent.click(screen.getByRole("button", { name: /apply this move/i }));
    expect(onApply).toHaveBeenCalledWith(0);
  });
});

describe("DecisionCard roll alternative card", () => {
  const rollDetail = (ft_before: number) => detail({
    action: "roll", moves: [], this_gw_gain: 0, horizon_gain: 0, ft_before, ft_after: ft_before + 1,
    plan_net: 14, roll_alternative: { net: 13, gw: 5, moves: [mv(1, 3, 2.0, 6.0)] },
    next_move: { gw: 6, moves: [mv(1, 3), mv(2, 4)], horizon_gain: 14 },
  });

  it("shows the rejected move as a card with its net versus rolling, and no button without a beam match", () => {
    render(<DecisionCard plan={plan(rollDetail(1))} onApplyTransferAtIndex={() => {}} />);
    const card = screen.getByTestId("move-card");
    expect(card.textContent).toContain("B3");
    expect(within(card).getByTestId("move-net").textContent).toBe("−1.0");
    expect(within(card).queryByRole("button")).toBeNull();
  });

  it("wires 'Make the move anyway' to the matching beam index when the FT is free", () => {
    const onApply = vi.fn();
    const beam = [{ sell: { id: 9, name: "X", team: "AAA", price: 5 }, buy: { id: 8, name: "Y", team: "BBB", price: 5 }, score_gain: 1 },
                  { sell: { id: 1, name: "S1", team: "LIV", price: 7 }, buy: { id: 3, name: "B3", team: "BOU", price: 6.1 }, score_gain: 6 }];
    render(<DecisionCard plan={plan(rollDetail(1))} onApplyTransferAtIndex={onApply} beamMoves={beam} />);
    fireEvent.click(screen.getByRole("button", { name: /make the move anyway/i }));
    expect(onApply).toHaveBeenCalledWith(1);
  });

  it("says 'Take the hit anyway' when there is no free transfer to spend", () => {
    const beam = [{ sell: { id: 1, name: "S1", team: "LIV", price: 7 }, buy: { id: 3, name: "B3", team: "BOU", price: 6.1 }, score_gain: 6 }];
    render(<DecisionCard plan={plan(rollDetail(0))} onApplyTransferAtIndex={() => {}} beamMoves={beam} />);
    expect(screen.getByRole("button", { name: /take the hit anyway/i })).toBeTruthy();
    expect(screen.getByTestId("move-card").textContent).toContain("−4 hit");
  });

  it("puts the roll reasoning in the tip box", () => {
    render(<DecisionCard plan={plan(rollDetail(1))} />);
    expect(screen.getByTestId("plan-tip").textContent).toMatch(/rolling nets \+14\.0/);
  });
});
