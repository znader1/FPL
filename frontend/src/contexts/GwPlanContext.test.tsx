// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { GwPlanProvider, useGwPlan } from "./GwPlanContext";
import { planStorageKey, seedPlan, type StoredPlan } from "@/lib/gwPlan";
import type { PlanRemote } from "@/lib/gwPlanRemote";
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

const wrap = (s: FplSquad | undefined, gw = 29, extra: { userId?: string; remote?: PlanRemote } = {}) =>
  ({ children }: { children: ReactNode }) => <GwPlanProvider entryId={7} gw={gw} squad={s} {...extra}>{children}</GwPlanProvider>;

/** In-memory stand-in for the Supabase row, resolving on demand so races can be staged. */
const fakeRemote = (initial: StoredPlan | null = null) => {
  let row = initial;
  let release: () => void = () => {};
  const gate = new Promise<void>((r) => (release = r));
  const remote: PlanRemote & { row: () => StoredPlan | null; release: () => void; save: ReturnType<typeof vi.fn> } = {
    load: vi.fn(async () => {
      await gate;
      return row;
    }),
    save: vi.fn(async (_args, stored: StoredPlan) => {
      row = stored;
    }),
    row: () => row,
    release: () => release(),
  };
  return remote;
};
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

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

  it("keeps a stored plan readable while the squad on screen is some other GW's", () => {
    localStorage.setItem(KEY, JSON.stringify({ plan: { ...seedPlan(squad), cap: 9 }, base: seedPlan(squad) }));
    const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(undefined) });
    expect(result.current.plan?.cap).toBe(9);
  });

  it("keys the plan by GW, so a new deadline starts a fresh plan", () => {
    localStorage.setItem(KEY, JSON.stringify({ plan: { ...seedPlan(squad), cap: 9 }, base: seedPlan(squad) }));
    const { result } = renderHook(() => useGwPlan(), { wrapper: wrap({ ...squad, event_id: 30 }, 30) });
    expect(result.current.plan?.cap).toBe(5);
    expect(localStorage.getItem(planStorageKey(7, 30))).toBeTruthy();
  });

  describe("account sync", () => {
    const seed = seedPlan(squad);
    const t0 = "2026-10-11T10:00:00.000Z";
    const t1 = "2026-10-11T11:00:00.000Z";

    it("restores the account's plan when this browser has none", async () => {
      const remote = fakeRemote({ plan: { ...seed, cap: 9, locked: true }, base: seed, updatedAt: t0 });
      const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad, 29, { userId: "u1", remote }) });
      remote.release();
      await flush();
      expect(result.current.plan).toMatchObject({ cap: 9, locked: true });
      expect(remote.load).toHaveBeenCalledWith({ userId: "u1", entryId: 7, gw: 29 });
      expect(JSON.parse(localStorage.getItem(KEY) ?? "{}").plan.cap).toBe(9);
    });

    it("a seed written before the account answers never overwrites the account's plan", async () => {
      const remote = fakeRemote({ plan: { ...seed, cap: 9 }, base: seed, updatedAt: t0 });
      const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad, 29, { userId: "u1", remote }) });
      expect(result.current.plan?.cap).toBe(5); // seeded locally meanwhile
      expect(remote.save).not.toHaveBeenCalled();
      remote.release();
      await flush();
      expect(result.current.plan?.cap).toBe(9);
      expect(remote.save).not.toHaveBeenCalled();
    });

    it("the newer side wins when both exist", async () => {
      localStorage.setItem(KEY, JSON.stringify({ plan: { ...seed, cap: 11 }, base: seed, updatedAt: t1 }));
      const remote = fakeRemote({ plan: { ...seed, cap: 9 }, base: seed, updatedAt: t0 });
      const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad, 29, { userId: "u1", remote }) });
      remote.release();
      await flush();
      expect(result.current.plan?.cap).toBe(11);
      localStorage.setItem(KEY, JSON.stringify({ plan: { ...seed, cap: 11 }, base: seed, updatedAt: t0 }));
      const remote2 = fakeRemote({ plan: { ...seed, cap: 9 }, base: seed, updatedAt: t1 });
      const { result: r2 } = renderHook(() => useGwPlan(), { wrapper: wrap(squad, 29, { userId: "u1", remote: remote2 }) });
      remote2.release();
      await flush();
      expect(r2.current.plan?.cap).toBe(9);
    });

    it("reseeds when the account's plan is for a different 15", async () => {
      const old = seedPlan({ ...squad, starting_xi: [...squad.starting_xi.slice(0, 10), mk(77, "FWD")] });
      const remote = fakeRemote({ plan: { ...old, cap: 77 }, base: old, updatedAt: t0 });
      const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad, 29, { userId: "u1", remote }) });
      remote.release();
      await flush();
      expect(result.current.plan).toMatchObject({ cap: 5, xi: seed.xi });
    });

    it("edits save to the account with a timestamp, once the account has answered", async () => {
      vi.useFakeTimers();
      try {
        const remote = fakeRemote(null);
        const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad, 29, { userId: "u1", remote }) });
        remote.release();
        await flush();
        act(() => result.current.setPlan({ cap: 9 }));
        expect("updatedAt" in (result.current.plan ?? {})).toBe(false); // timestamp lives on the stored wrapper, not the plan
        expect(JSON.parse(localStorage.getItem(KEY) ?? "{}").updatedAt).toMatch(/^\d{4}-/);
        await act(async () => { await vi.advanceTimersByTimeAsync(600); });
        expect(remote.save).toHaveBeenCalledTimes(1);
        expect(remote.save.mock.calls[0][0]).toEqual({ userId: "u1", entryId: 7, gw: 29 });
        expect(remote.row()?.plan.cap).toBe(9);
        expect(remote.row()?.updatedAt).toMatch(/^\d{4}-/);
      } finally {
        vi.useRealTimers();
      }
    });

    it("falls back to this browser's plan when the account cannot be read", async () => {
      localStorage.setItem(KEY, JSON.stringify({ plan: { ...seed, cap: 11 }, base: seed, updatedAt: t0 }));
      const remote: PlanRemote = { load: vi.fn(async () => { throw new Error("offline"); }), save: vi.fn(async () => {}) };
      const { result } = renderHook(() => useGwPlan(), { wrapper: wrap(squad, 29, { userId: "u1", remote }) });
      await flush();
      expect(result.current.plan?.cap).toBe(11);
    });

    it("signed out: no account calls at all", () => {
      const remote = fakeRemote(null);
      renderHook(() => useGwPlan(), { wrapper: wrap(squad, 29, { remote }) });
      expect(remote.load).not.toHaveBeenCalled();
    });
  });

  it("throws outside the provider", () => {
    expect(() => renderHook(() => useGwPlan())).toThrow(/GwPlanProvider/);
  });
});
