import type { PlanTier } from "@/hooks/useProfile";

export interface Entitlements {
  plan: PlanTier;
  canUseWildcardDrafter: boolean;
  canUseMultiGwHorizon: boolean;
  canUseLeagueDashboard: boolean;
}

/**
 * Beta switch: while true, every plan gets full access.
 * Flipping this to false (post-Stripe) activates real plan gating —
 * components never read plan strings, only the flags below.
 */
export const BETA_ALL_ACCESS = true;

export function computeEntitlements(
  plan: PlanTier,
  opts?: { betaAllAccess?: boolean }
): Entitlements {
  const beta = opts?.betaAllAccess ?? BETA_ALL_ACCESS;
  if (beta) {
    return {
      plan,
      canUseWildcardDrafter: true,
      canUseMultiGwHorizon: true,
      canUseLeagueDashboard: true,
    };
  }
  const proOrBetter = plan === "pro" || plan === "elite";
  return {
    plan,
    canUseWildcardDrafter: proOrBetter,
    canUseMultiGwHorizon: proOrBetter,
    canUseLeagueDashboard: plan === "elite",
  };
}
