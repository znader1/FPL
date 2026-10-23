import type { ReactNode } from "react";
import { ArrowRightLeft } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { FplTransfersRecommendation } from "@/lib/fplAssistantApi";

interface TransferPlannerProps {
  transfers?: FplTransfersRecommendation;
  planSlot?: ReactNode;
  isLoading?: boolean;
  /** Plan horizon, for the ranking subtitle. */
  horizonGws?: number;
}

/** The Transfer moves card is a shell around the plan slot — the decision
 * card's move cards + collapsed staircase are the only advice on this tab.
 * The beam alternatives list and Hot Targets moved off entirely: the beam
 * still feeds Apply indexing server-side but is no longer displayed, and
 * Hot Targets now lives on the Watchlist tab (`HotTargets.tsx`). */
export const TransferPlanner = ({ transfers, planSlot, isLoading = false, horizonGws }: TransferPlannerProps) => {
  const hasMoves = (transfers?.moves ?? []).length > 0;
  const window = horizonGws === 1 ? "this GW" : `over the next ${horizonGws ?? 3} GWs`;

  return (
    <Card className="p-4 space-y-3">
      <div>
        <h3 className="font-bold text-foreground flex items-center gap-2">
          <ArrowRightLeft className="h-4 w-4 text-primary" />
          Transfer moves
        </h3>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          Ranked by xPts gained {window}, after the cost of any hit.
        </p>
      </div>

      {planSlot}

      {isLoading && (
        <div className="rounded-lg border border-border p-3 text-sm text-muted-foreground">
          Computing transfer suggestions…
        </div>
      )}
      {!isLoading && !planSlot && !hasMoves && (
        <div className="rounded-lg border border-border p-3 text-sm text-muted-foreground">
          No transfer suggestions returned.
        </div>
      )}
    </Card>
  );
};
