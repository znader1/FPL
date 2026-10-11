import { useEffect, useRef } from "react";
import { PLAN_STEPS, STEP_LABELS, type PlanStep } from "@/lib/gwPlan";
import type { WeekDecision } from "@/lib/weekDecisions";

interface StepChipsProps {
  decisions: WeekDecision[];
  step: PlanStep;
  onSelect: (step: PlanStep) => void;
}

/** Phone header's horizontal step row: the active chip in pink, ✓ / ! marks on decisions. */
export function StepChips({ decisions, step, onSelect }: StepChipsProps) {
  // Six chips overflow a phone width; the active one (Review, say) could sit
  // off the right edge with nothing hinting the row scrolls.
  const activeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [step]);
  const chip = (k: PlanStep, pinned: boolean) => {
    const d = decisions.find((x) => x.key === k);
    const active = k === step;
    const mark = d?.warn ? "! " : d?.done ? "✓ " : "";
    return (
      <button
        key={k}
        ref={active ? activeRef : undefined}
        type="button"
        data-pinned={pinned || undefined}
        data-state={d ? (d.warn ? "warn" : d.done ? "done" : "pending") : undefined}
        onClick={() => onSelect(k)}
        aria-current={active ? "step" : undefined}
        className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
          active
            ? "border-primary bg-primary text-white"
            : d?.warn
              ? "border-transparent bg-muted/60 text-fdr-4"
              : d && !d.done
                ? "border-primary/45 bg-primary/[0.08] text-foreground"
                : "border-transparent bg-muted/60 text-foreground"
        }`}
      >
        {mark}
        {STEP_LABELS[k]}
      </button>
    );
  };
  // Squad is pinned outside the scrolling row: the way home never slides off
  // the left edge when a later step scrolls into view.
  return (
    <div className="flex items-center py-2.5 pl-4" role="group" aria-label="Plan steps">
      <div className="flex shrink-0 border-r border-border pr-1.5">{chip("squad", true)}</div>
      <div className="flex gap-1.5 overflow-x-auto px-1.5 pr-4 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {PLAN_STEPS.filter((k) => k !== "squad").map((k) => chip(k, false))}
      </div>
    </div>
  );
}
