import type { FplSquad, FplTeamRecommendation } from "@/lib/fplAssistantApi";

/** Players on the displayed (post-transfer) squad who weren't in the base
 *  squad, each mapped to the gain of the move that brought them in — the
 *  pitch's "IN +2.4" pill — or null when no move names them (bare "IN", never
 *  a fabricated +0.0). Empty until a transfer is actually applied. */
export function findIncomingPlayers(team: FplSquad | FplTeamRecommendation): Record<number, number | null> {
  if (!("horizon_gws" in team)) return {};
  const applied = team.transfer_application?.applied ?? 0;
  const after = team.squad_with_transfers;
  if (applied <= 0 || !after) return {};
  const baseIds = new Set([...team.starting_xi, ...team.bench].map((p) => p.player_id));
  const gainByBuyId = new Map<number, number>();
  for (const m of team.transfers?.moves ?? []) {
    gainByBuyId.set(m.buy.id, m.this_gw_gain ?? m.score_gain ?? 0);
  }
  const out: Record<number, number | null> = {};
  for (const p of [...after.starting_xi, ...after.bench]) {
    if (!baseIds.has(p.player_id)) out[p.player_id] = gainByBuyId.get(p.player_id) ?? null;
  }
  return out;
}
