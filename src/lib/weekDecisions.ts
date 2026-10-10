import {
  CHIP_LABELS,
  type ChipPlanResponse,
  type FplChipStrategy,
  type FplTeamRecommendation,
} from "@/lib/fplAssistantApi";
import { fmtGain } from "@/lib/format";

export type WeekDecisionKey = "transfers" | "captain" | "bench" | "chip";

export interface WeekDecision {
  key: WeekDecisionKey;
  label: string;
  /** One line of status under the label. */
  value: string;
  done: boolean;
}

export interface WeekDecisionInput {
  /** The active recommendation (already resolved to the applied-transfer step). */
  recommendation?: FplTeamRecommendation;
  appliedTransferCount: number;
  chipStrategy: FplChipStrategy;
  chipPlan?: ChipPlanResponse | null;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function transfersRow(rec: FplTeamRecommendation | undefined, applied: number): WeekDecision {
  const row = (value: string, done: boolean): WeekDecision => ({ key: "transfers", label: "Transfers", value, done });
  const d = rec?.transfer_plan_horizon?.verdict_detail;
  if (!rec) return row("Run ZN Pick to see your moves", false);
  if (!d) {
    const n = rec.transfers?.moves?.length ?? 0;
    return n > 0 ? row(`${plural(n, "suggested move")} to review`, false) : row("No moves suggested", true);
  }
  if (d.action === "roll") {
    const nextGw = d.horizon.start_gw != null ? ` for GW${d.horizon.start_gw + 1}` : "";
    return row(`Roll · ${plural(d.ft_after, "FT")}${nextGw}`, true);
  }
  const k = d.moves.length;
  if (k === 0) return row("No move clears the bar", true);
  if (applied >= k) {
    const m = d.moves[0];
    return row(k === 1 ? `${m.sell.name} → ${m.buy.name} applied` : `${k} moves applied`, true);
  }
  const hit = d.hit_cost > 0 ? ` after a −${d.hit_cost} hit` : "";
  const what = k === 1 && d.hit_cost === 0 ? "1 free move" : plural(k, "move");
  return row(`${what} worth ${fmtGain(d.horizon_gain)} xPts${hit}`, false);
}

function captainRow(rec: FplTeamRecommendation | undefined): WeekDecision {
  const row = (value: string, done: boolean): WeekDecision => ({ key: "captain", label: "Captain", value, done });
  if (!rec) return row("Run ZN Pick to check your armband", false);
  const all = [...rec.starting_xi, ...rec.bench];
  const cap = all.find((p) => p.is_captain_suggested) ?? all.find((p) => p.player_id === rec.captain_player_id);
  const vice = all.find((p) => p.is_vice_suggested) ?? all.find((p) => p.player_id === rec.vice_player_id);
  if (!cap) return row("No captain pick returned", false);
  return row(vice ? `${cap.web_name} (C) · ${vice.web_name} (VC)` : `${cap.web_name} (C)`, true);
}

function benchRow(rec: FplTeamRecommendation | undefined): WeekDecision {
  const row = (value: string, done: boolean): WeekDecision => ({ key: "bench", label: "Bench order", value, done });
  if (!rec) return row("Set after ZN Pick", false);
  const bench = [...rec.bench].sort((a, b) => a.bench_order - b.bench_order);
  const firstSub = bench.find((p) => p.pos !== "GKP");
  const gk = bench.find((p) => p.pos === "GKP");
  if (!firstSub) return row("No bench returned", false);
  return row(gk ? `${firstSub.web_name} first sub · ${gk.web_name} covers GK` : `${firstSub.web_name} first sub`, true);
}

function chipRow(chipStrategy: FplChipStrategy, plan: ChipPlanResponse | null | undefined): WeekDecision {
  const row = (value: string, done: boolean): WeekDecision => ({ key: "chip", label: "Chip", value, done });
  if (chipStrategy !== "none") return row(`${CHIP_LABELS[chipStrategy]} this week`, true);
  if (!plan) return row("Waiting for the chip plan", false);
  if (plan.nudge) {
    return row(`${CHIP_LABELS[plan.nudge.chip]} nudge for GW${plan.nudge.event_id} · ${fmtGain(plan.nudge.ev_gain)} xPts`, false);
  }
  const next = [...plan.recommendations].sort((a, b) => a.event_id - b.event_id)[0];
  return row(next ? `Save · ${CHIP_LABELS[next.chip]} peaks in GW${next.event_id}` : "Save · no chip window ahead", true);
}

/** The four weekly decisions on the Command Center rail, in display order. */
export function deriveWeekDecisions(input: WeekDecisionInput): WeekDecision[] {
  return [
    transfersRow(input.recommendation, input.appliedTransferCount),
    captainRow(input.recommendation),
    benchRow(input.recommendation),
    chipRow(input.chipStrategy, input.chipPlan),
  ];
}
