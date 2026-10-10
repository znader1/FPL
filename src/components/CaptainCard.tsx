import { Badge } from "@/components/ui/badge";
import { JerseyIcon } from "@/components/JerseyIcon";
import { FixtureChip } from "@/components/FixtureChip";
import type { CaptainCandidate } from "@/lib/captainLab";

interface CaptainCardProps {
  c: CaptainCandidate;
  selected: boolean;
  znPick: boolean;
  onSelect: (id: number) => void;
}

/** The range bar's axis: 0–20 points, so a 2–16 band reads the same on every card. */
const RANGE_MAX = 20;
const pct = (v: number) => Math.max(0, Math.min(100, (v / RANGE_MAX) * 100));

const fmtRank = (n: number) => `${n >= 0 ? "+" : "−"}${Math.round(Math.abs(n) / 1000)}k`;

/** One captain candidate: xPts hero, likely range, EO and rank-if-haul tiles, note. */
export function CaptainCard({ c, selected, znPick, onSelect }: CaptainCardProps) {
  const hasRange = typeof c.p10 === "number" && typeof c.p90 === "number";
  return (
    <button
      type="button"
      data-testid="captain-card"
      aria-pressed={selected}
      aria-label={`${c.name}, ${c.xpts.toFixed(1)} xPts`}
      onClick={() => onSelect(c.id)}
      className={`flex w-full flex-col gap-[18px] rounded-2xl border p-[22px] text-left transition-[border-color,background-color,box-shadow] duration-200 ${
        selected
          ? "border-primary/70 bg-primary/10 shadow-[0_0_0_1px_hsl(var(--primary)/.5),0_12px_40px_hsl(var(--primary)/.25)]"
          : "border-border bg-card hover:border-primary/30"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3.5">
          <JerseyIcon team={c.team} size="lg" isCaptain={selected} />
          <div>
            <div className="text-xl font-extrabold text-foreground">{c.name}</div>
            {c.fixture && (
              <div className="mt-1.5">
                <FixtureChip opponent={c.fixture.opponent} isHome={c.fixture.isHome} difficulty={c.fixture.difficulty} className="text-[10px]" />
              </div>
            )}
          </div>
        </div>
        {znPick && <Badge className="shrink-0 bg-primary text-white hover:bg-primary">ZN Pick</Badge>}
      </div>

      <div className="flex items-baseline gap-2">
        <span data-testid="cap-xpts" className="text-[56px] font-black leading-[.9] tracking-[-0.03em] tabular-nums text-foreground">
          {c.xpts.toFixed(1)}
        </span>
        <span className="text-[13px] text-muted-foreground">xPts (×2 = {c.doubled.toFixed(1)})</span>
      </div>

      <div>
        <div className="mb-1.5 flex justify-between text-[10px] font-semibold uppercase tracking-[.06em] text-muted-foreground">
          <span>Likely range</span>
          <span className="tabular-nums">{hasRange ? `${c.p10}–${c.p90} pts` : "—"}</span>
        </div>
        <div className="relative h-2.5 rounded-full bg-muted">
          {hasRange && (
            <>
              <div
                data-testid="range-fill"
                className="absolute inset-y-0 rounded-full"
                style={{
                  left: `${pct(c.p10 as number)}%`,
                  width: `${pct(c.p90 as number) - pct(c.p10 as number)}%`,
                  background: "linear-gradient(90deg, hsl(var(--primary) / .35), hsl(var(--primary)))",
                }}
              />
              <div
                data-testid="range-median"
                className="absolute -inset-y-[3px] w-[3px] rounded-sm bg-white"
                style={{ left: `calc(${pct(c.xpts)}% - 1px)` }}
                title={`Median ${c.xpts.toFixed(1)} xPts`}
              />
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        <div className="rounded-[10px] bg-background/60 px-3 py-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-[.06em] text-muted-foreground">Top 10k EO</div>
          <div className="mt-0.5 text-lg font-extrabold tabular-nums text-foreground">
            {typeof c.eoTop10k === "number" ? `${Math.round(c.eoTop10k)}%` : "—"}
          </div>
        </div>
        <div className="rounded-[10px] bg-background/60 px-3 py-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-[.06em] text-muted-foreground">Rank if he hauls</div>
          <div className={`mt-0.5 text-lg font-extrabold tabular-nums ${c.bigGain ? "text-accent" : "text-foreground"}`}>
            {typeof c.rankGainIfHaul === "number" ? fmtRank(c.rankGainIfHaul) : "—"}
          </div>
        </div>
      </div>

      <p className="text-xs leading-relaxed text-foreground/80">
        {typeof c.pHaul === "number"
          ? `${Math.round(c.pHaul * 100)}% chance of a 10+ haul${typeof c.eoTop10k === "number" ? (c.eoTop10k > 100 ? "; the top 10k already captain him, so a haul only keeps pace." : c.eoTop10k < 40 ? "; low captaincy among rivals makes this a real rank swing." : ".") : "."}`
          : "Range from the xG model's points distribution."}
      </p>
    </button>
  );
}
