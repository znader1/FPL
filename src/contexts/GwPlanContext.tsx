import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  applyPatch,
  parseStoredPlan,
  planStorageKey,
  samePlayers,
  seedPlan,
  type GwPlan,
  type PlanPatch,
  type StoredPlan,
} from "@/lib/gwPlan";
import type { FplSquad } from "@/lib/fplAssistantApi";
import { supabasePlanRemote, type PlanRemote } from "@/lib/gwPlanRemote";

export interface GwPlanContextValue {
  /** Null until the squad for this entry + GW has arrived (or a stored plan exists). */
  plan: GwPlan | null;
  /** The seeded squad — what "no changes" and "Reset plan" mean. */
  base: GwPlan | null;
  setPlan: (patch: PlanPatch) => void;
  resetPlan: () => void;
}

const GwPlanContext = createContext<GwPlanContextValue | null>(null);

const read = (key: string): StoredPlan | null => {
  try {
    return parseStoredPlan(localStorage.getItem(key));
  } catch {
    return null;
  }
};
const write = (key: string, value: StoredPlan) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Private mode / quota: the plan still lives in memory for this session.
  }
};

export interface GwPlanStoreArgs {
  entryId: number;
  gw: number;
  /** The latest squad (the one the plan GW will be played with). Pass undefined
   *  while some other GW's picks are on screen; a stored plan stays readable. */
  squad: FplSquad | undefined;
  /** Signed-in user; without one the plan is this browser's only. */
  userId?: string | null;
  /** The account store (Supabase by default; tests inject a fake). */
  remote?: PlanRemote;
}

const SAVE_DEBOUNCE_MS = 500;
const newer = (a: StoredPlan | null, b: StoredPlan | null): StoredPlan | null => {
  if (!a) return b;
  if (!b) return a;
  // An untouched seed has no updatedAt and loses to anything with one.
  return (b.updatedAt ?? "") > (a.updatedAt ?? "") ? b : a;
};

/**
 * One plan per entry + GW. localStorage (`fpl_gw_plan:{entry}:{gw}`) is the
 * per-browser cache; the signed-in user's account (`gw_plans`) is the copy
 * that follows them across devices — newest `updatedAt` wins when both exist.
 * Seeded once from the squad; restored on later visits while the squad still
 * holds the same 15 players, reseeded when it doesn't (the user transferred in
 * the FPL app). A new GW is a new key, so the deadline passing starts fresh.
 * Nothing is written to the account until its copy has been read, so a seed
 * made while that read is in flight can never overwrite a real plan.
 */
export function useGwPlanStore({ entryId, gw, squad, userId, remote = supabasePlanRemote }: GwPlanStoreArgs): GwPlanContextValue {
  const key = planStorageKey(entryId, gw);
  const [stored, setStored] = useState<StoredPlan | null>(null);
  const [storedKey, setStoredKey] = useState<string | null>(null);
  // Which key the account has answered for (success or failure); writes to the
  // account are held until it matches.
  const [remoteSettled, setRemoteSettled] = useState<string | null>(null);
  const remoteKey = userId ? `${userId}|${key}` : null;
  const lastSaved = useRef<StoredPlan | null>(null);

  // Only the identity of the 15 matters for (re)seeding — a live-GW poll that
  // refreshes xPts must not touch the plan.
  const squadIds = squad ? [...squad.starting_xi, ...squad.bench].map((p) => p.player_id).sort((a, b) => a - b).join(",") : "";

  /** The plan to show for `candidate` given the squad on screen: itself while
   *  it still holds the same 15, a fresh seed otherwise (null with no squad). */
  const reconcile = useCallback(
    (candidate: StoredPlan | null): StoredPlan | null => {
      if (!squad || squadIds === "") return candidate;
      if (candidate && samePlayers(candidate.base, squad)) return candidate;
      const seed = seedPlan(squad);
      return { plan: seed, base: seed };
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [squadIds],
  );

  useEffect(() => {
    const next = reconcile(read(key));
    if (next) write(key, next);
    setStored(next);
    setStoredKey(key);
  }, [key, reconcile]);

  // Read the account's copy once per user + key and merge it in.
  useEffect(() => {
    if (!remoteKey || !userId) return;
    let cancelled = false;
    setRemoteSettled(null);
    remote
      .load({ userId, entryId, gw })
      .then((fromAccount) => {
        if (cancelled) return;
        if (fromAccount) {
          setStored((cur) => {
            const winner = newer(cur, fromAccount);
            const next = reconcile(winner);
            if (next && next !== cur) write(key, next);
            if (winner === fromAccount) lastSaved.current = fromAccount;
            return next;
          });
          setStoredKey(key);
        }
      })
      .catch(() => {
        // Offline or RLS hiccup: this browser's copy carries the session.
      })
      .finally(() => {
        if (!cancelled) setRemoteSettled(remoteKey);
      });
    return () => {
      cancelled = true;
    };
    // entryId/gw are what `remoteKey` encodes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remoteKey, remote, reconcile]);

  // Write edits to the account, debounced, only after it has answered for this key.
  useEffect(() => {
    if (!remoteKey || !userId || remoteSettled !== remoteKey || !stored || storedKey !== key) return;
    if (!stored.updatedAt || stored === lastSaved.current) return;
    const t = setTimeout(() => {
      lastSaved.current = stored;
      remote.save({ userId, entryId, gw }, stored).catch(() => {
        // Keep the local copy; the next edit retries.
        lastSaved.current = null;
      });
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stored, storedKey, key, remoteKey, remoteSettled, remote]);

  const ready = stored !== null && storedKey === key;

  const setPlan = useCallback(
    (patch: PlanPatch) => {
      setStored((cur) => {
        if (!cur) return cur;
        const next = { ...cur, plan: applyPatch(cur.plan, patch), updatedAt: new Date().toISOString() };
        write(key, next);
        return next;
      });
    },
    [key],
  );

  const resetPlan = useCallback(() => {
    setStored((cur) => {
      if (!cur) return cur;
      const next = { ...cur, plan: cur.base, updatedAt: new Date().toISOString() };
      write(key, next);
      return next;
    });
  }, [key]);

  return useMemo<GwPlanContextValue>(
    () => ({ plan: ready ? stored.plan : null, base: ready ? stored.base : null, setPlan, resetPlan }),
    [ready, stored, setPlan, resetPlan],
  );
}

/** Owns the store and provides it. */
export function GwPlanProvider({ children, ...args }: GwPlanStoreArgs & { children: ReactNode }) {
  const value = useGwPlanStore(args);
  return <GwPlanContext.Provider value={value}>{children}</GwPlanContext.Provider>;
}

/** Provides a store the parent already owns (Index derives from it before rendering). */
export function GwPlanValueProvider({ value, children }: { value: GwPlanContextValue; children: ReactNode }) {
  return <GwPlanContext.Provider value={value}>{children}</GwPlanContext.Provider>;
}

export function useGwPlan(): GwPlanContextValue {
  const ctx = useContext(GwPlanContext);
  if (!ctx) throw new Error("useGwPlan must be used inside a GwPlanProvider");
  return ctx;
}
