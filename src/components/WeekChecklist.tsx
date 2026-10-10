import type { WeekDecision } from "@/lib/weekDecisions";

interface WeekChecklistProps {
  decisions: WeekDecision[];
  /** Compact strip for narrow viewports: rows wrap into a 2-column grid. */
  compact?: boolean;
}

/** "THIS WEEK · n of 4 decisions made" — the Command Center's left-rail checklist. */
export function WeekChecklist({ decisions, compact = false }: WeekChecklistProps) {
  const done = decisions.filter((d) => d.done).length;
  const pct = decisions.length ? Math.round((done / decisions.length) * 100) : 0;
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
      <ul className={compact ? "grid grid-cols-2 gap-1.5" : "flex flex-col gap-1.5"}>
        {decisions.map((d) => (
          <li
            key={d.key}
            data-done={d.done}
            className={`flex items-center gap-2.5 rounded-[10px] border p-2.5 transition-colors duration-200 ${
              d.done ? "border-border bg-transparent" : "border-primary/40 bg-primary/[0.08]"
            }`}
          >
            <span
              aria-hidden
              className={`flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white ${
                d.done ? "bg-accent" : "bg-muted"
              }`}
            >
              {d.done ? "✓" : ""}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-semibold text-foreground">{d.label}</span>
              <span className="mt-px block truncate text-[11px] text-muted-foreground" title={d.value}>{d.value}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
