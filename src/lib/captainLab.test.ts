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
  it("is the pitch's parser: tolerates a missing H-/A- prefix and finds (Dn) anywhere", () => {
    expect(parseFixtureLabel("BOU(D2)")).toEqual({ opponent: "", isHome: undefined, difficulty: 2 });
    expect(parseFixtureLabel("H-BOU DGW (D3)")).toEqual({ opponent: "BOU", isHome: true, difficulty: 3 });
  });
});

describe("buildCaptainLab", () => {
  it("chase compares rank swings only among players that have one — never a rank count against an xPts ceiling", () => {
    // Haaland has no rank_gain_if_haul; Saka (41k) and Palmer (29k) do. Haaland's p90 of 18 must not
    // be read as "18 ranks" and lose, nor as a swing and win: he is simply out of the comparison.
    const mixed = [{ ...withEo[0], rank_gain_if_haul: undefined }, withEo[1], withEo[2], withEo[3]];
    expect(buildCaptainLab(rec(mixed), "chase", null).znPickId).toBe(2);
    // No candidate has a swing (EO sampled, rank model not yet): the ceiling the
    // fewest top-10k rivals share decides — Haaland's 142% EO (everyone captains
    // him) makes his 18 worth nothing as a climb; Palmer 15 × (1 − 0.22) wins.
    const none = withEo.map((c) => ({ ...c, rank_gain_if_haul: undefined }));
    expect(buildCaptainLab(rec(none), "chase", null).znPickId).toBe(3);
  });

  it("carries the GW the top-10k sample was taken in, so the tile can say it lags the plan", () => {
    const sampled = withEo.map((c) => ({ ...c, eo_top10k_event_id: 6 }));
    expect(buildCaptainLab(rec(sampled), "safe", null).eoEventId).toBe(6);
    expect(buildCaptainLab(rec(withEo), "safe", null).eoEventId).toBeNull();
  });

  it("re-bases the projection on captain_player_id when no is_captain_suggested flag is sent", () => {
    const xi = withEo.map((c) => ({ ...c, is_captain_suggested: undefined }));
    const lab = buildCaptainLab(rec(xi, { captain_player_id: 1 }), "safe", 3);
    // Re-based from Haaland (8.6) to Palmer (6.9): 66 − 8.6 + 6.9.
    expect(lab.projected).toBeCloseTo(64.3, 5);
  });

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

  it("uses overall ownership when top-10k EO is absent: protect = most owned, chase = low-owned ceiling", () => {
    const owned = rec([
      p(1, "Haaland", "MCI", 8.6, { is_captain_suggested: true, ownership_pct: 82, score_breakdown: { distribution: { p80_low: 2, p80_high: 18 } } }),
      p(2, "Saka", "ARS", 7.4, { ownership_pct: 38, score_breakdown: { distribution: { p80_low: 2, p80_high: 16 } } }),
      p(3, "Palmer", "CHE", 6.9, { ownership_pct: 22, score_breakdown: { distribution: { p80_low: 1, p80_high: 15 } } }),
    ]);
    const safe = run("safe", undefined, owned);
    const chase = run("chase", undefined, owned);
    expect(safe.znPickId).toBe(1);
    expect(chase.znPickId).toBe(3); // 15 × 0.78 = 11.7 beats 16 × 0.62 = 9.9 and 18 × 0.18
    expect(chase.rankAware).toBe(true);
    expect(chase.ownershipBasis).toBe("overall");
    expect(chase.candidates[0].ownershipPct).toBe(82);
    expect(chase.subcopy).toContain("82% owned");
    expect(run("chase").ownershipBasis).toBe("top10k");
  });

  it("re-bases against the suggested captain even when he isn't a candidate", () => {
    // Suggested captain is the 4th-highest xPts starter (odd but possible: DGW logic server-side).
    const r = rec([
      p(1, "Haaland", "MCI", 8.6), p(2, "Saka", "ARS", 7.4), p(3, "Palmer", "CHE", 6.9),
      p(4, "Watkins", "AVL", 6.1, { is_captain_suggested: true }),
    ]);
    const lab = run("chase", 1, r);
    expect(lab.projected).toBeCloseTo(66 - 6.1 + 8.6, 5);
    expect(lab.znPickId).toBe(1); // no ownership data: highest xPts candidate
  });

  it("flags a large rank gain", () => {
    const lab = run("chase");
    expect(lab.candidates.map((c) => c.bigGain)).toEqual([false, true, true]);
  });
});

describe("buildCaptainLab from the plan (v2 flow)", () => {
  it("draws candidates from the given pool, flags the benched ones, and reads the plan's armbands", () => {
    const bench = p(5, "Isak", "NEW", 7.9);
    const r = rec(withEo, { bench: [{ ...bench, bench_order: 2 }] });
    const lab = buildCaptainLab(r, "chase", 3, { pool: [...withEo, bench], benchedIds: new Set([5]), viceId: 1 });
    expect(lab.candidates.map((c) => c.name)).toEqual(["Haaland", "Isak", "Saka"]);
    expect(lab.candidates[1].benched).toBe(true);
    expect(lab.candidates[0].benched).toBe(false);
    expect(lab.captainId).toBe(3);
    expect(lab.viceId).toBe(1);
    // A benched player is never the ZN Pick.
    expect(lab.znPickId).toBe(2);
  });
});
