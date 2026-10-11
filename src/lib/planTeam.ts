import type { FplSquad, FplTeamRecommendationBenchPlayer, FplTeamRecommendationPlayer } from "@/lib/fplAssistantApi";
import type { PlayerLookup, ResolvedPlan } from "@/lib/gwPlan";

/**
 * A squad payload rebuilt from the plan, so the existing pitch renders the
 * user's XI, bench order and armbands without knowing the plan exists. Ids
 * with no record (should not happen; a defensive guard) are dropped rather
 * than rendered as holes.
 */
export function planToTeam(squad: FplSquad, r: ResolvedPlan, lookup: PlayerLookup): FplSquad {
  const player = (id: number): FplTeamRecommendationPlayer | undefined => {
    const p = lookup[id];
    if (!p) return undefined;
    const isCap = id === r.cap;
    return { ...p, is_captain: isCap, is_vice_captain: id === r.vice, multiplier: isCap ? 2 : 1 };
  };
  const starting_xi = r.xi.map(player).filter((p): p is FplTeamRecommendationPlayer => Boolean(p));
  const bench = r.bench
    .map((id, i) => {
      const p = player(id);
      return p ? ({ ...p, bench_order: i + 1 } as FplTeamRecommendationBenchPlayer) : undefined;
    })
    .filter((p): p is FplTeamRecommendationBenchPlayer => Boolean(p));
  const count = (pos: string) => starting_xi.filter((p) => p.pos === pos).length;
  return {
    ...squad,
    formation: [count("DEF"), count("MID"), count("FWD")],
    captain_player_id: r.cap,
    vice_player_id: r.vice,
    starting_xi,
    bench,
  };
}
