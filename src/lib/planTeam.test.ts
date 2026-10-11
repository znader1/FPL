import { describe, expect, it } from "vitest";
import { planToTeam } from "./planTeam";
import { buildPlayerLookup, makeMoves, resolvePlan, seedPlan, swapPlayers } from "./gwPlan";
import { SAMPLE_SQUAD, SAMPLE_TEAM_RECOMMENDATION, type FplTeamRecommendation } from "./fplAssistantApi";

describe("planToTeam", () => {
  const lookup = buildPlayerLookup(SAMPLE_SQUAD, undefined);
  const seed = seedPlan(SAMPLE_SQUAD);

  it("rebuilds a squad payload from the resolved plan: XI order, bench order, armbands, multipliers", () => {
    const edited = { ...swapPlayers(seed, 136, 430), cap: 449, vice: 5 }; // Thiago on for Haaland; Gabriel vice
    const team = planToTeam(SAMPLE_SQUAD, resolvePlan(edited, []), lookup);
    expect(team.starting_xi.map((p) => p.player_id)).toEqual(edited.xi);
    expect(team.bench.map((p) => p.player_id)).toEqual(edited.bench);
    expect(team.bench.map((p) => p.bench_order)).toEqual([1, 2, 3, 4]);
    expect(team.captain_player_id).toBe(449);
    expect(team.vice_player_id).toBe(5);
    const cap = team.starting_xi.find((p) => p.player_id === 449)!;
    expect(cap).toMatchObject({ is_captain: true, is_vice_captain: false, multiplier: 2 });
    expect(team.starting_xi.find((p) => p.player_id === 5)).toMatchObject({ is_captain: false, is_vice_captain: true, multiplier: 1 });
    expect(team.formation).toEqual([4, 5, 1]);
    expect(team.entry).toBe(SAMPLE_SQUAD.entry);
  });

  it("uses the buy's record once the plan makes the move", () => {
    const rec: FplTeamRecommendation = {
      ...SAMPLE_TEAM_RECOMMENDATION,
      transfer_plan_horizon: {
        verdict_detail: {
          action: "spend", horizon: { start_gw: 29, end_gw: 31, n: 3 }, ft_before: 1, ft_after: 0, threshold: 2,
          moves: [{ sell: { id: 430, name: "Haaland", team: "MCI", price: 14 }, buy: { id: 9, name: "Solanke", team: "BOU", price: 7 }, this_gw_gain: 0.5, horizon_gain: 2 }],
          this_gw_gain: 0.5, horizon_gain: 2, hit_cost: 0, plan_net: 2, roll_alternative: null, next_move: null,
        },
      },
    };
    const lk = buildPlayerLookup(SAMPLE_SQUAD, rec);
    const team = planToTeam(SAMPLE_SQUAD, resolvePlan({ ...seed, transfer: "make" }, makeMoves(rec)), lk);
    expect(team.starting_xi.some((p) => p.web_name === "Solanke")).toBe(true);
    expect(team.starting_xi.some((p) => p.player_id === 430)).toBe(false);
  });

  it("drops ids with no record rather than rendering holes", () => {
    const team = planToTeam(SAMPLE_SQUAD, { ...resolvePlan(seed, []), xi: [...seed.xi.slice(0, 10), 123456] }, lookup);
    expect(team.starting_xi).toHaveLength(10);
  });
});
