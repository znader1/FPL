import { supabase } from "@/integrations/supabase/client";
import type { Json } from "@/integrations/supabase/types";
import { parseStoredPlan, type StoredPlan } from "./gwPlan";

export interface PlanKey {
  userId: string;
  entryId: number;
  gw: number;
}

/** Where the account's copy of a GW plan lives. The store takes this as an
 *  argument so tests run against an in-memory one. */
export interface PlanRemote {
  load: (key: PlanKey) => Promise<StoredPlan | null>;
  save: (key: PlanKey, stored: StoredPlan) => Promise<void>;
}

/** Supabase `gw_plans`: one row per user + entry + GW, RLS-scoped to the user. */
export const supabasePlanRemote: PlanRemote = {
  async load({ userId, entryId, gw }) {
    const { data, error } = await supabase
      .from("gw_plans")
      .select("plan, base, updated_at")
      .eq("user_id", userId)
      .eq("entry_id", entryId)
      .eq("gw", gw)
      .maybeSingle();
    if (error) throw error;
    if (!data) return null;
    // Validate through the same gate as localStorage: a row from an older
    // client (or a hand edit) must not crash the store.
    return parseStoredPlan(JSON.stringify({ plan: data.plan, base: data.base, updatedAt: data.updated_at }));
  },
  async save({ userId, entryId, gw }, stored) {
    const { error } = await supabase.from("gw_plans").upsert(
      {
        user_id: userId,
        entry_id: entryId,
        gw,
        plan: stored.plan as unknown as Json,
        base: stored.base as unknown as Json,
        updated_at: stored.updatedAt ?? new Date().toISOString(),
      },
      { onConflict: "user_id,entry_id,gw" },
    );
    if (error) throw error;
  },
};
