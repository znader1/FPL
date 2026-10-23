import { ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fmtGain } from "@/lib/format";
import type { PlanStep } from "@/lib/gwPlan";
import type { ReviewRow, ReviewWarning } from "@/lib/planFlow";

interface ReviewStepProps {
  rows: ReviewRow[];
  onRow: (step: PlanStep) => void;
  warnings: ReviewWarning[];
  onFix: (step: PlanStep) => void;
  projected: number | null;
  delta: number | undefined;
  locked: boolean;
  /** What to change in the FPL app, once saved. */
  todo: string[];
  gw: number;
  countdown: string;
}

/** Review: warnings (blocking), the saved to-do panel, the four summary rows and the projected total. */
export function ReviewStep({ rows, onRow, warnings, onFix, projected, delta, locked, todo, gw, countdown }: ReviewStepProps) {
  const deltaTone = typeof delta !== "number" ? "" : delta > 0.05 ? "text-accent" : delta < -0.05 ? "text-fdr-4" : "text-muted-foreground";
  return (
    <div className="flex flex-col gap-3.5">
      {warnings.map((w) => (
        <div key={w.text} role="alert" className="flex items-center gap-2.5 rounded-xl border border-fdr-4/45 bg-fdr-4/10 px-3.5 py-3">
          <span className="flex-1 text-[13px] text-foreground">⚠ {w.text}</span>
          <Button type="button" variant="outline" size="sm" className="h-8" onClick={() => onFix(w.fixStep)}>
            Fix
          </Button>
        </div>
      ))}

      {locked && (
        <div className="flex flex-col gap-3 rounded-2xl border border-accent/45 bg-accent/[0.08] p-5">
          <div className="flex items-center gap-3">
            <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-lg font-bold text-white">✓</span>
            <div>
              <div className="text-lg font-extrabold text-foreground">GW{gw} plan saved</div>
              <div className="text-xs text-muted-foreground">
                Make these changes in the FPL app before the deadline{countdown ? ` (${countdown})` : ""}.
              </div>
            </div>
          </div>
          <ul className="flex flex-col gap-1.5">
            {todo.map((t) => (
              <li key={t} className="flex gap-2 text-[13px] text-foreground">
                <span className="font-bold text-accent" aria-hidden>›</span>
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        {rows.map((r) => (
          <button
            key={r.key}
            type="button"
            onClick={() => onRow(r.key)}
            className="flex min-h-[44px] w-full items-center gap-3 border-b border-border px-4 py-3.5 text-left transition-colors hover:bg-muted/40"
          >
            <span className="w-24 shrink-0 text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">{r.label}</span>
            <span className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{r.value}</span>
            {r.changed && <Badge variant="secondary" className="shrink-0">Changed</Badge>}
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          </button>
        ))}
        <div className="flex items-baseline justify-between px-4 py-4">
          <span className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">Projected points</span>
          <span>
            <span data-testid="review-projected" className="text-[32px] font-black tabular-nums text-primary">
              {projected === null ? "—" : projected.toFixed(1)}
            </span>
            {typeof delta === "number" && (
              <span data-testid="review-delta" className={`ml-1.5 text-[13px] font-semibold ${deltaTone}`}>
                {Math.abs(delta) < 0.05 ? "±0.0" : fmtGain(delta)}
              </span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
