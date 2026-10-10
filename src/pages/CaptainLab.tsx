import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Navbar } from "@/components/layout/Navbar";
import { CaptainCard } from "@/components/CaptainCard";
import { QueryErrorCard } from "@/components/QueryErrorCard";
import { useProfile } from "@/hooks/useProfile";
import { buildCaptainLab, type CaptainGoal } from "@/lib/captainLab";
import { fmtGain } from "@/lib/format";
import {
  fetchNextEvent,
  fetchTeamRecommendation,
  type FplNextEventSummary,
  type FplTeamRecommendation,
} from "@/lib/fplAssistantApi";

const getInitialEntryId = () => {
  const fromQuery = Number(new URLSearchParams(window.location.search).get("entry_id"));
  if (Number.isFinite(fromQuery) && fromQuery > 0) return fromQuery;
  const fromStorage = Number(localStorage.getItem("fpl_entry_id"));
  if (Number.isFinite(fromStorage) && fromStorage > 0) return fromStorage;
  return 0;
};

const getInitialGoal = (): CaptainGoal => (localStorage.getItem("fpl_captain_goal") === "safe" ? "safe" : "chase");

/** Shares the planner's cache entry: same entry, GW and (default) horizon. */
const REC_HORIZON = 6;

const STEPS = ["Transfers", "Captain", "Bench", "Confirm"] as const;
const CURRENT_STEP = 1;

function Stepper({ transfersDone }: { transfersDone: boolean }) {
  return (
    <ol className="flex items-center gap-1.5" aria-label="Gameweek steps">
      {STEPS.map((label, i) => {
        const state = i < CURRENT_STEP ? (transfersDone ? "done" : "upcoming") : i === CURRENT_STEP ? "now" : "upcoming";
        return (
          <li key={label} className="flex items-center gap-1.5">
            <div
              aria-current={state === "now" ? "step" : undefined}
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${
                state === "now" ? "bg-primary/15 text-foreground" : state === "done" ? "text-foreground" : "text-muted-foreground"
              }`}
            >
              <span
                className={`flex h-[18px] w-[18px] items-center justify-center rounded-full text-[10px] font-bold text-white ${
                  state === "done" ? "bg-accent" : state === "now" ? "bg-primary" : "bg-muted"
                }`}
              >
                {state === "done" ? "✓" : i + 1}
              </span>
              {label}
            </div>
            {i < STEPS.length - 1 && <span aria-hidden className="h-px w-5 bg-border" />}
          </li>
        );
      })}
    </ol>
  );
}

const CaptainLab = () => {
  const [entryId, setEntryId] = useState(getInitialEntryId);
  const [goal, setGoal] = useState<CaptainGoal>(getInitialGoal);
  const [manualCaptainId, setManualCaptainId] = useState<number | null>(null);
  const { profile } = useProfile();

  useEffect(() => {
    if (entryId > 0) return;
    if (profile?.entryId && profile.entryId > 0) setEntryId(profile.entryId);
  }, [entryId, profile?.entryId]);

  useEffect(() => {
    try {
      localStorage.setItem("fpl_captain_goal", goal);
    } catch {
      // ignore
    }
  }, [goal]);

  const changeGoal = (g: CaptainGoal) => {
    setGoal(g);
    // Resetting the goal clears the manual pick (handoff state table).
    setManualCaptainId(null);
  };

  const nextEventQuery = useQuery<FplNextEventSummary>({
    queryKey: ["next-event"],
    queryFn: ({ signal }) => fetchNextEvent(signal),
    staleTime: 5 * 60_000,
  });
  const gw = nextEventQuery.data?.event_id ?? null;
  const hasEntry = entryId > 0;

  const recQuery = useQuery<FplTeamRecommendation>({
    queryKey: ["planner-rec", entryId, gw, REC_HORIZON],
    queryFn: ({ signal }) =>
      fetchTeamRecommendation(
        { entryId, eventId: gw as number, horizonGws: REC_HORIZON, chipStrategy: "none", includeTransfers: true, applyTransferCount: 0 },
        signal,
      ),
    enabled: hasEntry && gw !== null,
    staleTime: 10 * 60_000,
    retry: 1,
  });

  const lab = useMemo(
    () => (recQuery.data ? buildCaptainLab(recQuery.data, goal, manualCaptainId) : null),
    [recQuery.data, goal, manualCaptainId],
  );
  const verdict = recQuery.data?.transfer_plan_horizon?.verdict_detail;
  const transfersLine = verdict
    ? verdict.action === "roll"
      ? "Roll the free transfer"
      : verdict.moves.map((m) => `${m.sell.name} → ${m.buy.name}`).join(" + ")
    : "—";
  const name = (id: number | null) => lab?.candidates.find((c) => c.id === id)?.name ?? "—";

  const goalToggle = (
    <div className="flex flex-col items-end gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">Your goal this week</span>
      <ToggleGroup
        type="single"
        value={goal}
        onValueChange={(v) => (v === "safe" || v === "chase") && changeGoal(v)}
        aria-label="Captaincy goal"
        className="min-w-[280px] whitespace-nowrap rounded-lg border border-border bg-card p-0.5"
      >
        <ToggleGroupItem value="safe" className="h-8 flex-1 rounded-md px-3 text-xs font-semibold data-[state=on]:bg-primary data-[state=on]:text-white">
          Protect rank
        </ToggleGroupItem>
        <ToggleGroupItem value="chase" className="h-8 flex-1 rounded-md px-3 text-xs font-semibold data-[state=on]:bg-primary data-[state=on]:text-white">
          Chase rank
        </ToggleGroupItem>
      </ToggleGroup>
    </div>
  );

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <Navbar />
      <main className="relative flex-1 overflow-hidden px-6 pb-10 pt-[76px] sm:px-12">
        {/* Hero glow: 700×500 primary/22 blurred 120, top centre. */}
        <div
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-[-260px] h-[500px] w-[700px] -translate-x-1/2 rounded-full bg-primary/[0.22] blur-[120px]"
        />
        <div className="relative mx-auto max-w-[1184px]">
          {/* The mock put the stepper in the navbar, which had no tab strip; ours does,
              so the steps lead the page instead. */}
          <div className="mb-6 overflow-x-auto">
            <Stepper transfersDone={Boolean(verdict)} />
          </div>
          <div className="mb-7 flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[.08em] text-primary">Step 2 of 4 · Captain</p>
              <h1 className="max-w-[640px] text-[40px] font-black leading-[1.05] tracking-[-0.02em] text-foreground [text-wrap:pretty]">
                {lab?.headline ?? "Pick your captain."}
              </h1>
              <p className="mt-2.5 max-w-[600px] text-sm leading-relaxed text-muted-foreground">
                {lab?.subcopy ?? "Loading your squad's projections…"}
              </p>
              {lab && !lab.rankAware && (
                <p className="mt-2 text-xs text-muted-foreground/80">
                  Rank-aware picks need ownership data from the backend; until then both goals use the projection.
                </p>
              )}
            </div>
            {goalToggle}
          </div>

          {!hasEntry ? (
            <Card className="mx-auto max-w-sm p-8 text-center">
              <h3 className="mb-1 font-bold text-foreground">Link your FPL team</h3>
              <p className="mb-5 text-sm text-muted-foreground">The Captain Lab needs your squad. Link it on the Squad page first.</p>
              <Button asChild>
                <Link to="/app">Open squad</Link>
              </Button>
            </Card>
          ) : nextEventQuery.isError || recQuery.isError ? (
            <div className="mx-auto max-w-md">
              <QueryErrorCard
                title="Couldn't load your captain options"
                message="The recommendation engine didn't answer. It may be waking up."
                onRetry={() => (nextEventQuery.isError ? nextEventQuery.refetch() : recQuery.refetch())}
                retrying={nextEventQuery.isFetching || recQuery.isFetching}
              />
            </div>
          ) : nextEventQuery.isSuccess && gw === null ? (
            <Card className="mx-auto max-w-sm p-8 text-center">
              <h3 className="mb-1 font-bold text-foreground">Season hasn't started</h3>
              <p className="text-sm text-muted-foreground">No upcoming gameweek to captain for yet.</p>
            </Card>
          ) : !lab ? (
            <Card className="flex items-center justify-center gap-2 p-10 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Projecting your captain options…
            </Card>
          ) : (
            <div className="grid gap-[18px] md:grid-cols-3">
              {lab.candidates.map((c) => (
                <CaptainCard
                  key={c.id}
                  c={c}
                  selected={c.id === lab.captainId}
                  znPick={c.id === lab.znPickId}
                  onSelect={setManualCaptainId}
                  ownershipBasis={lab.ownershipBasis}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      <footer className="sticky bottom-0 mt-7 border-t border-border bg-card px-6 py-4 sm:px-12">
        <div className="mx-auto flex max-w-[1184px] flex-wrap items-center justify-between gap-6">
          <div className="flex flex-wrap items-center gap-7 text-[13px]">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">Transfers</div>
              <div data-testid="footer-transfers" className="mt-0.5 font-semibold text-foreground">
                {transfersLine}
                {verdict && verdict.action !== "roll" && <span className="text-accent"> {fmtGain(verdict.horizon_gain)}</span>}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">Captain</div>
              <div data-testid="footer-captain" className="mt-0.5 font-semibold text-foreground">{lab ? `${name(lab.captainId)} (C)` : "—"}</div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">Vice</div>
              <div data-testid="footer-vice" className="mt-0.5 font-semibold text-foreground">{lab ? `${name(lab.viceId)} (VC)` : "—"}</div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">Projected</div>
              <div data-testid="footer-projected" className="mt-0.5 font-extrabold tabular-nums text-primary">
                {lab ? `${lab.projected.toFixed(1)} pts` : "—"}
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <Button asChild variant="ghost">
              <Link to="/app">Back</Link>
            </Button>
            {/* The bench step isn't built yet; the Squad page's bench strip is where that lives today. */}
            <Button asChild>
              <Link to="/app">Next: bench order</Link>
            </Button>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default CaptainLab;
