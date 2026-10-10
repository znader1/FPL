import { useState } from "react";
import { JerseyIcon } from "./JerseyIcon";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import type { FplPlayerAlert, FplPlayerScoreBreakdown } from "@/lib/fplAssistantApi";

export interface PlayerFixture {
  label?: string;
  opponent?: string;
  isHome?: boolean;
  difficulty?: number;
  extraCount?: number;
}

export interface Player {
  id: number;
  name: string;
  team: string;
  teamName?: string;
  price?: number;
  points: number;
  livePoints?: number | null;
  isLiveGw?: boolean;
  number?: number;
  isCaptain?: boolean;
  isViceCaptain?: boolean;
  fixture?: PlayerFixture;
  alerts?: FplPlayerAlert[];
  scoreBreakdown?: FplPlayerScoreBreakdown;
  /** Command Center: radial xPts glow behind the jersey, sized from `points`. */
  aura?: boolean;
  /** Command Center: this-GW gain of the move that brought the player in ("IN +2.4"). */
  inGain?: number;
}

interface PlayerCardProps {
  player: Player;
}

/** Aura diameter in px: 30 + xPts × 11 (handoff spec), so a 2-pointer barely glows
 *  and an 8-pointer floods the row. */
const auraSizePx = (xpts: number) => Math.round(30 + Math.max(0, xpts) * 11);

const formatPoints = (points: number) => {
  if (!Number.isFinite(points)) return "—";
  if (Number.isInteger(points)) return points.toString();
  return points.toFixed(2).replace(/\.?0+$/, "");
};

const formatPercent = (value?: number | null) =>
  typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "—";

const getDifficultyClass = (difficulty?: number) => {
  switch (difficulty) {
    case 1:
      return "bg-emerald-500/15 text-emerald-800 dark:text-emerald-200";
    case 2:
      return "bg-emerald-500/10 text-emerald-800 dark:text-emerald-200";
    case 3:
      return "bg-amber-500/15 text-amber-900 dark:text-amber-200";
    case 4:
      return "bg-rose-500/15 text-rose-900 dark:text-rose-200";
    case 5:
      return "bg-rose-500/25 text-rose-900 dark:text-rose-200";
    default:
      return "bg-muted/60 text-muted-foreground";
  }
};

const formatMetric = (value?: number | null, digits = 1) => {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(digits).replace(/\.?0+$/, "");
};

const getAlertTone = (severity?: string) => {
  switch (severity) {
    case "high":
      return "bg-rose-500/15 text-rose-700";
    case "medium":
      return "bg-amber-500/15 text-amber-700";
    case "info":
      return "bg-sky-500/15 text-sky-700";
    default:
      return "bg-muted text-muted-foreground";
  }
};

const getObjectiveLabel = (objectiveScoreCol?: string | null) => {
  if (objectiveScoreCol === "wildcard_score") return "Wildcard draft score";
  if (objectiveScoreCol) return objectiveScoreCol.replace(/_/g, " ");
  return "Lineup score";
};

export const PlayerCard = ({ player }: PlayerCardProps) => {
  const [open, setOpen] = useState(false);
  const fixture = player.fixture;
  const alerts = Array.isArray(player.alerts) ? player.alerts.filter((item) => item.text) : [];
  // Actual points are shown whenever the payload has them -- not only during a
  // live gameweek. A finished GW has real scores too, and gating on `isLiveGw`
  // meant browsing back to GW1 fell through to a projection (or to "—" when the
  // squad payload carries no projection at all).
  const hasActualPoints =
    typeof player.livePoints === "number" && Number.isFinite(player.livePoints);
  const hasProjectedPoints = Number.isFinite(player.points);
  const displayPoints = hasActualPoints ? player.livePoints! : player.points;
  const isLiveScore = hasActualPoints && Boolean(player.isLiveGw);
  const breakdown = player.scoreBreakdown;
  const components = breakdown?.components;
  const distribution = breakdown?.distribution;
  const wildcard = breakdown?.wildcard;
  const recentForm = breakdown?.recent_form;
  const baseline = breakdown?.baseline;
  const objectiveScore = wildcard?.score ?? breakdown?.objective_score ?? breakdown?.horizon_xpts;
  const weightedFutureXpts = wildcard?.weighted_xpts ?? breakdown?.horizon_xpts;
  const dgwBonus = wildcard?.future_dgw_bonus ?? 0;
  const captaincyBonus = wildcard?.captaincy_bonus ?? 0;
  const fixtureDifficulty =
    fixture && typeof fixture.difficulty === "number" && Number.isFinite(fixture.difficulty)
      ? fixture.difficulty
      : undefined;
  const fixtureMeta =
    fixture && typeof fixture.extraCount === "number" && fixture.extraCount > 0
      ? `+${fixture.extraCount}`
      : "";

  const fixtureShort = fixture
    ? fixture.label ??
      `${fixture.isHome === false ? "A-" : fixture.isHome === true ? "H-" : ""}${fixture.opponent ?? ""}${
        fixtureDifficulty ? `(D${fixtureDifficulty})` : ""
      }`
    : undefined;

  return (
    // Controlled so a tap can open it: HoverCard only responds to pointer
    // hover, which touch devices never fire, leaving the whole score
    // breakdown unreachable on a phone despite the cursor-pointer affordance.
    <HoverCard openDelay={120} open={open} onOpenChange={setOpen}>
      <HoverCardTrigger asChild>
        <div
          className="flex flex-col items-center gap-0.5 group cursor-pointer"
          role="button"
          tabIndex={0}
          aria-expanded={open}
          aria-label={`${player.name} — score breakdown`}
          onClick={() => setOpen((prev) => !prev)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setOpen((prev) => !prev);
            }
          }}
        >
          <div className="relative transition-transform group-hover:scale-110">
            {player.aura && hasProjectedPoints && (
              <div
                data-testid="xpts-aura"
                aria-hidden="true"
                className="pointer-events-none absolute left-1/2 top-[22px] -z-10 -translate-x-1/2 -translate-y-1/2 rounded-full"
                style={{
                  width: `${auraSizePx(player.points)}px`,
                  height: `${auraSizePx(player.points)}px`,
                  background: "radial-gradient(circle, hsl(var(--primary) / 0.55) 0%, hsl(var(--primary) / 0) 68%)",
                }}
              />
            )}
            {typeof player.inGain === "number" && (
              <div className="absolute -top-3.5 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-full bg-accent px-1.5 py-px text-[10px] font-bold text-white shadow-sm">
                IN {player.inGain < 0 ? "−" : "+"}{Math.abs(player.inGain).toFixed(1)}
              </div>
            )}
            <JerseyIcon
              team={player.team}
              number={player.number}
              size="md"
              isCaptain={player.isCaptain}
            />
            {player.isViceCaptain && (
              <div className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-muted-foreground flex items-center justify-center text-[8px] font-bold text-background border border-background">
                V
              </div>
            )}
            {alerts.length > 0 && (
              <div className="absolute -bottom-1 -right-1 min-w-4 h-4 rounded-full bg-amber-500 text-[9px] font-bold text-white flex items-center justify-center border border-background px-1">
                {alerts.length}
              </div>
            )}
          </div>
          {/* Width is responsive because the pitch clips: a five-defender row
              needs 5 cards plus 4 gaps to fit ~343px of usable width on a
              375px viewport, so 80px cards cut the outermost players in half. */}
          <div className="bg-card/95 backdrop-blur-sm rounded-md px-1 sm:px-2 py-0.5 text-center shadow-sm border border-border w-[58px] sm:w-auto sm:min-w-[80px] max-w-full">
            <p className="text-[10px] sm:text-xs font-bold text-foreground truncate">{player.name}</p>
            {fixtureShort && (
              <span
                className={`inline-block px-1 sm:px-1.5 py-0.5 rounded-full text-[9px] font-medium max-w-full truncate ${getDifficultyClass(fixtureDifficulty)}`}
                title={fixtureDifficulty ? `FDR ${fixtureDifficulty}` : undefined}
              >
                {fixtureShort}
                {fixtureMeta ? ` ${fixtureMeta}` : ""}
              </span>
            )}
            <div className="flex justify-center gap-1 text-[10px] mt-0.5">
              {!fixtureShort && (
                <span className="text-muted-foreground">{player.team}</span>
              )}
              {hasActualPoints ? (
                <>
                  <span
                    className={
                      isLiveScore
                        ? "font-semibold text-emerald-400"
                        : "font-semibold text-foreground"
                    }
                    title={isLiveScore ? "Live points" : "Final points"}
                  >
                    {formatPoints(displayPoints)}
                  </span>
                  {hasProjectedPoints && (
                    <>
                      <span className="text-muted-foreground/60">·</span>
                      <span className="text-muted-foreground/70" title="Projected points">
                        {formatPoints(player.points)}
                      </span>
                    </>
                  )}
                </>
              ) : (
                <span className="font-semibold text-primary">{formatPoints(player.points)}</span>
              )}
            </div>
          </div>
        </div>
      </HoverCardTrigger>
      <HoverCardContent className="w-96 space-y-3" align="center" sideOffset={10}>
        <div>
          <p className="text-sm font-semibold text-foreground">{player.name}</p>
          <p className="text-xs text-muted-foreground">{player.teamName ?? player.team}</p>
        </div>

        {distribution && (
          <div className="space-y-1 rounded-md border border-border bg-card px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Likely Return
            </p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <p>Most likely: <span className="font-semibold text-foreground">{distribution.modal_points ?? "—"} pts</span></p>
              <p>80% range: <span className="font-semibold text-foreground">
                {distribution.p80_low ?? "—"}–{distribution.p80_high ?? "—"} pts
              </span></p>
              <p>Returns (6+): <span className="font-semibold text-foreground">{formatPercent(distribution.p_return_6)}</span></p>
              <p>Haul (10+): <span className="font-semibold text-foreground">{formatPercent(distribution.p_haul_10)}</span></p>
            </div>
            <p className="pt-1 text-[11px] text-muted-foreground">
              xPts is an average. This is the spread behind it — nobody scores 2.3.
            </p>
          </div>
        )}

        {components && (
          <div className="space-y-1 rounded-md border border-border bg-card px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Model Chances
            </p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <p>To score: <span className="font-semibold text-foreground">{formatPercent(components.p_goal)}</span></p>
              <p>To assist: <span className="font-semibold text-foreground">{formatPercent(components.p_assist)}</span></p>
              <p>Clean sheet: <span className="font-semibold text-foreground">{formatPercent(components.p_clean_sheet)}</span></p>
              <p>Plays 60&apos;: <span className="font-semibold text-foreground">{formatPercent(components.p_60)}</span></p>
              <p>Exp. goals: <span className="font-semibold text-foreground">{formatMetric(components.exp_goals, 2)}</span></p>
              <p>Exp. minutes: <span className="font-semibold text-foreground">{formatMetric(components.exp_minutes, 0)}</span></p>
            </div>
            <p className="pt-1 text-[11px] text-muted-foreground">
              From the xG model, worth {formatMetric(components.model_exp_points, 2)} pts on its own. The
              headline xPts blends this with the points-per-game baseline, so the two differ.
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-md bg-muted/50 px-2 py-1.5">
            <p className="text-muted-foreground">Selected GW xPts</p>
            <p className="font-semibold text-foreground">{formatMetric(breakdown?.current_gw_xpts)}</p>
          </div>
          <div className="rounded-md bg-muted/50 px-2 py-1.5">
            <p className="text-muted-foreground">Horizon xPts</p>
            <p className="font-semibold text-foreground">{formatMetric(breakdown?.horizon_xpts)}</p>
          </div>
          <div className="col-span-2 rounded-md bg-muted/50 px-2 py-1.5">
            <p className="text-muted-foreground">{getObjectiveLabel(breakdown?.objective_score_col)}</p>
            <p className="font-semibold text-foreground">
              {formatMetric(objectiveScore, 2)}
            </p>
          </div>
        </div>

        {(recentForm || baseline) && (
          <details className="group">
            <summary className="cursor-pointer list-none text-[11px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground">
              Model inputs
              <span className="ml-1 font-normal normal-case opacity-60 group-open:hidden">— show</span>
              <span className="ml-1 font-normal normal-case opacity-60 hidden group-open:inline">— hide</span>
            </summary>
            <div className="mt-2 space-y-2">
              {breakdown?.objective_explanation && (
                <p className="text-xs text-muted-foreground">{breakdown.objective_explanation}</p>
              )}
        {recentForm && (
          <div className="space-y-1 rounded-md border border-border bg-card px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Recent Form Input</p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <p>Window: <span className="font-semibold text-foreground">{recentForm.window_gws ?? "—"} GWs</span></p>
              <p>Samples: <span className="font-semibold text-foreground">{recentForm.samples ?? "—"}</span></p>
              <p>Avg points: <span className="font-semibold text-foreground">{formatMetric(recentForm.avg_points, 2)}</span></p>
              <p>Avg minutes: <span className="font-semibold text-foreground">{formatMetric(recentForm.avg_minutes, 1)}</span></p>
              <p>Last GW used: <span className="font-semibold text-foreground">{recentForm.last_gw ?? "—"}</span></p>
              <p>History file through: <span className="font-semibold text-foreground">{recentForm.history_max_gw ?? "—"}</span></p>
            </div>
          </div>
        )}

        {baseline && (
          <div className="space-y-1 rounded-md border border-border bg-card px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Projection Baseline</p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <p>Long-term: <span className="font-semibold text-foreground">{formatMetric(baseline.long_term, 2)}</span></p>
              <p>Recent GW avg: <span className="font-semibold text-foreground">{formatMetric(baseline.recent_gw, 2)}</span></p>
              <p>Blended base: <span className="font-semibold text-foreground">{formatMetric(baseline.blended, 2)}</span></p>
              <p>GW32/GW start base: <span className="font-semibold text-foreground">{formatMetric(baseline.gw1_after_ep_next_blend, 2)}</span></p>
            </div>
          </div>
        )}

            </div>
          </details>
        )}

        {(breakdown?.objective_score_col === "wildcard_score" || breakdown?.wildcard) && (
          <div className="space-y-1 rounded-md border border-border bg-card px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Wildcard Score</p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <p>Score: <span className="font-semibold text-foreground">{formatMetric(objectiveScore, 2)}</span></p>
              <p>Weighted xPts: <span className="font-semibold text-foreground">{formatMetric(weightedFutureXpts, 2)}</span></p>
              <p>DGW bonus: <span className="font-semibold text-foreground">{formatMetric(dgwBonus, 2)}</span></p>
              <p>Captaincy: <span className="font-semibold text-foreground">{formatMetric(captaincyBonus, 2)}</span></p>
            </div>
            <div className="space-y-1 pt-1 text-[11px] text-muted-foreground">
              <p>Base score comes from future projected xPts across the wildcard window.</p>
              <p>DGW bonus only appears when a later gameweek has more than one fixture.</p>
              <p>Captaincy bonus mainly rewards premium MID/FWD options, so many defenders or cheaper mids stay at 0.</p>
            </div>
          </div>
        )}

        {alerts.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Flags</p>
            <div className="space-y-1">
              {alerts.slice(0, 3).map((alert, index) => (
                <div
                  key={`${alert.category ?? "flag"}-${index}`}
                  className={`rounded-md px-2 py-1.5 text-xs ${getAlertTone(alert.severity)}`}
                >
                  {alert.text}
                </div>
              ))}
            </div>
          </div>
        )}

        {Array.isArray(breakdown?.fixtures_horizon) && breakdown.fixtures_horizon.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Upcoming Window</p>
            <div className="space-y-1">
              {breakdown.fixtures_horizon.slice(0, 3).map((item) => (
                <div key={`gw-${item.event_id}`} className="grid grid-cols-[64px_1fr_auto] items-center gap-2 text-xs">
                  <span className="text-muted-foreground">GW {item.event_id}</span>
                  <span className="font-medium text-foreground">{item.fixtures || "—"}</span>
                  <span className="text-primary font-semibold">
                    {formatMetric(item.xpts, 1)}
                    {typeof item.fixture_count === "number" && item.fixture_count > 1 ? ` · x${item.fixture_count}` : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </HoverCardContent>
    </HoverCard>
  );
};
