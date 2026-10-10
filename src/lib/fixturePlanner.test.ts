import { describe, expect, it } from "vitest";
import {
  bandToFdr,
  buildPlannerRows,
  chipWindowsInRange,
  columnTags,
  totalTone,
  weakestLinks,
} from "./fixturePlanner";
import type {
  ChipPlanResponse,
  FixtureDifficultyResponse,
  FixtureTickerCell,
  FplSquad,
  FplTeamRecommendation,
  FplTeamRecommendationPlayer,
} from "./fplAssistantApi";

const player = (id: number, name: string, team: string, pos: FplTeamRecommendationPlayer["pos"], over: Partial<FplTeamRecommendationPlayer> = {}): FplTeamRecommendationPlayer => ({
  player_id: id, web_name: name, team_short: team, team_name: team, pos,
  is_captain: false, is_vice_captain: false, multiplier: 1, xpts: 4, ...over,
});

const squad: FplSquad = {
  entry_id: 1, event_id: 29,
  captain_player_id: 4,
  starting_xi: [
    player(1, "Raya", "ARS", "GKP"),
    player(2, "Gabriel", "ARS", "DEF"),
    player(3, "Van Dijk", "LIV", "DEF"),
    player(4, "Saka", "ARS", "MID", { is_captain: true }),
    player(5, "Isak", "NEW", "FWD"),
  ],
  bench: [
    { ...player(6, "Sels", "NFO", "GKP"), bench_order: 1 },
    { ...player(7, "Mbeumo", "BRE", "MID"), bench_order: 2 },
  ],
};

const cell = (opps: Array<[string, boolean, string]>): FixtureTickerCell => ({
  opponents: opps.map(([opp_short, home, band]) => ({ opp_id: 0, opp_short, home, difficulty: 3, band: band as never, color: "#000" })),
  difficulty: opps.length ? 3 : null, count: opps.length, blank: opps.length === 0,
});

const team = (team_short: string, gws: Record<string, FixtureTickerCell>) => ({
  team_id: 0, team_short, avg_difficulty: 3, sum_difficulty: 9, n_fixtures: 3, band: "medium" as const, color: "#000", gws,
});

const ticker: FixtureDifficultyResponse = {
  gw_start: 29, horizon_gws: 3, gws: [29, 30, 31],
  teams: [
    team("ARS", { "29": cell([["BHA", true, "very_easy"]]), "30": cell([["BRE", false, "easy"], ["WOL", true, "medium"]]), "31": cell([["CHE", true, "hard"]]) }),
    team("LIV", { "29": cell([["NEW", false, "very_hard"]]), "30": cell([["EVE", true, "easy"]]), "31": cell([]) }),
    team("NEW", { "29": cell([["LIV", true, "hard"]]), "30": cell([["MCI", false, "very_hard"]]), "31": cell([]) }),
    team("NFO", { "29": cell([["CRY", true, "easy"]]), "30": cell([["LUT", false, "easy"]]), "31": cell([]) }),
    team("BRE", { "29": cell([["WOL", false, "easy"]]), "30": cell([["ARS", true, "hard"]]), "31": cell([["FUL", false, "medium"]]) }),
  ],
  easiest_runs: [], hardest_runs: [],
};

const fh = (xs: Array<[number, number, number]>) => xs.map(([event_id, xpts, fixture_count]) => ({ event_id, xpts, fixture_count, fixtures: "" }));

const rec: FplTeamRecommendation = {
  ...squad, horizon_gws: 3, formation: [2, 1, 1], captain_player_id: 4, vice_player_id: 2, projected_points_with_captain: 40,
  starting_xi: [
    { ...squad.starting_xi[0], fixtures_horizon: fh([[29, 4.1, 1], [30, 3.9, 1], [31, 3.0, 1]]) },
    { ...squad.starting_xi[1], fixtures_horizon: fh([[29, 5.8, 1], [30, 9.2, 2], [31, 4.0, 1]]) },
    { ...squad.starting_xi[2], fixtures_horizon: fh([[29, 2.1, 1], [30, 5.0, 1], [31, 0, 0]]) },
    { ...squad.starting_xi[3], fixtures_horizon: fh([[29, 7.4, 1], [30, 8.0, 2], [31, 6.6, 1]]) },
    squad.starting_xi[4], // Isak: no horizon from the backend
  ],
  bench: squad.bench,
  transfers: { moves: [] },
  transfer_plan_horizon: {
    verdict: "spend",
    verdict_detail: {
      action: "spend", horizon: { start_gw: 29, end_gw: 31, n: 3 }, ft_before: 1, ft_after: 0, threshold: 2,
      moves: [{ sell: { id: 5, name: "Isak", team: "NEW", price: 8.5 }, buy: { id: 50, name: "Solanke", team: "BOU", price: 6.7 }, this_gw_gain: 0.8, horizon_gain: 2.4 }],
      this_gw_gain: 0.8, horizon_gain: 2.4, hit_cost: 0, plan_net: 2.4, roll_alternative: null, next_move: null,
      runner_ups: [
        { sell: { id: 3, name: "Van Dijk", team: "LIV", price: 6.2 }, buy: { id: 51, name: "Saliba", team: "ARS", price: 6.0 }, this_gw_gain: 0.2, horizon_gain: 1.1, clears_bar: false },
        { sell: { id: 2, name: "Gabriel", team: "ARS", price: 6.1 }, buy: { id: 52, name: "Gvardiol", team: "MCI", price: 6.3 }, this_gw_gain: -0.3, horizon_gain: -0.9, clears_bar: false },
      ],
    },
  },
};

describe("bandToFdr", () => {
  it("maps the five bands onto fdr-1…5 and falls back to the numeric score", () => {
    expect(bandToFdr("very_easy")).toBe(1);
    expect(bandToFdr("easy")).toBe(2);
    expect(bandToFdr("medium")).toBe(3);
    expect(bandToFdr("hard")).toBe(4);
    expect(bandToFdr("very_hard")).toBe(5);
    expect(bandToFdr("odd", 4.4)).toBe(4);
    expect(bandToFdr("odd", null)).toBe(3);
  });
});

describe("buildPlannerRows", () => {
  const rows = buildPlannerRows({ squad, ticker, gws: [29, 30, 31], horizon: 3, recommendation: rec });

  it("orders starters by position then the bench, with group gaps", () => {
    expect(rows.map((r) => r.name)).toEqual(["Raya", "Gabriel", "Van Dijk", "Saka", "Isak", "Sels", "Mbeumo"]);
    expect(rows.map((r) => r.gapBefore)).toEqual([0, 8, 0, 8, 8, 14, 0]);
    expect(rows[5].isBench).toBe(true);
    expect(rows[3].isCaptain).toBe(true);
  });

  it("joins the ticker cell by team and the per-GW xPts by player", () => {
    const gabriel = rows[1];
    expect(gabriel.cells[1].fixtures.map((f) => `${f.opponent}${f.isHome ? "H" : "A"}${f.fdr}`)).toEqual(["BREA2", "WOLH3"]);
    expect(gabriel.cells[1].count).toBe(2);
    expect(gabriel.cells[1].xpts).toBe(9.2);
    expect(gabriel.total).toBe(19);
  });

  it("marks blank cells and leaves xPts undefined when the backend sent none", () => {
    const vvd = rows[2];
    expect(vvd.cells[2].blank).toBe(true);
    expect(vvd.cells[2].xpts).toBe(0);
    const isak = rows[4];
    expect(isak.cells[0].fixtures[0].opponent).toBe("LIV");
    expect(isak.cells[0].xpts).toBeUndefined();
    expect(isak.total).toBeNull();
  });

  it("fades cells beyond the horizon and totals only the visible ones", () => {
    const short = buildPlannerRows({ squad, ticker, gws: [29, 30, 31], horizon: 2, recommendation: rec });
    expect(short[1].cells.map((c) => c.inHorizon)).toEqual([true, true, false]);
    expect(short[1].total).toBe(15);
  });

  it("renders fixtures from the ticker alone before a recommendation lands", () => {
    const bare = buildPlannerRows({ squad, ticker, gws: [29, 30, 31], horizon: 3 });
    expect(bare[0].cells[0].fixtures[0].opponent).toBe("BHA");
    expect(bare.every((r) => r.total === null)).toBe(true);
  });
});

describe("totalTone", () => {
  it("is pink above 6 per GW, rose below 4.4, neutral between", () => {
    expect(totalTone(6.1)).toBe("hot");
    expect(totalTone(4.3)).toBe("cold");
    expect(totalTone(5)).toBe("neutral");
    expect(totalTone(null)).toBe("neutral");
  });
});

describe("columnTags", () => {
  const rows = buildPlannerRows({ squad, ticker, gws: [29, 30, 31], horizon: 3, recommendation: rec });

  it("derives DGW from any doubling squad player and BLANK from three or more blank starters", () => {
    const tags = columnTags({ gws: [29, 30, 31], rows });
    expect(tags.map((t) => t.tag)).toEqual([null, "DGW", null]);
  });

  it("prefers the chip plan's calendar when present", () => {
    const calendar = [
      { gw: 29, has_dgw: false, is_blank_heavy: false },
      { gw: 30, has_dgw: false, is_blank_heavy: false },
      { gw: 31, has_dgw: false, is_blank_heavy: true },
    ] as ChipPlanResponse["calendar"];
    const tags = columnTags({ gws: [29, 30, 31], rows, calendar });
    expect(tags.map((t) => t.tag)).toEqual([null, null, "BLANK"]);
  });
});

describe("weakestLinks", () => {
  it("lists only positive-gain swaps, best first, with the seller's horizon xPts when known", () => {
    const links = weakestLinks(rec, { 5: 14.2 });
    expect(links.map((l) => l.out)).toEqual(["Isak", "Van Dijk"]);
    expect(links[0]).toMatchObject({ in: "Solanke", outX: 14.2, inX: 16.6, gain: 2.4, price: 6.7 });
    expect(links[1].outX).toBeUndefined();
  });
  it("is empty without a verdict", () => {
    expect(weakestLinks({ ...rec, transfer_plan_horizon: undefined }, {})).toEqual([]);
  });
});

describe("chipWindowsInRange", () => {
  const rows = buildPlannerRows({ squad, ticker, gws: [29, 30, 31], horizon: 3, recommendation: rec });
  const plan = {
    recommendations: [
      { chip: "bench_boost", event_id: 30, ev_gain: 6, provisional: false, reasons: ["Two doubles"], ev_curve: [], guidance: "Play it in GW30." },
      { chip: "free_hit", event_id: 31, ev_gain: 4, provisional: true, reasons: ["Blank-heavy week"], ev_curve: [] },
      { chip: "triple_captain", event_id: 36, ev_gain: 3, provisional: false, reasons: [], ev_curve: [] },
    ],
    nudge: { chip: "bench_boost", event_id: 30, ev_gain: 6 },
  } as unknown as ChipPlanResponse;

  it("keeps only windows inside the displayed GWs and counts the squad's doubles/blanks", () => {
    const w = chipWindowsInRange(plan, [29, 30, 31], rows);
    expect(w.map((x) => `${x.label} GW${x.gw}`)).toEqual(["Bench Boost GW30", "Free Hit GW31"]);
    expect(w[0].nudged).toBe(true);
    expect(w[0].reason).toBe("3 of your players have a double gameweek. Play it in GW30.");
    expect(w[1].nudged).toBe(false);
    expect(w[1].reason).toBe("2 starters blank. Blank-heavy week");
  });
});
