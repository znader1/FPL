import { ArrowDown, ArrowUp, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import { JerseyIcon } from "@/components/JerseyIcon";
import type { PlayerLookup, ResolvedPlan } from "@/lib/gwPlan";

export interface BenchMessage {
  text: string;
  tone: "primary" | "accent" | "warning" | "danger";
}

interface BenchStepProps {
  resolved: ResolvedPlan;
  lookup: PlayerLookup;
  /** The bench player whose Swap is armed (pink row; starters outline on the pitch). */
  swapSelection: number | null;
  onSwapSelect: (id: number | null) => void;
  onMoveBench: (index: number, dir: -1 | 1) => void;
  /** The auto-sub preview tip. */
  autoSub: string;
  message: BenchMessage | null;
}

const TONE: Record<BenchMessage["tone"], string> = {
  primary: "border-primary/40 bg-primary/[0.08] text-primary",
  accent: "border-accent/40 bg-accent/[0.08] text-accent",
  warning: "border-warning/45 bg-warning/10 text-warning",
  danger: "border-fdr-4/45 bg-fdr-4/10 text-fdr-4",
};

/** Step 3: bench rows (order badge, jersey, name · pos · xPts, ↑ ↓, Swap) plus the tip
 *  and the rule/outcome message. The pitch above it comes from Index. */
export function BenchStep({ resolved, lookup, swapSelection, onSwapSelect, onMoveBench, autoSub, message }: BenchStepProps) {
  return (
    <div className="flex flex-col gap-3">
      {autoSub && (
        <div className="flex items-start gap-2.5 rounded-xl bg-muted/50 px-3.5 py-3">
          <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
          <p className="text-xs leading-relaxed text-foreground/85">{autoSub}</p>
        </div>
      )}
      {message && (
        <div role="status" className={`rounded-[10px] border px-3.5 py-2.5 text-[13px] font-semibold ${TONE[message.tone]}`}>
          {message.text}
        </div>
      )}
      <ul className="flex flex-col gap-1.5">
        {resolved.bench.map((id, i) => {
          const p = lookup[id];
          const selected = swapSelection === id;
          const movable = i > 0;
          return (
            <li
              key={id}
              data-testid="bench-row"
              data-selected={selected}
              className={`flex items-center gap-2.5 rounded-xl border px-2.5 py-2 transition-colors duration-200 ${
                selected ? "border-primary/70 bg-primary/10" : "border-border bg-card"
              }`}
            >
              <span data-testid="bench-order" className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-bold text-foreground">
                {i === 0 ? "GK" : String(i)}
              </span>
              <JerseyIcon team={p?.team_short ?? "???"} size="sm" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-semibold text-foreground">{p?.web_name ?? `#${id}`}</div>
                <div className="text-[11px] text-muted-foreground">
                  {p?.pos ?? "—"} · {typeof p?.xpts === "number" ? `${p.xpts.toFixed(1)} xPts` : "— xPts"}
                </div>
              </div>
              <div className="flex shrink-0 gap-1">
                {movable && (
                  <>
                    <Button type="button" variant="ghost" size="icon" className="h-9 w-9" disabled={i <= 1} onClick={() => onMoveBench(i, -1)} aria-label="Move up">
                      <ArrowUp className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-9 w-9"
                      disabled={i >= resolved.bench.length - 1}
                      onClick={() => onMoveBench(i, 1)}
                      aria-label="Move down"
                    >
                      <ArrowDown className="h-4 w-4" />
                    </Button>
                  </>
                )}
                <Button
                  type="button"
                  variant={selected ? "default" : "outline"}
                  size="sm"
                  className="h-9 min-w-[64px] text-xs"
                  onClick={() => onSwapSelect(selected ? null : id)}
                >
                  {selected ? "Cancel" : "Swap"}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
