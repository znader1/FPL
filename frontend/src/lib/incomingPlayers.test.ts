import { describe, expect, it } from "vitest";
import { findIncomingPlayers } from "./incomingPlayers";
import { SAMPLE_TEAM_RECOMMENDATION, type FplTeamRecommendation } from "./fplAssistantApi";

const base = SAMPLE_TEAM_RECOMMENDATION;
const [first, ...restXi] = base.starting_xi;
const newcomer = { ...first, player_id: 9999, web_name: "Solanke" };

const withApplied = (over: Partial<FplTeamRecommendation> = {}): FplTeamRecommendation => ({
  ...base,
  transfers: {
    moves: [
      { sell: { id: first.player_id, name: first.web_name, team: first.team_short, price: 7 }, buy: { id: 9999, name: "Solanke", team: "BOU", price: 6 }, score_gain: 5.1, this_gw_gain: 2.4 },
    ],
  },
  transfer_application: { requested: 1, applied: 1, skipped: 0 },
  squad_with_transfers: {
    ...base,
    formation: base.formation,
    captain_player_id: base.captain_player_id,
    vice_player_id: base.vice_player_id,
    projected_points_with_captain: 60,
    starting_xi: [newcomer, ...restXi],
  },
  ...over,
});

describe("findIncomingPlayers", () => {
  it("maps each player not in the base squad to the matching move's this-GW gain", () => {
    expect(findIncomingPlayers(withApplied())).toEqual({ 9999: 2.4 });
  });

  it("falls back to the move's horizon gain when there is no this-GW slice", () => {
    const rec = withApplied();
    rec.transfers!.moves[0] = { ...rec.transfers!.moves[0], this_gw_gain: undefined };
    expect(findIncomingPlayers(rec)).toEqual({ 9999: 5.1 });
  });

  it("marks a newcomer with no matching move as null rather than a fake +0.0", () => {
    const rec = withApplied({ transfers: { moves: [] } });
    expect(findIncomingPlayers(rec)).toEqual({ 9999: null });
  });

  it("returns nothing when no transfer has been applied", () => {
    expect(findIncomingPlayers(withApplied({ transfer_application: { requested: 0, applied: 0, skipped: 0 } }))).toEqual({});
    expect(findIncomingPlayers(base)).toEqual({});
  });
});
