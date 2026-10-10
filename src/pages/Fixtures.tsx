import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarRange, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Navbar } from "@/components/layout/Navbar";
import { FixturePlannerGrid } from "@/components/FixturePlannerGrid";
import { PlannerRail } from "@/components/PlannerRail";
import { QueryErrorCard } from "@/components/QueryErrorCard";
import { useProfile } from "@/hooks/useProfile";
import {
  buildPlannerRows,
  chipWindowsInRange,
  columnTags,
  weakestLinks,
} from "@/lib/fixturePlanner";
import {
  fetchChipPlan,
  fetchFixtureDifficulty,
  fetchNextEvent,
  fetchSquad,
  fetchTeamRecommendation,
  type ChipPlanResponse,
  type FixtureDifficultyResponse,
  type FixtureTickerCell,
  type FplNextEventSummary,
  type FplSquad,
  type FplTeamRecommendation,
} from "@/lib/fplAssistantApi";

/** The grid always shows six columns; the toggle only decides how many count. */
const GRID_GWS = 6;
const HORIZONS = [3, 6] as const;
type Horizon = (typeof HORIZONS)[number];

const getInitialEntryId = () => {
  const fromQuery = Number(new URLSearchParams(window.location.search).get("entry_id"));
  if (Number.isFinite(fromQuery) && fromQuery > 0) return fromQuery;
  const fromStorage = Number(localStorage.getItem("fpl_entry_id"));
  if (Number.isFinite(fromStorage) && fromStorage > 0) return fromStorage;
  return 0;
};

const parseHorizon = (raw: string | null): Horizon => (raw === "3" ? 3 : 6);

/* ── Legacy all-teams ticker (kept behind a <details>) ───────────────────── */

const BAND_LEGEND: Array<{ label: string; color: string }> = [
  { label: "Very easy", color: "#1a9850" },
  { label: "Easy", color: "#66bd63" },
  { label: "Medium", color: "#fee08b" },
  { label: "Hard", color: "#f46d43" },
  { label: "Very hard", color: "#d73027" },
];
const cellTextColor = (color: string) => (color.toLowerCase() === "#fee08b" ? "#1f1f1f" : "#ffffff");

const TickerCell = ({ cell }: { cell: FixtureTickerCell }) => {
  if (cell.blank || cell.opponents.length === 0) {
    return (
      <td className="px-1 py-1 text-center">
        <div className="rounded-md bg-white/5 text-white/30 text-[11px] py-1.5">—</div>
      </td>
    );
  }
  return (
    <td className="px-1 py-1 text-center">
      <div className="flex flex-col gap-0.5">
        {cell.opponents.map((opp, i) => (
          <div
            key={`${opp.opp_id}-${i}`}
            className="rounded-md text-[11px] font-semibold py-1.5 leading-none"
            style={{ backgroundColor: opp.color, color: cellTextColor(opp.color) }}
            title={`Difficulty ${opp.difficulty} (${opp.band.replace("_", " ")})`}
          >
            {opp.opp_short} ({opp.home ? "H" : "A"})
          </div>
        ))}
      </div>
    </td>
  );
};

function AllTeamsTicker({ data }: { data: FixtureDifficultyResponse }) {
  return (
    <details className="mt-6 rounded-xl border border-border bg-card">
      <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-foreground">
        All teams
        <span className="ml-2 text-xs font-normal text-muted-foreground">xG-model difficulty, easiest run first</span>
      </summary>
      <div className="border-t border-border p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {BAND_LEGEND.map((b) => (
            <span key={b.label} className="flex items-center gap-1 text-[10px] text-white/60">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: b.color }} />
              {b.label}
            </span>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 text-xs text-muted-foreground">
                <th className="px-3 py-2 text-left font-medium">Team</th>
                {data.gws.map((gw) => (
                  <th key={gw} className="px-1 py-2 text-center font-medium">GW{gw}</th>
                ))}
                <th className="px-3 py-2 text-right font-medium">Avg</th>
              </tr>
            </thead>
            <tbody>
              {data.teams.map((team) => (
                <tr key={team.team_id} className="border-b border-white/5 last:border-0">
                  <td className="px-3 py-1 font-bold">{team.team_short}</td>
                  {data.gws.map((gw) => (
                    <TickerCell key={gw} cell={team.gws[String(gw)] ?? { opponents: [], difficulty: null, count: 0, blank: true }} />
                  ))}
                  <td className="px-3 py-1 text-right tabular-nums text-white/70">{team.avg_difficulty.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 text-sm">
          <div>
            <p className="text-xs text-muted-foreground mb-1">Easiest runs</p>
            <p className="font-semibold">{data.easiest_runs.join(" · ")}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground mb-1">Hardest runs</p>
            <p className="font-semibold">{data.hardest_runs.join(" · ")}</p>
          </div>
        </div>
        {data.meta && (
          <p className="mt-3 text-[11px] text-white/40">
            Model {data.meta.model}
            {data.meta.knowledge_as_of ? ` · knowledge file as of ${data.meta.knowledge_as_of}` : ""}
          </p>
        )}
      </div>
    </details>
  );
}

/* ── Planner page ──────────────────────────────────────────────────────────── */

const Fixtures = () => {
  const [entryId, setEntryId] = useState(getInitialEntryId);
  const { profile } = useProfile();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const horizon = parseHorizon(searchParams.get("h"));
  const setHorizon = (h: Horizon) => {
    const next = new URLSearchParams(searchParams);
    if (h === 6) next.delete("h");
    else next.set("h", String(h));
    setSearchParams(next, { replace: true });
  };

  useEffect(() => {
    if (entryId > 0) return;
    if (profile?.entryId && profile.entryId > 0) setEntryId(profile.entryId);
  }, [entryId, profile?.entryId]);

  const nextEventQuery = useQuery<FplNextEventSummary>({
    queryKey: ["next-event"],
    queryFn: ({ signal }) => fetchNextEvent(signal),
    staleTime: 5 * 60_000,
  });
  // Planning basis: the next deadline's GW. /squad substitutes the latest picks
  // for a GW that hasn't locked, which is exactly what a planner wants.
  const gw = nextEventQuery.data?.event_id ?? null;
  const hasEntry = entryId > 0;

  const squadQuery = useQuery<FplSquad>({
    queryKey: ["squad", entryId, gw],
    queryFn: ({ signal }) => fetchSquad({ entryId, eventId: gw as number }, signal),
    enabled: hasEntry && gw !== null,
  });
  const tickerQuery = useQuery<FixtureDifficultyResponse>({
    queryKey: ["fixture-difficulty", gw, GRID_GWS],
    queryFn: ({ signal }) => fetchFixtureDifficulty({ gw_start: gw as number, horizon_gws: GRID_GWS }, signal),
    enabled: gw !== null,
    staleTime: 30 * 60_000,
  });
  const chipPlanQuery = useQuery<ChipPlanResponse>({
    queryKey: ["chipPlan", entryId, gw],
    queryFn: ({ signal }) => fetchChipPlan(entryId, undefined, signal),
    enabled: hasEntry && gw !== null,
    staleTime: 5 * 60_000,
    retry: 1,
  });
  // The slow one (Fly cold start + optimiser). Keyed by horizon because the
  // backend computes per-GW xPts and the transfer verdict over that window.
  const recQuery = useQuery<FplTeamRecommendation>({
    queryKey: ["planner-rec", entryId, gw, horizon],
    queryFn: ({ signal }) =>
      fetchTeamRecommendation(
        { entryId, eventId: gw as number, horizonGws: horizon, chipStrategy: "none", includeTransfers: true, applyTransferCount: 0 },
        signal,
      ),
    enabled: hasEntry && gw !== null && squadQuery.isSuccess,
    staleTime: 10 * 60_000,
    retry: 1,
    // Flipping 3 ↔ 6 refires the slow call; the other horizon's answer already
    // holds per-GW xPts for every column, so keep the cells filled meanwhile.
    placeholderData: () => {
      const other = HORIZONS.find((h) => h !== horizon);
      return queryClient.getQueryData<FplTeamRecommendation>(["planner-rec", entryId, gw, other]);
    },
  });

  const gws = useMemo(() => {
    if (tickerQuery.data?.gws?.length) return tickerQuery.data.gws.slice(0, GRID_GWS);
    if (gw === null) return [];
    return Array.from({ length: GRID_GWS }, (_, i) => gw + i).filter((g) => g <= 38);
  }, [tickerQuery.data, gw]);

  const rows = useMemo(
    () =>
      squadQuery.data
        ? buildPlannerRows({ squad: squadQuery.data, ticker: tickerQuery.data, gws, horizon, recommendation: recQuery.data })
        : [],
    [squadQuery.data, tickerQuery.data, gws, horizon, recQuery.data],
  );
  const tags = useMemo(() => columnTags({ gws, rows, calendar: chipPlanQuery.data?.calendar }), [gws, rows, chipPlanQuery.data]);
  const chips = useMemo(() => chipWindowsInRange(chipPlanQuery.data, gws, rows), [chipPlanQuery.data, gws, rows]);
  const links = useMemo(() => {
    const byId: Record<number, number> = {};
    for (const r of rows) if (r.total !== null) byId[r.playerId] = r.total;
    return weakestLinks(recQuery.data, byId);
  }, [recQuery.data, rows]);

  const toggle = (
    <ToggleGroup
      type="single"
      value={String(horizon)}
      onValueChange={(v) => v && setHorizon(parseHorizon(v))}
      aria-label="Planning horizon"
      className="min-w-[160px] whitespace-nowrap rounded-lg border border-border bg-card p-0.5"
    >
      {HORIZONS.map((h) => (
        <ToggleGroupItem
          key={h}
          value={String(h)}
          className="h-7 flex-1 rounded-md px-3 text-xs font-semibold data-[state=on]:bg-primary data-[state=on]:text-white"
        >
          {h} GWs
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );

  // Both feeds gate the grid: squad-only would paint fifteen rows of "—".
  const loadingGrid = hasEntry && (nextEventQuery.isPending || squadQuery.isPending || tickerQuery.isPending);
  const recState = recQuery.isError ? "error" : recQuery.isSuccess && !recQuery.isPlaceholderData ? "ready" : "loading";

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar extras={toggle} />
      <div className="mx-auto max-w-[1280px] px-4 pt-20 pb-8">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-extrabold tracking-tight">
              <CalendarRange className="h-6 w-6 text-primary" />
              Fixture Planner
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Your 15 over the next {GRID_GWS} gameweeks — xPts per fixture, chip weeks and the weakest links to fix.
            </p>
          </div>
          <div className="lg:hidden">{toggle}</div>
        </div>

        {!hasEntry ? (
          <Card className="mx-auto max-w-sm p-8 text-center">
            <h3 className="mb-1 font-bold text-foreground">Link your FPL team</h3>
            <p className="mb-5 text-sm text-muted-foreground">The planner needs your squad. Link it on the Squad page first.</p>
            <Button asChild>
              <Link to="/app">Open squad</Link>
            </Button>
          </Card>
        ) : nextEventQuery.isError ? (
          <div className="mx-auto max-w-md">
            <QueryErrorCard
              title="Couldn't reach the FPL Assistant"
              message="The server may be waking up. Try again in a moment."
              onRetry={() => nextEventQuery.refetch()}
              retrying={nextEventQuery.isFetching}
            />
          </div>
        ) : nextEventQuery.isSuccess && gw === null ? (
          <Card className="mx-auto max-w-sm p-8 text-center">
            <h3 className="mb-1 font-bold text-foreground">Season hasn't started</h3>
            <p className="text-sm text-muted-foreground">No upcoming gameweek to plan for yet.</p>
          </Card>
        ) : squadQuery.isError ? (
          <div className="mx-auto max-w-md">
            <QueryErrorCard
              message={squadQuery.error instanceof Error ? squadQuery.error.message : String(squadQuery.error)}
              onRetry={() => squadQuery.refetch()}
              retrying={squadQuery.isFetching}
            />
          </div>
        ) : tickerQuery.isError ? (
          <div className="mx-auto max-w-md">
            <QueryErrorCard
              title="Couldn't load fixtures"
              message={tickerQuery.error instanceof Error ? tickerQuery.error.message : String(tickerQuery.error)}
              onRetry={() => tickerQuery.refetch()}
              retrying={tickerQuery.isFetching}
            />
          </div>
        ) : loadingGrid ? (
          <Card className="flex items-center justify-center gap-2 p-10 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading your squad and fixtures…
          </Card>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
            <Card className="overflow-x-auto p-4">
              <FixturePlannerGrid rows={rows} gws={gws} horizon={horizon} tags={tags} />
              {recQuery.isError && (
                <p className="mt-3 text-[11px] text-muted-foreground">
                  Per-GW xPts and totals need the recommendation engine, which didn't answer.{" "}
                  <button type="button" className="underline" onClick={() => recQuery.refetch()}>Retry</button>
                </p>
              )}
            </Card>
            <PlannerRail
              chips={chips}
              links={links}
              horizon={horizon}
              recommendationState={recState}
              onRetryRecommendation={() => recQuery.refetch()}
            />
          </div>
        )}

        {tickerQuery.data && hasEntry && <AllTeamsTicker data={tickerQuery.data} />}
      </div>
    </div>
  );
};

export default Fixtures;
