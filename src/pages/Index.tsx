import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { CommandRail } from "@/components/CommandRail";
import { WeekChecklist } from "@/components/WeekChecklist";
import { deriveWeekDecisions } from "@/lib/weekDecisions";
import { GwPlanValueProvider, useGwPlanStore } from "@/contexts/GwPlanContext";
import {
  buildPlayerLookup,
  buildTodo,
  countChanges,
  isPlanStep,
  makeMoves,
  moveBench,
  projectPlan,
  resolvePlan,
  swapCheck,
  swapPlayers,
  toPlanId,
  type PlanStep,
} from "@/lib/gwPlan";
import { planToTeam } from "@/lib/planTeam";
import {
  autoSubPreview,
  chipOptions,
  firstUnfinishedStep,
  footerFor,
  nextStep,
  prevStep,
  reviewSummary,
  reviewWarnings,
  stepCopy,
  transferOptions,
} from "@/lib/planFlow";
import { buildCaptainLab, type CaptainGoal } from "@/lib/captainLab";
import { useCountdown } from "@/hooks/useCountdown";
import { formatCountdown } from "@/lib/deadline";
import { StepChips } from "@/components/plan/StepChips";
import { StepHeader } from "@/components/plan/StepHeader";
import { PlanFooter } from "@/components/plan/PlanFooter";
import { TransfersStep } from "@/components/plan/TransfersStep";
import { CaptainStep } from "@/components/plan/CaptainStep";
import { BenchStep, type BenchMessage } from "@/components/plan/BenchStep";
import { ChipStep } from "@/components/plan/ChipStep";
import { ReviewStep } from "@/components/plan/ReviewStep";
import { MobileParameterDrawer } from "@/components/MobileParameterDrawer";
import { PitchVisualization } from "@/components/PitchVisualization";
import { RecommendationsPanel } from "@/components/RecommendationsPanel";
import { ChipNudgeCard } from "@/components/ChipNudgeCard";
import { OptimizeSquadDialog } from "@/components/OptimizeSquadDialog";
import { Navbar } from "@/components/layout/Navbar";
import { QueryErrorCard } from "@/components/QueryErrorCard";
import { isLatestSquad, resolveGwGateState, shouldAutoRecommend } from "@/lib/gwGate";
import { Button } from "@/components/ui/button";
import { Zap } from "lucide-react";
import { parseEntryIdInput } from "@/lib/entryId";
import { checkEntryIdentity, rolloverMessage } from "@/lib/entryIdentity";
import { useProfile } from "@/hooks/useProfile";
import { useAuth } from "@/contexts/AuthContext";
import { useIsDesktop } from "@/hooks/use-desktop";
import {
  fetchFixtures,
  fetchEntryIdentity,
  fetchNextEvent,
  fetchSquad,
  fetchTeamRecommendation,
  fetchChipPlan,
  getNextEventUrlTemplate,
  getRecommendationUrlTemplate,
  getFixturesUrlTemplate,
  getSquadUrlTemplate,
  CHIP_LABELS,
  type FplNextEventSummary,
  type FplChipStrategy,
  type FplEntryIdentity,
  type FplSquad,
  type FplTeamFixture,
  type FplTeamRecommendation,
  type TeamRecommendationParams,
  type ChipPlanResponse,
  type ChipName,
} from "@/lib/fplAssistantApi";

type PitchMode = "squad" | "recommendation";

// How often to refetch the squad while a gameweek is live. Matches the backend's
// EVENT_LIVE_TTL, so a poll that lands sooner would only re-serve the same cache.
const LIVE_POLL_MS = 60_000;

const clampGw = (gw: number) => Math.min(38, Math.max(1, gw));
const hasExplicitGwQuery = () => {
  const query = new URLSearchParams(window.location.search);
  return query.has("gw");
};

const getInitialGw = () => {
  const fromQuery = Number(new URLSearchParams(window.location.search).get("gw"));
  if (Number.isFinite(fromQuery) && fromQuery >= 1 && fromQuery <= 38) return clampGw(fromQuery);

  const fromStorage = Number(localStorage.getItem("fpl_selected_gw"));
  if (Number.isFinite(fromStorage) && fromStorage >= 1 && fromStorage <= 38) return clampGw(fromStorage);

  // No stored GW — return null so we wait for the next-event API before rendering
  return null;
};

const getInitialEntryId = () => {
  const fromQuery = Number(new URLSearchParams(window.location.search).get("entry_id"));
  if (Number.isFinite(fromQuery) && fromQuery > 0) return fromQuery;

  const fromStorage = Number(localStorage.getItem("fpl_entry_id"));
  if (Number.isFinite(fromStorage) && fromStorage > 0) return fromStorage;

  // No stored ID — 0 triggers the onboarding overlay in PitchVisualization.
  return 0;
};

const getInitialHorizon = () => {
  const fromQuery = Number(new URLSearchParams(window.location.search).get("horizon_gws"));
  if (Number.isFinite(fromQuery) && fromQuery > 0) return fromQuery;

  const fromStorage = Number(localStorage.getItem("fpl_horizon_gws"));
  if (Number.isFinite(fromStorage) && fromStorage > 0) return fromStorage;

  return 3;
};

// Canonical chip vocabulary lives in CHIP_LABELS (fplAssistantApi.ts) — reuse its keys
// here instead of hardcoding a second wildcard/free_hit-only whitelist, which used to
// silently drop bench_boost/triple_captain back to "none" on reload.
const isChipStrategyValue = (value: string): value is FplChipStrategy =>
  value === "none" || Object.prototype.hasOwnProperty.call(CHIP_LABELS, value);

const getInitialChipStrategy = (): FplChipStrategy => {
  const query = new URLSearchParams(window.location.search);
  const fromQuery = query.get("chip_strategy") ?? query.get("strategy");
  if (fromQuery && isChipStrategyValue(fromQuery)) return fromQuery;

  const fromStorage = localStorage.getItem("fpl_chip_strategy") ?? localStorage.getItem("fpl_transfer_strategy");
  if (fromStorage && isChipStrategyValue(fromStorage)) return fromStorage;
  return "none";
};

const getInitialChipPlayEventId = () => {
  const fromQuery = Number(new URLSearchParams(window.location.search).get("chip_play_event_id"));
  if (Number.isFinite(fromQuery) && fromQuery >= 1 && fromQuery <= 38) return clampGw(fromQuery);

  const fromStorage = Number(localStorage.getItem("fpl_chip_play_event_id"));
  if (Number.isFinite(fromStorage) && fromStorage >= 1 && fromStorage <= 38) return clampGw(fromStorage);

  return undefined;
};

const getInitialIncludeTransfers = () => {
  const fromQuery = new URLSearchParams(window.location.search).get("include_transfers");
  if (fromQuery === "true") return true;
  if (fromQuery === "false") return false;

  const fromStorage = localStorage.getItem("fpl_include_transfers");
  if (fromStorage === "true") return true;
  if (fromStorage === "false") return false;

  return true;
};

const getInitialCaptainGoal = (): CaptainGoal => (localStorage.getItem("fpl_captain_goal") === "safe" ? "safe" : "chase");

const Index = () => {
  const [entryId, setEntryId] = useState(getInitialEntryId);
  const [captainGoal, setCaptainGoal] = useState<CaptainGoal>(getInitialCaptainGoal);
  const [swapSelection, setSwapSelection] = useState<number | null>(null);
  const [benchMessage, setBenchMessage] = useState<BenchMessage | null>(null);
  const [selectedGW, setSelectedGW] = useState<number | null>(getInitialGw);
  // Invariant: squadGW always initializes equal to selectedGW and is only ever
  // written in lockstep with it (setGwAndReset / setEntryAndReset / next-event default).
  // It exists as separate state solely so the squad query key is explicit about which
  // GW's picks it is for. It must never be written from a response (that was the P0 bug).
  const [squadGW, setSquadGW] = useState<number | null>(getInitialGw);
  const [horizonGws, setHorizonGws] = useState(getInitialHorizon);
  const [chipStrategy, setChipStrategy] = useState<FplChipStrategy>(getInitialChipStrategy);
  const [differential, setDifferential] = useState<boolean>(
    () => typeof window !== "undefined" && localStorage.getItem("fpl_differential") === "true"
  );
  const [prioritizeInjured, setPrioritizeInjured] = useState<boolean>(
    () => typeof window === "undefined" || localStorage.getItem("fpl_prioritize_injured") !== "false"
  );
  const [chipPlayEventId, setChipPlayEventId] = useState<number | undefined>(getInitialChipPlayEventId);
  const [includeTransfers, setIncludeTransfers] = useState(getInitialIncludeTransfers);
  const [pitchMode, setPitchMode] = useState<PitchMode>("squad");
  const [didApplyNextGwDefault, setDidApplyNextGwDefault] = useState(hasExplicitGwQuery);

  const { profile, saveEntryId } = useProfile();
  const isDesktop = useIsDesktop();
  const queryClient = useQueryClient();

  // Cross-device hydration: profile beats "nothing", localStorage beats profile.
  useEffect(() => {
    if (entryId > 0) return;
    if (profile?.entryId && profile.entryId > 0) {
      setEntryId(profile.entryId);
    }
  }, [entryId, profile?.entryId]);

  const nextEventTemplate = getNextEventUrlTemplate();
  const squadTemplate = getSquadUrlTemplate();
  const fixturesTemplate = getFixturesUrlTemplate();
  const recommendationTemplate = getRecommendationUrlTemplate();

  const canFetchNextEvent = Boolean(nextEventTemplate);
  const canFetchSquad = Boolean(squadTemplate);
  const canFetchFixtures = Boolean(fixturesTemplate);
  const canRecommend = Boolean(recommendationTemplate);
  const canChangeGw = true;
  const effectiveHorizonGws = chipStrategy === "free_hit" ? 1 : horizonGws;

  const nextEventQuery = useQuery<FplNextEventSummary>({
    queryKey: ["next-event"],
    queryFn: ({ signal }) => fetchNextEvent(signal),
    enabled: canFetchNextEvent && (canFetchSquad || canRecommend || canFetchFixtures),
    // Was `retry: false`, which meant one cold-start 502 from Fly's
    // scale-to-zero wedged /app on a bare "Loading…" for first-time users.
    // Audit U1 — the render now surfaces a retryable error instead.
    retry: 2,
    staleTime: 5 * 60_000,
  });

  // gwResolved is declared later in this component (after the queries) — express the
  // same gate directly here rather than depending on a not-yet-declared binding.
  const chipPlanQuery = useQuery<ChipPlanResponse>({
    queryKey: ["chipPlan", entryId, selectedGW],
    queryFn: ({ signal }) => fetchChipPlan(entryId, undefined, signal),
    enabled: selectedGW !== null && entryId > 0,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  const nextEventId = nextEventQuery.data?.event_id ?? undefined;
  // The GW in progress, from bootstrap's `is_current`. Previously derived as
  // `nextEventId - 1`, which marks a finished GW as live in the window before
  // the next one is flagged, and yields GW0 pre-season. Fall back to the old
  // arithmetic only while an older backend is still deployed.
  const currentLiveGw =
    typeof nextEventQuery.data?.current_event_id === "number"
      ? nextEventQuery.data.current_event_id
      : nextEventQuery.data?.current_event_id === null
        ? undefined
        : typeof nextEventId === "number"
          ? nextEventId - 1
          : undefined;
  const isLiveGw =
    typeof currentLiveGw === "number" && selectedGW !== null && selectedGW === currentLiveGw;

  const squadQuery = useQuery<FplSquad>({
    queryKey: ["squad", entryId, squadGW],
    queryFn: ({ signal }) => fetchSquad({ entryId, eventId: squadGW! }, signal),
    enabled: canFetchSquad && Number.isFinite(entryId) && entryId > 0 && squadGW !== null,
    placeholderData: (previousData) => previousData,
    // Poll only while the selected GW is actually live. A finished GW's points
    // never change and a future one has none, so polling those is pure waste.
    refetchInterval: isLiveGw ? LIVE_POLL_MS : false,
    refetchOnWindowFocus: isLiveGw,
  });
  const squadUpdatedAt = squadQuery.dataUpdatedAt;

  const fixturesQuery = useQuery<FplTeamFixture[]>({
    queryKey: ["fixtures", selectedGW],
    queryFn: ({ signal }) => fetchFixtures({ eventId: selectedGW! }, signal),
    enabled: canFetchFixtures && selectedGW !== null && selectedGW >= 1 && selectedGW <= 38,
  });

  const fixturesByTeam = useMemo(() => {
    const mapping: Record<string, FplTeamFixture[]> = {};
    for (const fixture of fixturesQuery.data ?? []) {
      const teamShort = fixture.team_short;
      if (!mapping[teamShort]) mapping[teamShort] = [];
      mapping[teamShort].push(fixture);
    }
    return mapping;
  }, [fixturesQuery.data]);

  const buildRecommendationParams = (
    eventId: number,
    overrides?: { chipPlayEventId?: number }
  ): TeamRecommendationParams => {
    const wildcardPlayEventId =
      chipStrategy === "wildcard"
        ? overrides?.chipPlayEventId ??
          chipPlayEventId ??
          recommendationMutation.data?.chip_strategy?.play_event_id ??
          eventId
        : undefined;

    return {
      entryId,
      eventId,
      horizonGws: effectiveHorizonGws,
      chipStrategy,
      chipHorizonGws: chipStrategy === "wildcard" ? horizonGws : undefined,
      chipPlayEventId: wildcardPlayEventId,
      differential:
        chipStrategy === "wildcard" || chipStrategy === "free_hit" ? differential : undefined,
      prioritizeInjured,
      strategy: chipStrategy,
      includeTransfers,
      applyTransferCount: 0,
    };
  };

  const recommendationMutation = useMutation<FplTeamRecommendation, unknown, TeamRecommendationParams>({
    mutationFn: async (params) => fetchTeamRecommendation(params),
    onSuccess: (data) => {
      if (data.chip_strategy?.selected === "wildcard" && typeof data.chip_strategy.play_event_id === "number") {
        setChipPlayEventId(data.chip_strategy.play_event_id);
      }
      setPitchMode("recommendation");
    },
  });

  useEffect(() => {
    if (didApplyNextGwDefault) return;
    if (!nextEventQuery.isFetched) return;


    // A failed next-event call is not off-season. Latching the GW-38 placeholder
    // here (and persisting it) is how a transient backend outage left the app
    // permanently opening on GW38: the placeholder was written to localStorage as
    // if the user had chosen it, and every later visit started there. Leave the GW
    // alone and stay unlatched so the real default applies once the API recovers.
    if (nextEventQuery.isError) return;

    const nextGw = nextEventQuery.data?.event_id;
    if (Number.isFinite(nextGw) && nextGw !== null && nextGw >= 1 && nextGw <= 38) {
      // Open on the live GW (current in-progress) so the user sees real scores first.
      // They can navigate forward to plan transfers for the next GW.
      const liveGw = clampGw(
        typeof nextEventQuery.data?.current_event_id === "number"
          ? nextEventQuery.data.current_event_id
          : nextGw - 1,
      );
      setSelectedGW(liveGw);
      setSquadGW(liveGw);
    } else {
      // Genuinely off-season: the API answered and has no upcoming gameweek.
      // isOffSeason (below) gates whether the pitch or the off-season card renders.
      setSelectedGW(38);
      setSquadGW(38);
    }

    setPitchMode("squad");
    recommendationMutation.reset();
    setDidApplyNextGwDefault(true);
  }, [
    didApplyNextGwDefault,
    nextEventQuery.data?.event_id,
    nextEventQuery.data?.current_event_id,
    nextEventQuery.isFetched,
    nextEventQuery.isError,
    recommendationMutation,
  ]);

  // Root cause of the GW-navigation wedge (see BACKLOG P0): when the backend can't
  // fetch picks for the requested event_id (deterministically for future GWs mid-season
  // — FPL has no picks yet — or transiently for historical GWs on upstream hiccups) it
  // silently substitutes the nearest available GW's squad (200 OK, different event_id).
  // A since-removed effect here used to adopt that returned event_id into squadGW while
  // selectedGW stayed put, desyncing the GW nav from the squad actually rendered with no
  // indication anything was off ("bounce-back"/"wedge").
  //
  // The fix: never mutate GW state from a response. A substitution is detected as a
  // derived value and surfaced as an informational banner on the pitch (the returned
  // squad still renders — for future GWs "your latest squad" is the correct planning
  // basis, which is why the backend substitutes at all). The settled-state guards
  // (placeholder/fetching) stop the banner flashing mid-navigation while the previous
  // GW's data is shown as placeholder.
  const returnedSquadGw = squadQuery.data?.event_id;
  const squadSubstituted =
    pitchMode === "squad" &&
    !squadQuery.isPlaceholderData &&
    !squadQuery.isFetching &&
    squadQuery.isSuccess &&
    typeof returnedSquadGw === "number" &&
    squadGW !== null &&
    returnedSquadGw !== squadGW;
  // FPL reissues entry ids each season, so a stored id can resolve to a
  // different manager. Compare what the squad payload says the entry is now
  // against the snapshot taken when the user linked it.
  const identityCheck = useMemo(
    () =>
      checkEntryIdentity(
        profile
          ? {
              managerName: profile.managerName,
              teamName: profile.teamName,
              joinedTime: profile.joinedTime,
            }
          : null,
        squadQuery.data?.entry ?? null,
      ),
    [profile, squadQuery.data?.entry],
  );

  // Real scores belong on the pitch only when the squad shown is the one the
  // user asked for AND that gameweek has actually started. A future GW renders
  // the substituted latest squad; painting its points under a "GW3" heading
  // claims a score that doesn't exist yet.
  const showActualPoints =
    pitchMode === "squad" &&
    !squadSubstituted &&
    typeof currentLiveGw === "number" &&
    selectedGW !== null &&
    selectedGW <= currentLiveGw;

  const substitutionNotice = squadSubstituted
    ? `Showing your latest squad (GW ${returnedSquadGw}) — your GW ${squadGW} picks aren't available yet.`
    : undefined;

  useEffect(() => {
    if (chipStrategy !== "wildcard" && chipPlayEventId !== undefined) {
      setChipPlayEventId(undefined);
    }
  }, [chipPlayEventId, chipStrategy]);

  useEffect(() => {
    try {
      localStorage.setItem("fpl_entry_id", String(entryId));
      // Only persist a GW the API actually confirmed. Storing a placeholder from
      // a failed fetch makes it the user's remembered choice forever.
      if (selectedGW !== null && nextEventQuery.isSuccess) {
        localStorage.setItem("fpl_selected_gw", String(selectedGW));
      }
      localStorage.setItem("fpl_horizon_gws", String(horizonGws));
      localStorage.setItem("fpl_chip_strategy", chipStrategy);
      localStorage.setItem("fpl_transfer_strategy", chipStrategy);
      if (typeof chipPlayEventId === "number") {
        localStorage.setItem("fpl_chip_play_event_id", String(chipPlayEventId));
      } else {
        localStorage.removeItem("fpl_chip_play_event_id");
      }
      localStorage.setItem("fpl_include_transfers", String(includeTransfers));
      localStorage.setItem("fpl_differential", String(differential));
      localStorage.setItem("fpl_prioritize_injured", String(prioritizeInjured));
    } catch {
      // ignore
    }
  }, [entryId, selectedGW, horizonGws, chipStrategy, chipPlayEventId, includeTransfers,
      nextEventQuery.isSuccess, prioritizeInjured]);

  useEffect(() => {
    if (!recommendationMutation.data) return;
    if (recommendationMutation.isPending) return;

    const nextChipPlayEventId =
      chipStrategy === "wildcard"
        ? recommendationMutation.data.chip_strategy?.play_event_id ?? chipPlayEventId ?? selectedGW
        : undefined;

    if (chipStrategy === "wildcard" && nextChipPlayEventId !== chipPlayEventId) {
      setChipPlayEventId(nextChipPlayEventId);
    }

    recommendationMutation.mutate(
      buildRecommendationParams(selectedGW, {
        chipPlayEventId: nextChipPlayEventId,
      })
    );
    setPitchMode("recommendation");
  }, [horizonGws, chipStrategy, includeTransfers]);

  // Don't render the app until we know which GW to show — avoids the fallback flash.
  const gwResolved = selectedGW !== null;
  const gwGateState = resolveGwGateState({
    gwResolved,
    nextEventError: nextEventQuery.isError,
    nextEventFetching: nextEventQuery.isFetching,
  });

  // isSuccess (not isFetched) — a failed next-event fetch must show the error path,
  // not a false "off-season" card.
  const isOffSeason = nextEventQuery.isSuccess && !Number.isFinite(nextEventQuery.data?.event_id);

  // ---- The GW plan (v2 flow) --------------------------------------------------
  // One client-side plan for the deadline GW. The pitch, the rail, the panel and
  // every step read it; only resetPlan() rebuilds the squad. It is keyed by the
  // deadline GW (not the GW on screen) and seeded from the latest picks — the
  // squad on screen counts as "latest" only when it is the live GW's or later,
  // so browsing back to GW20 never reseeds the plan from GW20's team.
  const deadlineGw = typeof nextEventId === "number" ? nextEventId : undefined;
  const squadIsLatest = isLatestSquad({
    squadEventId: squadQuery.data?.event_id,
    deadlineGw,
    placeholder: squadQuery.isPlaceholderData,
  });
  const [latestSquad, setLatestSquad] = useState<FplSquad | undefined>(undefined);
  useEffect(() => {
    if (squadIsLatest && squadQuery.data) setLatestSquad(squadQuery.data);
  }, [squadIsLatest, squadQuery.data]);
  useEffect(() => {
    setLatestSquad(undefined);
  }, [entryId]);
  const { user } = useAuth();
  const planStore = useGwPlanStore({ entryId, gw: deadlineGw ?? 0, squad: squadIsLatest ? squadQuery.data : undefined, userId: user?.id ?? null });
  const { plan, base: basePlan, setPlan, resetPlan } = planStore;

  // The recommendation informs the plan only when it was run for the deadline GW.
  const planRec =
    recommendationMutation.data && recommendationMutation.data.event_id === deadlineGw ? recommendationMutation.data : undefined;
  const planMoves = useMemo(() => makeMoves(planRec), [planRec]);
  const playerLookup = useMemo(() => buildPlayerLookup(latestSquad ?? squadQuery.data, planRec), [latestSquad, squadQuery.data, planRec]);
  const resolvedPlan = useMemo(() => (plan ? resolvePlan(plan, planMoves) : null), [plan, planMoves]);
  // Derived, never stored: "make" applies the verdict's moves, nothing else does.
  const appliedTransferCount = plan?.transfer === "make" ? planMoves.length : 0;
  const chipOpts = useMemo(
    () => (resolvedPlan && typeof deadlineGw === "number" ? chipOptions({ resolved: resolvedPlan, lookup: playerLookup, chipPlan: chipPlanQuery.data, gw: deadlineGw }) : []),
    [resolvedPlan, playerLookup, chipPlanQuery.data, deadlineGw],
  );
  const freeHitGain = chipOpts.find((o) => o.chip === "free_hit")?.gain ?? null;
  const planProjected = resolvedPlan && plan ? projectPlan(resolvedPlan, playerLookup, plan.chip, freeHitGain) : null;
  const baseProjected = basePlan ? projectPlan(resolvePlan(basePlan, []), playerLookup, null) : null;
  const planDelta =
    typeof planProjected === "number" && typeof baseProjected === "number" ? Math.round((planProjected - baseProjected) * 10) / 10 : undefined;
  const planChanges = plan && basePlan ? countChanges(plan, basePlan, planMoves) : 0;
  const planDirty = Boolean(plan && (planChanges > 0 || plan.transfer !== null || plan.chip !== null || Object.keys(plan.reviewed).length > 0));

  // Steps route as /app/plan/:step; /app is the squad overview.
  const { step: stepParam } = useParams();
  const step: PlanStep = isPlanStep(stepParam) ? stepParam : "squad";
  const navigate = useNavigate();
  const goStep = (s: PlanStep) => {
    setSwapSelection(null);
    setBenchMessage(null);
    navigate(s === "squad" ? "/app" : `/app/plan/${s}`);
  };

  useEffect(() => {
    try {
      localStorage.setItem("fpl_captain_goal", captainGoal);
    } catch {
      // ignore
    }
  }, [captainGoal]);

  // The step views (flow handoff §3). Everything here reads the plan; nothing
  // refetches the squad.
  const transferOpts = useMemo(() => (planRec ? transferOptions(planRec) : null), [planRec]);
  const planPosOf = (id: number) => playerLookup[id]?.pos ?? "MID";
  const captainLab = useMemo(() => {
    if (!planRec || !resolvedPlan) return null;
    const pool = [...resolvedPlan.xi, ...resolvedPlan.bench].map((id) => playerLookup[id]).filter(Boolean);
    return buildCaptainLab(planRec, captainGoal, resolvedPlan.cap, { pool, benchedIds: new Set(resolvedPlan.bench), viceId: resolvedPlan.vice });
  }, [planRec, resolvedPlan, playerLookup, captainGoal]);
  const planWarnings = resolvedPlan ? reviewWarnings(resolvedPlan) : [];
  const deadlineRemaining = useCountdown(nextEventQuery.data?.deadline_time_utc);
  const countdownText = deadlineRemaining !== null && deadlineRemaining > 0 ? formatCountdown(deadlineRemaining) : "";

  const makeCaptain = (id: number) => {
    const pid = toPlanId(id, planMoves);
    setPlan((p) => ({ cap: pid, vice: p.vice === pid ? p.cap : p.vice }));
  };
  const makeVice = (id: number) => setPlan({ vice: toPlanId(id, planMoves) });
  const changeGoal = (g: CaptainGoal) => setCaptainGoal(g);

  const armSwap = (id: number | null) => {
    setSwapSelection(id);
    setBenchMessage(id === null ? null : { text: `Tap a highlighted starter to bring ${playerLookup[id]?.web_name ?? "him"} on.`, tone: "primary" });
  };
  const starterState = swapSelection !== null && resolvedPlan
    ? (id: number) => (swapCheck(resolvedPlan.xi, swapSelection, id, planPosOf) ? ("invalid" as const) : ("valid" as const))
    : undefined;
  const onStarterClick = (starterId: number) => {
    if (swapSelection === null || !resolvedPlan || !plan) return;
    const rule = swapCheck(resolvedPlan.xi, swapSelection, starterId, planPosOf);
    if (rule) {
      setBenchMessage({ text: rule, tone: "warning" });
      return;
    }
    const next = swapPlayers(plan, toPlanId(swapSelection, planMoves), toPlanId(starterId, planMoves));
    setPlan({ xi: next.xi, bench: next.bench });
    const inName = playerLookup[swapSelection]?.web_name ?? "He";
    const outName = playerLookup[starterId]?.web_name ?? "the starter";
    const capOut = starterId === resolvedPlan.cap;
    setBenchMessage(
      capOut
        ? { text: `${inName} is in for ${outName}. Your captain is now on the bench, so pick a new one.`, tone: "danger" }
        : { text: `${inName} is in for ${outName}.`, tone: "accent" },
    );
    setSwapSelection(null);
  };
  const onMoveBench = (index: number, dir: -1 | 1) => {
    if (!plan) return;
    const next = moveBench(plan, index, dir);
    if (next !== plan) setPlan({ bench: next.bench });
  };


  // DecisionCard's Apply/Undo write the plan's transfer decision; the per-move
  // index no longer matters — the plan applies the verdict's moves as one.
  const applyTransferAtIndex = () => {
    if (planMoves.length === 0) return;
    setPlan({ transfer: "make" });
  };

  const resetAppliedTransfers = () => {
    setPlan({ transfer: null });
  };

  const activeRecommendation = useMemo(() => {
    const rec = recommendationMutation.data;
    if (!rec) return undefined;

    const steps = Array.isArray(rec.squad_with_transfers_steps) ? rec.squad_with_transfers_steps : [];
    if (steps.length === 0) return rec;

    const maxStep = Math.max(0, steps.length - 1);
    const targetCount = Math.min(Math.max(0, appliedTransferCount), maxStep);
    const fallbackStep = steps[targetCount];
    const selectedStep = steps.find((step) => step.applied_count === targetCount) ?? fallbackStep;
    if (!selectedStep) return rec;

    return {
      ...rec,
      transfer_application: selectedStep.transfer_application ?? rec.transfer_application,
      transfer_impact: selectedStep.transfer_impact ?? rec.transfer_impact,
      squad_with_transfers: selectedStep,
    };
  }, [appliedTransferCount, recommendationMutation.data]);

  // On the deadline GW the squad view is the plan: the user's XI, bench order
  // and armbands with the transfer decision applied. Other GWs render their
  // own picks as before.
  const planTeam = useMemo(
    () => (plan && resolvedPlan && latestSquad && selectedGW === deadlineGw ? planToTeam(latestSquad, resolvedPlan, playerLookup) : undefined),
    [plan, resolvedPlan, latestSquad, selectedGW, deadlineGw, playerLookup],
  );
  // The bench step always shows the plan, whatever GW the squad view is on.
  const benchTeam = useMemo(
    () => (plan && resolvedPlan && latestSquad ? planToTeam(latestSquad, resolvedPlan, playerLookup) : undefined),
    [plan, resolvedPlan, latestSquad, playerLookup],
  );
  const activeTeam = useMemo(() => {
    if (pitchMode === "recommendation" && activeRecommendation) return activeRecommendation;
    return planTeam ?? squadQuery.data;
  }, [pitchMode, activeRecommendation, planTeam, squadQuery.data]);

  const activeError =
    pitchMode === "recommendation"
      ? recommendationMutation.error
      : squadQuery.error;

  const activeErrorMessage = useMemo(() => {
    if (!activeError) return undefined;
    if (activeError instanceof Error) return activeError.message;
    return String(activeError);
  }, [activeError]);

  const recommendErrorMessage = useMemo(() => {
    const err = recommendationMutation.error;
    if (!err) return undefined;
    if (err instanceof Error) return err.message;
    return String(err);
  }, [recommendationMutation.error]);

  const isLoading =
    pitchMode === "recommendation"
      ? recommendationMutation.isPending
      : squadQuery.isFetching;

  const setGwAndReset = (gw: number) => {
    setSelectedGW(gw);
    setSquadGW(gw);
    const shouldRefreshRecommendation =
      Boolean(recommendationMutation.data) &&
      (pitchMode === "recommendation" || chipStrategy !== "none");

    if (shouldRefreshRecommendation) {
      const nextChipPlayEventId =
        chipStrategy === "wildcard"
          ? chipPlayEventId ?? recommendationMutation.data?.chip_strategy?.play_event_id ?? gw
          : undefined;
      setPitchMode("recommendation");
      recommendationMutation.mutate(
        buildRecommendationParams(gw, { chipPlayEventId: nextChipPlayEventId })
      );
      return;
    }

    setPitchMode("squad");
    recommendationMutation.reset();
  };

  const setEntryAndReset = (value: number, identity?: FplEntryIdentity | null) => {
    setEntryId(value);
    setSquadGW(selectedGW);
    setChipPlayEventId(undefined);
    setPitchMode("squad");
    recommendationMutation.reset();
    // The identity snapshot rides along with the id: without it a season
    // rollover is undetectable and the app renders a stranger's squad.
    if (value > 0) {
      void saveEntryId(value, identity
        ? {
            managerName: identity.manager_name ?? null,
            teamName: identity.team_name ?? null,
            joinedTime: identity.joined_time ?? null,
          }
        : undefined);
    }
  };

  // Resolved GW for rendering — pre-resolution placeholder; gwResolved gates rendering
  const resolvedGW = selectedGW ?? 38;

  // "Optimize my squad" is a pre-first-deadline action: only surface it when the
  // current recommendation reports pre_first_deadline (unlimited free swaps, no hits).
  const showOptimize =
    recommendationMutation.data?.pre_first_deadline === true &&
    Number.isFinite(entryId) &&
    entryId > 0;

  // After Apply persists the optimized squad server-side, refetch the squad and
  // re-run the recommendation so the pitch + insights reflect the new squad.
  const handleOptimizeApplied = () => {
    void queryClient.invalidateQueries({ queryKey: ["squad", entryId, squadGW] });
    const nextChipPlayEventId = chipStrategy === "wildcard" ? resolvedGW : undefined;
    if (chipStrategy === "wildcard") {
      setChipPlayEventId(nextChipPlayEventId);
    }
    setPitchMode("recommendation");
    recommendationMutation.mutate(
      buildRecommendationParams(resolvedGW, { chipPlayEventId: nextChipPlayEventId })
    );
  };

  // A live gameweek cannot be planned — FPL has no picks for it yet. The old UI
  // disabled the button and told the user to go change the gameweek themselves.
  // Do it for them: the same constraint, expressed as the next step.
  const planGw = isLiveGw ? clampGw((currentLiveGw ?? resolvedGW) + 1) : resolvedGW;

  const runRecommendation = (eventId: number) => {
    const nextChipPlayEventId = chipStrategy === "wildcard" ? eventId : undefined;
    if (chipStrategy === "wildcard") setChipPlayEventId(nextChipPlayEventId);
    recommendationMutation.mutate(
      buildRecommendationParams(eventId, { chipPlayEventId: nextChipPlayEventId })
    );
  };

  const handlePrimaryRecommend = () => {
    if (planGw !== resolvedGW) {
      // Move the view forward too, so the pitch and the result agree.
      // Deliberately not switching to squad mode first: the requested GW has no
      // picks yet, so the squad view would render the substituted latest squad
      // under a "GW3" heading for the length of the request, then flip to the
      // recommendation. Staying put until the result lands avoids that flash.
      setSelectedGW(planGw);
      setSquadGW(planGw);
    }
    runRecommendation(planGw);
  };

  // Applying a nudge just sets the chip strategy — the same thing the sidebar's
  // onChipStrategyChange does. Persistence to localStorage is handled by the
  // existing effect that reacts to chipStrategy changes; no separate write needed.
  const handleApplyChipNudge = (chip: ChipName) => {
    setChipStrategy(chip);
    setPlan({ chip });
  };

  // Entering a step needs ZN Pick's answer for the deadline GW; run it once per
  // entry + deadline GW if the user hasn't, asking for that GW explicitly (the
  // Recommend button's planGw follows the GW on screen, which may be another).
  // The squad itself is never refetched — handoff §1.
  const autoRecommendFired = useRef<string | null>(null);
  const autoRecommendKey = shouldAutoRecommend({
    step,
    hasPlanRec: Boolean(planRec),
    pending: recommendationMutation.isPending,
    canRecommend,
    entryId,
    deadlineGw,
    firedKey: autoRecommendFired.current,
  });
  useEffect(() => {
    if (!autoRecommendKey || typeof deadlineGw !== "number") return;
    autoRecommendFired.current = autoRecommendKey;
    setSelectedGW(deadlineGw);
    setSquadGW(deadlineGw);
    runRecommendation(deadlineGw);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRecommendKey]);

  const parameterProps = {
    entryId,
    onEntryIdChange: setEntryAndReset,
    horizonGws,
    onHorizonGwsChange: setHorizonGws,
    chipStrategy,
    onChipStrategyChange: setChipStrategy,
    differential,
    onDifferentialChange: setDifferential,
    prioritizeInjured,
    onPrioritizeInjuredChange: setPrioritizeInjured,
    includeTransfers,
    onIncludeTransfersChange: setIncludeTransfers,
    canRecommend,
    isRecommending: recommendationMutation.isPending,
    isLiveGw,
    planGw,
    maxHorizon: Math.max(1, 38 - resolvedGW + 1),
    onRecommend: handlePrimaryRecommend,
    recommendErrorMessage,
  };

  // The Command Center's four weekly decisions, derived — never stored — from
  // the plan, with the recommendation and the chip plan as context.
  const weekDecisions = useMemo(
    () =>
      deriveWeekDecisions({
        plan,
        base: basePlan,
        lookup: playerLookup,
        recommendation: planRec,
        chipPlan: chipPlanQuery.data ?? null,
        chipPlanError: chipPlanQuery.isError,
      }),
    [plan, basePlan, playerLookup, planRec, chipPlanQuery.data, chipPlanQuery.isError],
  );
  const reviewRows = plan && basePlan ? reviewSummary(plan, basePlan, planMoves, playerLookup, weekDecisions) : [];
  const planTodo =
    plan && basePlan ? buildTodo(plan, basePlan, planMoves, playerLookup, planRec?.transfer_plan_horizon?.verdict_detail?.hit_cost ?? 0) : [];
  const footer = footerFor({ step, plan, decisions: weekDecisions, warnings: planWarnings, gw: deadlineGw ?? planGw });
  const onFooterNext = () => {
    if (!plan) return;
    if (step === "confirm") {
      if (plan.locked) goStep("squad");
      else setPlan({ locked: true });
      return;
    }
    if (step === "squad") {
      goStep(firstUnfinishedStep(weekDecisions));
      return;
    }
    setPlan((p) => ({ reviewed: { ...p.reviewed, [step]: true } }));
    const next = nextStep(step);
    if (next) goStep(next);
  };
  const onFooterBack = () => {
    const prev = prevStep(step);
    if (prev) goStep(prev);
  };
  const header = stepCopy(step, deadlineGw ?? planGw, { locked: Boolean(plan?.locked), desktop: isDesktop });
  const stepHeader =
    step === "captain" && captainLab ? { ...header, title: captainLab.headline, sub: captainLab.subcopy } : header;
  const verdictDetail = activeRecommendation?.transfer_plan_horizon?.verdict_detail;
  const freeTransfers =
    verdictDetail?.ft_before ??
    activeRecommendation?.transfer_plan_horizon?.start_free_transfers ??
    activeRecommendation?.transfers?.transfer_plan?.free_transfers;
  const bank = squadQuery.data?.entry_history?.bank;
  // Projected = the plan's own total (client-side, plan-GW xPts); until the
  // recommendation brings those, fall back to the engine's number.
  const projected = planProjected ?? activeRecommendation?.projected_points_with_captain;
  const projectedDelta = planProjected !== null ? planDelta : undefined;
  const navbarStats =
    typeof bank === "number" || typeof freeTransfers === "number" ? (
      <>
        {typeof bank === "number" && (
          <span className="whitespace-nowrap">Bank <b className="font-semibold text-foreground">£{bank.toFixed(1)}m</b></span>
        )}
        {typeof freeTransfers === "number" && (
          <span className="whitespace-nowrap">FT <b className="font-semibold text-foreground">{freeTransfers}</b></span>
        )}
      </>
    ) : undefined;

  const handleEntryIdSubmit = async (raw: string): Promise<string | null> => {
    const id = parseEntryIdInput(raw);
    if (id === null) {
      return "That doesn't look like a team ID. Paste the number or your full FPL team URL.";
    }
    // Validated against the entry itself, not against a squad fetch: the picks
    // endpoint 404s for any gameweek that hasn't locked, so checking the squad
    // rejects perfectly valid IDs before a deadline. The lookup also yields the
    // identity snapshot we need to store.
    let identity: FplEntryIdentity | null = null;
    try {
      identity = await fetchEntryIdentity(id);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      // Only a definitive not-found blocks onboarding; transient/backend
      // errors must not lock the user out — accept and let error states surface.
      if (/\b404\b|no fpl team found|not found/i.test(message)) {
        return "Couldn't find a team with that ID. Double-check it on the FPL site.";
      }
    }
    setEntryAndReset(id, identity);
    return null;
  };

  return (
    <GwPlanValueProvider value={planStore}>
    <div className="flex flex-col h-screen bg-background">
      <Navbar extras={navbarStats} planStatus={plan ? { changes: planChanges, locked: plan.locked } : undefined} />
      {entryId > 0 && gwGateState === "ready" && (
        <div className="fixed inset-x-0 top-14 z-40 border-b border-border bg-background/95 backdrop-blur lg:hidden">
          <StepChips decisions={weekDecisions} step={step} onSelect={goStep} />
        </div>
      )}
      <div className={`flex flex-1 min-h-0 flex-col lg:flex-row overflow-y-auto lg:overflow-hidden ${entryId > 0 && gwGateState === "ready" ? "pt-[106px] lg:pt-14" : "pt-14"}`}>
      {gwGateState === "error" ? (
        // A failed /events/next used to fall through to the "Loading…" branch
        // below and stay there forever (audit U1). Give the user a way out.
        <div className="flex flex-1 items-center justify-center p-6" role="alert">
          <div className="w-full max-w-md">
            <QueryErrorCard
              title="Couldn't reach the FPL Assistant"
              message="The server may be waking up. Try again in a moment."
              onRetry={() => nextEventQuery.refetch()}
              retrying={nextEventQuery.isFetching}
            />
          </div>
        </div>
      ) : gwGateState === "loading" ? (
        // Wait for next-event API before showing anything — prevents fallback-squad flash
        <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm">
          Loading…
        </div>
      ) : (
        <>
      {isDesktop ? (
        <div className="hidden lg:flex shrink-0">
          <CommandRail
            decisions={weekDecisions}
            onSelectStep={goStep}
            activeStep={step}
            onReset={resetPlan}
            dirty={planDirty}
            gw={deadlineGw ?? planGw}
            projected={projected}
            delta={projectedDelta}
            percentile={activeRecommendation?.projected_percentile ?? undefined}
            top10kAvg={activeRecommendation?.projected_top10k_avg ?? undefined}
            overallAvg={activeRecommendation?.projected_overall_avg ?? undefined}
            parameters={parameterProps}
          />
        </div>
      ) : (
        <>
          {/* The drawer's floating button would sit on the flow footer's Next. */}
          {step === "squad" && <MobileParameterDrawer {...parameterProps} />}
          {/* The drawer closes before the request resolves, and the only other
              place this renders is inside it — so on a phone a failed
              recommendation produced no feedback at all. */}
          {recommendErrorMessage && (
            <div
              role="alert"
              className="lg:hidden mx-3 mt-3 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive break-words"
            >
              {recommendErrorMessage}
            </div>
          )}
        </>
      )}
      {/* entryId <= 0 falls through to the pitch so the onboarding overlay stays
          reachable during pre-season — otherwise first-run signups in the launch
          window would only ever see the off-season card. */}
      {step !== "squad" && entryId > 0 ? (
        <div className="flex flex-1 flex-col lg:min-h-0 lg:min-w-0">
          <div className="flex-1 px-4 py-5 lg:overflow-y-auto lg:px-8 lg:py-6">
            <div className="mx-auto flex max-w-[880px] flex-col gap-4">
              <StepHeader copy={stepHeader} savedBanner={false} />
              {step === "transfers" && (
                <TransfersStep
                  options={transferOpts}
                  value={plan?.transfer ?? null}
                  onPick={(choice) => setPlan({ transfer: choice })}
                  loading={recommendationMutation.isPending}
                />
              )}
              {step === "captain" &&
                (captainLab ? (
                  <CaptainStep lab={captainLab} goal={captainGoal} onGoal={changeGoal} onMakeCaptain={makeCaptain} onMakeVice={makeVice} />
                ) : (
                  <div className="rounded-2xl border border-border bg-card p-10 text-center text-sm text-muted-foreground">
                    {recommendationMutation.isPending ? "Projecting your captain options…" : "Run ZN Pick to see your captain options."}
                  </div>
                ))}
              {step === "bench" && resolvedPlan && plan && (
                <>
                  {benchTeam && (
                    <PitchVisualization
                      team={benchTeam}
                      requestedGw={deadlineGw ?? planGw}
                      onRequestedGwChange={() => {}}
                      gwSelectable={false}
                      compact
                      hideBench
                      fixturesByTeam={fixturesByTeam}
                      incoming={resolvedPlan.incoming}
                      starterState={starterState}
                      onStarterClick={onStarterClick}
                    />
                  )}
                  <BenchStep
                    resolved={resolvedPlan}
                    lookup={playerLookup}
                    swapSelection={swapSelection}
                    onSwapSelect={armSwap}
                    onMoveBench={onMoveBench}
                    autoSub={autoSubPreview(resolvedPlan, playerLookup)}
                    message={benchMessage}
                  />
                </>
              )}
              {step === "chip" && plan && <ChipStep options={chipOpts} value={plan.chip} onPick={(chip) => setPlan({ chip })} />}
              {step === "confirm" && plan && (
                <ReviewStep
                  rows={reviewRows}
                  onRow={goStep}
                  warnings={planWarnings}
                  onFix={goStep}
                  projected={planProjected}
                  delta={planDelta}
                  locked={plan.locked}
                  todo={planTodo}
                  gw={deadlineGw ?? planGw}
                  countdown={countdownText}
                />
              )}
              {recommendErrorMessage && step !== "bench" && (
                <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  {recommendErrorMessage}
                </div>
              )}
            </div>
          </div>
          <PlanFooter spec={footer} onBack={onFooterBack} onNext={onFooterNext} />
        </div>
      ) : isOffSeason && entryId > 0 ? (
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="max-w-sm text-center rounded-2xl border border-border bg-card p-8">
            <h3 className="font-bold text-foreground mb-2">Season hasn't started</h3>
            <p className="text-sm text-muted-foreground">
              The FPL API has no upcoming gameweek yet. Check back when the new season fixtures are live.
            </p>
          </div>
        </div>
      ) : pitchMode === "squad" && squadQuery.isError && !squadQuery.data ? (
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="w-full max-w-sm">
            <QueryErrorCard
              message={activeErrorMessage}
              onRetry={() => squadQuery.refetch()}
              retrying={squadQuery.isFetching}
            />
          </div>
        </div>
      ) : (
        // A dedicated column wrapper: this whole branch used to spread the rollover
        // banner, the chip nudge, and PitchVisualization as separate ROW siblings
        // (JSX fragments don't add a DOM node), so on lg+ each one became its own
        // flex-row column and starved PitchVisualization's flex-1 down to ~0px
        // whenever the banner or nudge rendered. Wrapping them in one flex-col here
        // makes this div the flex-row item (taking over PitchVisualization's old
        // flex-1 min-w-0 role) and lets the banner/nudge stack above the pitch
        // inside it instead. min-h-0/flex-1 are lg-only: on mobile the page
        // stacks vertically and a collapsed-height column makes the pitch
        // overlap its siblings.
        <div className="flex flex-col lg:flex-1 lg:min-w-0 lg:min-h-0">
        {plan?.locked && (
          <div className="mx-auto w-full max-w-5xl px-4 pt-4">
            <StepHeader copy={header} savedBanner />
          </div>
        )}
        {/* Phones get the checklist as a strip above the pitch; the rail is lg+. */}
        {!isDesktop && entryId > 0 && (
          <div className="mx-auto w-full max-w-5xl px-4 pt-4 lg:hidden">
            <WeekChecklist decisions={weekDecisions} compact onSelect={goStep} activeStep={step} onReset={resetPlan} dirty={planDirty} />
          </div>
        )}
        {identityCheck.status === "rolled-over" && (
          <div className="mx-auto w-full max-w-5xl px-4 pt-4">
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              {rolloverMessage(identityCheck)}
            </div>
          </div>
        )}
        {/* Wrapper only renders when there's an actionable nudge (mirrors ChipNudgeCard's
            own null-return gate) — an unconditional wrapper would leave a blank padded
            strip above the pitch on every load where there's nothing to show. */}
        {chipPlanQuery.data?.nudge && chipPlanQuery.data.nudge.chip !== chipStrategy && (
          <div className="mx-auto w-full max-w-5xl px-4 pt-4">
            <ChipNudgeCard
              nudge={chipPlanQuery.data.nudge}
              activeChipStrategy={chipStrategy}
              onApplyChip={handleApplyChipNudge}
            />
          </div>
        )}
        <PitchVisualization
          entryId={entryId}
          onEntryIdSubmit={handleEntryIdSubmit}
          team={activeTeam}
          requestedGw={resolvedGW}
          onRequestedGwChange={setGwAndReset}
          gwSelectable={canChangeGw}
          isLoading={isLoading}
          errorMessage={activeErrorMessage}
          substitutionNotice={substitutionNotice}
          fixturesByTeam={fixturesByTeam}
          pitchMode={pitchMode}
          onPitchModeChange={setPitchMode}
          incoming={activeTeam === planTeam && resolvedPlan ? resolvedPlan.incoming : undefined}
          hasRecommendation={Boolean(recommendationMutation.data)}
          isLiveGw={isLiveGw}
          updatedAt={squadUpdatedAt}
          showActualPoints={showActualPoints}
          headerAction={
            <>
              {showOptimize && (
                <OptimizeSquadDialog
                  entryId={entryId}
                  horizonGws={horizonGws}
                  onApplied={handleOptimizeApplied}
                />
              )}
              {/* The single recommend entry point on desktop. The sidebar keeps
                  its own button for narrow viewports, where this bar has no room. */}
              <Button
                size="sm"
                className="hidden lg:inline-flex"
                onClick={handlePrimaryRecommend}
                disabled={!canRecommend || !(entryId > 0) || recommendationMutation.isPending}
                title={
                  planGw !== resolvedGW
                    ? `GW${resolvedGW} is in progress — plan GW${planGw} instead`
                    : undefined
                }
              >
                <Zap className="h-3.5 w-3.5" />
                {recommendationMutation.isPending
                  ? "Working…"
                  : planGw !== resolvedGW
                    ? `Plan GW${planGw}`
                    : "Recommend"}
              </Button>
            </>
          }
        />
        {entryId > 0 && plan && <PlanFooter spec={footer} onBack={onFooterBack} onNext={onFooterNext} />}
        </div>
      )}
      {step === "squad" && (
      <RecommendationsPanel
        squad={squadQuery.data}
        recommendation={activeRecommendation}
        isRecommending={recommendationMutation.isPending}
        horizonGws={horizonGws}
        appliedTransferCount={appliedTransferCount}
        isApplyingTransfer={recommendationMutation.isPending}
        onResetAppliedTransfers={resetAppliedTransfers}
        onApplyTransferAtIndex={applyTransferAtIndex}
        entryId={entryId}
        currentGw={selectedGW ?? undefined}
        chipPlan={chipPlanQuery.data ?? null}
        isChipPlanLoading={chipPlanQuery.isLoading}
        isChipPlanError={chipPlanQuery.isError}
      />
      )}
        </>
      )}
      </div>
    </div>
    </GwPlanValueProvider>
  );
};

export default Index;
