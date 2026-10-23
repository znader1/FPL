import { useMemo } from "react";
import { computeEntitlements, type Entitlements } from "@/lib/entitlements";
import { useProfile } from "@/hooks/useProfile";

export function useEntitlement(): Entitlements {
  const { profile } = useProfile();
  // TODO(pre-Stripe): while profile loads, plan defaults to "free" — gate UIs must handle profileLoading to avoid a paywall flash once BETA_ALL_ACCESS is off.
  return useMemo(
    () => computeEntitlements(profile?.plan ?? "free"),
    [profile?.plan]
  );
}
