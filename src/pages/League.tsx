import { useEffect, useMemo, useState } from "react";
import { Loader2, Trophy, Target, Shield, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Navbar } from "@/components/layout/Navbar";
import {
  fetchUserLeagues,
  fetchLeagueStrategy,
  type LeagueSummary,
  type LeagueStrategyMode,
  type LeagueStrategyResponse,
} from "@/lib/fplAssistantApi";
import { useEntitlement } from "@/hooks/useEntitlement";
import { getInitialEntryId } from "@/lib/entryId";


const MODES: Array<{ id: LeagueStrategyMode; label: string; icon: typeof Target; blurb: string }> = [
  { id: "chase", label: "Chase", icon: Target, blurb: "Catch rivals above by targeting their differentials" },
  { id: "defend", label: "Defend", icon: Shield, blurb: "Stay ahead of rivals below by matching their template" },
  { id: "differential", label: "Differential", icon: Zap, blurb: "High-EV picks no one in your league owns" },
];

const ownPct = (o: number | null | undefined): string =>
  o != null ? `${Math.round(o * 100)}%` : "?";

const playerLookup = (strategy: LeagueStrategyResponse) => {
  const map = new Map<
    number,
    { name: string; team: string; xpts: number | null; ownership: number | null; diffEv: number | null }
  >();
  for (const c of strategy.candidates) {
    map.set(c.id, {
      name: c.web_name ?? `#${c.id}`,
      team: c.team_short ?? "",
      xpts: c.model_xpts_horizon,
      ownership: c.league_ownership,
      diffEv: c.differential_ev ?? null,
    });
  }
  return map;
};

const League = () => {
  const [entryId, setEntryId] = useState(getInitialEntryId);
  const [entryInput, setEntryInput] = useState(String(getInitialEntryId() || ""));
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);
  const [leaguesLoading, setLeaguesLoading] = useState(false);
  const [leaguesError, setLeaguesError] = useState<string | null>(null);
  const [selectedLeagueId, setSelectedLeagueId] = useState<number | null>(null);
  const [mode, setMode] = useState<LeagueStrategyMode>("chase");
  const [strategy, setStrategy] = useState<LeagueStrategyResponse | null>(null);
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [strategyError, setStrategyError] = useState<string | null>(null);

  const { canUseLeagueDashboard } = useEntitlement();

  useEffect(() => {
    if (!entryId) return;
    let cancelled = false;
    setLeaguesLoading(true);
    setLeaguesError(null);
    fetchUserLeagues(entryId)
      .then((data) => {
        if (!cancelled) setLeagues(data.leagues);
      })
      .catch((err) => {
        if (!cancelled) setLeaguesError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLeaguesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [entryId]);

  const selectedLeague = useMemo(
    () => leagues.find((l) => l.id === selectedLeagueId),
    [leagues, selectedLeagueId]
  );

  // Gate: League strategy is only available to entitled users.
  // While BETA_ALL_ACCESS is true, this is unreachable.
  if (!canUseLeagueDashboard) {
    return (
      <div className="min-h-screen bg-background">
        <Navbar />
        <div className="pt-20 pb-8 px-4 text-center">
          <p className="text-muted-foreground">League strategy is part of a paid tier.</p>
        </div>
      </div>
    );
  }

  const runStrategy = async () => {
    if (!entryId || !selectedLeagueId) return;
    setStrategyLoading(true);
    setStrategyError(null);
    setStrategy(null);
    try {
      const result = await fetchLeagueStrategy({
        entry_id: entryId,
        league_id: selectedLeagueId,
        mode,
        horizon_gws: 3,
      });
      setStrategy(result);
      if (result.error) setStrategyError(result.error);
    } catch (err) {
      setStrategyError(err instanceof Error ? err.message : String(err));
    } finally {
      setStrategyLoading(false);
    }
  };

  const submitEntry = (e: React.FormEvent) => {
    e.preventDefault();
    const n = Number(entryInput);
    if (Number.isFinite(n) && n > 0) {
      setEntryId(n);
      localStorage.setItem("fpl_entry_id", String(n));
    }
  };

  const lookup = strategy ? playerLookup(strategy) : null;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />
      <div className="container mx-auto px-4 pt-20 pb-8 max-w-5xl">
        <div className="flex items-center gap-3 mb-6">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Trophy className="h-6 w-6 text-primary" />
            Mini-league strategy
          </h1>
          <Badge variant="outline" className="text-[10px]">Beta</Badge>
        </div>

        {!entryId && (
          <Card className="p-6 mb-6">
            <h2 className="font-semibold mb-2">Enter your FPL ID</h2>
            <p className="text-sm text-muted-foreground mb-4">
              We'll use it to find your leagues and rivals.
            </p>
            <form onSubmit={submitEntry} className="flex gap-2">
              <input
                type="number"
                aria-label="FPL team ID"
                value={entryInput}
                onChange={(e) => setEntryInput(e.target.value)}
                placeholder="e.g. 588004"
                className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              <Button type="submit">Continue</Button>
            </form>
          </Card>
        )}

        {entryId > 0 && (
          <>
            <Card className="p-6 mb-6">
              <div className="flex items-center justify-between mb-3">
                <h2 className="font-semibold">Your leagues</h2>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className="text-xs">Entry #{entryId}</Badge>
                  {/* The form above only renders when no ID is stored, so a
                      typo previously stranded the user on a failing fetch with
                      no way to correct it short of clearing localStorage. */}
                  <button
                    type="button"
                    onClick={() => {
                      setEntryInput(String(entryId));
                      setEntryId(0);
                      setSelectedLeagueId(null);
                      setStrategy(null);
                      localStorage.removeItem("fpl_entry_id");
                    }}
                    className="text-xs text-primary underline hover:text-primary/80"
                  >
                    Change
                  </button>
                </div>
              </div>
              {leaguesLoading && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" /> Fetching leagues…
                </div>
              )}
              {leaguesError && (
                <p className="text-sm text-destructive">{leaguesError}</p>
              )}
              {/* Without this the card rendered as a bare heading, leaving no
                  way to tell "no leagues" apart from a silent failure. */}
              {!leaguesLoading && !leaguesError && leagues.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No classic leagues found for this team ID. Join a mini-league in the
                  FPL app, or use Change above if the ID is wrong.
                </p>
              )}
              {!leaguesLoading && !leaguesError && leagues.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {leagues.map((l) => (
                    <button
                      key={l.id}
                      type="button"
                      onClick={() => setSelectedLeagueId(l.id)}
                      className={`text-left rounded-md border px-3 py-2 transition-colors ${
                        selectedLeagueId === l.id
                          ? "border-primary bg-primary/10"
                          : "border-border hover:bg-muted/50"
                      }`}
                    >
                      <div className="font-medium text-sm truncate">{l.name}</div>
                      <div className="text-xs text-muted-foreground">
                        Rank {l.entry_rank ?? "—"}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </Card>

            {selectedLeague && (
              <Card className="p-6 mb-6">
                <h2 className="font-semibold mb-3">Strategy mode</h2>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-4">
                  {MODES.map((m) => {
                    const Icon = m.icon;
                    const active = mode === m.id;
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => setMode(m.id)}
                        className={`text-left rounded-md border px-3 py-3 transition-colors ${
                          active ? "border-primary bg-primary/10" : "border-border hover:bg-muted/50"
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <Icon className="h-4 w-4" />
                          <span className="font-medium text-sm">{m.label}</span>
                        </div>
                        <p className="text-xs text-muted-foreground">{m.blurb}</p>
                      </button>
                    );
                  })}
                </div>
                <Button onClick={runStrategy} disabled={strategyLoading} className="w-full sm:w-auto">
                  {strategyLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Analyzing…
                    </>
                  ) : (
                    `Run ${mode} strategy`
                  )}
                </Button>
              </Card>
            )}

            {strategyError && !strategyLoading && (
              <Card className="p-4 mb-6 border-destructive">
                <p className="text-sm text-destructive">{strategyError}</p>
              </Card>
            )}

            {strategy && !strategyLoading && (
              <Card className="p-6 space-y-5">
                <div>
                  <div className="flex items-baseline justify-between mb-1">
                    <h2 className="font-semibold">{strategy.league.name}</h2>
                    <span className="text-xs text-muted-foreground capitalize">{strategy.mode} mode</span>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    You: rank {strategy.user.rank} ({strategy.user.total} pts)
                  </p>
                </div>

                {strategy.captain_differential && (
                  <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4">
                    <div className="mb-1.5 flex items-center gap-2">
                      <Zap className="h-4 w-4 text-amber-500" />
                      <span className="text-xs font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
                        Captain differential
                      </span>
                    </div>
                    <p className="text-sm leading-snug">{strategy.captain_differential.reason}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                      <span className="text-muted-foreground">Consensus</span>
                      <Badge variant="outline">
                        {strategy.captain_differential.consensus_captain.web_name} ·{" "}
                        {ownPct(strategy.captain_differential.consensus_captain.league_ownership)} own
                      </Badge>
                      <span className="text-muted-foreground">→ Differential</span>
                      <Badge className="border-amber-500/40 bg-amber-500/20 text-amber-700 hover:bg-amber-500/30 dark:text-amber-300">
                        {strategy.captain_differential.alternative.web_name} ·{" "}
                        {ownPct(strategy.captain_differential.alternative.league_ownership)} own
                      </Badge>
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                  {strategy.rivals_above.length > 0 && (
                    <div>
                      <h3 className="text-xs uppercase text-muted-foreground mb-1">Above you</h3>
                      <ul className="space-y-1">
                        {strategy.rivals_above.map((r) => (
                          <li key={r.entry_id} className="flex justify-between">
                            <span>{r.player_name}</span>
                            <span className="text-muted-foreground">
                              #{r.rank} · {r.total} pts
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {strategy.rivals_below.length > 0 && (
                    <div>
                      <h3 className="text-xs uppercase text-muted-foreground mb-1">Below you</h3>
                      <ul className="space-y-1">
                        {strategy.rivals_below.map((r) => (
                          <li key={r.entry_id} className="flex justify-between">
                            <span>{r.player_name}</span>
                            <span className="text-muted-foreground">
                              #{r.rank} · {r.total} pts
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {strategy.narrative && !strategy.narrative.error && (
                  <div className="space-y-4 border-t border-border pt-4">
                    {strategy.narrative.headline && (
                      <p className="font-semibold text-sm leading-snug">{strategy.narrative.headline}</p>
                    )}

                    {strategy.narrative.recommended_targets && strategy.narrative.recommended_targets.length > 0 && (
                      <ul className="space-y-2">
                        {strategy.narrative.recommended_targets.map((t, i) => {
                          const meta = lookup?.get(t.player_id);
                          return (
                            <li key={i} className="flex gap-3 items-start">
                              <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold text-primary">
                                {i + 1}
                              </div>
                              <div>
                                <span className="font-medium text-sm">
                                  {(t as { name?: string }).name ?? meta?.name ?? `#${t.player_id}`}
                                  {meta?.team && <span className="text-xs text-muted-foreground ml-1.5">{meta.team}</span>}
                                  {meta?.xpts != null && <span className="text-xs text-primary ml-1.5">{meta.xpts.toFixed(1)} xPts</span>}
                                  {meta?.diffEv != null && (
                                    <span className="text-xs text-amber-600 dark:text-amber-400 ml-1.5">
                                      {meta.diffEv >= 0 ? "+" : ""}
                                      {meta.diffEv.toFixed(1)} diff-EV
                                    </span>
                                  )}
                                  {meta?.ownership != null && (
                                    <span className="text-xs text-muted-foreground ml-1.5">{ownPct(meta.ownership)} own</span>
                                  )}
                                </span>
                                <p className="text-xs text-muted-foreground mt-0.5">{t.rationale}</p>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    )}

                    {strategy.narrative.watchouts && (
                      <p className="text-xs text-muted-foreground border-l-2 border-yellow-500/40 pl-2">
                        ⚠ {strategy.narrative.watchouts}
                      </p>
                    )}

                    {strategy.narrative.model && (
                      <p className="text-[10px] text-muted-foreground/40">
                        {strategy.narrative.model}
                      </p>
                    )}
                  </div>
                )}

                {strategy.narrative?.error && (
                  <p className="text-sm text-destructive border-t border-border pt-4">
                    Narrative unavailable: {strategy.narrative.error}
                  </p>
                )}
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default League;
