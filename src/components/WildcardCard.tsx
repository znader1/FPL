import { RefreshCw } from "lucide-react";
import { CHIP_LABELS, type ChipOutlookRow } from "@/lib/fplAssistantApi";
import { fmtGain } from "@/lib/format";

type Props = {
  /** The chip plan's wildcard outlook row; absent once the wildcard is played. */
  row: ChipOutlookRow | undefined;
  /** The pitch is showing the wildcard draft. */
  previewing: boolean;
  onToggle: () => void;
};

/** The wildcard on the main page: its best week and the engine's guidance, with a
 *  preview of the wildcard draft on the pitch. Quieter than ChipNudgeCard — it is an
 *  option, not a recommendation, until the backend's wildcard timing clears its bar. */
export const WildcardCard = ({ row, previewing, onToggle }: Props) => {
  if (!row) return null;
  const best = row.event_id !== null && row.ev_gain !== null ? { gw: row.event_id, gain: row.ev_gain } : null;

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <RefreshCw className="h-4 w-4 shrink-0 text-primary" />
      <div className="min-w-0 text-sm">
        <p>
          <span className="font-semibold">{CHIP_LABELS.wildcard}</span>
          {best ? (
            <>
              {" "}
              · best week GW{best.gw}, <span className="font-semibold text-primary">{fmtGain(best.gain)} xPts</span> over your squad
            </>
          ) : (
            " · no wildcard week stands out yet"
          )}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {previewing ? "The pitch shows the wildcard draft. Play it from the Chip step." : row.guidance}
        </p>
      </div>
      <button
        onClick={onToggle}
        className="ml-auto shrink-0 rounded-md border border-primary/50 px-3 py-1.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/10"
      >
        {previewing ? "Back to my squad" : "See wildcard squad"}
      </button>
    </div>
  );
};
