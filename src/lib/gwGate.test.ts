import { describe, it, expect } from "vitest";

import { resolveGwGateState } from "./gwGate";

/**
 * Regression guard for the wedged-/app bug (audit finding U1).
 *
 * `nextEventQuery` ran with `retry: false`, the snap-back effect returns early
 * on `isError` (deliberately — latching the GW-38 placeholder is what once
 * pinned users to GW38), and the render then fell through to a bare "Loading…"
 * with no error and no retry. One failed /events/next call wedged the app.
 */
describe("resolveGwGateState", () => {
  it("is ready once a gameweek is resolved", () => {
    expect(
      resolveGwGateState({
        gwResolved: true,
        nextEventError: false,
        nextEventFetching: false,
      }),
    ).toBe("ready");
  });

  it("surfaces an error instead of loading forever when next-event fails", () => {
    expect(
      resolveGwGateState({
        gwResolved: false,
        nextEventError: true,
        nextEventFetching: false,
      }),
    ).toBe("error");
  });

  it("shows loading while a retry is in flight, not the stale error", () => {
    expect(
      resolveGwGateState({
        gwResolved: false,
        nextEventError: true,
        nextEventFetching: true,
      }),
    ).toBe("loading");
  });

  it("shows loading on the first attempt", () => {
    expect(
      resolveGwGateState({
        gwResolved: false,
        nextEventError: false,
        nextEventFetching: true,
      }),
    ).toBe("loading");
  });

  it("stays ready even if a later refetch errors", () => {
    expect(
      resolveGwGateState({
        gwResolved: true,
        nextEventError: true,
        nextEventFetching: false,
      }),
    ).toBe("ready");
  });
});

import { isLatestSquad, shouldAutoRecommend } from "./gwGate";

describe("isLatestSquad (the squad the GW plan may seed from)", () => {
  const base = { squadEventId: 28, deadlineGw: 29, placeholder: false };
  it("accepts the finished GW between gameweeks and the live GW", () => {
    expect(isLatestSquad(base)).toBe(true); // between GWs: default view is GW28, deadline GW29
    expect(isLatestSquad({ ...base, squadEventId: 29 })).toBe(true); // substituted latest picks under a future GW
  });
  it("rejects a GW browsed back to, placeholder data, and an unknown deadline", () => {
    expect(isLatestSquad({ ...base, squadEventId: 20 })).toBe(false);
    expect(isLatestSquad({ ...base, placeholder: true })).toBe(false);
    expect(isLatestSquad({ ...base, deadlineGw: undefined })).toBe(false);
    expect(isLatestSquad({ ...base, squadEventId: undefined })).toBe(false);
  });
});

describe("isLatestSquad after a Free Hit", () => {
  // GW7 played with Free Hit, deadline GW8: /squad reverts to the GW6 picks.
  const base = { squadEventId: 6, deadlineGw: 8, placeholder: false };
  it("accepts the permanent squad the Free Hit was undone to", () => {
    expect(isLatestSquad({ ...base, freeHitRevertedFrom: 7 })).toBe(true);
  });
  it("still rejects an old squad with no Free Hit behind it", () => {
    expect(isLatestSquad(base)).toBe(false);
    expect(isLatestSquad({ ...base, freeHitRevertedFrom: null })).toBe(false);
  });
});

describe("shouldAutoRecommend (entering a flow step without ZN Pick's answer)", () => {
  const ok = { step: "transfers" as const, hasPlanRec: false, pending: false, canRecommend: true, entryId: 7, deadlineGw: 29, firedKey: null };
  it("fires once per entry + deadline GW, never on the squad step or while pending", () => {
    expect(shouldAutoRecommend(ok)).toBe("7:29");
    expect(shouldAutoRecommend({ ...ok, firedKey: "7:29" })).toBeNull();
    expect(shouldAutoRecommend({ ...ok, firedKey: "7:28" })).toBe("7:29");
    expect(shouldAutoRecommend({ ...ok, step: "squad" })).toBeNull();
    expect(shouldAutoRecommend({ ...ok, pending: true })).toBeNull();
    expect(shouldAutoRecommend({ ...ok, hasPlanRec: true })).toBeNull();
    expect(shouldAutoRecommend({ ...ok, deadlineGw: undefined })).toBeNull();
    expect(shouldAutoRecommend({ ...ok, entryId: 0 })).toBeNull();
    expect(shouldAutoRecommend({ ...ok, canRecommend: false })).toBeNull();
  });
});
