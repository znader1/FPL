import { PLAN_STEPS, STEP_LABELS, type PlanStep } from "@/lib/gwPlan";
import type { WeekDecision } from "@/lib/weekDecisions";

interface StepChipsProps {
  decisions: WeekDecision[];
  step: PlanStep;
  onSelect: (step: PlanStep) => void;
}

/** Phone header's horizontal step row: the active chip in pink, ✓ / ! marks on decisions. */
export function StepChips({ decisions, step, onSelect }: StepChipsProps) {
  return (
    <div className="flex gap-1.5 overflow-x-auto px-4 py-2.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" role="group" aria-label="Plan steps">
      {PLAN_STEPS.map((k) => {
        const d = decisions.find((x) => x.key === k);
        const active = k === step;
        const mark = d?.warn ? "! " : d?.done ? "✓ " : "";
        return (
          <button
            key={k}
            type="button"
            onClick={() => onSelect(k)}
            aria-current={active ? "step" : undefined}
            className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
              active
                ? "border-primary bg-primary text-white"
                : d?.warn
                  ? "border-transparent bg-muted/60 text-fdr-4"
                  : "border-transparent bg-muted/60 text-foreground"
            }`}
          >
            {mark}
            {STEP_LABELS[k]}
          </button>
        );
      })}
    </div>
  );
}
