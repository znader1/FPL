import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
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

interface GwPlanContextValue {
  /** Null until the squad for this entry + GW has arrived. */
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

interface GwPlanProviderProps {
  entryId: number;
  gw: number;
  /** The squad query's data for the plan GW; the plan seeds from it once. */
  squad: FplSquad | undefined;
  children: ReactNode;
}

/**
 * One plan per entry + GW, persisted to localStorage (`fpl_gw_plan:{entry}:{gw}`).
 * Seeded once from the squad; restored on later visits while the squad still
 * holds the same 15 players, reseeded when it doesn't (the user transferred in
 * the FPL app). A new GW is a new key, so the deadline passing starts fresh.
 */
export function GwPlanProvider({ entryId, gw, squad, children }: GwPlanProviderProps) {
  const key = planStorageKey(entryId, gw);
  const [stored, setStored] = useState<StoredPlan | null>(null);
  const [storedKey, setStoredKey] = useState<string | null>(null);

  // Only the identity of the 15 matters for (re)seeding — a live-GW poll that
  // refreshes xPts must not touch the plan.
  const squadIds = squad ? [...squad.starting_xi, ...squad.bench].map((p) => p.player_id).sort((a, b) => a - b).join(",") : "";

  useEffect(() => {
    if (!squad || squadIds === "") {
      setStored(null);
      setStoredKey(null);
      return;
    }
    const existing = read(key);
    const next: StoredPlan =
      existing && samePlayers(existing.base, squad)
        ? existing
        : (() => {
            const seed = seedPlan(squad);
            return { plan: seed, base: seed };
          })();
    write(key, next);
    setStored(next);
    setStoredKey(key);
    // `squad` is intentionally reduced to `squadIds`; see the comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, squadIds]);

  const ready = stored !== null && storedKey === key;

  const setPlan = useCallback(
    (patch: PlanPatch) => {
      setStored((cur) => {
        if (!cur) return cur;
        const next = { ...cur, plan: applyPatch(cur.plan, patch) };
        write(key, next);
        return next;
      });
    },
    [key],
  );

  const resetPlan = useCallback(() => {
    setStored((cur) => {
      if (!cur) return cur;
      const next = { ...cur, plan: cur.base };
      write(key, next);
      return next;
    });
  }, [key]);

  const value = useMemo<GwPlanContextValue>(
    () => ({ plan: ready ? stored.plan : null, base: ready ? stored.base : null, setPlan, resetPlan }),
    [ready, stored, setPlan, resetPlan],
  );

  return <GwPlanContext.Provider value={value}>{children}</GwPlanContext.Provider>;
}

export function useGwPlan(): GwPlanContextValue {
  const ctx = useContext(GwPlanContext);
  if (!ctx) throw new Error("useGwPlan must be used inside a GwPlanProvider");
  return ctx;
}
