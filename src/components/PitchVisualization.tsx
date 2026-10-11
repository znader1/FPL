import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { PlayerCard, type Player } from "./PlayerCard";
import { GameweekNav } from "./GameweekNav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Search } from "lucide-react";
import { findIncomingPlayers } from "@/lib/incomingPlayers";
import {
  CHIP_LABELS,
  type ChipName,
  type FplSquad,
  type FplTeamFixture,
  type FplTeamRecommendation,
  type FplTeamRecommendationBenchPlayer,
  type FplTeamRecommendationPlayer,
} from "@/lib/fplAssistantApi";

type PitchTeam = FplSquad | FplTeamRecommendation;

interface PitchVisualizationProps {
  entryId?: number;
  onEntryIdSubmit?: (raw: string) => Promise<string | null>;
  team?: PitchTeam;
  requestedGw: number;
  onRequestedGwChange: (gw: number) => void;
  gwSelectable: boolean;
  isLoading?: boolean;
  errorMessage?: string;
  /** Informational (non-error) notice — e.g. the backend substituted the latest
   *  available squad because the requested GW's picks don't exist yet. */
  substitutionNotice?: string;
  fixturesByTeam?: Record<string, FplTeamFixture[]>;
  pitchMode?: "squad" | "recommendation";
  onPitchModeChange?: (mode: "squad" | "recommendation") => void;
  hasRecommendation?: boolean;
  isLiveGw?: boolean;
  /** Timestamp of the last successful squad fetch; shown while a GW is live. */
  updatedAt?: number | null;
  /** True when the rendered squad's real scores belong to the GW being viewed. */
  showActualPoints?: boolean;
  /** Optional action rendered next to the Squad / ZN Pick tabs (e.g. Optimize my squad). */
  headerAction?: ReactNode;
  /** v2 flow: incoming players by id (gain, or null when unknown). Overrides the
   *  payload-derived map, which a plan-built squad can't carry. */
  incoming?: Record<number, number | null>;
  /** v2 flow bench step: outline valid swap targets, dim invalid ones. */
  starterState?: (playerId: number) => "valid" | "invalid" | undefined;
  onStarterClick?: (playerId: number) => void;
  /** Bench step: no GW bar, heading or legend — just the turf. */
  compact?: boolean;
  /** Bench step lists the bench itself; don't draw the strip under the pitch. */
  hideBench?: boolean;
}

export const getRowGapClass = (count: number) => {
  if (count >= 6) return "gap-0.5 sm:gap-1";
  if (count === 5) return "gap-1 sm:gap-3";
  if (count === 4) return "gap-2 sm:gap-5";
  if (count === 3) return "gap-4 sm:gap-6";
  if (count === 2) return "gap-6 sm:gap-10";
  return "gap-2 sm:gap-4";
};

const round1 = (value: number) => Math.round(value * 10) / 10;
const chipLabel = (value?: string | null) => {
  if (!value) return "";
  return Object.prototype.hasOwnProperty.call(CHIP_LABELS, value) ? CHIP_LABELS[value as ChipName] : value;
};

const parseNextFixturesLabel = (label?: string): Player["fixture"] | undefined => {
  if (typeof label !== "string") return undefined;
  const trimmed = label.trim();
  if (!trimmed) return undefined;

  const difficultyMatch = trimmed.match(/\(D([1-5])\)/i);
  const difficulty = difficultyMatch ? Number(difficultyMatch[1]) : undefined;

  const isHome = trimmed.startsWith("H-") ? true : trimmed.startsWith("A-") ? false : undefined;
  const opponentMatch = trimmed.match(/^[HA]-([A-Z]{2,4})/);
  const opponent = opponentMatch?.[1] ?? "";

  return {
    label: trimmed,
    opponent,
    isHome,
    difficulty,
  };
};

const getCaptainIds = (team: PitchTeam) => {
  const captainFromId = typeof team.captain_player_id === "number" ? team.captain_player_id : undefined;
  const viceFromId = typeof team.vice_player_id === "number" ? team.vice_player_id : undefined;

  if ("horizon_gws" in team) {
    const all = [...team.starting_xi, ...team.bench];
    const captainSuggested = all.find((p) => p.is_captain_suggested)?.player_id;
    const viceSuggested = all.find((p) => p.is_vice_suggested)?.player_id;
    return {
      captainId: captainSuggested ?? captainFromId,
      viceId: viceSuggested ?? viceFromId,
    };
  }

  const captainFromFlags = team.starting_xi.find((p) => p.is_captain)?.player_id;
  const viceFromFlags = team.starting_xi.find((p) => p.is_vice_captain)?.player_id;
  return {
    captainId: captainFromId ?? captainFromFlags,
    viceId: viceFromId ?? viceFromFlags,
  };
};

const toPitchPlayer = (
  player: FplTeamRecommendationPlayer,
  captainId?: number,
  viceId?: number,
  fixture?: Player["fixture"],
  isLiveGw = false,
  showActualPoints = false,
  inGain?: number,
): Player => ({
  id: player.player_id,
  // The glow reads xPts this GW; it's only legible on the pitch, so the bench
  // never gets one. Starters pass `aura` where they're rendered below.
  inGain,
  name: player.web_name,
  team: player.team_short,
  teamName: player.team_name,
  points: player.xpts,
  // Only surface a real score when it belongs to the gameweek on screen. A
  // future GW renders the substituted latest squad, whose points are an earlier
  // gameweek's — showing them here reads as "your GW3 score", which is wrong.
  livePoints: showActualPoints ? player.event_points : undefined,
  isLiveGw,
  fixture,
  isCaptain: typeof captainId === "number" && player.player_id === captainId,
  isViceCaptain: typeof viceId === "number" && player.player_id === viceId,
  alerts: player.alerts,
  scoreBreakdown: player.score_breakdown,
});

const toBenchPlayer = (
  player: FplTeamRecommendationBenchPlayer,
  captainId?: number,
  viceId?: number,
  fixture?: Player["fixture"],
  isLiveGw = false,
  showActualPoints = false,
): Player => ({
  ...toPitchPlayer(player, captainId, viceId, fixture, isLiveGw, showActualPoints),
  number: player.bench_order,
});

const computeTeamPoints = (team: PitchTeam) => {
  if ("projected_points_with_captain" in team && typeof team.projected_points_with_captain === "number") {
    return team.projected_points_with_captain;
  }
  return team.starting_xi.reduce((sum, p) => sum + p.xpts * p.multiplier, 0);
};

const getActualGwPoints = (team: PitchTeam) => {
  if (!("entry_history" in team)) return undefined;
  const history = team.entry_history;
  if (!history || typeof history !== "object") return undefined;
  const points = history.points;
  return typeof points === "number" && Number.isFinite(points) ? points : undefined;
};

const getDisplayedTeam = (team: PitchTeam): PitchTeam => {
  if (!("horizon_gws" in team)) return team;
  const applied = team.transfer_application?.applied ?? 0;
  if (applied > 0 && team.squad_with_transfers) return team.squad_with_transfers;
  return team;
};

const formatRank = (value?: number) => {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  try {
    return value.toLocaleString();
  } catch {
    return String(Math.round(value));
  }
};

export const PitchVisualization = ({
  entryId,
  onEntryIdSubmit,
  team,
  requestedGw,
  onRequestedGwChange,
  gwSelectable,
  isLoading = false,
  errorMessage,
  substitutionNotice,
  fixturesByTeam,
  pitchMode = "squad",
  onPitchModeChange,
  hasRecommendation = false,
  isLiveGw = false,
  updatedAt = null,
  showActualPoints = false,
  headerAction,
  incoming: incomingProp,
  starterState,
  onStarterClick,
  compact = false,
  hideBench = false,
}: PitchVisualizationProps) => {
  const [draftId, setDraftId] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const hasTeam = Boolean(team);
  const recommendationTeam = team && "horizon_gws" in team ? team : undefined;
  const chipInfo = recommendationTeam?.chip_strategy;
  const chipName = chipLabel(chipInfo?.selected);
  const chipPlayGw = chipInfo?.play_event_id;
  const displayedTeam = useMemo(() => (team ? getDisplayedTeam(team) : undefined), [team]);
  const { captainId, viceId } = useMemo(
    () => (displayedTeam ? getCaptainIds(displayedTeam) : { captainId: undefined, viceId: undefined }),
    [displayedTeam]
  );

  const gwPoints = useMemo(() => {
    if (!displayedTeam) return 0;
    const points = computeTeamPoints(displayedTeam);
    return Number.isFinite(points) ? round1(points) : 0;
  }, [displayedTeam]);
  const actualGwPoints = useMemo(() => {
    if (!displayedTeam) return undefined;
    const points = getActualGwPoints(displayedTeam);
    return typeof points === "number" ? round1(points) : undefined;
  }, [displayedTeam]);
  const displayedPoints = recommendationTeam ? gwPoints : actualGwPoints ?? gwPoints;
  const displayedRank = useMemo(() => {
    if (!team || !("entry_history" in team)) return "—";
    const overallRank = team.entry_history?.overall_rank;
    return formatRank(overallRank);
  }, [team]);

  const { goalkeeper, defenders, midfielders, forwards } = useMemo(() => {
    const starting = displayedTeam?.starting_xi ?? [];
    return {
      goalkeeper: starting.filter((p) => p.pos === "GKP"),
      defenders: starting.filter((p) => p.pos === "DEF"),
      midfielders: starting.filter((p) => p.pos === "MID"),
      forwards: starting.filter((p) => p.pos === "FWD"),
    };
  }, [displayedTeam]);

  const bench = useMemo(() => {
    return [...(displayedTeam?.bench ?? [])].sort((a, b) => a.bench_order - b.bench_order);
  }, [displayedTeam]);
  const incomingFromTeam = useMemo(() => (team ? findIncomingPlayers(team) : {}), [team]);
  const incoming = incomingProp ?? incomingFromTeam;
  const teamName = team?.entry?.team_name ?? undefined;

  const starter = (player: FplTeamRecommendationPlayer): Player => ({
    ...toPitchPlayer(player, captainId, viceId, getFixtureForPlayer(player), isLiveGw, showActualPoints, incoming[player.player_id]),
    aura: true,
  });

  // Bench step: a bench row is selected, so every starter is either a valid
  // swap target (teal outline, tappable) or not (dimmed; a tap explains why).
  const Starter = ({ player }: { player: FplTeamRecommendationPlayer }) => {
    const state = starterState?.(player.player_id);
    const swapping = Boolean(starterState);
    return (
      <div
        data-testid={`starter-${player.player_id}`}
        data-swap={state}
        onClick={swapping && onStarterClick ? () => onStarterClick(player.player_id) : undefined}
        className={`rounded-xl transition-[opacity,box-shadow] duration-200 ${
          state === "valid"
            ? "cursor-pointer shadow-[0_0_0_2px_hsl(var(--accent))]"
            : state === "invalid"
              ? "cursor-not-allowed opacity-[.35]"
              : ""
        } ${swapping ? "[&_*]:pointer-events-none" : ""}`}
      >
        <PlayerCard player={starter(player)} />
      </div>
    );
  };

  const getFixtureForTeam = (teamShort: string): Player["fixture"] | undefined => {
    const fixtures = fixturesByTeam?.[teamShort];
    if (!fixtures || fixtures.length === 0) return undefined;
    const primary = fixtures[0];
    const extraCount = fixtures.length - 1;
    return {
      opponent: primary.opponent_short,
      isHome: primary.is_home,
      difficulty: primary.difficulty,
      extraCount: extraCount > 0 ? extraCount : undefined,
    };
  };

  const getFixtureForPlayer = (player: FplTeamRecommendationPlayer): Player["fixture"] | undefined => {
    // Prefer live per-GW fixtures fetch — always reflects the GW being viewed.
    // Fall back to the baked-in next_fixtures label only if fixtures haven't loaded yet.
    const fromLive = getFixtureForTeam(player.team_short);
    if (fromLive) return fromLive;
    return parseNextFixturesLabel(player.next_fixtures);
  };

  return (
    // min-h-0 pairs with overflow-y-auto so this scrolls internally instead of
    // growing past its share of the flex column now that it's nested one level
    // deeper (under the banner/nudge stacking wrapper in Index.tsx) rather than
    // being a direct flex-row child — without it, the default flex min-height:auto
    // would let content push past the available height instead of scrolling.
    <div className="flex-1 min-w-0 lg:min-h-0 p-2 sm:p-4 lg:overflow-y-auto">
      <div className="w-full max-w-3xl mx-auto">

        {/* Squad / ZN Pick toggle. Rendered inside the gameweek bar rather than
            above it: two stacked control strips cost ~60px of vertical space,
            which is the difference between the bench being on screen or not on
            a 14" laptop. */}
        {errorMessage && (
          <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            <p>Failed to load from backend. Showing last loaded data.</p>
            <p className="mt-1 text-xs opacity-80">{errorMessage}</p>
          </div>
        )}

        {substitutionNotice && (
          <div className="mb-4 rounded-lg border border-border bg-muted/50 px-4 py-3 text-sm text-muted-foreground">
            {substitutionNotice}
          </div>
        )}

        {!compact && (
        <GameweekNav
          leading={
            onPitchModeChange ? (
              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => onPitchModeChange("squad")}
                  className={`px-3 py-1 rounded-lg text-sm font-semibold transition-all ${
                    pitchMode === "squad"
                      ? "bg-primary text-white shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  Squad
                </button>
                <button
                  onClick={() => hasRecommendation && onPitchModeChange("recommendation")}
                  disabled={!hasRecommendation}
                  className={`px-3 py-1 rounded-lg text-sm font-semibold transition-all ${
                    pitchMode === "recommendation"
                      ? "bg-primary text-white shadow-sm"
                      : hasRecommendation
                        ? "text-muted-foreground hover:text-foreground"
                        : "text-muted-foreground/30 cursor-not-allowed"
                  }`}
                >
                  ZN Pick
                </button>
                {chipInfo?.is_active && chipName && (
                  <span className="ml-1 px-2 py-0.5 rounded-md bg-accent/15 text-accent text-xs font-semibold">
                    {chipName}
                  </span>
                )}
              </div>
            ) : undefined
          }
          action={headerAction}
          currentGW={requestedGw}
          totalGW={38}
          points={displayedPoints}
          rank={displayedRank}
          onPrev={() => gwSelectable && onRequestedGwChange(Math.max(1, requestedGw - 1))}
          onNext={() => gwSelectable && onRequestedGwChange(Math.min(38, requestedGw + 1))}
          navEnabled={gwSelectable}
          onSelectGW={(gw) => gwSelectable && onRequestedGwChange(gw)}
          isRecommendation={Boolean(recommendationTeam)}
          isLiveGw={isLiveGw}
          updatedAt={updatedAt}
        />
        )}

        {hasTeam && !compact && (
          <div className="mb-3 flex items-end justify-between gap-3 px-1">
            {teamName ? (
              <h2 className="truncate text-xl font-extrabold tracking-tight text-foreground">{teamName}</h2>
            ) : (
              <span />
            )}
            <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
              <span
                aria-hidden
                className="h-2.5 w-2.5 rounded-full"
                style={{ background: "radial-gradient(circle, hsl(var(--primary)) 0, transparent 70%)" }}
              />
              Glow = xPts this GW
            </div>
          </div>
        )}

        {/* Pitch height follows the viewport instead of a fixed 600px. On a 14"
            laptop the fixed height pushed the bench below the fold; on a large
            monitor it left the pitch stranded at 600px with dead space around
            it. The clamp keeps it playable at both ends. */}
        <div
          className="relative mx-auto w-full max-w-[700px] rounded-2xl overflow-hidden
                     px-2 py-3 sm:px-3 sm:py-4
                     min-h-[clamp(420px,56vh,680px)] flex flex-col justify-between gap-2"
          style={{
            // Mown stripes: eight bands rather than four, and a horizontal
            // lighting gradient over the top so it reads as turf under
            // floodlights rather than a flat CSS gradient.
            backgroundImage: `linear-gradient(90deg,
                hsl(0 0% 0% / 0.18) 0%,
                hsl(0 0% 0% / 0) 25%,
                hsl(0 0% 100% / 0.04) 50%,
                hsl(0 0% 0% / 0) 75%,
                hsl(0 0% 0% / 0.18) 100%),
              repeating-linear-gradient(180deg,
                hsl(var(--pitch)) 0,
                hsl(var(--pitch)) 12.5%,
                hsl(var(--pitch-dark)) 12.5%,
                hsl(var(--pitch-dark)) 25%)`,
          }}
        >
          {/* Pitch markings. Purely decorative, so hidden from assistive tech
              and pinned behind the players. */}
          <div aria-hidden className="pointer-events-none absolute inset-0 z-0">
            {/* Touchlines */}
            <div className="absolute inset-2 sm:inset-3 rounded-lg border border-white/10" />
            {/* Penalty area + six-yard box, top and bottom. Shallow enough to sit
                above the goalkeeper's label and below the forwards' — a marking
                that crosses a player card reads as a misaligned box, not a pitch. */}
            <div className="absolute left-1/2 -translate-x-1/2 top-2 sm:top-3 h-[9%] w-[58%] border border-t-0 border-white/10" />
            <div className="absolute left-1/2 -translate-x-1/2 top-2 sm:top-3 h-[4%] w-[26%] border border-t-0 border-white/10" />
            <div className="absolute left-1/2 -translate-x-1/2 bottom-2 sm:bottom-3 h-[9%] w-[58%] border border-b-0 border-white/10" />
            <div className="absolute left-1/2 -translate-x-1/2 bottom-2 sm:bottom-3 h-[4%] w-[26%] border border-b-0 border-white/10" />
          </div>
          {/* Entry ID prompt overlay — shown when no valid ID is set */}
          {onEntryIdSubmit && (!entryId || entryId <= 0) && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm rounded-2xl">
              <div className="bg-card border border-border rounded-2xl p-8 w-full max-w-sm mx-4 text-center shadow-xl">
                <Search className="h-8 w-8 text-primary mx-auto mb-3" />
                <h3 className="font-bold text-foreground mb-1">Link your FPL team</h3>
                <p className="text-sm text-muted-foreground mb-1">
                  On the FPL site, open <span className="font-medium text-foreground">Points</span> —
                  your team URL looks like:
                </p>
                <p className="text-xs font-mono text-muted-foreground mb-5 break-all">
                  fantasy.premierleague.com/entry/<span className="text-primary font-bold">588004</span>/event/38
                </p>
                <form
                  className="flex gap-2"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    if (submitting) return;
                    setSubmitting(true);
                    setSubmitError(null);
                    const error = await onEntryIdSubmit(draftId);
                    setSubmitting(false);
                    if (error) setSubmitError(error);
                  }}
                >
                  <Input
                    type="text"
                    inputMode="numeric"
                    placeholder="Team ID or full URL"
                    value={draftId}
                    onChange={(e) => setDraftId(e.target.value)}
                    className="flex-1"
                    autoFocus
                  />
                  <Button
                    type="submit"
                    disabled={submitting}
                    className="bg-primary text-white hover:bg-primary/90 shrink-0"
                  >
                    {submitting ? "Checking…" : "Load"}
                  </Button>
                </form>
                {submitError && (
                  <p className="mt-3 text-xs text-destructive">{submitError}</p>
                )}
                <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="h-px flex-1 bg-border" />
                  or
                  <span className="h-px flex-1 bg-border" />
                </div>
                <Button asChild variant="outline" className="w-full">
                  <Link to="/app/squad-picker">No team yet? Draft my squad →</Link>
                </Button>
              </div>
            </div>
          )}

          {/* Centre circle, spot and halfway line */}
          <div aria-hidden className="pointer-events-none absolute inset-0 z-0">
            <div className="absolute left-2 right-2 sm:left-3 sm:right-3 top-1/2 h-px bg-white/10" />
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-[14%] aspect-square rounded-full border border-white/10" />
          </div>

          {!hasTeam ? (
            <div className="relative z-10 flex flex-1 flex-col items-center justify-between py-4">
              {[1, 4, 4, 2].map((count, row) => (
                <div key={row} className="flex justify-center gap-4">
                  {Array.from({ length: count }).map((_, i) => (
                    <Skeleton key={i} className="h-20 w-16 rounded-md bg-white/10" />
                  ))}
                </div>
              ))}
            </div>
          ) : (
            <>
              {/* Goalkeeper */}
              <div className="flex justify-center relative z-10">
                {goalkeeper.map((player) => (
                  <Starter key={player.player_id} player={player} />
                ))}
              </div>

              {/* Defenders */}
              <div className={`flex justify-center ${getRowGapClass(defenders.length)} relative z-10`}>
                {defenders.map((player) => (
                  <Starter key={player.player_id} player={player} />
                ))}
              </div>

              {/* Midfielders */}
              <div className={`flex justify-center ${getRowGapClass(midfielders.length)} relative z-10`}>
                {midfielders.map((player) => (
                  <Starter key={player.player_id} player={player} />
                ))}
              </div>

              {/* Forwards */}
              <div className={`flex justify-center ${getRowGapClass(forwards.length)} relative z-10`}>
                {forwards.map((player) => (
                  <Starter key={player.player_id} player={player} />
                ))}
              </div>
            </>
          )}
        </div>

        {/* Bench */}
        {hasTeam && !hideBench && (
          <div className="mx-auto mt-3 w-full max-w-[700px] px-3 py-2 rounded-xl bg-card border border-border">
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-[.08em]">Bench</p>
              {isLoading && <p className="text-[10px] text-muted-foreground">Updating…</p>}
            </div>
            <div className="flex flex-wrap justify-center gap-2 sm:gap-4">
              {bench.map((player) => (
                <PlayerCard
                  key={player.player_id}
                  player={{
                    ...toBenchPlayer(player, captainId, viceId, getFixtureForPlayer(player), isLiveGw, showActualPoints),
                    inGain: incoming[player.player_id],
                  }}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
