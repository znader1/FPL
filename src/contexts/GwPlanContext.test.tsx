// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ReactNode } from "react";
import { GwPlanProvider, useGwPlan } from "./GwPlanContext";
import { planStorageKey, seedPlan } from "@/lib/gwPlan";
import type { FplPosition, FplSquad, FplTeamRecommendationPlayer } from "@/lib/fplAssistantApi";

const mk = (id: number, pos: FplPosition): FplTeamRecommendationPlayer => ({
  player_id: id, web_name: `P${id}`, pos, team_short: "AAA", team_name: "A", is_captain: id === 5, is_vice_captain: id === 6, multiplier: 1, xpts: 3,
});
const squad: FplSquad = {
  entry_id: 7,
  event_id: 29,
  starting_xi: [mk(1, "GKP"), mk(2, "DEF"), mk(3, "DEF"), mk(4, "DEF"), mk(5, "MID"), mk(6, "MID"), mk(7, "MID"), mk(8, "MID"), mk(9, "FWD"), mk(10, "FWD"), mk(11, "FWD")],
  bench: [{ ...mk(12, "GKP"), bench_order: 1 }, { ...mk(13, "DEF"), bench_order: 2 }, { ...mk(14, "MID"), bench_order: 3 }, { ...mk(15, "FWD"), bench_order: 4 }],
  captain_player_id: 5,
  vice_player_id: 6,
};
const KEY = planStorageKey(7, 29);

const wrap = (s: FplSquad | undefined, gw = 29) =>
  ({ children }: { children: ReactNode }) => <GwPlanProvider entryId={7} gw={gw} squad={s}>{children}</GwPlanProvider>;

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe("GwPlanProvider", () => {
  it("has no plan until the squad arrives, then seeds from it and persists", () => {
    const { result, rerender } = renderHook(() => useGwPlan(), { wrapper: wrap(undefined) });
    expect(result.current.plan).toBeNull();
    rerender();
    expect(result.current.plan).toBeNull();
    const { result: r2 } = renderHook(() => useGwPlan(), { wrapper: wrap(squad) });
    expect(r2.current.plan).toEqual(seedPlan(squad));
    expect(JSON.parse(localStorage.getItem(KEY) ?? "{}").plan).toEqual(seedPlan(squad));
  });

  it("restores a stored plan for the same 15 players instead of reseeding", () => {
    const stored = { plan: { ...seedPlan(squad), cap: 9, locked: true }, base: seedPlan(squad) };
    localStorage.setItem(KEY, JSON.stringify(stored));
    const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad) });
    expect(result.current.plan?.cap).toBe(9);
    expect(result.current.plan?.locked).toBe(true);
  });

  it("reseeds when the stored plan no longer matches the squad's players", () => {
    const old = seedPlan({ ...squad, starting_xi: [...squad.starting_xi.slice(0, 10), mk(77, "FWD")] });
    localStorage.setItem(KEY, JSON.stringify({ plan: { ...old, cap: 77 }, base: old }));
    const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad) });
    expect(result.current.plan).toEqual(seedPlan(squad));
  });

  it("setPlan applies the patch, unlocks on material edits, and writes through", () => {
    const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad) });
    act(() => result.current.setPlan({ locked: true }));
    expect(result.current.plan?.locked).toBe(true);
    act(() => result.current.setPlan((p) => ({ vice: p.cap, cap: p.vice })));
    expect(result.current.plan).toMatchObject({ cap: 6, vice: 5, locked: false });
    expect(JSON.parse(localStorage.getItem(KEY) ?? "{}").plan.cap).toBe(6);
  });

  it("resetPlan is the only way back to the seeded squad", () => {
    const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad) });
    act(() => result.current.setPlan({ cap: 9, transfer: "make", chip: "bench_boost", reviewed: { chip: true } }));
    act(() => result.current.resetPlan());
    expect(result.current.plan).toEqual(seedPlan(squad));
    expect(result.current.base).toEqual(seedPlan(squad));
  });

  it("keys the plan by GW, so a new deadline starts a fresh plan", () => {
    localStorage.setItem(KEY, JSON.stringify({ plan: { ...seedPlan(squad), cap: 9 }, base: seedPlan(squad) }));
    const { result } = renderHook(() => useGwPlan(), { wrapper: wrap({ ...squad, event_id: 30 }, 30) });
    expect(result.current.plan?.cap).toBe(5);
    expect(localStorage.getItem(planStorageKey(7, 30))).toBeTruthy();
  });

  it("throws outside the provider", () => {
    expect(() => renderHook(() => useGwPlan())).toThrow(/GwPlanProvider/);
  });
});
