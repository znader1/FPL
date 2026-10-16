import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { JerseyIcon } from "@/components/JerseyIcon";
import { FixtureChip } from "@/components/FixtureChip";
import type { CaptainCandidate } from "@/lib/captainLab";

interface CaptainCardProps {
  c: CaptainCandidate;
  /** The plan's armband on this player, if any. */
  role: "C" | "VC" | null;
  znPick: boolean;
  onMakeCaptain: (id: number) => void;
  onMakeVice: (id: number) => void;
  /** Which ownership figure the tile shows; null renders a dash. */
  ownershipBasis?: "top10k" | "overall" | null;
  /** The GW the top-10k sample was taken in; named on the tile since it lags the plan. */
  eoEventId?: number | null;
}

/** The range bar's axis: 0–20 points, so a 2–16 band reads the same on every card. */
const RANGE_MAX = 20;
const pct = (v: number) => Math.max(0, Math.min(100, (v / RANGE_MAX) * 100));

const fmtRank = (n: number) => `${n >= 0 ? "+" : "−"}${Math.round(Math.abs(n) / 1000)}k`;

/** One captain candidate: xPts hero, likely range, EO and rank-if-haul tiles, note,
 *  and separate Make captain / Make vice buttons (v2 flow — no whole-card click). */
export function CaptainCard({ c, role, znPick, onMakeCaptain, onMakeVice, ownershipBasis = "top10k", eoEventId = null }: CaptainCardProps) {
  const hasRange = typeof c.p10 === "number" && typeof c.p90 === "number";
  const ownership = ownershipBasis === "overall" ? c.ownershipPct : c.eoTop10k;
  const isCap = role === "C";
  const isVice = role === "VC";
  const note = c.benched
    ? `${c.name} is on your bench. Bring him on in the Bench step first.`
    : typeof c.pHaul === "number"
      ? `${Math.round(c.pHaul * 100)}% chance of a 10+ haul${typeof ownership === "number" ? (ownership > (ownershipBasis === "overall" ? 60 : 100) ? "; most rivals already have him, so a haul only keeps pace." : ownership < 40 ? "; few rivals hold him, so a haul is a real rank swing." : ".") : "."}`
      : "Range from the xG model's points distribution.";
  return (
    <div
      data-testid="captain-card"
      data-role={role ?? undefined}
      data-benched={c.benched}
      className={`flex w-full flex-col gap-[14px] rounded-2xl border p-[18px] text-left transition-[border-color,background-color,box-shadow,opacity] duration-200 ${
        isCap
          ? "border-primary/70 bg-primary/10 shadow-[0_0_0_1px_hsl(var(--primary)/.5),0_12px_40px_hsl(var(--primary)/.22)]"
          : "border-border bg-card"
      } ${c.benched ? "opacity-50" : ""}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3">
          <JerseyIcon team={c.team} size="md" isCaptain={isCap} />
          <div>
            <div className="text-[17px] font-extrabold text-foreground">{c.name}</div>
            {c.fixture && (
              <div className="mt-1.5">
                <FixtureChip opponent={c.fixture.opponent} isHome={c.fixture.isHome} difficulty={c.fixture.difficulty} className="text-[10px]" />
              </div>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {znPick && <Badge className="bg-primary text-white hover:bg-primary">ZN Pick</Badge>}
          {role && <Badge className="bg-accent text-white hover:bg-accent">{role}</Badge>}
        </div>
      </div>

      <div className="flex items-baseline gap-2">
        <span data-testid="cap-xpts" className="text-[44px] font-black leading-[.9] tracking-[-0.03em] tabular-nums text-foreground">
          {c.xpts.toFixed(1)}
        </span>
        <span className="text-xs text-muted-foreground">xPts (×2 = {c.doubled.toFixed(1)})</span>
      </div>

      <div>
        <div className="mb-1.5 flex justify-between text-[10px] font-semibold uppercase tracking-[.06em] text-muted-foreground">
          <span>Likely range</span>
          <span className="tabular-nums">{hasRange ? `${c.p10}–${c.p90} pts` : "—"}</span>
        </div>
        <div className="relative h-2 rounded-full bg-muted">
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

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-[10px] bg-background/60 px-2.5 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-[.06em] text-muted-foreground">
            {ownershipBasis === "overall" ? "Ownership" : typeof eoEventId === "number" ? `Top 10k EO · GW${eoEventId}` : "Top 10k EO"}
          </div>
          <div className="mt-0.5 text-base font-extrabold tabular-nums text-foreground">
            {typeof ownership === "number" ? `${Math.round(ownership)}%` : "—"}
          </div>
        </div>
        <div className="rounded-[10px] bg-background/60 px-2.5 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-[.06em] text-muted-foreground">Rank if he hauls</div>
          <div className={`mt-0.5 text-base font-extrabold tabular-nums ${c.bigGain ? "text-accent" : "text-foreground"}`}>
            {typeof c.rankGainIfHaul === "number" ? fmtRank(c.rankGainIfHaul) : "—"}
          </div>
        </div>
      </div>

      <p className="text-xs leading-relaxed text-foreground/80">{note}</p>

      <div className="grid grid-cols-2 gap-2">
        <Button
          type="button"
          size="sm"
          variant={isCap ? "default" : "outline"}
          className="h-9 text-xs"
          disabled={c.benched}
          onClick={() => onMakeCaptain(c.id)}
        >
          {isCap ? "Captain ✓" : "Make captain"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant={isVice ? "secondary" : "ghost"}
          className={`h-9 text-xs ${isVice ? "bg-accent text-white hover:bg-accent/90" : ""}`}
          disabled={c.benched || isCap}
          onClick={() => onMakeVice(c.id)}
        >
          {isVice ? "Vice ✓" : "Make vice"}
        </Button>
      </div>
    </div>
  );
}
