import { describe, expect, it } from "vitest";
import { findGems, type GemCandidate } from "../gems";

const p = (over: Partial<GemCandidate>): GemCandidate => ({
  player_id: 1,
  web_name: "Player",
  pos: "MID",
  team_short: "ARS",
  price_m: 6.0,
  xpts_horizon: 15,
  selected_by_percent: 5,
  ...over,
});

describe("findGems", () => {
  it("ranks low-owned players by projected points per million", () => {
    const pool = [
      p({ player_id: 1, web_name: "Gem", price_m: 5.0, xpts_horizon: 20, selected_by_percent: 3 }),
      p({ player_id: 2, web_name: "Meh", price_m: 10.0, xpts_horizon: 20, selected_by_percent: 3 }),
    ];
    const gems = findGems(pool);
    expect(gems[0].web_name).toBe("Gem");
    expect(gems[0].value).toBeCloseTo(4.0);
  });

  it("excludes template players above the ownership cap", () => {
    const pool = [
      p({ player_id: 1, web_name: "Template", selected_by_percent: 45 }),
      p({ player_id: 2, web_name: "Hidden", selected_by_percent: 4 }),
    ];
    expect(findGems(pool).map((g) => g.web_name)).toEqual(["Hidden"]);
  });

  it("excludes zero-projection players and caps the list", () => {
    const pool = [
      p({ player_id: 99, xpts_horizon: 0, selected_by_percent: 1 }),
      ...Array.from({ length: 12 }, (_, i) =>
        p({ player_id: i + 1, xpts_horizon: 10 + i, selected_by_percent: 2 })
      ),
    ];
    const gems = findGems(pool);
    expect(gems).toHaveLength(8);
    expect(gems.every((g) => g.xpts_horizon > 0)).toBe(true);
  });
});
