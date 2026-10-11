import { ChevronRight, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { WeekDecision } from "@/lib/weekDecisions";
import type { PlanStep } from "@/lib/gwPlan";

interface WeekChecklistProps {
  decisions: WeekDecision[];
  /** Compact strip for narrow viewports: one count line plus label-only chips. */
  compact?: boolean;
  /** When given, rows (and a "Squad overview" row) become buttons that open their step. */
  onSelect?: (step: PlanStep) => void;
  activeStep?: PlanStep;
  /** "Reset plan" (ghost) — shown only while `dirty`. */
  onReset?: () => void;
  dirty?: boolean;
}

/** "THIS WEEK · n of 4 decisions made" — the Command Center's left-rail checklist,
 *  and since the v2 flow the way between steps. */
export function WeekChecklist({ decisions, compact = false, onSelect, activeStep, onReset, dirty = false }: WeekChecklistProps) {
  const done = decisions.filter((d) => d.done).length;
  const pct = decisions.length ? Math.round((done / decisions.length) * 100) : 0;
  const interactive = Boolean(onSelect);

  const rowClass = (active: boolean, done: boolean, warn: boolean) =>
    `flex w-full items-center gap-2.5 rounded-[10px] border p-2.5 text-left transition-colors duration-200 ${
      active
        ? "border-primary/55 bg-primary/10"
        : warn
          ? "border-fdr-4/40 bg-fdr-4/[0.06]"
          : done
            ? "border-border bg-transparent"
            : "border-primary/40 bg-primary/[0.08]"
    } ${interactive ? "hover:bg-muted/60" : ""}`;

  const rowBody = (d: WeekDecision) => (
    <>
      <span
        aria-hidden
        className={`flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white ${
          d.warn ? "bg-fdr-4" : d.done ? "bg-accent" : "bg-muted"
        }`}
      >
        {d.warn ? "!" : d.done ? "✓" : ""}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-semibold text-foreground">{d.label}</span>
        <span className={`mt-px block truncate text-[11px] ${d.warn ? "text-fdr-4" : "text-muted-foreground"}`} title={d.value}>
          {d.value}
        </span>
      </span>
      {interactive && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />}
    </>
  );

  if (compact) {
    // Phone strip above the pitch: one line (count + Reset), a hairline bar,
    // and four label-only chips — the squad has to show in the first screen.
    return (
      <section aria-label="This week's decisions" className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-extrabold tracking-tight text-foreground">
            {done} of {decisions.length} decisions made
          </p>
          {onReset && dirty && (
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground" onClick={onReset}>
              Reset plan
            </Button>
          )}
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div data-testid="week-progress" className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${pct}%` }} />
        </div>
        <ul className="flex gap-1.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {decisions.map((d) => {
            const active = activeStep === d.key;
            const cls = `flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-semibold ${
              active
                ? "border-primary/55 bg-primary/10 text-foreground"
                : d.warn
                  ? "border-fdr-4/40 bg-fdr-4/[0.06] text-fdr-4"
                  : d.done
                    ? "border-border text-foreground"
                    : "border-primary/40 bg-primary/[0.08] text-foreground"
            }`;
            const mark = d.warn ? <span aria-hidden className="text-fdr-4">!</span> : d.done ? <span aria-hidden className="text-accent">✓</span> : null;
            return (
              <li key={d.key} data-done={d.done} data-warn={Boolean(d.warn)} data-active={active}>
                {interactive ? (
                  <button type="button" onClick={() => onSelect?.(d.key)} className={cls} title={d.value}>
                    {mark}
                    {d.label}
                  </button>
                ) : (
                  <span className={cls} title={d.value}>
                    {mark}
                    {d.label}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    );
  }

  return (
    <section aria-label="This week's decisions">
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">This week</p>
      <p className="mb-3.5 text-lg font-extrabold tracking-tight text-foreground">
        {done} of {decisions.length} decisions made
      </p>
      <div className="mb-4 h-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div
          data-testid="week-progress"
          className="h-full rounded-full bg-accent transition-[width] duration-300 ease-[cubic-bezier(.4,0,.2,1)]"
          style={{ width: `${pct}%` }}
        />
      </div>
      {interactive && (
        <button
          type="button"
          onClick={() => onSelect?.("squad")}
          data-active={activeStep === "squad"}
          className={`mb-1.5 flex w-full items-center gap-2.5 rounded-[10px] border p-2.5 text-left transition-colors duration-200 hover:bg-muted/60 ${
            activeStep === "squad" ? "border-primary/55 bg-primary/10" : "border-border"
          }`}
        >
          <span aria-hidden className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-muted">
            <Users className="h-3 w-3 text-muted-foreground" />
          </span>
          <span className="text-[13px] font-semibold text-foreground">Squad overview</span>
        </button>
      )}
      <ul className="flex flex-col gap-1.5">
        {decisions.map((d) => {
          const active = activeStep === d.key;
          return (
            <li key={d.key} data-done={d.done} data-warn={Boolean(d.warn)} data-active={active}>
              {interactive ? (
                <button type="button" onClick={() => onSelect?.(d.key)} className={rowClass(active, d.done, Boolean(d.warn))}>
                  {rowBody(d)}
                </button>
              ) : (
                <div className={rowClass(false, d.done, Boolean(d.warn))}>{rowBody(d)}</div>
              )}
            </li>
          );
        })}
      </ul>
      {onReset && dirty && (
        <Button variant="ghost" size="sm" className="mt-2 w-full text-muted-foreground" onClick={onReset}>
          Reset plan
        </Button>
      )}
    </section>
  );
}
