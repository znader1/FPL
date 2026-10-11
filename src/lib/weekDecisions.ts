import {
  CHIP_LABELS,
  type ChipPlanResponse,
  type FplTeamRecommendation,
} from "@/lib/fplAssistantApi";
import { fmtGain } from "@/lib/format";
import { makeMoves, resolvePlan, type GwPlan, type PlanDecisionKey, type PlayerLookup } from "@/lib/gwPlan";

export type WeekDecisionKey = PlanDecisionKey;

export interface WeekDecision {
  key: WeekDecisionKey;
  label: string;
  /** One line of status under the label. */
  value: string;
  done: boolean;
  /** Something is wrong with this decision (e.g. the captain is on the bench). */
  warn?: boolean;
}

export interface WeekDecisionInput {
  /** The GW plan; null until the squad has seeded it. */
  plan: GwPlan | null;
  base?: GwPlan | null;
  lookup: PlayerLookup;
  recommendation?: FplTeamRecommendation;
  chipPlan?: ChipPlanResponse | null;
  /** `/chips/plan` failed — say so rather than "waiting" forever. */
  chipPlanError?: boolean;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const row = (key: WeekDecisionKey, label: string) => (value: string, done: boolean, warn = false): WeekDecision => ({ key, label, value, done, warn });

const transfersRow = row("transfers", "Transfers");
const captainRow = row("captain", "Captain");
const benchRow = row("bench", "Bench order");
const chipRow = row("chip", "Chip");

function transfers(plan: GwPlan, rec: FplTeamRecommendation | undefined): WeekDecision {
  const d = rec?.transfer_plan_horizon?.verdict_detail;
  const moves = makeMoves(rec);
  if (plan.transfer === "roll") {
    if (!d) return transfersRow("Roll the transfer", true);
    const nextGw = d.horizon.start_gw != null ? ` for GW${d.horizon.start_gw + 1}` : "";
    return transfersRow(`Roll · ${plural(d.ft_after, "FT")}${nextGw}`, true);
  }
  if (plan.transfer === "make" && d && moves.length > 0) {
    // Spend: the verdict's own total net of the hit. Roll: the rejected walk's
    // moves summed — the verdict's totals describe rolling, not them.
    const gain = d.action === "roll" ? moves.reduce((s, m) => s + m.horizon_gain, 0) : d.horizon_gain - d.hit_cost;
    if (moves.length === 1) return transfersRow(`${moves[0].sell.name} → ${moves[0].buy.name} · ${fmtGain(gain)}`, true);
    const hit = d.hit_cost > 0 && d.action !== "roll" ? ` after a −${d.hit_cost} hit` : "";
    return transfersRow(`${plural(moves.length, "move")} · ${fmtGain(gain)}${hit}`, true);
  }
  if (!rec) return transfersRow("Run ZN Pick to see your moves", false);
  if (!d) return transfersRow("Not decided", false);
  return transfersRow(`Not decided · ${plural(d.ft_before, "FT")}`, false);
}

function captain(plan: GwPlan, rec: FplTeamRecommendation | undefined, lookup: PlayerLookup): WeekDecision {
  const r = resolvePlan(plan, makeMoves(rec));
  if (!r.xi.includes(r.cap)) return captainRow("Captain is on the bench", false, true);
  const name = (id: number) => lookup[id]?.web_name ?? `#${id}`;
  return captainRow(`${name(r.cap)} (C) · ${name(r.vice)} (VC)`, Boolean(plan.reviewed.captain));
}

function bench(plan: GwPlan, rec: FplTeamRecommendation | undefined, lookup: PlayerLookup): WeekDecision {
  const r = resolvePlan(plan, makeMoves(rec));
  const first = r.bench[1];
  const name = first != null ? lookup[first]?.web_name ?? `#${first}` : undefined;
  return benchRow(name ? `${name} first sub` : "No bench returned", Boolean(plan.reviewed.bench));
}

function chip(plan: GwPlan, chipPlan: ChipPlanResponse | null | undefined, planError: boolean): WeekDecision {
  if (plan.chip && plan.chip !== "none") return chipRow(`${CHIP_LABELS[plan.chip]} this week`, true);
  if (plan.chip === "none") {
    if (!chipPlan) return chipRow("Save chips", true);
    const next = [...chipPlan.recommendations].sort((a, b) => a.event_id - b.event_id)[0];
    return chipRow(next ? `Save · ${CHIP_LABELS[next.chip]} peaks in GW${next.event_id}` : "Save · no chip window ahead", true);
  }
  if (!chipPlan) return chipRow(planError ? "Chip plan unavailable · decide in the Chip step" : "Waiting for the chip plan", false);
  if (chipPlan.nudge) {
    return chipRow(`${CHIP_LABELS[chipPlan.nudge.chip]} nudge for GW${chipPlan.nudge.event_id} · ${fmtGain(chipPlan.nudge.ev_gain)} xPts`, false);
  }
  return chipRow("Not decided · Save is the ZN Pick", false);
}

/** The four weekly decisions on the Command Center rail, in display order — read
 *  from the GW plan (never stored), with the recommendation and chip plan as context. */
export function deriveWeekDecisions(input: WeekDecisionInput): WeekDecision[] {
  const { plan, recommendation, lookup, chipPlan, chipPlanError } = input;
  if (!plan) {
    return [
      transfersRow("Loading your squad…", false),
      captainRow("—", false),
      benchRow("—", false),
      chipRow("—", false),
    ];
  }
  return [
    transfers(plan, recommendation),
    captain(plan, recommendation, lookup),
    bench(plan, recommendation, lookup),
    chip(plan, chipPlan, Boolean(chipPlanError)),
  ];
}
