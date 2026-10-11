import { describe, expect, it } from "vitest";
import { deriveWeekDecisions, type WeekDecisionInput } from "./weekDecisions";
import { buildPlayerLookup, makeMoves, seedPlan, swapPlayers, type GwPlan } from "./gwPlan";
import {
  SAMPLE_SQUAD,
  SAMPLE_TEAM_RECOMMENDATION,
  type ChipPlanResponse,
  type FplTeamRecommendation,
  type FplTransferVerdictDetail,
} from "./fplAssistantApi";

// Sample squad: B.Fernandes (449) captain, Enzo (237) vice; bench Dúbravka (GK), Thiago, Calvert-Lewin, Estève.
const mv = (sell: string, buy: string) => ({
  sell: { id: 136, name: sell, team: "BRE", price: 8.5 },
  buy: { id: 2, name: buy, team: "BOU", price: 7.1 },
  this_gw_gain: 0.8,
  horizon_gain: 2.4,
});

const detail = (over: Partial<FplTransferVerdictDetail>): FplTransferVerdictDetail => ({
  action: "spend",
  horizon: { start_gw: 29, end_gw: 31, n: 3 },
  ft_before: 1,
  ft_after: 0,
  threshold: 2,
  moves: [mv("Thiago", "Solanke")],
  this_gw_gain: 0.8,
  horizon_gain: 2.4,
  hit_cost: 0,
  plan_net: 2.4,
  roll_alternative: null,
  next_move: null,
  ...over,
});

const rec = (d?: FplTransferVerdictDetail): FplTeamRecommendation => ({
  ...SAMPLE_TEAM_RECOMMENDATION,
  transfer_plan_horizon: d ? { verdict: d.action, verdict_detail: d } : undefined,
});

const chipPlan = (over: Partial<ChipPlanResponse>): ChipPlanResponse => ({
  entry_id: 1,
  current_gw: 29,
  chips_remaining: [],
  horizon_model_gws: 6,
  recommendations: [],
  nudge: null,
  transfer_context: { planned_transfers_net_gain: 0, wc_alternative_gw: null },
  ...over,
});

const seed = seedPlan(SAMPLE_SQUAD);
const base: WeekDecisionInput = {
  plan: seed,
  base: seed,
  lookup: buildPlayerLookup(SAMPLE_SQUAD, undefined),
  recommendation: undefined,
  chipPlan: null,
};

const byKey = (input: WeekDecisionInput) => Object.fromEntries(deriveWeekDecisions(input).map((d) => [d.key, d]));
const withPlan = (over: Partial<GwPlan>, rest: Partial<WeekDecisionInput> = {}) => byKey({ ...base, ...rest, plan: { ...seed, ...over } });

describe("deriveWeekDecisions", () => {
  it("returns the four rows in order, none done on a fresh plan", () => {
    const rows = deriveWeekDecisions(base);
    expect(rows.map((r) => r.label)).toEqual(["Transfers", "Captain", "Bench order", "Chip"]);
    expect(rows.every((r) => !r.done)).toBe(true);
  });

  it("waits for the squad before saying anything", () => {
    const rows = deriveWeekDecisions({ ...base, plan: null });
    expect(rows.every((r) => !r.done)).toBe(true);
    expect(rows[0].value).toBe("Loading your squad…");
  });

  it("transfers: undecided until the plan says make or roll", () => {
    expect(byKey(base).transfers.value).toBe("Run ZN Pick to see your moves");
    const r = rec(detail({}));
    const open = byKey({ ...base, recommendation: r });
    expect(open.transfers.done).toBe(false);
    expect(open.transfers.value).toBe("Not decided · 1 FT");
    const made = withPlan({ transfer: "make" }, { recommendation: r, lookup: buildPlayerLookup(SAMPLE_SQUAD, r) });
    expect(made.transfers.done).toBe(true);
    expect(made.transfers.value).toBe("Thiago → Solanke · +2.4");
    const rolled = withPlan({ transfer: "roll" }, { recommendation: rec(detail({ action: "roll", moves: [], ft_after: 2 })) });
    expect(rolled.transfers.done).toBe(true);
    expect(rolled.transfers.value).toBe("Roll · 2 FTs for GW30");
  });

  it("transfers: counts several moves and names the hit", () => {
    const r = rec(detail({ moves: [mv("A", "B"), { ...mv("C", "D"), sell: { id: 691, name: "C", team: "X", price: 5 }, buy: { id: 3, name: "D", team: "Y", price: 5 } }], hit_cost: 4, horizon_gain: 5.1 }));
    expect(withPlan({ transfer: "make" }, { recommendation: r }).transfers.value).toBe("2 moves · +1.1 after a −4 hit");
    const roll = withPlan({ transfer: "roll" }, { recommendation: undefined });
    expect(roll.transfers.value).toBe("Roll the transfer");
  });

  it("captain: reads the plan's armbands, done once reviewed, warns when he's benched", () => {
    const fresh = byKey(base);
    expect(fresh.captain.value).toBe("B.Fernandes (C) · Enzo (VC)");
    expect(fresh.captain.done).toBe(false);
    expect(withPlan({ reviewed: { captain: true } }).captain.done).toBe(true);
    const benched = byKey({ ...base, plan: { ...swapPlayers(seed, 136, 449), reviewed: { captain: true } } });
    expect(benched.captain).toMatchObject({ done: false, warn: true, value: "Captain is on the bench" });
  });

  it("captain: follows the transfer when the captain is the player sold", () => {
    const r = rec(detail({ moves: [{ ...mv("B.Fernandes", "Solanke"), sell: { id: 449, name: "B.Fernandes", team: "MUN", price: 9 } }] }));
    const d = withPlan({ transfer: "make" }, { recommendation: r, lookup: buildPlayerLookup(SAMPLE_SQUAD, r) });
    expect(d.captain.value).toBe("Solanke (C) · Enzo (VC)");
  });

  it("bench: names the first sub; done once reviewed", () => {
    expect(byKey(base).bench).toMatchObject({ value: "Thiago first sub", done: false });
    expect(withPlan({ reviewed: { bench: true } }).bench.done).toBe(true);
  });

  it("chip: a chosen chip is decided; Save names the next window", () => {
    expect(withPlan({ chip: "bench_boost" }).chip).toMatchObject({ done: true, value: "Bench Boost this week" });
    const saved = withPlan(
      { chip: "none" },
      { chipPlan: chipPlan({ recommendations: [{ chip: "bench_boost", event_id: 32, ev_gain: 6, provisional: false, reasons: [], ev_curve: [] }] }) },
    );
    expect(saved.chip).toMatchObject({ done: true, value: "Save · Bench Boost peaks in GW32" });
    expect(withPlan({ chip: "none" }, { chipPlan: chipPlan({}) }).chip.value).toBe("Save · no chip window ahead");
    expect(withPlan({ chip: "none" }).chip.value).toBe("Save chips");
  });

  it("chip: undecided rows surface the nudge, the failure, or the wait", () => {
    const nudged = byKey({ ...base, chipPlan: chipPlan({ nudge: { chip: "triple_captain", event_id: 29, ev_gain: 3.1 } }) });
    expect(nudged.chip).toMatchObject({ done: false, value: "Triple Captain nudge for GW29 · +3.1 xPts" });
    expect(byKey({ ...base, chipPlanError: true }).chip.value).toBe("Chip plan unavailable · decide in the Chip step");
    expect(byKey(base).chip.value).toBe("Waiting for the chip plan");
    expect(byKey({ ...base, chipPlan: chipPlan({}) }).chip.value).toBe("Not decided · Save is the ZN Pick");
  });
});
