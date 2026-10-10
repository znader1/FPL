import {
  CHIP_LABELS,
  type ChipPlanResponse,
  type FixtureDifficultyResponse,
  type FixtureTickerCell,
  type FplPosition,
  type FplSquad,
  type FplTeamRecommendation,
  type FplTeamRecommendationPlayer,
} from "@/lib/fplAssistantApi";

export type Fdr = 1 | 2 | 3 | 4 | 5;

const BAND_FDR: Record<string, Fdr> = { very_easy: 1, easy: 2, medium: 3, hard: 4, very_hard: 5 };

/** Ticker band → `--fdr-N`. The band is authoritative; the numeric score is the fallback. */
export function bandToFdr(band: string, difficulty?: number | null): Fdr {
  const fromBand = BAND_FDR[band];
  if (fromBand) return fromBand;
  if (typeof difficulty === "number" && Number.isFinite(difficulty)) {
    return Math.min(5, Math.max(1, Math.round(difficulty))) as Fdr;
  }
  return 3;
}

export interface PlannerFixture {
  opponent: string;
  isHome: boolean;
  fdr: Fdr;
}

export interface PlannerCell {
  gw: number;
  blank: boolean;
  fixtures: PlannerFixture[];
  count: number;
  /** Per-GW xPts from the recommendation's `fixtures_horizon`; undefined until it lands. */
  xpts?: number;
  inHorizon: boolean;
}

export interface PlannerRow {
  playerId: number;
  name: string;
  team: string;
  pos: FplPosition;
  isBench: boolean;
  isCaptain: boolean;
  cells: PlannerCell[];
  /** Sum of xPts over the in-horizon cells; null when no cell has xPts. */
  total: number | null;
  /** 8px between position groups, 14px before the bench. */
  gapBefore: 0 | 8 | 14;
}

const POS_ORDER: FplPosition[] = ["GKP", "DEF", "MID", "FWD"];
const round1 = (n: number) => Math.round(n * 10) / 10;

const cellFromTicker = (gw: number, t: FixtureTickerCell | undefined, inHorizon: boolean): PlannerCell => {
  if (!t || t.blank || t.opponents.length === 0) return { gw, blank: true, fixtures: [], count: 0, inHorizon };
  return {
    gw,
    blank: false,
    count: t.count || t.opponents.length,
    fixtures: t.opponents.map((o) => ({ opponent: o.opp_short, isHome: o.home, fdr: bandToFdr(o.band, o.difficulty) })),
    inHorizon,
  };
};

export interface BuildPlannerRowsInput {
  squad: FplSquad;
  ticker?: FixtureDifficultyResponse | null;
  gws: number[];
  horizon: number;
  recommendation?: FplTeamRecommendation | null;
}

/** The 15-row planner: starters by position, then the bench in order. Fixtures
 *  come from the team ticker (instant); per-GW xPts overlay from the
 *  recommendation's `fixtures_horizon` once that slower call lands. */
export function buildPlannerRows({ squad, ticker, gws, horizon, recommendation }: BuildPlannerRowsInput): PlannerRow[] {
  const tickerByTeam = new Map((ticker?.teams ?? []).map((t) => [t.team_short, t]));
  const recById = new Map<number, FplTeamRecommendationPlayer>();
  for (const p of [...(recommendation?.starting_xi ?? []), ...(recommendation?.bench ?? [])]) recById.set(p.player_id, p);
  const captainId = squad.captain_player_id ?? squad.starting_xi.find((p) => p.is_captain)?.player_id;

  const starters = [...squad.starting_xi].sort((a, b) => POS_ORDER.indexOf(a.pos) - POS_ORDER.indexOf(b.pos));
  const bench = [...squad.bench].sort((a, b) => a.bench_order - b.bench_order);
  const ordered: Array<{ p: FplTeamRecommendationPlayer; isBench: boolean }> = [
    ...starters.map((p) => ({ p, isBench: false })),
    ...bench.map((p) => ({ p, isBench: true })),
  ];

  let prevPos: FplPosition | null = null;
  let benchStarted = false;
  return ordered.map(({ p, isBench }) => {
    let gapBefore: 0 | 8 | 14 = 0;
    if (isBench && !benchStarted) {
      gapBefore = 14;
      benchStarted = true;
    } else if (!isBench && prevPos !== null && prevPos !== p.pos) {
      gapBefore = 8;
    }
    prevPos = p.pos;

    const horizonByGw = new Map<number, { xpts?: number; fixture_count?: number }>();
    const rp = recById.get(p.player_id);
    for (const h of rp?.fixtures_horizon ?? rp?.score_breakdown?.fixtures_horizon ?? []) horizonByGw.set(h.event_id, h);

    const team = tickerByTeam.get(p.team_short);
    const cells = gws.map((gw, i) => {
      const cell = cellFromTicker(gw, team?.gws[String(gw)], i < horizon);
      const h = horizonByGw.get(gw);
      if (h && typeof h.xpts === "number" && Number.isFinite(h.xpts)) cell.xpts = h.xpts;
      // No ticker row for the team: the player's own horizon still knows the count.
      if (!team && h && typeof h.fixture_count === "number") {
        cell.count = h.fixture_count;
        cell.blank = h.fixture_count === 0;
      }
      return cell;
    });

    const visible = cells.filter((c) => c.inHorizon && typeof c.xpts === "number");
    const total = visible.length ? round1(visible.reduce((s, c) => s + (c.xpts as number), 0)) : null;

    return {
      playerId: p.player_id,
      name: p.web_name,
      team: p.team_short,
      pos: p.pos,
      isBench,
      isCaptain: p.player_id === captainId,
      cells,
      total,
      gapBefore,
    };
  });
}

export type TotalTone = "hot" | "cold" | "neutral";

/** Pink above 6 xPts/GW, rose below 4.4, foreground otherwise. */
export function totalTone(avgPerGw: number | null): TotalTone {
  if (avgPerGw === null || !Number.isFinite(avgPerGw)) return "neutral";
  if (avgPerGw > 6) return "hot";
  if (avgPerGw < 4.4) return "cold";
  return "neutral";
}

export type ColumnTag = "DGW" | "BLANK" | null;

const BLANK_STARTERS_FOR_TAG = 3;

/** Column head tags. The chip plan's calendar is authoritative when it covers
 *  the GW; otherwise read the squad's own cells. */
export function columnTags({
  gws,
  rows,
  calendar,
}: {
  gws: number[];
  rows: PlannerRow[];
  calendar?: ChipPlanResponse["calendar"];
}): Array<{ gw: number; tag: ColumnTag }> {
  const calByGw = new Map((calendar ?? []).map((c) => [c.gw, c]));
  return gws.map((gw, i) => {
    const cal = calByGw.get(gw);
    if (cal) return { gw, tag: cal.has_dgw ? "DGW" : cal.is_blank_heavy ? "BLANK" : null };
    const doubles = rows.some((r) => (r.cells[i]?.count ?? 0) > 1);
    const blankStarters = rows.filter((r) => !r.isBench && r.cells[i]?.blank).length;
    return { gw, tag: doubles ? "DGW" : blankStarters >= BLANK_STARTERS_FOR_TAG ? "BLANK" : null };
  });
}

export interface WeakestLink {
  out: string;
  in: string;
  outX?: number;
  inX?: number;
  gain: number;
  price: number;
}

/** The verdict's moves plus runner-ups with a positive horizon gain, best first.
 *  `a → b xPts` only when the seller's horizon xPts is known (b = a + gain). */
export function weakestLinks(rec: FplTeamRecommendation | null | undefined, horizonXptsById: Record<number, number>): WeakestLink[] {
  const d = rec?.transfer_plan_horizon?.verdict_detail;
  if (!d) return [];
  const all = [...d.moves, ...(d.runner_ups ?? [])];
  return all
    .filter((m) => m.horizon_gain > 0)
    .sort((a, b) => b.horizon_gain - a.horizon_gain)
    .map((m) => {
      const outX = horizonXptsById[m.sell.id];
      const known = typeof outX === "number" && Number.isFinite(outX);
      return {
        out: m.sell.name,
        in: m.buy.name,
        outX: known ? outX : undefined,
        inX: known ? round1(outX + m.horizon_gain) : undefined,
        gain: m.horizon_gain,
        price: m.buy.price,
      };
    });
}

export interface ChipWindow {
  chip: ChipPlanResponse["recommendations"][number]["chip"];
  gw: number;
  label: string;
  reason: string;
  nudged: boolean;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** Chip plan recommendations that fall inside the displayed GWs, each prefixed
 *  with what the squad's own grid says about that week. No EV is recomputed here. */
export function chipWindowsInRange(plan: ChipPlanResponse | null | undefined, gws: number[], rows: PlannerRow[]): ChipWindow[] {
  if (!plan) return [];
  return plan.recommendations
    .filter((r) => gws.includes(r.event_id))
    .sort((a, b) => a.event_id - b.event_id)
    .map((r) => {
      const i = gws.indexOf(r.event_id);
      const doubles = rows.filter((row) => (row.cells[i]?.count ?? 0) > 1).length;
      const blankStarters = rows.filter((row) => !row.isBench && row.cells[i]?.blank).length;
      const benchPlaying = rows.filter((row) => row.isBench && !row.cells[i]?.blank).length;
      let count = "";
      if (r.chip === "bench_boost") {
        count = doubles > 0
          ? `${doubles} of your players have a double gameweek.`
          : `${benchPlaying} of ${rows.filter((row) => row.isBench).length} bench players have a fixture.`;
      } else if (r.chip === "free_hit" || r.chip === "wildcard") {
        if (blankStarters > 0) count = `${plural(blankStarters, "starter blanks", "starters blank")}.`;
      } else if (r.chip === "triple_captain" && doubles > 0) {
        count = `${doubles} of your players have a double gameweek.`;
      }
      const why = r.guidance ?? r.reasons[0] ?? "";
      return {
        chip: r.chip,
        gw: r.event_id,
        label: CHIP_LABELS[r.chip],
        reason: [count, why].filter(Boolean).join(" "),
        nudged: plan.nudge?.chip === r.chip && plan.nudge?.event_id === r.event_id,
      };
    });
}
