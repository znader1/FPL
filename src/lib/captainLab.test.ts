import { describe, expect, it } from "vitest";
import { buildCaptainLab, parseFixtureLabel, type CaptainGoal } from "./captainLab";
import type { FplTeamRecommendation, FplTeamRecommendationPlayer } from "./fplAssistantApi";

const p = (id: number, name: string, team: string, xpts: number, over: Partial<FplTeamRecommendationPlayer> = {}): FplTeamRecommendationPlayer => ({
  player_id: id, web_name: name, team_short: team, team_name: team, pos: "MID",
  is_captain: false, is_vice_captain: false, multiplier: 1, xpts,
  next_fixtures: "H-BHA(D1)",
  score_breakdown: { distribution: { p80_low: 2, p80_high: 16, p_haul_10: 0.31 } },
  ...over,
});

const rec = (players: FplTeamRecommendationPlayer[], over: Partial<FplTeamRecommendation> = {}): FplTeamRecommendation => ({
  entry_id: 1, event_id: 29, horizon_gws: 3, formation: [4, 4, 2], captain_player_id: 1, vice_player_id: 2,
  projected_points_with_captain: 66, starting_xi: players, bench: [], ...over,
});

const withEo = [
  p(1, "Haaland", "MCI", 8.6, { is_captain_suggested: true, eo_top10k: 142, rank_gain_if_haul: 3000, xpts_p10: 2, xpts_p90: 18 }),
  p(2, "Saka", "ARS", 7.4, { is_vice_suggested: true, eo_top10k: 38, rank_gain_if_haul: 41000, xpts_p10: 2, xpts_p90: 16 }),
  p(3, "Palmer", "CHE", 6.9, { eo_top10k: 22, rank_gain_if_haul: 29000, xpts_p10: 1, xpts_p90: 15 }),
  p(4, "Raya", "ARS", 4.2, { pos: "GKP" }),
];

describe("parseFixtureLabel", () => {
  it("reads the backend's H-BOU(D2) form", () => {
    expect(parseFixtureLabel("H-BOU(D2)")).toEqual({ opponent: "BOU", isHome: true, difficulty: 2 });
    expect(parseFixtureLabel("A-LIV(D5)")).toEqual({ opponent: "LIV", isHome: false, difficulty: 5 });
    expect(parseFixtureLabel("")).toBeUndefined();
  });
});

describe("buildCaptainLab", () => {
  const run = (goal: CaptainGoal, manual?: number, r = rec(withEo)) => buildCaptainLab(r, goal, manual ?? null);

  it("takes the three highest-xPts starters as candidates, with the ×2 value and range", () => {
    const lab = run("chase");
    expect(lab.candidates.map((c) => c.name)).toEqual(["Haaland", "Saka", "Palmer"]);
    expect(lab.candidates[0]).toMatchObject({ xpts: 8.6, doubled: 17.2, p10: 2, p90: 18, eoTop10k: 142, rankGainIfHaul: 3000 });
    expect(lab.candidates[0].fixture).toEqual({ opponent: "BHA", isHome: true, difficulty: 1 });
  });

  it("protect picks the highest-EO candidate; chase picks the biggest rank swing", () => {
    expect(run("safe").znPickId).toBe(1);
    expect(run("chase").znPickId).toBe(2);
    expect(run("safe").headline).toBe("Protect your rank with Haaland.");
    expect(run("chase").headline).toBe("Captain Saka to climb the ranks.");
    expect(run("chase").subcopy).toContain("142% EO in the top 10k");
  });

  it("a manual pick overrides the ZN Pick and the vice is the best remaining by xPts", () => {
    const lab = run("chase", 3);
    expect(lab.captainId).toBe(3);
    expect(lab.viceId).toBe(1);
    expect(run("chase").viceId).toBe(1); // Saka captain → Haaland vice
    expect(run("safe").viceId).toBe(2);
  });

  it("re-projects the total for the chosen captain", () => {
    // Backend projected 66 with Haaland (suggested). Palmer instead: 66 − 8.6 + 6.9.
    expect(run("chase", 3).projected).toBeCloseTo(64.3, 5);
    expect(run("safe").projected).toBe(66);
  });

  it("falls back without ownership data: both goals land on the backend's suggested captain", () => {
    const bare = rec(withEo.map(({ eo_top10k, rank_gain_if_haul, xpts_p10, xpts_p90, ...rest }) => rest as FplTeamRecommendationPlayer));
    expect(run("safe", undefined, bare).znPickId).toBe(1);
    expect(run("chase", undefined, bare).znPickId).toBe(1);
    expect(run("chase", undefined, bare).rankAware).toBe(false);
    expect(run("chase", undefined, bare).candidates[0]).toMatchObject({ p10: 2, p90: 16, eoTop10k: undefined });
  });

  it("flags a large rank gain", () => {
    const lab = run("chase");
    expect(lab.candidates.map((c) => c.bigGain)).toEqual([false, true, true]);
  });
});
