import { describe, expect, it } from "vitest";
import { computeEntitlements, BETA_ALL_ACCESS } from "../entitlements";

describe("computeEntitlements", () => {
  it("grants everything during beta regardless of plan", () => {
    const e = computeEntitlements("free");
    expect(e.canUseWildcardDrafter).toBe(true);
    expect(e.canUseMultiGwHorizon).toBe(true);
    expect(e.canUseLeagueDashboard).toBe(true);
  });

  it("beta flag is on", () => {
    expect(BETA_ALL_ACCESS).toBe(true);
  });

  it("free plan loses pro features when beta access is off", () => {
    const e = computeEntitlements("free", { betaAllAccess: false });
    expect(e.canUseWildcardDrafter).toBe(false);
    expect(e.canUseMultiGwHorizon).toBe(false);
    expect(e.canUseLeagueDashboard).toBe(false);
  });

  it("pro plan gets pro features but not elite when beta off", () => {
    const e = computeEntitlements("pro", { betaAllAccess: false });
    expect(e.canUseWildcardDrafter).toBe(true);
    expect(e.canUseMultiGwHorizon).toBe(true);
    expect(e.canUseLeagueDashboard).toBe(false);
  });

  it("elite gets everything when beta off", () => {
    const e = computeEntitlements("elite", { betaAllAccess: false });
    expect(e.canUseLeagueDashboard).toBe(true);
  });
});
