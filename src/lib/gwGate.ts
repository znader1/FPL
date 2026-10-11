/**
 * What /app should render before a gameweek has been resolved.
 *
 * The bug this closes: `nextEventQuery` ran with `retry: false`, the snap-back
 * effect returns early on `isError` (deliberately — latching the GW-38
 * placeholder is what once pinned users to GW38), and the render then fell
 * through to a bare "Loading…" with no error and no retry. So a single failed
 * /events/next call wedged the app permanently. Only first-time users were
 * exposed, since a stored `fpl_selected_gw` resolves the GW without the API —
 * and Fly's scale-to-zero makes one cold-start 502 enough to trigger it.
 *
 * See docs/prelaunch_audit_2026-09-12.md (U1) in the backend repo.
 */
export type GwGateState = "ready" | "loading" | "error";

export interface GwGateInput {
  /** True once a gameweek is known (from the API or from localStorage). */
  gwResolved: boolean;
  /** The /events/next query failed and is not currently retrying. */
  nextEventError: boolean;
  /** A fetch or retry is in flight. */
  nextEventFetching: boolean;
}

export const resolveGwGateState = ({
  gwResolved,
  nextEventError,
  nextEventFetching,
}: GwGateInput): GwGateState => {
  if (gwResolved) return "ready";
  // A retry in flight outranks the stale error — show the spinner, not the card.
  if (nextEventError && !nextEventFetching) return "error";
  return "loading";
};

/* ── GW plan gates (v2 flow) ─────────────────────────────────────────────── */

/**
 * Whether the squad on screen is the one the deadline GW will be played with,
 * i.e. safe to seed the GW plan from. Pre-deadline, picks can never be newer
 * than the GW before the deadline (the finished or live one), and `/squad` for
 * a future GW substitutes those same picks under a higher event_id — so
 * `event_id >= deadlineGw − 1` is the invariant. Placeholder data (the previous
 * GW's squad shown while a new one loads) never counts.
 */
export const isLatestSquad = (args: { squadEventId: number | undefined; deadlineGw: number | undefined; placeholder: boolean }): boolean => {
  const { squadEventId, deadlineGw, placeholder } = args;
  if (placeholder || typeof deadlineGw !== "number" || typeof squadEventId !== "number") return false;
  return squadEventId >= deadlineGw - 1;
};

/**
 * Entering a flow step needs ZN Pick's answer for the deadline GW. Returns the
 * key to fire for (`entry:gw`), or null. The caller remembers the last key it
 * fired so one plan never triggers more than one automatic run — whatever the
 * engine answers.
 */
export const shouldAutoRecommend = (args: {
  step: string;
  hasPlanRec: boolean;
  pending: boolean;
  canRecommend: boolean;
  entryId: number;
  deadlineGw: number | undefined;
  firedKey: string | null;
}): string | null => {
  const { step, hasPlanRec, pending, canRecommend, entryId, deadlineGw, firedKey } = args;
  if (step === "squad" || hasPlanRec || pending || !canRecommend || entryId <= 0 || typeof deadlineGw !== "number") return null;
  const key = `${entryId}:${deadlineGw}`;
  return firedKey === key ? null : key;
};
