import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/contexts/AuthContext";

export type PlanTier = "free" | "pro" | "elite";

export interface Profile {
  entryId: number | null;
  plan: PlanTier;
  /** Who the entry id belonged to when it was linked. Null on rows linked before this existed. */
  managerName: string | null;
  teamName: string | null;
  joinedTime: string | null;
}

/** Identity captured at link time, persisted so a rollover can be spotted later. */
export interface EntryIdentitySnapshot {
  managerName?: string | null;
  teamName?: string | null;
  joinedTime?: string | null;
}

const isPlanTier = (value: unknown): value is PlanTier =>
  value === "free" || value === "pro" || value === "elite";

/**
 * Loads the signed-in user's profile (FPL entry ID + plan tier) and exposes
 * a saver for the entry ID. Plan is read-only on the client.
 */
export function useProfile() {
  const { user } = useAuth();
  const userId = user?.id;
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  // Bumped on every saveEntryId call so an in-flight initial load can't
  // clobber a write that landed while the GET was pending.
  const writeVersion = useRef(0);

  useEffect(() => {
    if (!userId) {
      setProfile(null);
      setProfileLoading(false);
      return;
    }
    let cancelled = false;
    setProfileLoading(true);
    const versionAtFetch = writeVersion.current;
    supabase
      .from("profiles")
      .select("entry_id, plan, manager_name, team_name, entry_joined_time")
      .eq("id", userId)
      .maybeSingle()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (writeVersion.current === versionAtFetch) {
          if (error) {
            // Profile load failure must never block the app — fall back to defaults.
            setProfile({
              entryId: null, plan: "free",
              managerName: null, teamName: null, joinedTime: null,
            });
          } else {
            setProfile({
              entryId: typeof data?.entry_id === "number" ? data.entry_id : null,
              plan: isPlanTier(data?.plan) ? data.plan : "free",
              managerName: data?.manager_name ?? null,
              teamName: data?.team_name ?? null,
              joinedTime: data?.entry_joined_time ?? null,
            });
          }
        }
        setProfileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const saveEntryId = useCallback(
    async (entryId: number, identity?: EntryIdentitySnapshot): Promise<boolean> => {
      writeVersion.current += 1;
      const previous = profile;
      // The identity snapshot is what makes a season rollover detectable, so it
      // is written with the id rather than backfilled later.
      const next: Profile = {
        entryId,
        plan: previous?.plan ?? "free",
        managerName: identity?.managerName ?? null,
        teamName: identity?.teamName ?? null,
        joinedTime: identity?.joinedTime ?? null,
      };
      setProfile(next);
      // Signed-out: localStorage remains the primary store; profile is
      // cross-device sync only, so the local-only update counts as success.
      if (!userId) return true;
      // Never write `plan` from the client.
      const { error } = await supabase
        .from("profiles")
        .upsert({
          id: userId,
          entry_id: entryId,
          manager_name: next.managerName,
          team_name: next.teamName,
          entry_joined_time: next.joinedTime,
          entry_linked_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      if (error) {
        // Revert the optimistic update so the UI reflects reality.
        setProfile(previous);
        return false;
      }
      return true;
    },
    [userId, profile]
  );

  return { profile, profileLoading, saveEntryId };
}
