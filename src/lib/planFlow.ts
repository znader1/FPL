import {
  CHIP_LABELS,
  type ChipName,
  type ChipPlanResponse,
  type FplTeamRecommendation,
  type FplTransferVerdictMove,
} from "@/lib/fplAssistantApi";
import { fmtGain, gwRange } from "@/lib/format";
import {
  PLAN_STEPS,
  STEP_LABELS,
  lineupChanged,
  resolvePlan,
  swapCheck,
  type GwPlan,
  type PlanChip,
  type PlanDecisionKey,
  type PlanStep,
  type PlayerLookup,
  type ResolvedPlan,
} from "@/lib/gwPlan";
import type { WeekDecision } from "@/lib/weekDecisions";

/* ── steps ────────────────────────────────────────────────────────────────── */

export const nextStep = (step: PlanStep): PlanStep | null => PLAN_STEPS[PLAN_STEPS.indexOf(step) + 1] ?? null;
export const prevStep = (step: PlanStep): PlanStep | null => (PLAN_STEPS.indexOf(step) > 0 ? PLAN_STEPS[PLAN_STEPS.indexOf(step) - 1] : null);

/** Where "Start / Continue plan" lands: the first undecided decision, else the review. */
export function firstUnfinishedStep(decisions: WeekDecision[]): PlanStep {
  const open = decisions.find((d) => !d.done);
  return open ? open.key : "confirm";
}

export interface ReviewWarning {
  text: string;
  fixStep: PlanStep;
}

export interface FooterSpec {
  label: string;
  disabled: boolean;
  hint: string;
  variant: "primary" | "accent";
  hasBack: boolean;
}

export function footerFor(args: { step: PlanStep; plan: GwPlan | null; decisions: WeekDecision[]; warnings: ReviewWarning[]; gw: number }): FooterSpec {
  const { step, plan, decisions, warnings, gw } = args;
  const hasBack = step !== "squad";
  if (!plan) return { label: step === "squad" ? `Start GW${gw} plan` : `Next: ${STEP_LABELS[nextStep(step) ?? "confirm"]}`, disabled: true, hint: "", variant: "primary", hasBack };
  if (step === "squad") {
    const doneN = decisions.filter((d) => d.done).length;
    return { label: doneN > 0 ? "Continue plan" : `Start GW${gw} plan`, disabled: false, hint: "", variant: "primary", hasBack };
  }
  if (step === "confirm") {
    if (plan.locked) return { label: "Saved ✓", disabled: true, hint: "", variant: "accent", hasBack };
    if (warnings.length > 0) return { label: `Save GW${gw} plan`, disabled: true, hint: "Fix the warning to save", variant: "accent", hasBack };
    // The step chips / rail can land here without visiting Transfers or Chip,
    // whose own Next buttons gate on a choice — so Save gates on them too.
    const undecided = [plan.transfer === null && "transfers", plan.chip === null && "chip"].filter(Boolean);
    if (undecided.length > 0) {
      const hint = undecided.length === 2 ? "Decide transfers and chip first" : undecided[0] === "transfers" ? "Decide transfers first" : "Decide your chip first";
      return { label: `Save GW${gw} plan`, disabled: true, hint, variant: "accent", hasBack };
    }
    return { label: `Save GW${gw} plan`, disabled: false, hint: "", variant: "accent", hasBack };
  }
  const label = `Next: ${STEP_LABELS[nextStep(step) as PlanStep]}`;
  if ((step === "transfers" && plan.transfer === null) || (step === "chip" && plan.chip === null)) {
    return { label, disabled: true, hint: "Pick an option to continue", variant: "primary", hasBack };
  }
  return { label, disabled: false, hint: "", variant: "primary", hasBack };
}

export interface StepCopy {
  eyebrow: string;
  title: string;
  sub: string;
}

/** Header copy per step. The captain step's title/sub come from the lab, so the
 *  caller overrides them when it has one. */
export function stepCopy(step: PlanStep, gw: number, opts: { locked: boolean; desktop: boolean }): StepCopy {
  switch (step) {
    case "squad":
      return {
        eyebrow: "Overview",
        title: `Your GW${gw} squad`,
        sub: `Work through the four decisions ${opts.desktop ? "on the left" : "below"}. Your changes appear here and stay put until you reset or the deadline passes.`,
      };
    case "transfers":
      return { eyebrow: "Step 1 of 4 · Transfers", title: "Make the move or roll?", sub: "ZN Pick compares the best free move with banking the transfer." };
    case "captain":
      return { eyebrow: "Step 2 of 4 · Captain", title: "Pick your captain.", sub: "Rank-aware captaincy: who the field holds, and what a haul would do." };
    case "bench":
      return { eyebrow: "Step 3 of 4 · Bench", title: "Set your bench order", sub: "Reorder subs, or swap a bench player with a starter. Formation rules are checked as you go." };
    case "chip":
      return { eyebrow: "Step 4 of 4 · Chip", title: "Play a chip this week?", sub: "Compared with the best week left this season for each chip." };
    case "confirm":
      return { eyebrow: "Review", title: opts.locked ? `You're set for GW${gw}.` : "Review and save your plan", sub: "Tap any row to change it." };
  }
}

/* ── review ───────────────────────────────────────────────────────────────── */

export function reviewWarnings(r: ResolvedPlan): ReviewWarning[] {
  return r.xi.includes(r.cap) ? [] : [{ text: "Your captain is on the bench. Pick a starter.", fixStep: "captain" }];
}

export interface ReviewRow {
  key: PlanDecisionKey;
  label: string;
  value: string;
  changed: boolean;
}

export function reviewSummary(plan: GwPlan, base: GwPlan, moves: FplTransferVerdictMove[], lookup: PlayerLookup, decisions: WeekDecision[]): ReviewRow[] {
  const r = resolvePlan(plan, moves);
  const name = (id: number) => lookup[id]?.web_name ?? `#${id}`;
  const transfersRow = decisions.find((d) => d.key === "transfers");
  return [
    {
      key: "transfers",
      label: "Transfers",
      value: plan.transfer === null ? "Not decided" : (transfersRow?.value ?? (plan.transfer === "roll" ? "Roll the transfer" : "Make the move")),
      changed: plan.transfer === "make" && moves.length > 0,
    },
    {
      key: "captain",
      label: "Captain",
      value: r.xi.includes(r.cap) ? `${name(r.cap)} (C) · ${name(r.vice)} (VC)` : "Captain is on the bench",
      changed: plan.cap !== base.cap || plan.vice !== base.vice,
    },
    {
      key: "bench",
      label: "Bench",
      value: `${r.bench.slice(1).map(name).join(", ")} · ${name(r.bench[0])} (GK)`,
      changed: lineupChanged(plan, base),
    },
    {
      key: "chip",
      label: "Chip",
      value: plan.chip === null ? "Not decided" : plan.chip === "none" ? "Save chips" : CHIP_LABELS[plan.chip],
      changed: plan.chip !== null && plan.chip !== "none",
    },
  ];
}

/* ── transfers step ───────────────────────────────────────────────────────── */

export interface TransferOption {
  zn: boolean;
  /** Net xPts over the horizon after any hit. */
  gain: number;
  meta: string;
  why: string;
  moves: FplTransferVerdictMove[];
}

export interface AlsoConsidered {
  sell: string;
  buy: string;
  net: number;
  hit: boolean;
  bar: number;
}

export interface TransferOptions {
  make: TransferOption | null;
  roll: TransferOption;
  alsoConsidered: AlsoConsidered[];
}

const fixturesLine = (moves: FplTransferVerdictMove[]) =>
  moves
    .filter((m) => m.sell.next_fixture || m.buy.next_fixture)
    .map((m) => `${m.sell.name} has ${m.sell.next_fixture ?? "no fixture"}; ${m.buy.name} gets ${m.buy.next_fixture ?? "no fixture"}.`)
    .join(" ");

/** The two radio cards and the "Also considered" row, from `verdict_detail`. */
export function transferOptions(rec: FplTeamRecommendation | undefined): TransferOptions {
  const d = rec?.transfer_plan_horizon?.verdict_detail;
  const empty: TransferOption = { zn: false, gain: 0, meta: "", why: "", moves: [] };
  if (!d) return { make: null, roll: empty, alsoConsidered: [] };
  const range = gwRange(d.horizon);
  const rollMeta = `this week · ${d.action === "roll" ? d.ft_after : Math.min(5, d.ft_before + 1)} FT${(d.action === "roll" ? d.ft_after : d.ft_before + 1) === 1 ? "" : "s"} in GW${(d.horizon.start_gw ?? 0) + 1}`;
  const alsoConsidered: AlsoConsidered[] = (d.runner_ups ?? [])
    .filter((m) => !m.clears_bar)
    .slice(0, 2)
    .map((m) => ({ sell: m.sell.name, buy: m.buy.name, net: m.horizon_gain, hit: d.ft_before === 0, bar: d.threshold }));

  if (d.action === "roll") {
    const alt = d.roll_alternative;
    const make: TransferOption | null =
      alt && alt.moves.length > 0
        ? {
            zn: false,
            gain: alt.moves.reduce((s, m) => s + m.horizon_gain, 0),
            meta: `xPts over ${range} · ${d.ft_before > 0 ? "free transfer" : "−4 hit"}`,
            why: `${fixturesLine(alt.moves)} Moving now nets ${fmtGain(alt.net)} over ${range}; rolling nets ${fmtGain(d.plan_net)}.`.trim(),
            moves: alt.moves,
          }
        : null;
    const next = d.next_move ? ` Next planned move: ${d.next_move.moves.map((m) => `${m.sell.name} → ${m.buy.name}`).join(", ")} in GW${d.next_move.gw}.` : "";
    return {
      make,
      roll: { zn: true, gain: 0, meta: rollMeta, why: `Bank the free transfer. No move clears ${fmtGain(d.threshold)} over ${range}.${next}`, moves: [] },
      alsoConsidered,
    };
  }

  const make: TransferOption = {
    zn: true,
    gain: Math.round((d.horizon_gain - d.hit_cost) * 10) / 10,
    meta: `xPts over ${range} · ${d.hit_cost > 0 ? `−${d.hit_cost} hit` : "free transfer"}`,
    why: fixturesLine(d.moves) || `Clears the ${fmtGain(d.threshold)} bar over ${range}.`,
    moves: d.moves,
  };
  const alt = d.roll_alternative;
  const roll: TransferOption = {
    zn: false,
    gain: 0,
    meta: rollMeta,
    why: alt ? `Rolling nets ${fmtGain(alt.net)} over ${range} against ${fmtGain(d.plan_net)} for moving now.` : `Rolling banks the transfer; moving now nets ${fmtGain(d.plan_net)} over ${range}.`,
    moves: [],
  };
  return { make, roll, alsoConsidered };
}

/* ── chip step ────────────────────────────────────────────────────────────── */

export interface ChipOption {
  chip: Exclude<PlanChip, null>;
  title: string;
  zn: boolean;
  /** This week's gain; null when unknown or the chip can't be played. */
  gain: number | null;
  why: string;
  /** Already played this season. */
  used: boolean;
}

const bestWeek = (plan: ChipPlanResponse | null | undefined, chip: ChipName) => {
  const recs = (plan?.recommendations ?? []).filter((r) => r.chip === chip && typeof r.ev_gain === "number");
  const top = recs.sort((a, b) => (b.ev_gain ?? 0) - (a.ev_gain ?? 0))[0];
  if (top) return { gw: top.event_id, gain: top.ev_gain as number };
  const o = plan?.outlook?.find((row) => row.chip === chip && typeof row.event_id === "number" && typeof row.ev_gain === "number");
  return o ? { gw: o.event_id as number, gain: o.ev_gain as number } : null;
};

const thisWeek = (plan: ChipPlanResponse | null | undefined, chip: ChipName, gw: number): number | null => {
  const r = plan?.recommendations.find((x) => x.chip === chip && x.event_id === gw && typeof x.ev_gain === "number");
  if (r) return r.ev_gain as number;
  const o = plan?.outlook?.find((x) => x.chip === chip && x.event_id === gw && typeof x.ev_gain === "number");
  return o ? (o.ev_gain as number) : null;
};

export function chipOptions(args: { resolved: ResolvedPlan; lookup: PlayerLookup; chipPlan: ChipPlanResponse | null | undefined; gw: number }): ChipOption[] {
  const { resolved: r, lookup, chipPlan, gw } = args;
  const nudge = chipPlan?.nudge && chipPlan.nudge.event_id === gw ? chipPlan.nudge.chip : null;
  const used = (chip: ChipName) => chipPlan?.chips_remaining.some((c) => c.name === chip && !c.available) ?? false;
  const capIn = r.xi.includes(r.cap);
  const capX = lookup[r.cap]?.xpts;
  const capName = lookup[r.cap]?.web_name ?? "your captain";

  const bestAny = (chipPlan?.recommendations ?? [])
    .filter((x) => typeof x.ev_gain === "number")
    .sort((a, b) => (b.ev_gain ?? 0) - (a.ev_gain ?? 0))[0];
  const saveWhy = bestAny
    ? `${CHIP_LABELS[bestAny.chip]} is worth ${fmtGain(bestAny.ev_gain as number)} in GW${bestAny.event_id}, the best week left for any chip.`
    : chipPlan
      ? "No chip window stands out ahead; keep them."
      : "The chip plan hasn't answered yet; saving is the default.";

  const bbBest = bestWeek(chipPlan, "bench_boost");
  const bbGain = r.bench.every((id) => typeof lookup[id]?.xpts === "number") ? Math.round(r.bench.reduce((s, id) => s + (lookup[id]?.xpts ?? 0), 0) * 10) / 10 : null;
  const bbWhy = `Adds your bench this week.${bbBest ? ` Worth ${fmtGain(bbBest.gain)} in GW${bbBest.gw}${bbGain !== null && bbBest.gain > 2 * bbGain ? ", more than double this week" : ""}.` : ""}`;

  const fhBest = bestWeek(chipPlan, "free_hit");
  const fhOutlook = chipPlan?.outlook?.find((x) => x.chip === "free_hit");
  const fhWhy = fhOutlook?.guidance ?? (fhBest ? `Better saved for GW${fhBest.gw}, where it is worth ${fmtGain(fhBest.gain)}.` : "A one-week squad rebuild; the engine has no window for it yet.");

  const tcBest = bestWeek(chipPlan, "triple_captain");
  const tcWhy = !capIn
    ? "Your captain is on the bench."
    : `On ${capName}.${tcBest ? ` Worth ${fmtGain(tcBest.gain)} in GW${tcBest.gw}.` : " No double gameweek this week, so the upside is capped."}`;

  return [
    { chip: "none", title: "Save chips", zn: nudge === null, gain: 0, why: saveWhy, used: false },
    { chip: "bench_boost", title: CHIP_LABELS.bench_boost, zn: nudge === "bench_boost", gain: bbGain, why: bbWhy, used: used("bench_boost") },
    { chip: "free_hit", title: CHIP_LABELS.free_hit, zn: nudge === "free_hit", gain: thisWeek(chipPlan, "free_hit", gw), why: fhWhy, used: used("free_hit") },
    {
      chip: "triple_captain",
      title: CHIP_LABELS.triple_captain,
      zn: nudge === "triple_captain",
      gain: capIn && typeof capX === "number" ? capX : null,
      why: tcWhy,
      used: used("triple_captain"),
    },
  ];
}

/* ── bench step ───────────────────────────────────────────────────────────── */

const FLAG_SEVERITY = new Set(["high", "medium"]);

/** "If X (75% fit) doesn't play, Y comes on automatically." for the first flagged starter. */
export function autoSubPreview(r: ResolvedPlan, lookup: PlayerLookup): string {
  const tail = "Order your bench by who you'd want first.";
  const flagged = r.xi.find((id) => lookup[id]?.alerts?.some((a) => FLAG_SEVERITY.has(a.severity ?? "")));
  if (!flagged) return `No flagged starters. ${tail}`;
  const p = lookup[flagged];
  const flag = p.alerts?.find((a) => FLAG_SEVERITY.has(a.severity ?? ""))?.text;
  const posOf = (id: number) => lookup[id]?.pos ?? "MID";
  const sub = r.bench.find((b) => swapCheck(r.xi, b, flagged, posOf) === null);
  return `If ${p.web_name}${flag ? ` (${flag})` : ""} doesn't play, ${sub ? lookup[sub]?.web_name : "nobody"} comes on automatically. ${tail}`;
}
