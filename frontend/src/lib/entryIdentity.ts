import type { FplEntryIdentity } from "@/lib/fplAssistantApi";

/**
 * Snapshot of who an entry id belonged to when the user linked it.
 * Persisted on the profile so a season rollover can be detected on load.
 */
export interface StoredEntryIdentity {
  managerName?: string | null;
  teamName?: string | null;
  joinedTime?: string | null;
}

export type EntityIdentityStatus = "ok" | "unknown" | "rolled-over";

export interface EntryIdentityCheck {
  status: EntityIdentityStatus;
  storedManager?: string | null;
  currentManager?: string | null;
  currentTeam?: string | null;
}

const norm = (value?: string | null) =>
  typeof value === "string" && value.trim() ? value.trim() : null;

/**
 * Compare the identity captured at link time against who the id resolves to now.
 *
 * `joined_time` is the decisive field: FPL reissues entry ids each season, and
 * the new manager's join timestamp differs. Manager name is only a fallback for
 * rows linked before the snapshot existed — a name can change without the id
 * being reissued.
 *
 * Team name is deliberately NOT compared. Managers rename their team mid-season
 * all the time, and treating that as a rollover would lock people out of their
 * own squad.
 */
export const checkEntryIdentity = (
  stored: StoredEntryIdentity | null | undefined,
  current: FplEntryIdentity | null | undefined,
): EntryIdentityCheck => {
  const currentManager = norm(current?.manager_name);
  const currentTeam = norm(current?.team_name);
  const storedManager = norm(stored?.managerName);

  // No snapshot (legacy row) or no lookup (upstream down) — cannot judge, and
  // must not block: a false rollover is worse than a missed one.
  if (!stored || !current) {
    return { status: "unknown", storedManager, currentManager, currentTeam };
  }

  const storedJoined = norm(stored.joinedTime);
  const currentJoined = norm(current.joined_time);

  if (storedJoined && currentJoined) {
    return storedJoined === currentJoined
      ? { status: "ok", storedManager, currentManager, currentTeam }
      : { status: "rolled-over", storedManager, currentManager, currentTeam };
  }

  if (storedManager && currentManager) {
    return storedManager.toLowerCase() === currentManager.toLowerCase()
      ? { status: "ok", storedManager, currentManager, currentTeam }
      : { status: "rolled-over", storedManager, currentManager, currentTeam };
  }

  return { status: "unknown", storedManager, currentManager, currentTeam };
};

/** Message shown when the stored id now belongs to somebody else. */
export const rolloverMessage = (check: EntryIdentityCheck): string => {
  const who = check.currentManager ? ` It now belongs to ${check.currentManager}.` : "";
  return (
    `This team ID isn't yours any more — FPL issues new IDs each season.${who} ` +
    `Open the Points tab on fantasy.premierleague.com and copy the ID from the URL.`
  );
};
