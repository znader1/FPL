import { fmtGain } from "@/lib/format";

interface ProjectedCardProps {
  gw: number;
  /** `projected_points_with_captain` of the active step; undefined before ZN Pick runs. */
  projected?: number;
  /** `transfer_impact.delta_projected_points_with_captain` once a move is applied. */
  delta?: number;
  /** Top-N percentile (8 = top 8%). Backend field `projected_percentile`; absent today. */
  percentile?: number;
  top10kAvg?: number;
  overallAvg?: number;
}

// Benchmark bars are scaled to a fixed 75-pt ceiling so You / Top 10k / Average
// read against the same axis week to week rather than always filling the row.
const BAR_SCALE = 75;
const fmt1 = (n: number) => (Math.round(n * 10) / 10).toFixed(1).replace(/\.0$/, "");

/** "PROJECTED GW29": the total, the applied-transfer delta, and — when the
 *  backend ships them — a percentile ring and benchmark bars. */
export function ProjectedCard({ gw, projected, delta, percentile, top10kAvg, overallAvg }: ProjectedCardProps) {
  const hasProjection = typeof projected === "number" && Number.isFinite(projected);
  const hasRing = hasProjection && typeof percentile === "number" && Number.isFinite(percentile);
  const bars =
    hasProjection && typeof top10kAvg === "number" && typeof overallAvg === "number"
      ? [
          { label: "You", v: projected as number, color: "bg-primary" },
          { label: "Top 10k", v: top10kAvg, color: "bg-accent" },
          { label: "Average", v: overallAvg, color: "bg-muted-foreground" },
        ]
      : null;

  return (
    <section aria-label={`Projected GW${gw}`} className="rounded-xl border border-border bg-card p-4">
      <p className="mb-3 text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">Projected GW{gw}</p>
      <div className="mb-4 flex items-center gap-3.5">
        {hasRing && (
          <div
            data-testid="percentile-ring"
            className="flex h-[72px] w-[72px] shrink-0 items-center justify-center rounded-full"
            style={{
              background: `conic-gradient(hsl(var(--primary)) 0 ${100 - (percentile as number)}%, hsl(var(--muted)) ${100 - (percentile as number)}% 100%)`,
            }}
          >
            <div className="flex h-[60px] w-[60px] flex-col items-center justify-center rounded-full bg-card">
              <span className="text-[15px] font-black tabular-nums text-foreground">{Math.round(percentile as number)}%</span>
              <span className="text-[9px] text-muted-foreground">TOP</span>
            </div>
          </div>
        )}
        <div>
          <div data-testid="projected-total" className="text-[30px] font-black leading-none tracking-tight tabular-nums text-foreground">
            {hasProjection ? fmt1(projected as number) : "—"}
          </div>
          {typeof delta === "number" && delta !== 0 ? (
            <div className={`mt-1 text-xs font-semibold ${delta > 0 ? "text-accent" : "text-[hsl(var(--fdr-4))]"}`}>
              {fmtGain(delta)} from your transfers
            </div>
          ) : (
            <div className="mt-1 text-xs text-muted-foreground">{hasProjection ? "xPts with captain" : "Run ZN Pick to project"}</div>
          )}
        </div>
      </div>
      {bars && (
        <div data-testid="benchmarks" className="flex flex-col gap-2">
          {bars.map((b) => (
            <div key={b.label} className="grid grid-cols-[64px_minmax(0,1fr)_34px] items-center gap-2 text-[11px]">
              <span className="text-muted-foreground">{b.label}</span>
              <div className="h-1.5 rounded-full bg-muted">
                <div
                  data-testid="benchmark-bar"
                  className={`h-full rounded-full ${b.color}`}
                  style={{ width: `${Math.min(100, Math.round((b.v / BAR_SCALE) * 100))}%` }}
                />
              </div>
              <span className="text-right font-semibold tabular-nums text-foreground">{fmt1(b.v)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
