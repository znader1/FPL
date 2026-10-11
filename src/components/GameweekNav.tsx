import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight, Trophy, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { compactRank } from "@/lib/format";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface GameweekNavProps {
  currentGW: number;
  totalGW: number;
  points: number;
  rank: string;
  onPrev: () => void;
  onNext: () => void;
  navEnabled?: boolean;
  onSelectGW?: (gw: number) => void;
  isRecommendation?: boolean;
  isLiveGw?: boolean;
  /** `Date.now()`-style timestamp of the last successful squad fetch. */
  updatedAt?: number | null;
  /** Squad / ZN Pick toggle. Lives here rather than in its own row so the two
   *  control strips cost one band of vertical space instead of two. */
  leading?: ReactNode;
  /** Primary call to action, right-aligned. */
  action?: ReactNode;
}

export const GameweekNav = ({
  currentGW,
  totalGW,
  points,
  rank,
  onPrev,
  onNext,
  navEnabled = true,
  onSelectGW,
  isRecommendation = false,
  isLiveGw = false,
  updatedAt = null,
  leading,
  action,
}: GameweekNavProps) => {
  const stateLabel = isLiveGw ? "Live" : "Planning";
  const stateDotClass = isLiveGw ? "bg-rose-500 animate-pulse" : "bg-emerald-500";
  // Only while live: a frozen score and a genuine zero look identical without
  // a timestamp, and the difference is the whole reason to trust the number.
  const updatedLabel =
    isLiveGw && typeof updatedAt === "number" && updatedAt > 0
      ? new Date(updatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : null;
  // One row on phones (no wrap; the rank truncates before anything wraps),
  // free to wrap from sm up where the action button joins.
  return (
    <div className="flex flex-nowrap items-center gap-x-1.5 mb-3 bg-card border border-border rounded-xl px-2 py-1.5 sm:flex-wrap sm:gap-x-2 sm:gap-y-2 sm:px-2.5 lg:flex-nowrap">
      {leading}
      {/* GW navigation */}
      <div className="flex items-center gap-1.5 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          className="hidden h-7 w-7 text-muted-foreground hover:text-foreground sm:inline-flex"
          aria-label="Previous gameweek"
          onClick={onPrev}
          disabled={!navEnabled || currentGW <= 1}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>

        {onSelectGW ? (
          <Select
            value={String(currentGW)}
            onValueChange={(v) => onSelectGW(Number(v))}
            disabled={!navEnabled}
          >
            <SelectTrigger className="h-7 w-[68px] px-1 text-sm font-bold text-foreground border-0 bg-transparent focus:ring-0 sm:w-[92px] sm:px-1.5">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Array.from({ length: totalGW }, (_, i) => i + 1).map((gw) => (
                <SelectItem key={gw} value={String(gw)}>
                  GW {gw}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="text-sm font-bold text-foreground w-[108px] text-center">
            Gameweek {currentGW}
          </span>
        )}

        <Button
          variant="ghost"
          size="icon"
          className="hidden h-7 w-7 text-muted-foreground hover:text-foreground sm:inline-flex"
          aria-label="Next gameweek"
          onClick={onNext}
          disabled={!navEnabled || currentGW >= totalGW}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      {/* State pill. Live collapses to a pulsing dot (details on hover) so the
          bar keeps everything — including the Plan button — on one row. */}
      <div
        className="hidden items-center gap-1.5 shrink-0 rounded-full bg-muted/50 px-2 py-0.5 sm:flex"
        title={
          isLiveGw
            ? `Live${updatedLabel ? ` · last refreshed ${updatedLabel}` : ""}`
            : undefined
        }
        data-testid="gw-state-pill"
      >
        <span className={`h-1.5 w-1.5 rounded-full ${stateDotClass}`} />
        {!isLiveGw && (
          <span className="hidden lg:inline text-[11px] font-medium text-muted-foreground">{stateLabel}</span>
        )}
      </div>

      {/* Stats */}
      <div className="flex items-center gap-2 min-w-0 sm:gap-4">
        <div className="flex items-center gap-1 sm:gap-1.5">
          <Star className="h-3.5 w-3.5 text-primary shrink-0" />
          <span className="hidden xl:inline text-xs text-muted-foreground shrink-0">
            {isRecommendation ? "Proj. xPts" : "GW Pts"}
          </span>
          <span className="text-sm font-bold text-primary tabular-nums">{points}</span>
        </div>

        {!isRecommendation && rank !== "—" && (
          <>
            <div className="hidden xl:block h-4 w-px bg-border shrink-0" />
            <div className="flex items-center gap-1 min-w-0 sm:gap-1.5">
              <Trophy className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <span className="hidden xl:inline text-xs text-muted-foreground shrink-0">Rank</span>
              <span className="hidden text-sm font-bold text-foreground tabular-nums sm:inline">{rank}</span>
              <span className="text-sm font-bold text-foreground tabular-nums sm:hidden">{compactRank(rank)}</span>
            </div>
          </>
        )}
      </div>

      {action && <div className="flex items-center gap-2 shrink-0 ml-auto">{action}</div>}
    </div>
  );
};
