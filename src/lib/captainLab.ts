import type { FplTeamRecommendation, FplTeamRecommendationPlayer } from "@/lib/fplAssistantApi";

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

/** `H-BOU(D2)` → parts; undefined when the label is empty or unrecognised. */
export function parseFixtureLabel(label?: string | null): CaptainFixture | undefined {
  if (!label) return undefined;
  const m = label.trim().match(/^([HA])-([A-Z]{2,4})(?:\(D([1-5])\))?/i);
  if (!m) return undefined;
  return { opponent: m[2].toUpperCase(), isHome: m[1].toUpperCase() === "H", difficulty: m[3] ? Number(m[3]) : undefined };
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
  };
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
export function buildCaptainLab(rec: FplTeamRecommendation, goal: CaptainGoal, manualCaptainId: number | null): CaptainLab {
  const candidates = [...rec.starting_xi]
    .sort((a, b) => b.xpts - a.xpts)
    .slice(0, CANDIDATES)
    .map(toCandidate);

  const hasTop10k = candidates.some((c) => typeof c.eoTop10k === "number" || typeof c.rankGainIfHaul === "number");
  const hasOverall = candidates.some((c) => typeof c.ownershipPct === "number");
  const ownershipBasis: CaptainLab["ownershipBasis"] = hasTop10k ? "top10k" : hasOverall ? "overall" : null;
  const rankAware = ownershipBasis !== null;
  const suggested = candidates.find((c) => c.suggested) ?? candidates[0];
  const fallback = suggested ?? null;
  const own = (c: CaptainCandidate) => (ownershipBasis === "top10k" ? c.eoTop10k : c.ownershipPct);

  let zn: CaptainCandidate | undefined;
  if (ownershipBasis === "top10k") {
    zn = goal === "safe" ? best(candidates, (c) => c.eoTop10k) : best(candidates, (c) => c.rankGainIfHaul ?? c.p90);
  } else if (ownershipBasis === "overall") {
    // No rank model: protect = ride the crowd; chase = the ceiling the fewest rivals share.
    zn =
      goal === "safe"
        ? best(candidates, (c) => c.ownershipPct)
        : best(candidates, (c) => (typeof c.p90 === "number" && typeof c.ownershipPct === "number" ? c.p90 * (1 - c.ownershipPct / 100) : undefined));
  }
  zn = zn ?? fallback ?? undefined;
  const znPickId = zn?.id ?? null;

  const captain = candidates.find((c) => c.id === manualCaptainId) ?? zn;
  const captainId = captain?.id ?? null;
  const vice = best(candidates.filter((c) => c.id !== captainId), (c) => c.xpts);
  const viceId = vice?.id ?? null;

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
    captain && suggested && captain.id !== suggested.id ? round1(base - suggested.xpts + captain.xpts) : base;

  return { candidates, znPickId, captainId, viceId, headline, subcopy, rankAware, ownershipBasis, projected };
}
