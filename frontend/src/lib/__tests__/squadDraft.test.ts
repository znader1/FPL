import { describe, expect, it } from "vitest";
import {
  formatSquadForClipboard,
  parseDraft,
  serializeDraft,
  type SquadDraft,
} from "../squadDraft";
import type { SquadPlayer } from "../squadPickerApi";

const player = (over: Partial<SquadPlayer>): SquadPlayer =>
  ({
    player_id: 1,
    web_name: "Haaland",
    pos: "FWD",
    team_short: "MCI",
    price_m: 14.5,
    ...over,
  }) as SquadPlayer;

describe("formatSquadForClipboard", () => {
  it("groups by position in GKP/DEF/MID/FWD order with prices", () => {
    const squad = [
      player({ player_id: 1, web_name: "Haaland", pos: "FWD", team_short: "MCI", price_m: 14.5 }),
      player({ player_id: 2, web_name: "Raya", pos: "GKP", team_short: "ARS", price_m: 5.5 }),
      player({ player_id: 3, web_name: "Saliba", pos: "DEF", team_short: "ARS", price_m: 6.0 }),
      player({ player_id: 4, web_name: "Salah", pos: "MID", team_short: "LIV", price_m: 12.5 }),
    ];
    const text = formatSquadForClipboard(squad);
    const lines = text.split("\n");
    expect(lines[0]).toBe("GKP");
    expect(lines[1]).toBe("Raya (ARS) £5.5m");
    expect(text.indexOf("DEF")).toBeLessThan(text.indexOf("MID"));
    expect(text.indexOf("MID")).toBeLessThan(text.indexOf("FWD"));
    expect(text).toContain("Haaland (MCI) £14.5m");
  });
});

describe("draft serialize/parse", () => {
  const draft: SquadDraft = {
    params: { budget_m: 100, horizon_gws: 5 },
    teamNudges: [],
    squadIds: [1, 2, 3],
    lastGood: null,
  };

  it("round-trips a draft", () => {
    expect(parseDraft(serializeDraft(draft))).toEqual(draft);
  });

  it("returns null on corrupt JSON", () => {
    expect(parseDraft("{not json")).toBeNull();
  });

  it("returns null on wrong version payload", () => {
    expect(parseDraft(JSON.stringify({ v: 999, squadIds: [1] }))).toBeNull();
  });

  it("returns null on null input (missing storage key)", () => {
    expect(parseDraft(null)).toBeNull();
  });
});
