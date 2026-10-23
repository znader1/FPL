import type { SquadPlayer } from "./squadPickerApi";

export interface GemCandidate {
  player_id: number;
  web_name: string;
  pos: SquadPlayer["pos"];
  team_short: string;
  price_m: number;
  xpts_horizon: number;
  selected_by_percent: number;
}

export interface Gem extends GemCandidate {
  /** Projected horizon points per £m — the ranking metric. */
  value: number;
}

const MAX_OWNERSHIP_PCT = 10;
const TOP_N = 8;

/**
 * Low-owned value picks: under the ownership cap, ranked by projected
 * points per £m. Trend flags (rising xG/minutes) come later once
 * per-GW season data exists.
 */
export function findGems(pool: GemCandidate[]): Gem[] {
  return pool
    .filter(
      (p) =>
        (p.xpts_horizon ?? 0) > 0 &&
        (p.selected_by_percent ?? 100) <= MAX_OWNERSHIP_PCT &&
        (p.price_m ?? 0) > 0
    )
    .map((p) => ({ ...p, value: p.xpts_horizon / p.price_m }))
    .sort((a, b) => b.value - a.value)
    .slice(0, TOP_N);
}
