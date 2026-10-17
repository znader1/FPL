// Squad drafter: simple style-first form on top, expert knobs under the
// Advanced collapse. Live at /app/squad-picker; backend routes need
// SQUAD_PICKER_MODE=1.
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, Info, Loader2 } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  buildSquad, getPlayers, optimizeLineup, getGkPairs,
  type SquadBuildParams, type SquadBuildResult, type SquadPlayer, type TeamNudge,
  type PoolPlayer, type LineupResult, type GkPair,
} from "@/lib/squadPickerApi";
import { applyStyle, detectStyle, type SquadStyle } from "@/lib/squadPresets";
import { pairBudgetGap } from "@/lib/draftPitch";
import { findGems } from "@/lib/gems";
import { DRAFT_STORAGE_KEY, parseDraft, serializeDraft } from "@/lib/squadDraft";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TeamStrengthGrid } from "@/components/TeamStrengthGrid";
import { PlayerListPanel } from "@/components/PlayerListPanel";
import { PlayerKnowledgePanel } from "@/components/PlayerKnowledgePanel";
import { TransferPlanPanel } from "@/components/TransferPlanPanel";
import { SquadHandoffPanel } from "@/components/SquadHandoffPanel";
import { DraftPitch } from "@/components/DraftPitch";
import { Navbar } from "@/components/layout/Navbar";

const FORMATIONS = ["3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"];

const STYLE_OPTIONS: { value: SquadStyle; label: string; hint: string }[] = [
  { value: "balanced", label: "Balanced", hint: "even mix of form and underlying xG" },
  { value: "attacking", label: "Attacking", hint: "chase xG upside, accept variance" },
  { value: "safe", label: "Safe picks", hint: "fit, nailed starters on proven form" },
];

const QUOTA: Record<SquadPlayer["pos"], number> = { GKP: 2, DEF: 5, MID: 5, FWD: 3 };

const DEFAULTS: SquadBuildParams = {
  horizon_gws: 5, budget_m: 100, objective: "wildcard", projection_basis: "blend",
  blend_weight: 0.5, minutes_prior_k: 500, include_flagged: false,
  min_chance_of_playing: 0, max_per_team: 3, min_fwd_minutes: 0, min_minutes: 600,
  formation: "auto", fdr_strength: 1.0, home_away_strength: 1.0, xi_objective: "horizon",
};

/** A build result that may also carry the fields only /squad-picker/lineup returns. */
type DraftResult = SquadBuildResult &
  Partial<Omit<LineupResult, keyof SquadBuildResult>>;

export default function SquadPicker() {
  // Draft survives reloads: hydrate once from localStorage, save on change below.
  const [storedDraft] = useState(() =>
    parseDraft(localStorage.getItem(DRAFT_STORAGE_KEY))
  );
  const [params, setParams] = useState<SquadBuildParams>(() => ({
    ...DEFAULTS,
    ...(storedDraft?.params ?? {}),
  }));
  const [teamNudges, setTeamNudges] = useState<TeamNudge[]>(
    () => storedDraft?.teamNudges ?? []
  );
  const [squadIds, setSquadIds] = useState<number[]>(
    () => storedDraft?.squadIds ?? []
  );
  // Last legal result drives the display; an illegal edit shows violations but
  // keeps the last valid squad/XI on screen until it's legal again.
  // lineupMutation writes a LineupResult into this state while the build
  // mutation writes a SquadBuildResult, so it holds a build result that may
  // additionally carry the lineup-only fields. A plain union doesn't work
  // (reading an optional field off a union requires it on every member).
  const [lastGood, setLastGood] = useState<DraftResult | null>(
    () => storedDraft?.lastGood ?? null
  );
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const style = detectStyle(params);

  const poolQuery = useQuery({
    queryKey: ["squad-pool", params, teamNudges],
    queryFn: () => getPlayers({ ...params, team_nudges: teamNudges }),
    enabled: false,
  });

  const mutation = useMutation<SquadBuildResult, Error, SquadBuildParams>({
    mutationFn: buildSquad,
    onSuccess: (r) => {
      if (r.ok) {
        setLastGood(r);
        setSquadIds(r.squad.map((p) => p.player_id));
        poolQuery.refetch();
      }
    },
  });

  const lineupMutation = useMutation<LineupResult, Error, number[]>({
    mutationFn: (ids) => optimizeLineup(ids, { ...params, team_nudges: teamNudges }),
    onSuccess: (d) => { if (d.valid) setLastGood(d); },
  });

  const gkPairsMutation = useMutation<{ pairs: GkPair[] }, Error, void>({
    mutationFn: () => getGkPairs({ ...params, team_nudges: teamNudges }),
  });

  // Re-optimize the XI whenever the 15 changes (debounced).
  useEffect(() => {
    if (squadIds.length === 0) return;
    const t = setTimeout(() => lineupMutation.mutate(squadIds), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [squadIds, params.xi_objective]);

  // Persist the draft so a page reload (or the FPL-site round-trip) keeps it.
  useEffect(() => {
    if (squadIds.length === 0 && !lastGood) return;
    localStorage.setItem(
      DRAFT_STORAGE_KEY,
      serializeDraft({ params, teamNudges, squadIds, lastGood })
    );
  }, [params, teamNudges, squadIds, lastGood]);

  // A hydrated draft needs the player pool for the swap list.
  useEffect(() => {
    if (storedDraft && storedDraft.squadIds.length > 0) poolQuery.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const res = lastGood;
  const xiIds = new Set((res?.starting_xi ?? []).map((p) => p.player_id));

  const pool = poolQuery.data?.players ?? [];
  const byId = useMemo(() => new Map(pool.map((p) => [p.player_id, p])), [pool]);
  const current = useMemo(
    () => squadIds.map((id) => byId.get(id)).filter(Boolean) as PoolPlayer[],
    [squadIds, byId]);

  const canAdd = (p: PoolPlayer) => {
    if (squadIds.includes(p.player_id)) return { ok: false, reason: "Already in squad" };
    if (squadIds.length >= 15) return { ok: false, reason: "Squad full (15)" };
    if (current.filter((x) => x.pos === p.pos).length >= QUOTA[p.pos])
      return { ok: false, reason: `${p.pos} full` };
    if (current.filter((x) => x.team_id === p.team_id).length >= (params.max_per_team ?? 3))
      return { ok: false, reason: `Max ${params.max_per_team ?? 3} from team` };
    const cost = current.reduce((s, x) => s + x.price_m, 0) + p.price_m;
    if (cost > (params.budget_m ?? 100)) return { ok: false, reason: "Over budget" };
    return { ok: true as const };
  };
  const addPlayer = (id: number) =>
    setSquadIds((s) => (s.length < 15 && !s.includes(id) ? [...s, id] : s));
  const removePlayer = (id: number) => setSquadIds((s) => s.filter((x) => x !== id));
  const set = <K extends keyof SquadBuildParams>(k: K, v: SquadBuildParams[K]) =>
    setParams((p) => ({ ...p, [k]: v }));

  const invalid = lineupMutation.data && !lineupMutation.data.valid ? lineupMutation.data : null;

  // Squad players resolved for display: prefer the live pool (reflects manual
  // swaps and has fixtures), fall back to the built squad for hydrated drafts
  // whose pool hasn't loaded.
  const pitchSquad = useMemo(() => {
    const fromRes = new Map((res?.squad ?? []).map((p) => [p.player_id, p]));
    return squadIds
      .map((id) => byId.get(id) ?? fromRes.get(id))
      .filter(Boolean) as (PoolPlayer | SquadPlayer)[];
  }, [squadIds, byId, res]);

  const handoffSquad = pitchSquad.length === 15 ? pitchSquad : null;

  const gems = useMemo(() => findGems(pool), [pool]);

  // Budget left for the two GKs = budget minus the current 13 outfielders.
  const outfieldCostM = useMemo(
    () => pitchSquad.filter((p) => p.pos !== "GKP").reduce((s, p) => s + p.price_m, 0),
    [pitchSquad]
  );

  // Uses pitchSquad (not the pool) so hydrated drafts still find the old GKs,
  // and re-checks affordability so a stale render can't apply an over-budget pair.
  const applyGkPair = (pair: GkPair) => {
    if (pairBudgetGap(pair.combined_cost_m, outfieldCostM, params.budget_m ?? 100) > 0) return;
    const gkIds = pitchSquad.filter((p) => p.pos === "GKP").map((p) => p.player_id);
    setSquadIds((s) => [...s.filter((id) => !gkIds.includes(id)), ...pair.player_ids]);
  };

  const revertToLastValid = () => {
    if (!lastGood?.squad?.length) return;
    setSquadIds(lastGood.squad.map((p) => p.player_id));
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />
      <div className="mx-auto max-w-6xl p-4 pt-20 space-y-4">
      <div>
        <h1 className="text-xl font-bold">Draft your squad</h1>
        <p className="text-sm text-muted-foreground">
          Auto-pick a 15 for your budget and style, then tweak it player by player.
        </p>
      </div>

      <Card className="p-4 space-y-4">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Budget (£m)">
            <Input type="number" step={0.1} className="w-28" value={params.budget_m}
              onChange={(e) => set("budget_m", e.target.value === "" ? undefined : Number(e.target.value))} />
          </Field>
          <div className="space-y-1">
            <Label className="text-xs">Style</Label>
            <div className="flex flex-wrap gap-2">
              {STYLE_OPTIONS.map((o) => (
                <Button
                  key={o.value}
                  type="button"
                  size="sm"
                  variant={style === o.value ? "default" : "outline"}
                  title={o.hint}
                  onClick={() => setParams((p) => applyStyle(p, o.value))}
                >
                  {o.label}
                </Button>
              ))}
              {style === "custom" && (
                <span className="self-center text-xs text-muted-foreground">
                  Custom — advanced settings edited
                </span>
              )}
            </div>
          </div>
          <Field label="Formation"
            hint="Auto lets the optimizer pick the best legal shape for your 15 (usually strongest). Fix a formation only if you have a strong preference — it can cost projected points.">
            <select className="w-32 rounded-md border bg-background p-2 text-sm"
              value={params.formation ?? "auto"}
              onChange={(e) => set("formation", e.target.value)}>
              <option value="auto">Auto (best)</option>
              {FORMATIONS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </Field>
          <Button
            className="ml-auto"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate({ ...params, team_nudges: teamNudges })}
          >
            {mutation.isPending ? "Drafting…" : "⚡ Draft my squad"}
          </Button>
        </div>
        {style !== "custom" && (
          <p className="text-xs text-muted-foreground">
            {STYLE_OPTIONS.find((o) => o.value === style)?.hint}
          </p>
        )}
      </Card>

      <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen} className="space-y-4">
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="text-muted-foreground">
            <ChevronDown
              className={`h-4 w-4 mr-1 transition-transform ${advancedOpen ? "rotate-180" : ""}`}
            />
            Advanced settings
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-4">
      <Card className="p-4 space-y-4">
        <div>
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Draft rules
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Field label="Horizon (GWs)"
              hint="How many upcoming gameweeks the draft optimizes for. Short (3) chases immediate fixtures; long (8) favours season-keepers.">
              <Input type="number" min={1} max={8} value={params.horizon_gws}
                onChange={(e) => set("horizon_gws", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
            <Field label="Objective"
              hint="wildcard = balanced multi-GW squad (default). free_hit = maximize next GW only. plain = raw projected points, no captaincy/premium structure bonuses.">
              <select className="w-full rounded-md border bg-background p-2 text-sm" value={params.objective}
                onChange={(e) => set("objective", e.target.value as SquadBuildParams["objective"])}>
                <option value="wildcard">wildcard</option>
                <option value="free_hit">free_hit</option>
                <option value="plain">plain</option>
              </select>
              {(params.objective === "wildcard" || params.objective === "free_hit") && (
                <label className="mt-2 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={!!params.differential}
                    onChange={(e) => set("differential", e.target.checked)}
                  />
                  Differential draft — penalise template ownership
                </label>
              )}
            </Field>
            <Field label="Max per team"
              hint="FPL allows at most 3 players from one club. Lower it to force more spread across teams.">
              <Input type="number" min={1} max={3} value={params.max_per_team}
                onChange={(e) => set("max_per_team", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
            <Field label="Min chance of playing %"
              hint="Drops players the FPL medical flag rates below this. 75 = only fit or near-fit players.">
              <Input type="number" min={0} max={100} value={params.min_chance_of_playing}
                onChange={(e) => set("min_chance_of_playing", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
            <Field label="Min minutes last season (outfield)"
              hint="Excludes fringe players below this many minutes (3420 = every minute). Styles set 600 (Balanced/Attacking) or 1200 (Safe). GKs exempt — a cheap backup keeper is fine.">
              <Input type="number" min={0} max={3420} step={30} value={params.min_minutes ?? 0}
                onChange={(e) => set("min_minutes", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
            <Field label="Min FWD minutes"
              hint="Stricter minutes floor for forwards only, on top of the general one. Use if you want only nailed strikers.">
              <Input type="number" value={params.min_fwd_minutes}
                onChange={(e) => set("min_fwd_minutes", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
            <Field label="Max player £m (blank=off)"
              hint="Caps any single player's price — forces a spread squad with no premiums.">
              <Input type="number" step={0.5} min={4} placeholder="no cap"
                value={params.max_player_price ?? ""}
                onChange={(e) => set("max_player_price", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
            <Field label="Include flagged (injured)"
              hint="Ticked = injured/doubtful players stay in the pool (their points are already discounted). Off = they're excluded entirely.">
              <input type="checkbox" checked={!!params.include_flagged}
                onChange={(e) => set("include_flagged", e.target.checked)} />
            </Field>
          </div>
        </div>
        <div>
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Model tuning
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Field label="Projection basis"
              hint="ppg = last season's points per game. xg = underlying expected-goals model (includes clean sheets). blend = mix of both (recommended). Team-strength nudges below only affect xg/blend.">
              <select className="w-full rounded-md border bg-background p-2 text-sm" value={params.projection_basis}
                onChange={(e) => set("projection_basis", e.target.value as SquadBuildParams["projection_basis"])}>
                <option value="ppg">ppg</option>
                <option value="xg">xg</option>
                <option value="blend">blend</option>
              </select>
            </Field>
            <Field label="Blend weight (xg share)"
              hint="0 = trust last season's points fully; 1 = trust underlying xG fully. Push up if you believe stats over reputation.">
              <Input type="number" step={0.05} min={0} max={1} value={params.blend_weight}
                onChange={(e) => set("blend_weight", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
            <Field label="Minutes prior K"
              hint="Shrinks part-timers' per-game numbers toward zero: a player's ppg is scaled by minutes/(minutes+K). Higher K punishes small samples harder.">
              <Input type="number" value={params.minutes_prior_k}
                onChange={(e) => set("minutes_prior_k", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
            <Field label="FDR strength"
              hint="How hard fixture difficulty swings projections. 1 = normal, 2 = fixtures matter double, 0 = ignore fixtures.">
              <Input type="number" step={0.1} min={0} max={3} value={params.fdr_strength}
                onChange={(e) => set("fdr_strength", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
            <Field label="Home/away strength"
              hint="Scales the home boost / away penalty. Raise it to prefer players with home-heavy fixture runs.">
              <Input type="number" step={0.1} min={0} max={4} value={params.home_away_strength}
                onChange={(e) => set("home_away_strength", e.target.value === "" ? undefined : Number(e.target.value))} />
            </Field>
          </div>
        </div>
      </Card>

      <TeamStrengthGrid onChange={setTeamNudges} />

      <PlayerKnowledgePanel pool={pool} todayISO={new Date().toISOString().slice(0, 10)} />
        </CollapsibleContent>
      </Collapsible>

      {mutation.isError && (
        <Card className="p-4 border-destructive">
          <p className="text-sm text-destructive">{mutation.error.message}</p>
          <p className="text-xs text-muted-foreground mt-1">
            The drafting service may be waking up — try again in a few seconds.
          </p>
        </Card>
      )}

      {!res && !mutation.isPending && !mutation.isError && (
        <Card className="p-4 text-sm text-muted-foreground">
          Pick a style and press <b>⚡ Draft my squad</b> — you'll get a full 15
          with captain, bench and projected points, ready to tweak.
        </Card>
      )}

      {/* The first draft is optimizer-bound and slow; without this everything
          below the form vanished while it ran, leaving only the button label
          as feedback. */}
      {mutation.isPending && !res && (
        <Card className="p-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Drafting your squad — optimising 15 picks across your fixture horizon…
          </div>
          <div className="mt-4 space-y-2" aria-hidden="true">
            <div className="h-24 rounded-md bg-muted/50 animate-pulse" />
            <div className="h-4 w-2/3 rounded bg-muted/50 animate-pulse" />
            <div className="h-4 w-1/2 rounded bg-muted/50 animate-pulse" />
          </div>
        </Card>
      )}

      {/* These three failed silently: an empty swap table, an XI that quietly
          stopped re-optimising, and a "Find pairs" button that just went idle. */}
      {(poolQuery.isError || lineupMutation.isError || gkPairsMutation.isError) && (
        <Card className="p-4 border-destructive">
          <p className="text-sm text-destructive">
            {poolQuery.error?.message ??
              lineupMutation.error?.message ??
              gkPairsMutation.error?.message}
          </p>
        </Card>
      )}

      {res && res.ok && (
        <>
          <Card className="p-4 flex flex-wrap gap-4 text-sm items-center">
            <span>Selected <b>{squadIds.length}/15</b></span>
            <span>Cost <b>£{res.squad_cost_m?.toFixed(1)}m</b></span>
            <span>Bank <b>£{res.remaining_budget_m?.toFixed(1)}m</b></span>
            <span>Formation <b>{res.formation ? res.formation.join("-") : "?"}</b></span>
            <span>Basis <b>{res.projection_basis}</b></span>
            {res.projected_points && (
              <span>Projected GW{res.gw_start}-{(res.gw_start ?? 1) + (res.horizon_gws ?? 1) - 1}
                {" "}<b>{res.projected_points.horizon_total.toFixed(1)} pts</b></span>
            )}
            <label className="flex items-center gap-1">Optimize XI:
              <select value={params.xi_objective ?? "horizon"}
                onChange={(e) => set("xi_objective", e.target.value as SquadBuildParams["xi_objective"])}
                className="rounded border bg-background p-1 text-xs">
                <option value="horizon">First {res.horizon_gws ?? 5} fixtures</option>
                <option value="next_gw">Next GW only</option>
                <option value="per_gw">Per-GW (rotate)</option>
              </select>
            </label>
            {res.xi_objective === "per_gw" && typeof res.rotation_gain === "number" && (
              <span className="text-emerald-600" title="extra points from re-picking the XI each GW vs one fixed XI">
                rotate +{res.rotation_gain.toFixed(1)} pts
              </span>
            )}
            {lineupMutation.isPending && <span className="text-muted-foreground">optimizing…</span>}
          </Card>

          <Tabs defaultValue="squad">
            <TabsList>
              <TabsTrigger value="squad">Squad</TabsTrigger>
              <TabsTrigger value="strategy">Strategy</TabsTrigger>
            </TabsList>
            <TabsContent value="squad" className="mt-4 space-y-4">

          {invalid && (
            <Card className="p-3 border-destructive">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-xs font-semibold text-destructive mb-1">
                    Squad not valid — showing last valid lineup
                  </div>
                  <ul className="text-xs text-destructive list-disc pl-4 space-y-0.5">
                    {invalid.violations?.map((v, i) => <li key={i}>{v}</li>)}
                  </ul>
                </div>
                {lastGood?.squad?.length ? (
                  <Button size="sm" variant="outline" className="shrink-0" onClick={revertToLastValid}>
                    Revert to last valid squad
                  </Button>
                ) : null}
              </div>
            </Card>
          )}

          {handoffSquad && <SquadHandoffPanel squad={handoffSquad} />}

          <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
            <div>
              <div className="text-xs font-semibold mb-1">
                All players {poolQuery.isFetching && <span className="text-muted-foreground">(loading…)</span>}
              </div>
              <PlayerListPanel players={pool} squadIds={squadIds}
                canAdd={canAdd} onAdd={addPlayer} onRemove={removePlayer} />
            </div>

            <DraftPitch
              squad={pitchSquad}
              xiIds={xiIds}
              captainId={res.captain_player_id ?? null}
              viceId={res.vice_player_id ?? null}
            />
          </div>

            </TabsContent>
            <TabsContent value="strategy" className="mt-4 space-y-4">

          {squadIds.length === 15 && (
            <TransferPlanPanel squadIds={squadIds} params={{ ...params, team_nudges: teamNudges }} />
          )}

          {res.projected_points && (
            <Card className="p-4">
              <div className="text-xs text-muted-foreground mb-2">
                Projected points per GW (XI + captain doubled) — directional cold-start estimate; do not compare totals across bases.
                {res.per_gw_lineups?.length ? " Per-GW rotate: the XI + formation shown maximizes each GW individually." : ""}
              </div>
              <div className="flex gap-3 flex-wrap">
                {(res.per_gw_lineups?.length
                  ? res.per_gw_lineups.map((g) => ({ gw: g.gw, total: g.total, formation: g.formation }))
                  : res.projected_points.per_gw.map((g) => ({ gw: g.gw, total: g.total, formation: undefined as [number, number, number] | undefined }))
                ).map((g) => (
                  <div key={g.gw} className="text-center">
                    <div className="text-xs text-muted-foreground">GW{g.gw}</div>
                    <div className="font-semibold">{g.total.toFixed(1)}</div>
                    {g.formation && (
                      <div className="text-[10px] text-muted-foreground">{g.formation.join("-")}</div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {res.value_menu && (
            <Card className="p-4">
              <div className="text-xs font-semibold mb-2">Value menu — top by 5-GW xPts</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                {(["GKP","DEF","MID","FWD"] as const).map((pos) => (
                  <div key={pos}>
                    <div className="font-semibold mb-1">{pos}</div>
                    <ul className="space-y-0.5">
                      {(res.value_menu?.[pos] ?? []).map((p) => (
                        <li key={p.player_id} className="flex justify-between gap-2">
                          <span>{p.web_name} <span className="text-muted-foreground">{p.team_short}</span></span>
                          <span className="text-muted-foreground">£{p.price_m?.toFixed(1)} · {p.xpts_horizon?.toFixed(1)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card className="p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-semibold">GK rotation pairs — nailed starters, complementary home/away</div>
              <Button size="sm" variant="outline" disabled={gkPairsMutation.isPending}
                onClick={() => gkPairsMutation.mutate()}>
                {gkPairsMutation.isPending ? "Finding…" : "Find pairs"}
              </Button>
            </div>
            {gkPairsMutation.data && (
              <ul className="text-xs space-y-1">
                {gkPairsMutation.data.pairs.map((pr, i) => {
                  const gap = pairBudgetGap(pr.combined_cost_m, outfieldCostM, params.budget_m ?? 100);
                  return (
                    <li key={i} className="flex items-center justify-between gap-2 border-t pt-1">
                      <span>
                        {pr.names[0]} <span className="text-muted-foreground">({pr.teams[0]})</span>
                        {" + "}{pr.names[1]} <span className="text-muted-foreground">({pr.teams[1]})</span>
                        <span className="text-muted-foreground">
                          {" · "}£{pr.combined_cost_m}m · rot {pr.rotation_xpts} · home {pr.home_weeks}/{pr.gws}
                        </span>
                      </span>
                      {gap > 0 ? (
                        <span className="text-muted-foreground shrink-0" title="This pair doesn't fit the current budget — free up funds among the outfielders first.">
                          needs £{gap.toFixed(1)}m
                        </span>
                      ) : (
                        <Button size="sm" variant="ghost" onClick={() => applyGkPair(pr)}>Use</Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          {gems.length > 0 && (
            <Card className="p-4">
              <div className="text-xs font-semibold mb-2">
                Gems — under 10% ownership, ranked by projected points per £m
              </div>
              <ul className="text-xs space-y-1">
                {gems.map((g) => (
                  <li key={g.player_id} className="flex items-center justify-between gap-2 border-t pt-1">
                    <span>
                      {g.web_name} <span className="text-muted-foreground">({g.team_short} · {g.pos})</span>
                    </span>
                    <span className="text-muted-foreground">
                      £{g.price_m.toFixed(1)} · {g.xpts_horizon.toFixed(1)} pts · {g.value.toFixed(1)}/£m · {g.selected_by_percent}% owned
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {res.notes?.length > 0 && (
            <Card className="p-4">
              <div className="text-xs font-semibold mb-1">Notes</div>
              <ul className="text-xs text-muted-foreground list-disc pl-4 space-y-0.5">
                {res.notes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </Card>
          )}

            </TabsContent>
          </Tabs>
        </>
      )}
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-xs flex items-center gap-1">
        {label}
        {hint && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Info className="h-3 w-3 text-muted-foreground cursor-help shrink-0" />
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-64 text-xs leading-snug">
              {hint}
            </TooltipContent>
          </Tooltip>
        )}
      </Label>
      {children}
    </div>
  );
}
