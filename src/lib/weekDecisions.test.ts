import { describe, expect, it } from "vitest";
import { deriveWeekDecisions, type WeekDecisionInput } from "./weekDecisions";
import {
  SAMPLE_TEAM_RECOMMENDATION,
  type ChipPlanResponse,
  type FplTeamRecommendation,
  type FplTransferVerdictDetail,
} from "./fplAssistantApi";

const mv = (sell: string, buy: string) => ({
  sell: { id: 1, name: sell, team: "NEW", price: 8.5 },
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
  moves: [mv("Isak", "Solanke")],
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

const base: WeekDecisionInput = {
  recommendation: undefined,
  appliedTransferCount: 0,
  chipStrategy: "none",
  chipPlan: null,
};

const byKey = (input: WeekDecisionInput) =>
  Object.fromEntries(deriveWeekDecisions(input).map((d) => [d.key, d]));

describe("deriveWeekDecisions", () => {
  it("returns the four rows in order, all pending before a recommendation", () => {
    const rows = deriveWeekDecisions(base);
    expect(rows.map((r) => r.label)).toEqual(["Transfers", "Captain", "Bench order", "Chip"]);
    expect(rows.every((r) => !r.done)).toBe(true);
  });

  it("transfers: a spend verdict is pending with the move's worth until applied", () => {
    const d = byKey({ ...base, recommendation: rec(detail({})) });
    expect(d.transfers.done).toBe(false);
    expect(d.transfers.value).toBe("1 free move worth +2.4 xPts");
    const applied = byKey({ ...base, recommendation: rec(detail({})), appliedTransferCount: 1 });
    expect(applied.transfers.done).toBe(true);
    expect(applied.transfers.value).toBe("Isak → Solanke applied");
  });

  it("transfers: counts moves and names the hit", () => {
    const d = byKey({ ...base, recommendation: rec(detail({ moves: [mv("A", "B"), mv("C", "D")], hit_cost: 4, horizon_gain: 5.1 })) });
    expect(d.transfers.value).toBe("2 moves worth +5.1 xPts after a −4 hit");
    const applied = byKey({ ...base, recommendation: rec(detail({ moves: [mv("A", "B"), mv("C", "D")] })), appliedTransferCount: 2 });
    expect(applied.transfers.value).toBe("2 moves applied");
  });

  it("transfers: a roll verdict is already decided", () => {
    const d = byKey({ ...base, recommendation: rec(detail({ action: "roll", moves: [], ft_after: 2 })) });
    expect(d.transfers.done).toBe(true);
    expect(d.transfers.value).toBe("Roll · 2 FTs for GW30");
  });

  it("captain and bench come from the recommendation's suggested picks", () => {
    const d = byKey({ ...base, recommendation: rec() });
    expect(d.captain.done).toBe(true);
    expect(d.captain.value).toBe("B.Fernandes (C) · Enzo (VC)");
    expect(d.bench.done).toBe(true);
    expect(d.bench.value).toBe("Thiago first sub · Dúbravka covers GK");
  });

  it("chip: a chosen chip is decided", () => {
    const d = byKey({ ...base, chipStrategy: "bench_boost" });
    expect(d.chip.done).toBe(true);
    expect(d.chip.value).toBe("Bench Boost this week");
  });

  it("chip: a pending nudge keeps the row open", () => {
    const d = byKey({ ...base, chipPlan: chipPlan({ nudge: { chip: "triple_captain", event_id: 29, ev_gain: 3.1 } }) });
    expect(d.chip.done).toBe(false);
    expect(d.chip.value).toBe("Triple Captain nudge for GW29 · +3.1 xPts");
  });

  it("chip: no nudge means save, naming the next window", () => {
    const d = byKey({
      ...base,
      chipPlan: chipPlan({
        recommendations: [{ chip: "bench_boost", event_id: 32, ev_gain: 6, provisional: false, reasons: [], ev_curve: [] }],
      }),
    });
    expect(d.chip.done).toBe(true);
    expect(d.chip.value).toBe("Save · Bench Boost peaks in GW32");
    const none = byKey({ ...base, chipPlan: chipPlan({}) });
    expect(none.chip.done).toBe(true);
    expect(none.chip.value).toBe("Save · no chip window ahead");
  });

  it("chip: a failed plan says so instead of waiting forever", () => {
    const d = byKey({ ...base, chipPlanError: true });
    expect(d.chip.done).toBe(false);
    expect(d.chip.value).toBe("Chip plan unavailable · pick one in Parameters");
  });

  it("chip: no plan yet stays pending", () => {
    expect(byKey(base).chip.done).toBe(false);
    expect(byKey(base).chip.value).toBe("Waiting for the chip plan");
  });
});
