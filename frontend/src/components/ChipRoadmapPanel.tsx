import { useState } from "react";
import { CalendarDays, ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import {
  CHIP_LABELS,
  EUROPEAN_LABELS,
  type ChipCalendarRow,
  type ChipDistribution,
  type ChipOutlookRow,
  type ChipPlanRecommendation,
  type ChipPlanResponse,
  type EuropeanCompetition,
} from "@/lib/fplAssistantApi";

type Props = {
  isError?: boolean;
  plan: ChipPlanResponse | null | undefined;
  isLoading: boolean;
};

const pct = (v: number) => `${Math.round(v * 100)}%`;

const EvCurve = ({ points }: { points: ChipPlanRecommendation["ev_curve"] }) => {
  if (!points.length) return null;
  const max = Math.max(...points.map((p) => p.ev), 1);
  const hasOdds = points.some((p) => p.p_beats_bar !== undefined);
  return (
    <div className="mt-2">
      <div className="flex items-end gap-1 h-10" aria-label="EV by gameweek">
        {points.map((p) => {
          const odds = p.p_beats_bar;
          const title =
            `GW${p.gw}: +${p.ev.toFixed(1)} xPts` +
            (odds !== undefined ? ` · ${pct(odds)} chance to beat the bar` : "") +
            (p.european ? ` · ${p.european} in European weeks` : "") +
            (p.post_break ? " · post-break" : "");
          return (
            <div key={p.gw} className="flex flex-col items-center gap-0.5">
              <div
                className="w-4 rounded-t bg-primary"
                style={{
                  height: `${Math.max(4, (p.ev / max) * 32)}px`,
                  opacity: odds !== undefined ? 0.35 + 0.65 * odds : 0.7,
                }}
                title={title}
              />
              {/* The bar above owns the tooltip; repeating `title` here made
                  every GW's title match two elements. */}
              <span
                className={`text-[9px] ${
                  p.post_break || p.european ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"
                }`}
              >
                {p.gw}
              </span>
            </div>
          );
        })}
      </div>
      {hasOdds && (
        <p className="text-[10px] text-muted-foreground mt-1">
          bar height = EV · shade = chance the chip beats its bar that week
        </p>
      )}
    </div>
  );
};

const DistributionLine = ({ d, chip }: { d: ChipDistribution; chip: ChipPlanRecommendation["chip"] }) => {
  const subject = chip === "bench_boost" ? "bench" : "captain";
  return (
    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
      {d.p_beats_bar !== undefined && (
        <span>
          <span className="font-semibold text-foreground">{pct(d.p_beats_bar)}</span> beats the bar
        </span>
      )}
      {d.p_return !== undefined && (
        <span>
          <span className="font-semibold text-foreground">{pct(d.p_return)}</span> {subject} returns (6+)
        </span>
      )}
      {d.p_haul !== undefined && (
        <span>
          <span className="font-semibold text-foreground">{pct(d.p_haul)}</span> haul (10+)
        </span>
      )}
      {d.p_blank !== undefined && (
        <span>
          <span className="font-semibold text-foreground">{pct(d.p_blank)}</span> blank
        </span>
      )}
      <span className="whitespace-nowrap">
        most likely {d.modal} · 80% band {d.p80_low}–{d.p80_high}
        {d.p80_open ? "+" : ""}
      </span>
    </div>
  );
};

const RecommendationRow = ({ rec }: { rec: ChipPlanRecommendation }) => {
  const [open, setOpen] = useState(false);
  const expected = rec.provisional && rec.likelihood !== undefined && rec.likelihood < 1;
  return (
    <div className="rounded-lg border border-border p-3">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="font-semibold text-sm">{CHIP_LABELS[rec.chip]}</span>
          {rec.provisional && (
            <span className="text-[10px] font-semibold uppercase tracking-wide rounded-full border border-dashed border-muted-foreground/50 text-muted-foreground px-2 py-0.5">
              {expected ? `~${pct(rec.likelihood as number)} likely` : "provisional"}
            </span>
          )}
          {rec.distribution?.p_beats_bar !== undefined && (
            <span
              className="text-[10px] font-medium rounded-full bg-primary/10 text-primary px-2 py-0.5 whitespace-nowrap"
              title="Chance the chip's extra points clear its play/hold bar"
            >
              {pct(rec.distribution.p_beats_bar)} beats bar
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-sm font-bold">GW{rec.event_id}</span>
          {rec.ev_gain !== null && (
            <span className="text-sm font-semibold text-primary">+{rec.ev_gain.toFixed(1)} xPts</span>
          )}
        </div>
      </button>
      {open && (
        <div className="mt-2 pl-5">
          {rec.guidance && <p className="text-xs text-foreground">{rec.guidance}</p>}
          {rec.distribution && <DistributionLine d={rec.distribution} chip={rec.chip} />}
          <ul className="space-y-1 mt-1.5">
            {rec.reasons.map((reason) => (
              <li
                key={reason}
                className={`text-xs ${
                  reason.startsWith("Risk:") ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"
                }`}
              >
                {reason}
              </li>
            ))}
          </ul>
          <EvCurve points={rec.ev_curve} />
        </div>
      )}
    </div>
  );
};

const OutlookRow = ({ row, expiresGw }: { row: ChipOutlookRow; expiresGw?: number }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border/60 p-2.5">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="text-sm text-muted-foreground font-medium truncate">{CHIP_LABELS[row.chip]}</span>
          <span className="text-[10px] font-semibold uppercase tracking-wide rounded-full border border-muted-foreground/40 text-muted-foreground px-2 py-0.5 shrink-0">
            hold
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
          {row.event_id !== null ? (
            <>
              <span className="font-semibold text-foreground">GW{row.event_id}</span>
              {row.ev_gain !== null && (
                <span className="whitespace-nowrap">
                  +{row.ev_gain.toFixed(1)} vs bar {row.bar.toFixed(0)}
                  {row.distribution?.p_beats_bar !== undefined && ` · ${pct(row.distribution.p_beats_bar)} odds`}
                </span>
              )}
            </>
          ) : (
            <span>no window</span>
          )}
        </div>
      </button>
      {open && (
        <div className="mt-2 pl-5">
          {row.guidance && <p className="text-xs text-foreground">{row.guidance}</p>}
          {row.distribution && <DistributionLine d={row.distribution} chip={row.chip} />}
          {row.guidance ? (
            <details className="mt-1.5">
              <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">
                model detail
              </summary>
              <ul className="space-y-1 mt-1">
                {row.reasons.map((reason) => (
                  <li key={reason} className="text-xs text-muted-foreground">
                    {reason}
                  </li>
                ))}
                {expiresGw !== undefined && (
                  <li className="text-xs text-muted-foreground/70">expires GW{expiresGw}</li>
                )}
              </ul>
            </details>
          ) : (
            <ul className="space-y-1 mt-1.5">
              {row.reasons.map((reason) => (
                <li key={reason} className="text-xs text-muted-foreground">
                  {reason}
                </li>
              ))}
              {expiresGw !== undefined && (
                <li className="text-xs text-muted-foreground/70">expires GW{expiresGw}</li>
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};

/* ── Fixture calendar strip ──────────────────────────────────────────────── */

const isNotable = (r: ChipCalendarRow) =>
  r.post_break || r.has_dgw || r.is_blank_heavy || r.cup_clash !== null;

const Tag = ({ tone, title, children }: { tone: "amber" | "blue" | "red" | "green" | "muted"; title?: string; children: React.ReactNode }) => {
  const cls = {
    amber: "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-400",
    blue: "border-sky-500/50 bg-sky-500/10 text-sky-700 dark:text-sky-400",
    red: "border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400",
    green: "border-emerald-500/50 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
    muted: "border-muted-foreground/30 text-muted-foreground",
  }[tone];
  return (
    <span title={title} className={`rounded-full border px-1.5 py-px text-[9px] font-semibold leading-tight whitespace-nowrap max-w-full overflow-hidden text-ellipsis ${cls}`}>
      {children}
    </span>
  );
};

const CalendarCell = ({ row, isCurrent }: { row: ChipCalendarRow; isCurrent: boolean }) => {
  const euroNames = row.squad_european.map((p) => `${p.name} (${EUROPEAN_LABELS[p.competition] ?? p.competition})`).join(", ");
  const euroComps = (Object.keys(row.european) as EuropeanCompetition[]).filter((c) => (row.european[c] ?? []).length > 0);
  const deadline = row.deadline_utc
    ? new Date(row.deadline_utc).toLocaleDateString(undefined, { day: "numeric", month: "short" })
    : null;
  return (
    <div
      className={`flex flex-col gap-1 rounded-md border px-2 py-1.5 min-w-[74px] max-w-[112px] overflow-hidden ${
        isCurrent ? "border-primary/60 bg-primary/5" : row.in_model_zone ? "border-border" : "border-dashed border-border/60"
      }`}
    >
      <div className="flex items-baseline justify-between gap-1">
        <span className="text-xs font-bold">GW{row.gw}</span>
        {deadline && <span className="text-[9px] text-muted-foreground whitespace-nowrap">{deadline}</span>}
      </div>
      <div className="flex flex-wrap gap-1">
        {row.post_break && (
          <Tag tone="amber" title={`First GW after an international break (${row.break_gap_days ?? "?"} days between deadlines)`}>
            break
          </Tag>
        )}
        {row.has_dgw && (
          <Tag tone="green" title={`Double gameweek: ${row.dgw_teams.join(", ") || "announced"}`}>
            DGW
          </Tag>
        )}
        {row.is_blank_heavy && (
          <Tag tone="red" title={`Blank gameweek: ${row.blank_teams.join(", ") || `${row.n_teams_playing} teams play`}`}>
            BGW
          </Tag>
        )}
        {row.cup_clash && (
          <Tag
            tone={row.cup_clash.likely_blank ? "red" : "muted"}
            title={`${row.cup_clash.competition.replace("_", " ")} ${row.cup_clash.label} weekend${
              row.cup_clash.likely_blank ? " — usually becomes a blank GW" : ""
            }`}
          >
            cup
          </Tag>
        )}
        {row.squad_european.length > 0 ? (
          <Tag tone="blue" title={`Your players in European weeks: ${euroNames}`}>
            {row.squad_european.length} in Europe
          </Tag>
        ) : (
          euroComps.length > 0 && (
            <Tag tone="muted" title={euroComps.map((c) => `${EUROPEAN_LABELS[c] ?? c}: ${(row.european[c] ?? []).join(", ")}`).join(" · ")}>
              Europe
            </Tag>
          )
        )}
      </div>
    </div>
  );
};

const FixtureCalendar = ({ plan }: { plan: ChipPlanResponse }) => {
  const rows = plan.calendar ?? [];
  if (!rows.length) return null;
  const modelZone = rows.filter((r) => r.in_model_zone);
  const later = rows.filter((r) => !r.in_model_zone && isNotable(r));
  const euroOff = plan.signals && !plan.signals.european_calendar;
  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Fixture context</h4>
        {plan.signals?.european_xpts_mult != null && plan.signals.european_xpts_mult < 1 && (
          <span className="text-[10px] text-muted-foreground ml-auto" title="Every player of a team in a European week carries this multiplier on both sides of each chip comparison">
            European weeks ×{plan.signals.european_xpts_mult.toFixed(2)} xPts
          </span>
        )}
      </div>
      <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1">
        {modelZone.map((r) => (
          <CalendarCell key={r.gw} row={r} isCurrent={r.gw === plan.current_gw} />
        ))}
      </div>
      {later.length > 0 && (
        <details className="mt-1.5">
          <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">
            Beyond the model horizon · {later.length} notable {later.length === 1 ? "week" : "weeks"}
          </summary>
          <div className="flex gap-1.5 overflow-x-auto pb-1 mt-1.5 -mx-1 px-1">
            {later.map((r) => (
              <CalendarCell key={r.gw} row={r} isCurrent={false} />
            ))}
          </div>
        </details>
      )}
      {euroOff && (
        <p className="text-[10px] text-muted-foreground/80 mt-1">
          European calendar not configured — Champions/Europa League weeks aren't factored in yet.
        </p>
      )}
    </div>
  );
};

export const ChipRoadmapPanel = ({ plan, isLoading, isError = false }: Props) => {
  if (isLoading && !plan) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        Analyzing chip windows…
      </div>
    );
  }
  if (isError && !plan) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        Couldn't load the chip plan — the chip-planner service isn't available yet.
      </div>
    );
  }
  if (!plan) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        No chip plan yet — set your entry ID and gameweek.
      </div>
    );
  }

  const recommendedChips = new Set(plan.recommendations.map((r) => r.chip));
  const holds = plan.chips_remaining.filter(
    (c) => c.available && !recommendedChips.has(c.name)
  );
  const used = plan.chips_remaining.filter((c) => !c.available);
  const outlookHolds = (plan.outlook ?? []).filter((o) => o.status === "hold");
  const expiresByChip = new Map(plan.chips_remaining.map((c) => [c.name, c.expires_gw]));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-bold">Chip roadmap</h3>
        <span className="text-[10px] text-muted-foreground ml-auto">
          model horizon: {plan.horizon_model_gws} GWs
        </span>
      </div>

      <FixtureCalendar plan={plan} />

      {plan.recommendations.length > 0 ? (
        <div className="space-y-2">
          {plan.recommendations.map((rec) => (
            <RecommendationRow key={`${rec.chip}-${rec.event_id}`} rec={rec} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          No chip clears the bar in the next {plan.horizon_model_gws} gameweeks — holding
          everything is the recommended play.
        </p>
      )}

      {outlookHolds.length > 0 ? (
        <div>
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">
            Outlook — holding
          </h4>
          <div className="space-y-1.5">
            {outlookHolds.map((row) => (
              <OutlookRow key={row.chip} row={row} expiresGw={expiresByChip.get(row.chip)} />
            ))}
          </div>
        </div>
      ) : holds.length > 0 ? (
        <div>
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">
            Holding
          </h4>
          <ul className="space-y-1">
            {holds.map((c) => (
              <li key={c.name} className="text-xs text-muted-foreground flex justify-between">
                <span>{CHIP_LABELS[c.name]}</span>
                <span>expires GW{c.expires_gw}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {used.length > 0 && (
        <div>
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">
            Used this half
          </h4>
          <ul className="space-y-1">
            {used.map((c) => (
              <li key={c.name} className="text-xs text-muted-foreground/70 flex justify-between">
                <span>{CHIP_LABELS[c.name]}</span>
                <span>used</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
