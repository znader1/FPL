import { describe, expect, it } from "vitest";
import {
  applyPatch,
  toPlanId,
  buildPlayerLookup,
  buildTodo,
  countChanges,
  makeMoves,
  moveBench,
  parseStoredPlan,
  planStorageKey,
  projectPlan,
  resolvePlan,
  samePlayers,
  seedPlan,
  swapCheck,
  swapPlayers,
  type GwPlan,
} from "./gwPlan";
import type {
  FplPosition,
  FplSquad,
  FplTeamRecommendation,
  FplTeamRecommendationBenchPlayer,
  FplTeamRecommendationPlayer,
  FplTransferVerdictDetail,
} from "./fplAssistantApi";

const mkPlayer = (id: number, pos: FplPosition, xpts: number, over: Partial<FplTeamRecommendationPlayer> = {}): FplTeamRecommendationPlayer => ({
  player_id: id,
  web_name: `P${id}`,
  pos,
  team_short: "AAA",
  team_name: "Team A",
  is_captain: false,
  is_vice_captain: false,
  multiplier: 1,
  xpts,
  ...over,
});

// XI: GK 1 · DEF 2,3,4 · MID 5,6,7,8 · FWD 9,10,11 (3-4-3). Bench: GK 12, 13 DEF, 14 MID, 15 FWD.
const XI = [
  mkPlayer(1, "GKP", 4),
  mkPlayer(2, "DEF", 3),
  mkPlayer(3, "DEF", 3),
  mkPlayer(4, "DEF", 3),
  mkPlayer(5, "MID", 7, { is_captain: true, multiplier: 2 }),
  mkPlayer(6, "MID", 6, { is_vice_captain: true }),
  mkPlayer(7, "MID", 5),
  mkPlayer(8, "MID", 4),
  mkPlayer(9, "FWD", 6),
  mkPlayer(10, "FWD", 5),
  mkPlayer(11, "FWD", 4),
];
const BENCH: FplTeamRecommendationBenchPlayer[] = [
  { ...mkPlayer(14, "MID", 2), bench_order: 2 },
  { ...mkPlayer(12, "GKP", 2), bench_order: 1 },
  { ...mkPlayer(15, "FWD", 1), bench_order: 4 },
  { ...mkPlayer(13, "DEF", 2), bench_order: 3 },
];
const SQUAD: FplSquad = { entry_id: 1, event_id: 29, starting_xi: XI, bench: BENCH, captain_player_id: 5, vice_player_id: 6 };
const posOf = (id: number): FplPosition => [...XI, ...BENCH].find((p) => p.player_id === id)!.pos;

const detail = (over: Partial<FplTransferVerdictDetail> = {}): FplTransferVerdictDetail => ({
  action: "spend",
  horizon: { start_gw: 29, end_gw: 31, n: 3 },
  ft_before: 1,
  ft_after: 0,
  threshold: 2,
  moves: [{ sell: { id: 11, name: "P11", team: "AAA", price: 6 }, buy: { id: 99, name: "Solanke", team: "BOU", price: 7 }, this_gw_gain: 1.5, horizon_gain: 2.4 }],
  this_gw_gain: 1.5,
  horizon_gain: 2.4,
  hit_cost: 0,
  plan_net: 2.4,
  roll_alternative: null,
  next_move: null,
  ...over,
});

const rec = (d: FplTransferVerdictDetail | undefined): FplTeamRecommendation =>
  ({
    ...SQUAD,
    horizon_gws: 3,
    formation: [3, 4, 3],
    projected_points_with_captain: 60,
    transfer_plan_horizon: d ? { verdict_detail: d } : undefined,
    transfers: { moves: [] },
  }) as unknown as FplTeamRecommendation;

describe("seedPlan", () => {
  it("takes the XI, the bench in bench_order, and the armbands from the squad", () => {
    const plan = seedPlan(SQUAD);
    expect(plan.xi).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    expect(plan.bench).toEqual([12, 14, 13, 15]);
    expect(plan.cap).toBe(5);
    expect(plan.vice).toBe(6);
    expect(plan).toMatchObject({ transfer: null, chip: null, reviewed: {}, locked: false });
  });

  it("pins the goalkeeper to the first bench slot whatever his bench_order", () => {
    const gkLast: FplSquad = { ...SQUAD, bench: BENCH.map((p) => ({ ...p, bench_order: p.pos === "GKP" ? 4 : p.bench_order - 1 })) };
    expect(seedPlan(gkLast).bench).toEqual([12, 14, 13, 15]);
  });

  it("falls back to the is_captain flags when the ids are absent", () => {
    const plan = seedPlan({ ...SQUAD, captain_player_id: undefined, vice_player_id: undefined });
    expect(plan.cap).toBe(5);
    expect(plan.vice).toBe(6);
  });
});

describe("applyPatch", () => {
  const locked: GwPlan = { ...seedPlan(SQUAD), locked: true, reviewed: { captain: true } };
  it("reopens a saved plan on a material change", () => {
    expect(applyPatch(locked, { cap: 9 }).locked).toBe(false);
  });
  it("keeps a saved plan locked when only reviewed/locked change", () => {
    expect(applyPatch(locked, { reviewed: { captain: true, bench: true } }).locked).toBe(true);
    expect(applyPatch(locked, { locked: true }).locked).toBe(true);
  });
  it("accepts a functional patch", () => {
    expect(applyPatch(locked, (p) => ({ vice: p.cap })).vice).toBe(5);
  });
});

describe("samePlayers", () => {
  it("is true when the plan's 15 match the squad's 15 in any order", () => {
    expect(samePlayers(seedPlan(SQUAD), SQUAD)).toBe(true);
  });
  it("is false after the user made a transfer in the FPL app", () => {
    const changed = { ...SQUAD, starting_xi: [...XI.slice(0, 10), mkPlayer(77, "FWD", 5)] };
    expect(samePlayers(seedPlan(SQUAD), changed)).toBe(false);
  });
});

describe("swapCheck", () => {
  const xi = seedPlan(SQUAD).xi;
  it("lets a goalkeeper swap only with a goalkeeper", () => {
    expect(swapCheck(xi, 12, 1, posOf)).toBeNull();
    expect(swapCheck(xi, 12, 2, posOf)).toMatch(/goalkeepers/i);
    expect(swapCheck(xi, 13, 1, posOf)).toMatch(/goalkeepers/i);
  });
  it("keeps at least 3 DEF, 2 MID and 1 FWD", () => {
    // DEF 2 out for MID 14 leaves 2 DEF.
    expect(swapCheck(xi, 14, 2, posOf)).toMatch(/3 defenders/);
    // FWD 11 out for DEF 13 is fine (4-4-2).
    expect(swapCheck(xi, 13, 11, posOf)).toBeNull();
    // Take the XI down to one forward then try to remove him.
    const oneFwd = [1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 14];
    expect(swapCheck(oneFwd, 15, 9, posOf)).toBeNull(); // FWD for FWD
    expect(swapCheck(oneFwd, 12, 9, posOf)).toMatch(/goalkeepers/i);
    const xiNoMid = [1, 2, 3, 4, 5, 13, 9, 10, 11, 15, 14];
    expect(swapCheck(xiNoMid, 13, 5, posOf)).toMatch(/2 midfielders/);
  });
});

describe("swapPlayers / moveBench", () => {
  it("swaps the two ids in place", () => {
    const plan = seedPlan(SQUAD);
    const next = swapPlayers(plan, 13, 11);
    expect(next.xi).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13]);
    expect(next.bench).toEqual([12, 14, 11, 15]);
  });
  it("moves a sub up or down but never past the GK slot or the ends", () => {
    const plan = seedPlan(SQUAD); // [12, 14, 13, 15]
    expect(moveBench(plan, 2, -1).bench).toEqual([12, 13, 14, 15]);
    expect(moveBench(plan, 1, -1).bench).toEqual([12, 14, 13, 15]);
    expect(moveBench(plan, 3, 1).bench).toEqual([12, 14, 13, 15]);
    expect(moveBench(plan, 0, 1).bench).toEqual([12, 14, 13, 15]);
  });
});

describe("makeMoves / resolvePlan", () => {
  it("uses the verdict's moves on spend and the rejected alternative on roll", () => {
    expect(makeMoves(rec(detail())).map((m) => m.buy.id)).toEqual([99]);
    const roll = detail({ action: "roll", moves: [], roll_alternative: { net: 1, gw: 29, moves: detail().moves } });
    expect(makeMoves(rec(roll)).map((m) => m.buy.id)).toEqual([99]);
    expect(makeMoves(rec(undefined))).toEqual([]);
  });

  it("substitutes buy for sell everywhere when the plan says make, else leaves the squad alone", () => {
    const plan: GwPlan = { ...seedPlan(SQUAD), transfer: "make", cap: 11 };
    const r = resolvePlan(plan, makeMoves(rec(detail())));
    expect(r.xi).toContain(99);
    expect(r.xi).not.toContain(11);
    expect(r.cap).toBe(99);
    expect(r.incoming).toEqual({ 99: 1.5 });
    const rolled = resolvePlan({ ...plan, transfer: "roll" }, makeMoves(rec(detail())));
    expect(rolled.xi).toContain(11);
    expect(rolled.incoming).toEqual({});
  });

  it("toPlanId maps a buy back to the seller it replaced, so edits store pre-transfer ids", () => {
    const moves = makeMoves(rec(detail()));
    expect(toPlanId(99, moves)).toBe(11);
    expect(toPlanId(5, moves)).toBe(5);
  });

  it("treats make with nothing to make as undecided", () => {
    const r = resolvePlan({ ...seedPlan(SQUAD), transfer: "make" }, []);
    expect(r.xi).toEqual(seedPlan(SQUAD).xi);
  });
});

describe("buildPlayerLookup", () => {
  it("prefers the recommendation's record (plan-GW xpts) over the squad's", () => {
    const r = rec(detail());
    r.starting_xi = XI.map((p) => (p.player_id === 5 ? { ...p, xpts: 9 } : p));
    const lookup = buildPlayerLookup(SQUAD, r);
    expect(lookup[5].xpts).toBe(9);
    expect(lookup[12].pos).toBe("GKP");
  });

  it("synthesises the buy from the move when no step squad carries him", () => {
    const lookup = buildPlayerLookup(SQUAD, rec(detail()));
    expect(lookup[99]).toMatchObject({ web_name: "Solanke", team_short: "BOU", pos: "FWD" });
    // Seller's xPts plus the move's this-GW gain, flagged as an estimate.
    expect(lookup[99].xpts).toBeCloseTo(5.5);
  });

  it("takes the buy's real record from squad_with_transfers_steps when present", () => {
    const r = rec(detail());
    r.squad_with_transfers_steps = [
      { ...SQUAD, applied_count: 1, formation: [3, 4, 3], captain_player_id: 5, vice_player_id: 6, projected_points_with_captain: 61, starting_xi: [...XI.slice(0, 10), mkPlayer(99, "FWD", 6.2, { web_name: "Solanke", team_short: "BOU" })] },
    ];
    expect(buildPlayerLookup(SQUAD, r)[99].xpts).toBe(6.2);
  });
});

describe("projectPlan", () => {
  const lookup = buildPlayerLookup(SQUAD, undefined);
  const base = seedPlan(SQUAD);
  it("sums the XI and doubles the captain", () => {
    // XI sum = 4+9+22+15 = 50; captain 5 adds 7.
    expect(projectPlan(resolvePlan(base, []), lookup, base.chip)).toBe(57);
  });
  it("does not double a benched captain", () => {
    const benched = swapPlayers(base, 14, 5);
    // XI loses 7 gains 2 → 45; no captain bonus.
    expect(projectPlan(resolvePlan(benched, []), lookup, null)).toBe(45);
  });
  it("adds the bench for Bench Boost and the captain again for Triple Captain", () => {
    expect(projectPlan(resolvePlan(base, []), lookup, "bench_boost")).toBe(64);
    expect(projectPlan(resolvePlan(base, []), lookup, "triple_captain")).toBe(64);
  });
  it("adds the engine's Free Hit gain when known, and is null when a player's xPts is unknown", () => {
    expect(projectPlan(resolvePlan(base, []), lookup, "free_hit", 6.2)).toBeCloseTo(63.2);
    expect(projectPlan(resolvePlan(base, []), lookup, "free_hit")).toBe(57);
    const { 5: _drop, ...partial } = lookup;
    expect(projectPlan(resolvePlan(base, []), partial, null)).toBeNull();
  });
});

describe("countChanges / buildTodo", () => {
  const base = seedPlan(SQUAD);
  const names = buildPlayerLookup(SQUAD, rec(detail()));
  const moves = makeMoves(rec(detail()));
  it("counts nothing on a fresh plan, even after a roll decision", () => {
    expect(countChanges(base, base, moves)).toBe(0);
    expect(countChanges({ ...base, transfer: "roll", chip: "none" }, base, moves)).toBe(0);
  });
  it("counts the transfer, each armband, the lineup and a played chip", () => {
    const edited: GwPlan = { ...swapPlayers(base, 13, 11), transfer: "make", cap: 9, vice: 5, chip: "bench_boost" };
    expect(countChanges(edited, base, moves)).toBe(5);
    expect(countChanges({ ...base, transfer: "make" }, base, [])).toBe(0);
  });
  it("writes the FPL-app to-do list from the diff", () => {
    const edited: GwPlan = { ...moveBench(base, 2, -1), transfer: "make", cap: 9, chip: "triple_captain" };
    const todo = buildTodo(edited, base, moves, names);
    expect(todo).toEqual([
      "Transfer out P11, bring in Solanke (free).",
      "Set P9 as captain and P6 as vice.",
      "Set your bench to P13, P14, P15.",
      "Activate Triple Captain.",
    ]);
    expect(buildTodo(base, base, moves, names)).toEqual(["No changes needed. Your FPL team already matches this plan."]);
  });
  it("names the hit when the move costs one", () => {
    const hitMoves = makeMoves(rec(detail({ ft_before: 0, hit_cost: 4 })));
    const todo = buildTodo({ ...base, transfer: "make" }, base, hitMoves, names, 4);
    expect(todo[0]).toBe("Transfer out P11, bring in Solanke (−4 hit).");
  });
});

describe("storage", () => {
  it("keys by entry and GW and round-trips only well-formed plans", () => {
    expect(planStorageKey(588004, 29)).toBe("fpl_gw_plan:588004:29");
    const stored = { plan: seedPlan(SQUAD), base: seedPlan(SQUAD) };
    expect(parseStoredPlan(JSON.stringify(stored))).toEqual(stored);
    expect(parseStoredPlan("{}")).toBeNull();
    expect(parseStoredPlan("not json")).toBeNull();
    expect(parseStoredPlan(JSON.stringify({ plan: { xi: "x" }, base: stored.base }))).toBeNull();
  });
});
