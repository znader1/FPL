import {
  CHIP_LABELS,
  type ChipName,
  type FplPosition,
  type FplSquad,
  type FplTeamRecommendation,
  type FplTeamRecommendationPlayer,
  type FplTransferVerdictMove,
} from "./fplAssistantApi";

/**
 * The single client-side plan for one gameweek (v2 flow handoff §1). Every
 * step reads and writes this; nothing rebuilds the squad from the server.
 * Chips use the canonical vocabulary (never bb/fh/tc) — see CLAUDE.md.
 */
export type PlanStep = "squad" | "transfers" | "captain" | "bench" | "chip" | "confirm";
export const PLAN_STEPS: PlanStep[] = ["squad", "transfers", "captain", "bench", "chip", "confirm"];
export const STEP_LABELS: Record<PlanStep, string> = {
  squad: "Squad",
  transfers: "Transfers",
  captain: "Captain",
  bench: "Bench",
  chip: "Chip",
  confirm: "Review",
};
export type PlanDecisionKey = Exclude<PlanStep, "squad" | "confirm">;
export const isPlanStep = (v: string | undefined): v is PlanStep => PLAN_STEPS.includes(v as PlanStep);

export type PlanChip = "none" | ChipName | null;

export interface GwPlan {
  /** 11 starters, as the user has them (not the optimiser's XI). */
  xi: number[];
  /** [GK, sub1, sub2, sub3]. */
  bench: number[];
  /** Ties to `verdict_detail`: "make" applies its moves, "roll" banks the FT. */
  transfer: "make" | "roll" | null;
  cap: number;
  vice: number;
  chip: PlanChip;
  reviewed: Partial<Record<PlanDecisionKey, true>>;
  /** "Saved". Any material edit clears it. */
  locked: boolean;
}

export type PlanPatch = Partial<GwPlan> | ((plan: GwPlan) => Partial<GwPlan>);

const NON_MATERIAL: ReadonlySet<keyof GwPlan> = new Set(["reviewed", "locked"]);

export function seedPlan(squad: FplSquad): GwPlan {
  const xi = squad.starting_xi.map((p) => p.player_id);
  const bench = [...squad.bench].sort((a, b) => a.bench_order - b.bench_order).map((p) => p.player_id);
  const all = [...squad.starting_xi, ...squad.bench];
  const cap = squad.captain_player_id ?? all.find((p) => p.is_captain)?.player_id ?? xi[0];
  const vice = squad.vice_player_id ?? all.find((p) => p.is_vice_captain)?.player_id ?? xi.find((id) => id !== cap) ?? xi[0];
  return { xi, bench, transfer: null, cap, vice, chip: null, reviewed: {}, locked: false };
}

/** Merge a patch; a material change (anything but reviewed/locked) reopens a saved plan. */
export function applyPatch(plan: GwPlan, patch: PlanPatch): GwPlan {
  const p = typeof patch === "function" ? patch(plan) : patch;
  const material = (Object.keys(p) as (keyof GwPlan)[]).some((k) => !NON_MATERIAL.has(k));
  const next = { ...plan, ...p };
  return material ? { ...next, locked: false } : next;
}

/** The plan still describes this squad (the user hasn't transferred in the FPL app since it was seeded). */
export function samePlayers(plan: GwPlan, squad: FplSquad): boolean {
  const a = [...plan.xi, ...plan.bench].sort((x, y) => x - y);
  const b = [...squad.starting_xi, ...squad.bench].map((p) => p.player_id).sort((x, y) => x - y);
  return a.length === b.length && a.every((id, i) => id === b[i]);
}

// ---- lineup rules -----------------------------------------------------------

const MIN_BY_POS: Partial<Record<FplPosition, [number, string]>> = {
  DEF: [3, "You need at least 3 defenders."],
  MID: [2, "You need at least 2 midfielders."],
  FWD: [1, "You need at least 1 forward."],
};

/** Null when `benchId` may replace `starterId` in `xi`; otherwise the rule that stops it. */
export function swapCheck(xi: number[], benchId: number, starterId: number, posOf: (id: number) => FplPosition): string | null {
  const bp = posOf(benchId);
  const sp = posOf(starterId);
  if ((bp === "GKP") !== (sp === "GKP")) return "Goalkeepers can only swap with goalkeepers.";
  const counts: Partial<Record<FplPosition, number>> = {};
  for (const id of xi) {
    const pos = id === starterId ? bp : posOf(id);
    counts[pos] = (counts[pos] ?? 0) + 1;
  }
  for (const [pos, [min, msg]] of Object.entries(MIN_BY_POS) as [FplPosition, [number, string]][]) {
    if ((counts[pos] ?? 0) < min) return msg;
  }
  return null;
}

export function swapPlayers(plan: GwPlan, benchId: number, starterId: number): GwPlan {
  return {
    ...plan,
    xi: plan.xi.map((id) => (id === starterId ? benchId : id)),
    bench: plan.bench.map((id) => (id === benchId ? starterId : id)),
  };
}

/** Move the sub at `index` by `dir` (±1). The GK slot (0) is pinned, the ends stop. */
export function moveBench(plan: GwPlan, index: number, dir: -1 | 1): GwPlan {
  const to = index + dir;
  if (index <= 0 || to <= 0 || to >= plan.bench.length) return plan;
  const bench = [...plan.bench];
  [bench[index], bench[to]] = [bench[to], bench[index]];
  return { ...plan, bench };
}

// ---- transfers --------------------------------------------------------------

/** The moves "Make the move" applies: the verdict's on spend, the rejected walk's on roll. */
export function makeMoves(rec: FplTeamRecommendation | undefined): FplTransferVerdictMove[] {
  const d = rec?.transfer_plan_horizon?.verdict_detail;
  if (!d) return [];
  return d.action === "roll" ? d.roll_alternative?.moves ?? [] : d.moves;
}

export interface ResolvedPlan {
  xi: number[];
  bench: number[];
  cap: number;
  vice: number;
  /** Incoming players → this-GW gain of the move that brought them in (the "IN" pill). */
  incoming: Record<number, number>;
}

/** The plan with its transfer decision applied: sell → buy everywhere. */
export function resolvePlan(plan: GwPlan, moves: FplTransferVerdictMove[]): ResolvedPlan {
  if (plan.transfer !== "make" || moves.length === 0) {
    return { xi: plan.xi, bench: plan.bench, cap: plan.cap, vice: plan.vice, incoming: {} };
  }
  const swap = new Map(moves.map((m) => [m.sell.id, m.buy.id]));
  const sub = (id: number) => swap.get(id) ?? id;
  const incoming: Record<number, number> = {};
  for (const m of moves) incoming[m.buy.id] = m.this_gw_gain;
  return { xi: plan.xi.map(sub), bench: plan.bench.map(sub), cap: sub(plan.cap), vice: sub(plan.vice), incoming };
}

// ---- player records ---------------------------------------------------------

export type PlayerLookup = Record<number, FplTeamRecommendationPlayer>;

/**
 * Every player the plan might show, by id. Recommendation records win (they
 * carry the plan GW's xPts; the squad's are for the GW on screen), then the
 * applied-step squads (real records for the buys), then a record synthesised
 * from the move itself for a buy no step squad carries — its xPts is the
 * seller's plus the move's this-GW gain, an estimate.
 */
export function buildPlayerLookup(squad: FplSquad | undefined, rec: FplTeamRecommendation | undefined): PlayerLookup {
  const out: PlayerLookup = {};
  const add = (players: FplTeamRecommendationPlayer[] | undefined) => {
    for (const p of players ?? []) out[p.player_id] = p;
  };
  add(squad?.starting_xi);
  add(squad?.bench);
  add(rec?.starting_xi);
  add(rec?.bench);
  for (const step of rec?.squad_with_transfers_steps ?? []) {
    for (const p of [...step.starting_xi, ...step.bench]) if (!out[p.player_id]) out[p.player_id] = p;
  }
  if (rec?.squad_with_transfers) {
    for (const p of [...rec.squad_with_transfers.starting_xi, ...rec.squad_with_transfers.bench]) if (!out[p.player_id]) out[p.player_id] = p;
  }
  for (const m of makeMoves(rec)) {
    if (out[m.buy.id]) continue;
    const seller = out[m.sell.id];
    out[m.buy.id] = {
      player_id: m.buy.id,
      web_name: m.buy.name,
      pos: (m.position as FplPosition | undefined) ?? seller?.pos ?? "MID",
      team_short: m.buy.team,
      team_name: m.buy.team,
      is_captain: false,
      is_vice_captain: false,
      multiplier: 1,
      xpts: (seller?.xpts ?? 0) + m.this_gw_gain,
      next_fixtures: m.buy.next_fixture,
    };
  }
  return out;
}

// ---- projection -------------------------------------------------------------

/**
 * Client-side projected points for the resolved plan: XI xPts plus the captain
 * again (only while he starts), plus the chip: Bench Boost adds the bench,
 * Triple Captain the captain once more, Free Hit the engine's gain when known.
 * Null when any starter has no xPts yet.
 */
export function projectPlan(r: ResolvedPlan, lookup: PlayerLookup, chip: PlanChip, freeHitGain?: number | null): number | null {
  let total = 0;
  for (const id of r.xi) {
    const x = lookup[id]?.xpts;
    if (typeof x !== "number" || !Number.isFinite(x)) return null;
    total += x;
  }
  const capIn = r.xi.includes(r.cap);
  const capX = lookup[r.cap]?.xpts ?? 0;
  if (capIn) total += capX;
  if (chip === "triple_captain" && capIn) total += capX;
  if (chip === "bench_boost") for (const id of r.bench) total += lookup[id]?.xpts ?? 0;
  if (chip === "free_hit" && typeof freeHitGain === "number") total += freeHitGain;
  return Math.round(total * 10) / 10;
}

// ---- diff against the no-change plan ----------------------------------------

const sameOrder = (a: number[], b: number[]) => a.length === b.length && a.every((id, i) => id === b[i]);

export const lineupChanged = (plan: GwPlan, base: GwPlan) => !sameOrder(plan.xi, base.xi) || !sameOrder(plan.bench, base.bench);

/** How many things the user would have to change in the FPL app — the navbar pill's number. */
export function countChanges(plan: GwPlan, base: GwPlan, moves: FplTransferVerdictMove[]): number {
  let n = 0;
  if (plan.transfer === "make" && moves.length > 0) n += 1;
  if (plan.cap !== base.cap) n += 1;
  if (plan.vice !== base.vice) n += 1;
  if (lineupChanged(plan, base)) n += 1;
  if (plan.chip && plan.chip !== "none") n += 1;
  return n;
}

/** The teal "do this in the FPL app" list on the saved review. */
export function buildTodo(plan: GwPlan, base: GwPlan, moves: FplTransferVerdictMove[], lookup: PlayerLookup, hitCost = 0): string[] {
  const name = (id: number) => lookup[id]?.web_name ?? `#${id}`;
  const todo: string[] = [];
  if (plan.transfer === "make" && moves.length > 0) {
    const cost = hitCost > 0 ? `−${hitCost} hit` : "free";
    for (const m of moves) todo.push(`Transfer out ${m.sell.name}, bring in ${m.buy.name} (${cost}).`);
  }
  const r = resolvePlan(plan, moves);
  if (plan.cap !== base.cap || plan.vice !== base.vice) todo.push(`Set ${name(r.cap)} as captain and ${name(r.vice)} as vice.`);
  if (lineupChanged(plan, base)) todo.push(`Set your bench to ${r.bench.slice(1).map(name).join(", ")}.`);
  if (plan.chip && plan.chip !== "none") todo.push(`Activate ${CHIP_LABELS[plan.chip]}.`);
  if (todo.length === 0) todo.push("No changes needed. Your FPL team already matches this plan.");
  return todo;
}

// ---- storage ----------------------------------------------------------------

export const planStorageKey = (entryId: number, gw: number) => `fpl_gw_plan:${entryId}:${gw}`;

export interface StoredPlan {
  plan: GwPlan;
  base: GwPlan;
}

const isIdList = (v: unknown, n?: number): v is number[] =>
  Array.isArray(v) && v.every((x) => typeof x === "number") && (n === undefined || v.length === n);

function isGwPlan(v: unknown): v is GwPlan {
  if (!v || typeof v !== "object") return false;
  const p = v as Record<string, unknown>;
  return (
    isIdList(p.xi) &&
    isIdList(p.bench) &&
    (p.transfer === "make" || p.transfer === "roll" || p.transfer === null) &&
    typeof p.cap === "number" &&
    typeof p.vice === "number" &&
    (p.chip === null || p.chip === "none" || (typeof p.chip === "string" && p.chip in CHIP_LABELS)) &&
    typeof p.reviewed === "object" &&
    p.reviewed !== null &&
    typeof p.locked === "boolean"
  );
}

export function parseStoredPlan(raw: string | null): StoredPlan | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as { plan?: unknown; base?: unknown };
    return isGwPlan(v?.plan) && isGwPlan(v?.base) ? { plan: v.plan, base: v.base } : null;
  } catch {
    return null;
  }
}
