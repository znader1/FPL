import { describe, expect, it } from "vitest";
import { pairBudgetGap, splitXiBench, toPitchPlayer, type DraftPitchPlayer } from "../draftPitch";

const p = (over: Partial<DraftPitchPlayer>): DraftPitchPlayer => ({
  player_id: 1,
  web_name: "Player",
  pos: "MID",
  team_short: "ARS",
  price_m: 5.0,
  xpts_horizon: 10.0,
  ...over,
});

describe("splitXiBench", () => {
  const squad = [
    p({ player_id: 1, pos: "GKP" }),
    p({ player_id: 2, pos: "GKP" }),
    p({ player_id: 3, pos: "DEF" }),
    p({ player_id: 4, pos: "DEF" }),
    p({ player_id: 5, pos: "DEF" }),
    p({ player_id: 6, pos: "DEF" }),
    p({ player_id: 7, pos: "MID" }),
    p({ player_id: 8, pos: "MID" }),
    p({ player_id: 9, pos: "MID" }),
    p({ player_id: 10, pos: "MID" }),
    p({ player_id: 11, pos: "FWD" }),
    p({ player_id: 12, pos: "FWD" }),
    p({ player_id: 13, pos: "FWD" }),
    p({ player_id: 14, pos: "DEF" }),
    p({ player_id: 15, pos: "MID" }),
  ];
  const xiIds = new Set([1, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13]);

  it("groups the XI into GKP/DEF/MID/FWD rows", () => {
    const { rows } = splitXiBench(squad, xiIds);
    expect(rows.map((r) => r.length)).toEqual([1, 3, 4, 3]);
    expect(rows[0][0].player_id).toBe(1);
  });

  it("bench holds the other four, GK first then position order", () => {
    const { bench } = splitXiBench(squad, xiIds);
    expect(bench.map((b) => b.player_id)).toEqual([2, 6, 14, 15]);
    expect(bench[0].pos).toBe("GKP");
  });

  it("players missing from the XI set all land on the bench", () => {
    const { rows, bench } = splitXiBench(squad, new Set());
    expect(rows.every((r) => r.length === 0)).toBe(true);
    expect(bench).toHaveLength(15);
  });
});

describe("toPitchPlayer", () => {
  it("maps names, price, projected points and badges", () => {
    const out = toPitchPlayer(
      p({ player_id: 7, web_name: "Salah", team_short: "LIV", price_m: 12.5, xpts_horizon: 31.24 }),
      { captainId: 7, viceId: 9 }
    );
    expect(out).toMatchObject({
      id: 7,
      name: "Salah",
      team: "LIV",
      price: 12.5,
      points: 31.2,
      isCaptain: true,
      isViceCaptain: false,
    });
  });

  it("maps the next fixture chip when fixtures exist", () => {
    const out = toPitchPlayer(
      p({ fixtures: [{ gw: 2, opp: "MCI", home: false, diff: 5 }] }),
      { captainId: null, viceId: null }
    );
    expect(out.fixture).toEqual({ opponent: "MCI", isHome: false, difficulty: 5 });
  });

  it("omits the fixture chip when no fixtures", () => {
    const out = toPitchPlayer(p({}), { captainId: null, viceId: null });
    expect(out.fixture).toBeUndefined();
  });
});

describe("pairBudgetGap", () => {
  it("returns 0 when the pair fits the remaining budget", () => {
    // 13 outfielders cost 90, budget 100 -> 10 available; pair costs 9.5
    expect(pairBudgetGap(9.5, 90, 100)).toBe(0);
  });

  it("returns the shortfall when the pair is too expensive", () => {
    expect(pairBudgetGap(11.5, 90, 100)).toBeCloseTo(1.5);
  });

  it("rounds away float noise", () => {
    expect(pairBudgetGap(10.1, 89.9, 100)).toBe(0);
  });
});
