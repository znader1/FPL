import { Badge } from "@/components/ui/badge";
import { fmtGain } from "@/lib/format";
import type { ChipWindow, WeakestLink } from "@/lib/fixturePlanner";

interface PlannerRailProps {
  chips: ChipWindow[];
  links: WeakestLink[];
  horizon: number;
  /** The recommendation feeds the links; say where it is instead of an empty list. */
  recommendationState?: "loading" | "ready" | "error";
  onRetryRecommendation?: () => void;
}

const Eyebrow = ({ children }: { children: React.ReactNode }) => (
  <p className="mb-2.5 text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">{children}</p>
);

/** Planner right rail: chip windows inside the grid, weakest links, FDR legend. */
export function PlannerRail({ chips, links, horizon, recommendationState = "ready", onRetryRecommendation }: PlannerRailProps) {
  return (
    <aside className="flex flex-col gap-4">
      <section>
        <Eyebrow>Chip windows</Eyebrow>
        <div className="flex flex-col gap-2">
          {chips.length === 0 && (
            <p className="text-xs text-muted-foreground">No chip window in these gameweeks — the Chips tab has the full season.</p>
          )}
          {chips.map((c) => (
            <div
              key={`${c.chip}-${c.gw}`}
              data-testid="chip-window"
              data-nudged={c.nudged}
              className={`rounded-xl border p-3 ${c.nudged ? "border-accent/40 bg-accent/[0.08]" : "border-border bg-card"}`}
            >
              <div className="mb-1 flex items-center justify-between">
                <span className="text-sm font-bold text-foreground">{c.label}</span>
                <span className={`text-xs font-bold ${c.nudged ? "text-accent" : "text-fdr-4"}`}>GW{c.gw}</span>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">{c.reason}</p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <Eyebrow>Weakest links · next {horizon} GW{horizon === 1 ? "" : "s"}</Eyebrow>
        <div className="flex flex-col gap-2">
          {links.length === 0 && recommendationState === "ready" && (
            <p className="text-xs text-muted-foreground">Nothing beats your current 15 over this window.</p>
          )}
          {recommendationState === "loading" && (
            <p className="text-xs text-muted-foreground">Loading your moves… the engine takes a few seconds.</p>
          )}
          {recommendationState === "error" && (
            <p className="text-xs text-muted-foreground">
              Couldn't load your moves.{" "}
              {onRetryRecommendation && (
                <button type="button" className="underline hover:text-foreground" onClick={onRetryRecommendation}>
                  Retry
                </button>
              )}
            </p>
          )}
          {recommendationState === "ready" && links.map((l) => (
            <div
              key={`${l.out}-${l.in}`}
              data-testid="weak-link"
              className="flex items-center gap-2.5 rounded-xl border border-border bg-card px-3 py-2.5"
            >
              <div className="min-w-0 flex-1">
                <div className="text-[13px] text-foreground">
                  <s className="text-muted-foreground">{l.out}</s> → <b>{l.in}</b>
                </div>
                <div className="mt-0.5 text-[11px] tabular-nums text-muted-foreground">
                  {typeof l.outX === "number" && typeof l.inX === "number" ? `${l.outX.toFixed(1)} → ${l.inX.toFixed(1)} xPts · ` : ""}
                  £{l.price.toFixed(1)}m
                </div>
              </div>
              <Badge variant="secondary" className="shrink-0 bg-accent/15 text-accent tabular-nums hover:bg-accent/15">
                {fmtGain(l.gain)}
              </Badge>
            </div>
          ))}
        </div>
      </section>

      <div data-testid="fdr-legend" className="mt-auto flex flex-col gap-2 pt-2">
        <div className="flex justify-between text-[11px] text-muted-foreground">
          <span>Easy</span>
          <span>Hard</span>
        </div>
        <div className="grid grid-cols-5 gap-[3px]">
          <div className="h-1.5 rounded-full bg-fdr-1" />
          <div className="h-1.5 rounded-full bg-fdr-2" />
          <div className="h-1.5 rounded-full bg-fdr-3" />
          <div className="h-1.5 rounded-full bg-fdr-4" />
          <div className="h-1.5 rounded-full bg-fdr-5" />
        </div>
      </div>
    </aside>
  );
}
