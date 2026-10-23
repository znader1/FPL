import type { SquadBuildParams } from "./squadPickerApi";

export type SquadStyle = "balanced" | "attacking" | "safe";

/**
 * Each style is a bundle of overrides on the expert knobs. blend_weight is the
 * xG share of the projection (1 = pure xG, 0 = pure ppg — see squad_draft_xg.py).
 * Budget/horizon/objective are deliberately absent: the simple form owns those.
 */
export const STYLE_PRESETS: Record<SquadStyle, Partial<SquadBuildParams>> = {
  balanced: {
    projection_basis: "blend",
    blend_weight: 0.5,
    minutes_prior_k: 500,
    include_flagged: false,
    min_chance_of_playing: 0,
    min_minutes: 600,
  },
  attacking: {
    projection_basis: "blend",
    blend_weight: 0.8,
    minutes_prior_k: 500,
    include_flagged: false,
    min_chance_of_playing: 0,
    min_minutes: 600,
  },
  safe: {
    projection_basis: "blend",
    blend_weight: 0.3,
    minutes_prior_k: 800,
    include_flagged: false,
    min_chance_of_playing: 75,
    min_minutes: 1200,
  },
};

export function applyStyle(
  params: SquadBuildParams,
  style: SquadStyle
): SquadBuildParams {
  return { ...params, ...STYLE_PRESETS[style] };
}

/** The preset whose overrides all match, or "custom" when none does. */
export function detectStyle(params: SquadBuildParams): SquadStyle | "custom" {
  for (const [style, preset] of Object.entries(STYLE_PRESETS)) {
    const matches = Object.entries(preset).every(
      ([key, value]) => params[key as keyof SquadBuildParams] === value
    );
    if (matches) return style as SquadStyle;
  }
  return "custom";
}
