import type { FplTeamRecommendation, FplTeamRecommendationPlayer } from "@/lib/fplAssistantApi";
import { parseFixtureLabel as parseSharedFixtureLabel } from "./fixtureLabel";

export type CaptainGoal = "safe" | "chase";

export interface CaptainFixture {
  opponent: string;
  isHome?: boolean;
  difficulty?: number;
}

export interface CaptainCandidate {
  id: number;
  name: string;
  team: string;
  xpts: number;
  doubled: number;
  /** Likely-range ends; `xpts_p10/p90` when sent, else the 80% band from the distribution. */
  p10?: number;
  p90?: number;
  pHaul?: number;
  eoTop10k?: number;
  /** Overall ownership (selected_by_percent); the fallback basis when EO is absent. */
  ownershipPct?: number;
  rankGainIfHaul?: number;
  /** True when the haul would move the rank by a lot (handoff: teal value). */
  bigGain: boolean;
  fixture?: CaptainFixture;
  suggested: boolean;
  /** v2 flow: the player sits on the plan's bench, so he can't wear the armband yet. */
  benched: boolean;
}

export interface CaptainLab {
  candidates: CaptainCandidate[];
  znPickId: number | null;
  captainId: number | null;
  viceId: number | null;
  headline: string;
  subcopy: string;
  /** False when no candidate carries ownership data — both goals then agree. */
  rankAware: boolean;
  /** Which ownership figure drove the picks and labels the tile. */
  ownershipBasis: "top10k" | "overall" | null;
  /** Backend total re-based on the chosen captain. */
  projected: number;
}

const CANDIDATES = 3;
const BIG_GAIN_RANKS = 20_000;
const round1 = (n: number) => Math.round(n * 10) / 10;

/** The pitch's parser (`src/lib/fixtureLabel.ts`), narrowed to the captain card's shape. */
export function parseFixtureLabel(label?: string | null): CaptainFixture | undefined {
  const f = parseSharedFixtureLabel(label);
  return f ? { opponent: f.opponent, isHome: f.isHome, difficulty: f.difficulty } : undefined;
}

const num = (v: number | null | undefined) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

function toCandidate(p: FplTeamRecommendationPlayer): CaptainCandidate {
  const dist = p.score_breakdown?.distribution;
  const rankGain = num(p.rank_gain_if_haul);
  return {
    id: p.player_id,
    name: p.web_name,
    team: p.team_short,
    xpts: p.xpts,
    doubled: round1(p.xpts * 2),
    p10: num(p.xpts_p10) ?? num(dist?.p80_low),
    p90: num(p.xpts_p90) ?? num(dist?.p80_high),
    pHaul: num(dist?.p_haul_10),
    eoTop10k: num(p.eo_top10k),
    ownershipPct: num(p.ownership_pct),
    rankGainIfHaul: rankGain,
    bigGain: typeof rankGain === "number" && rankGain >= BIG_GAIN_RANKS,
    fixture: parseFixtureLabel(p.next_fixtures ?? p.fixtures_horizon?.[0]?.fixtures),
    suggested: Boolean(p.is_captain_suggested),
    benched: false,
  };
}

export interface CaptainLabOptions {
  /** Candidate pool (the plan's 15); defaults to the recommendation's XI. */
  pool?: FplTeamRecommendationPlayer[];
  /** Ids on the plan's bench — shown dimmed, never the ZN Pick. */
  benchedIds?: Set<number>;
  /** The plan's vice; when given it replaces the best-remaining derivation. */
  viceId?: number | null;
}

const best = <T,>(xs: T[], score: (x: T) => number | undefined): T | undefined => {
  let top: T | undefined;
  let topScore = -Infinity;
  for (const x of xs) {
    const s = score(x);
    if (typeof s === "number" && s > topScore) {
      topScore = s;
      top = x;
    }
  }
  return top;
};

/** Everything the Captain Lab renders, from one recommendation + the user's goal and pick. */
export function buildCaptainLab(rec: FplTeamRecommendation, goal: CaptainGoal, manualCaptainId: number | null, opts: CaptainLabOptions = {}): CaptainLab {
  const benchedIds = opts.benchedIds ?? new Set<number>();
  const candidates = [...(opts.pool ?? rec.starting_xi)]
    .sort((a, b) => b.xpts - a.xpts)
    .slice(0, CANDIDATES)
    .map((p) => ({ ...toCandidate(p), benched: benchedIds.has(p.player_id) }));
  const eligible = candidates.filter((c) => !c.benched);

  const hasTop10k = candidates.some((c) => typeof c.eoTop10k === "number" || typeof c.rankGainIfHaul === "number");
  const hasOverall = candidates.some((c) => typeof c.ownershipPct === "number");
  const ownershipBasis: CaptainLab["ownershipBasis"] = hasTop10k ? "top10k" : hasOverall ? "overall" : null;
  const rankAware = ownershipBasis !== null;
  // The backend's total doubles its own suggested captain, who may sit outside
  // the top three (DGW logic server-side) — look across the whole XI for him.
  const suggestedPlayer =
    rec.starting_xi.find((p) => p.is_captain_suggested) ?? rec.starting_xi.find((p) => p.player_id === rec.captain_player_id);
  const suggested = eligible.find((c) => c.suggested) ?? eligible[0];
  const fallback = suggested ?? null;
  const own = (c: CaptainCandidate) => (ownershipBasis === "top10k" ? c.eoTop10k : c.ownershipPct);

  let zn: CaptainCandidate | undefined;
  if (ownershipBasis === "top10k") {
    // Rank swings and xPts ceilings are different units: compare swings only
    // among players that have one, and fall back to the ceiling only when none does.
    const anySwing = eligible.some((c) => typeof c.rankGainIfHaul === "number");
    zn = goal === "safe" ? best(eligible, (c) => c.eoTop10k) : best(eligible, (c) => (anySwing ? c.rankGainIfHaul : c.p90));
  } else if (ownershipBasis === "overall") {
    // No rank model: protect = ride the crowd; chase = the ceiling the fewest rivals share.
    zn =
      goal === "safe"
        ? best(eligible, (c) => c.ownershipPct)
        : best(eligible, (c) => (typeof c.p90 === "number" && typeof c.ownershipPct === "number" ? c.p90 * (1 - c.ownershipPct / 100) : undefined));
  }
  zn = zn ?? fallback ?? undefined;
  const znPickId = zn?.id ?? null;

  // The plan may captain someone outside the top three; honour any pool member.
  const manualInPool = manualCaptainId !== null ? (opts.pool ?? rec.starting_xi).find((p) => p.player_id === manualCaptainId) : undefined;
  const captain = candidates.find((c) => c.id === manualCaptainId) ?? (manualInPool ? toCandidate(manualInPool) : undefined) ?? zn;
  const captainId = captain?.id ?? null;
  const vice = best(candidates.filter((c) => c.id !== captainId), (c) => c.xpts);
  const viceId = opts.viceId !== undefined ? opts.viceId : vice?.id ?? null;

  const topXpts = candidates[0];
  let headline = "Pick your captain.";
  let subcopy = "Run ZN Pick to see the candidates.";
  if (zn) {
    const ownText = (c: CaptainCandidate) => {
      const v = own(c);
      if (typeof v !== "number") return null;
      return ownershipBasis === "top10k" ? `${Math.round(v)}% EO in the top 10k` : `${Math.round(v)}% owned overall`;
    };
    if (goal === "safe") {
      headline = `Protect your rank with ${zn.name}.`;
      const o = ownText(zn);
      subcopy = o
        ? `${zn.name} is the crowd's captain (${o}). Matching them limits your downside if he hauls.`
        : `${zn.name} is the highest projected captain. Without ownership data, the safe and chasing picks are the same.`;
    } else {
      headline = `Captain ${zn.name} to climb the ranks.`;
      const topOwn = topXpts ? ownText(topXpts) : null;
      if (topXpts && topXpts.id !== zn.id && topOwn) {
        subcopy = `${topXpts.name} projects higher, but ${topOwn} means a haul gains you little on the field. ${zn.name} offers the best upside for the risk.`;
      } else if (rankAware) {
        subcopy = `${zn.name} is the biggest rank swing if he hauls, and the field's favourite besides.`;
      } else {
        subcopy = `${zn.name} is the highest projected captain. Without ownership data, the safe and chasing picks are the same.`;
      }
    }
  }

  // The backend's total assumes its own suggested captain doubled; swap in ours.
  const base = rec.projected_points_with_captain;
  const projected =
    captain && suggestedPlayer && captain.id !== suggestedPlayer.player_id
      ? round1(base - suggestedPlayer.xpts + captain.xpts)
      : base;

  return { candidates, znPickId, captainId, viceId, headline, subcopy, rankAware, ownershipBasis, projected };
}
