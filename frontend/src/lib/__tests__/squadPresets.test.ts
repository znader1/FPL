import { describe, expect, it } from "vitest";
import { applyStyle, detectStyle, type SquadStyle } from "../squadPresets";
import type { SquadBuildParams } from "../squadPickerApi";

const BASE: SquadBuildParams = {
  horizon_gws: 5,
  budget_m: 100,
  objective: "wildcard",
  projection_basis: "blend",
  blend_weight: 0.5,
  minutes_prior_k: 500,
  include_flagged: false,
  min_chance_of_playing: 0,
  max_per_team: 3,
  min_fwd_minutes: 0,
  formation: "auto",
  fdr_strength: 1.0,
  home_away_strength: 1.0,
  xi_objective: "horizon",
};

describe("applyStyle", () => {
  it("attacking leans harder on xG than balanced", () => {
    const balanced = applyStyle(BASE, "balanced");
    const attacking = applyStyle(BASE, "attacking");
    expect(attacking.blend_weight!).toBeGreaterThan(balanced.blend_weight!);
  });

  it("safe requires fit players and leans on proven ppg", () => {
    const safe = applyStyle(BASE, "safe");
    expect(safe.min_chance_of_playing).toBe(75);
    expect(safe.include_flagged).toBe(false);
    expect(safe.blend_weight!).toBeLessThan(applyStyle(BASE, "balanced").blend_weight!);
  });

  it("every style filters out never-played fringe; safe demands regulars", () => {
    expect(applyStyle(BASE, "balanced").min_minutes).toBe(600);
    expect(applyStyle(BASE, "attacking").min_minutes).toBe(600);
    expect(applyStyle(BASE, "safe").min_minutes).toBe(1200);
  });

  it("preserves user's budget and horizon untouched", () => {
    const params = { ...BASE, budget_m: 98.5, horizon_gws: 8 };
    for (const style of ["balanced", "attacking", "safe"] as SquadStyle[]) {
      const out = applyStyle(params, style);
      expect(out.budget_m).toBe(98.5);
      expect(out.horizon_gws).toBe(8);
    }
  });
});

describe("detectStyle", () => {
  it("round-trips every style", () => {
    for (const style of ["balanced", "attacking", "safe"] as SquadStyle[]) {
      expect(detectStyle(applyStyle(BASE, style))).toBe(style);
    }
  });

  it("reports custom when an advanced knob diverges from every preset", () => {
    const tweaked = { ...applyStyle(BASE, "balanced"), blend_weight: 0.93 };
    expect(detectStyle(tweaked)).toBe("custom");
  });
});
