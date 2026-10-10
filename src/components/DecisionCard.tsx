import { ArrowRight, Lightbulb } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { JerseyIcon } from "@/components/JerseyIcon";
import { fmtGain, gwRange } from "@/lib/format";
import type {
  FplTransferMove,
  FplTransferPlanHorizon,
  FplTransferRunnerUp,
  FplTransferVerdictDetail,
  FplTransferVerdictMove,
} from "@/lib/fplAssistantApi";

export { fmtGain, gwRange };

type Verdict = NonNullable<FplTransferPlanHorizon["verdict"]>;

const LABEL: Record<Verdict, string> = {
  roll: "Roll it",
  spend: "Make the move",
  spend_forced_injury: "Injury: act now",
};

// 300/400-weight shades on dark per the 2026-09-12 audit (U5); 600/700 on light.
const TONE: Record<Verdict, string> = {
  roll: "border-border bg-muted/10 text-muted-foreground",
  spend: "border-emerald-600/30 bg-emerald-600/[0.08] text-emerald-700 dark:text-emerald-300",
  spend_forced_injury: "border-destructive/30 bg-destructive/[0.08] text-destructive",
};

/** The comparison bars share one axis so a 14 → 17 move reads as a nudge, not a leap. */
const BAR_SCALE_XPTS = 18;
const HIT_COST = 4;

/** `gwRange`, wrapped so it never wraps mid-string at phone width. */
function GwRange({ h }: { h: { start_gw: number | null; end_gw: number | null } }) {
  return <span className="whitespace-nowrap">{gwRange(h)}</span>;
}

const movesText = (moves: FplTransferVerdictMove[]) =>
  moves.map((m) => `${m.sell.name} → ${m.buy.name}`).join(" + ");

/** Amber flag when the buy plays against your own keeper/defence (or vice versa) this GW. */
function ConflictChip({ names }: { names?: string[] }) {
  if (!names || names.length === 0) return null;
  return (
    <span
      className="rounded bg-amber-500/15 px-1 text-[10px] text-amber-700 dark:text-amber-400 whitespace-nowrap"
      title="Plays against your own player this GW — their returns cancel each other's"
    >
      faces your {names.join(", ")}
    </span>
  );
}

const AVAILABILITY_STATUS_WORD: Record<string, string> = {
  i: "injured",
  s: "suspended",
  d: "doubtful",
  u: "unavailable",
};

/** Amber flag on the seller when they carry availability risk (injury/doubt/suspension). */
function FitnessChip({ availability }: { availability?: { status: string; chance: number | null } }) {
  if (!availability) return null;
  const label =
    typeof availability.chance === "number"
      ? `${availability.chance}% fit`
      : AVAILABILITY_STATUS_WORD[availability.status] ?? availability.status;
  return (
    <span
      className="rounded bg-amber-500/15 px-1 text-[10px] text-amber-700 dark:text-amber-400 whitespace-nowrap"
      title="Seller's availability risk"
    >
      {label}
    </span>
  );
}

/* ── Move card ─────────────────────────────────────────────────────────────── */

type MoveAction =
  | { kind: "none" }
  | { kind: "apply"; label: string; variant: "accent" | "outline"; index: number }
  | { kind: "applied"; undo: boolean };

interface TransferMoveCardProps {
  m: FplTransferVerdictMove;
  /** "Free transfer" / "−4 hit". */
  cost: "free" | "hit";
  /** xPts after the hit share (or versus rolling, on a rejected move). */
  net: number;
  horizon: FplTransferVerdictDetail["horizon"];
  sellerHorizonXpts?: number;
  action: MoveAction;
  isApplying: boolean;
  onApply?: (index: number) => void;
  onUndo?: () => void;
}

function TransferMoveCard({ m, cost, net, horizon, sellerHorizonXpts, action, isApplying, onApply, onUndo }: TransferMoveCardProps) {
  const applied = action.kind === "applied";
  const positive = net >= 0;
  const hasBars = typeof sellerHorizonXpts === "number" && Number.isFinite(sellerHorizonXpts);
  const outX = hasBars ? (sellerHorizonXpts as number) : 0;
  const inX = outX + m.horizon_gain;
  const pct = (v: number) => `${Math.max(0, Math.min(100, Math.round((v / BAR_SCALE_XPTS) * 100)))}%`;
  const fixtures =
    m.sell.next_fixture || m.buy.next_fixture
      ? `${m.sell.name} has ${m.sell.next_fixture ?? "no fixture"}; ${m.buy.name} gets ${m.buy.next_fixture ?? "no fixture"}. `
      : "";

  return (
    <div
      data-testid="move-card"
      data-applied={applied}
      className={`flex flex-col gap-3 rounded-xl border p-3.5 text-foreground transition-[border-color,background-color] duration-200 ${
        applied ? "border-accent/45 bg-accent/[0.08]" : "border-border bg-card"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <JerseyIcon team={m.sell.team} size="sm" />
          <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <JerseyIcon team={m.buy.team} size="sm" />
          <div className="ml-1 min-w-0">
            <div className="flex flex-wrap items-center gap-x-1 text-[13px] font-bold leading-tight">
              <span>{m.buy.name}</span>
              <span className="font-normal text-muted-foreground">({m.buy.team} £{m.buy.price.toFixed(1)})</span>
              <ConflictChip names={m.h2h_conflicts} />
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-1 text-[11px] text-muted-foreground">
              <span>for {m.sell.name}</span>
              <span>({m.sell.team} £{m.sell.price.toFixed(1)})</span>
              <FitnessChip availability={m.sell_availability} />
              {m.forced_injury && (
                <Badge variant="outline" className="border-destructive/50 px-1 py-0 text-[10px] text-destructive">flagged</Badge>
              )}
              <span>· {cost === "free" ? "Free transfer" : `−${HIT_COST} hit`}</span>
            </div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div
            data-testid="move-net"
            className={`text-lg font-black leading-none tabular-nums ${positive ? "text-accent" : "text-fdr-4"}`}
          >
            {fmtGain(net)}
          </div>
          <div className="mt-0.5 text-[10px] text-muted-foreground">net xPts</div>
        </div>
      </div>

      {hasBars && (
        <div data-testid="xpts-bars" className="flex flex-col gap-1.5">
          {[
            { name: m.sell.name, v: outX, fill: "bg-muted-foreground/60", tone: "text-muted-foreground" },
            { name: m.buy.name, v: inX, fill: "bg-accent", tone: "font-semibold text-foreground" },
          ].map((row) => (
            <div key={row.name} className="grid grid-cols-[56px_minmax(0,1fr)_32px] items-center gap-2 text-[11px]">
              <span className={`truncate ${row.tone}`}>{row.name}</span>
              <div className="h-1.5 rounded-full bg-muted">
                <div data-testid="xpts-bar-fill" className={`h-full rounded-full ${row.fill}`} style={{ width: pct(row.v) }} />
              </div>
              <span className={`text-right tabular-nums ${row.tone}`}>{row.v.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}

      <p className="text-xs leading-relaxed text-foreground/80">
        {fixtures}
        {horizon.n === 1 ? (
          <>{fmtGain(m.horizon_gain)} this GW.</>
        ) : (
          <>{fmtGain(m.this_gw_gain)} this GW · {fmtGain(m.horizon_gain)} over <GwRange h={horizon} />.</>
        )}
      </p>

      {action.kind === "apply" && onApply && (
        <Button
          type="button"
          size="sm"
          variant={action.variant === "accent" ? "default" : "outline"}
          className={`h-8 w-full text-xs ${action.variant === "accent" ? "bg-accent text-white hover:bg-accent/90" : ""}`}
          disabled={isApplying}
          onClick={() => onApply(action.index)}
        >
          {action.label}
        </Button>
      )}
      {action.kind === "applied" && (
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="secondary" className="h-8 flex-1 text-xs" disabled>
            Applied
          </Button>
          {action.undo && onUndo && (
            <Button type="button" size="sm" variant="ghost" className="h-8 text-xs" disabled={isApplying} onClick={onUndo}>
              Undo
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Runner-ups ────────────────────────────────────────────────────────────── */

const RUNNER_UPS_VISIBLE = 3;

function RunnerUpRow({ m, index, singleGw }: { m: FplTransferRunnerUp; index: number; singleGw?: boolean }) {
  return (
    <li className="flex items-center justify-between gap-2 text-xs">
      <span className="min-w-0 truncate">
        {index}. {m.sell.name}
        {m.sell_availability && (
          <>
            {" "}
            <FitnessChip availability={m.sell_availability} />
          </>
        )}{" "}
        → {m.buy.name} <ConflictChip names={m.h2h_conflicts} />
      </span>
      <span className="shrink-0 text-muted-foreground">
        {singleGw ? `${fmtGain(m.horizon_gain)} this GW` : `${fmtGain(m.this_gw_gain)} this GW · ${fmtGain(m.horizon_gain)}`}
        {!m.clears_bar && <span className="ml-1 text-muted-foreground/70">below bar</span>}
      </span>
    </li>
  );
}

/** "Also considered" (spend) / "Best available — all below the bar" (roll): the other candidates, ranked. */
function RunnerUps({ d }: { d: FplTransferVerdictDetail }) {
  const list = d.runner_ups ?? [];
  if (list.length === 0) return null;
  const startIndex = d.action === "roll" ? 1 : 2;
  const heading = d.action === "roll" ? "Best available — all below the bar" : "Also considered";
  const visible = list.slice(0, RUNNER_UPS_VISIBLE);
  const rest = list.slice(RUNNER_UPS_VISIBLE);
  return (
    <div data-testid="runner-ups" className="flex flex-col gap-1 border-t pt-1.5 mt-0.5">
      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{heading}</p>
      <ul className="space-y-0.5">
        {visible.map((m, i) => <RunnerUpRow singleGw={d.horizon.n === 1} key={i} m={m} index={startIndex + i} />)}
      </ul>
      {rest.length > 0 && (
        <details>
          <summary className="cursor-pointer text-[11px] text-muted-foreground">show {rest.length} more</summary>
          <ul className="mt-0.5 space-y-0.5">
            {rest.map((m, i) => (
              <RunnerUpRow singleGw={d.horizon.n === 1} key={i} m={m} index={startIndex + visible.length + i} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** The bottom tip box: why rolling (or spending) is the call, in one breath. */
function Tip({ children }: { children: React.ReactNode }) {
  return (
    <div data-testid="plan-tip" className="flex gap-2.5 rounded-xl bg-muted/50 p-3">
      <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
      <div className="flex flex-col gap-1 text-xs leading-relaxed text-foreground/85">{children}</div>
    </div>
  );
}

/** Pre-verdict_detail backends: the prose banner, unchanged. */
function LegacyVerdictBanner({ plan }: { plan: FplTransferPlanHorizon }) {
  if (!plan.verdict) return null;
  const showFt =
    typeof plan.first_gw_ft_before === "number" && typeof plan.first_gw_ft_after === "number";
  const n = plan.horizon_gws ?? plan.gws?.length ?? 1;
  return (
    <div data-testid="plan-verdict-banner" className={`rounded-lg border p-3 flex flex-col gap-1 ${TONE[plan.verdict]}`}>
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-wider">{LABEL[plan.verdict]}</Badge>
        {showFt && <span className="ml-auto text-xs text-muted-foreground">FT {plan.first_gw_ft_before}→{plan.first_gw_ft_after}</span>}
      </div>
      {plan.reasoning && <p className="text-xs leading-relaxed">{plan.reasoning}</p>}
      <p className="text-[11px] opacity-70 leading-relaxed">
        {plan.allow_hits
          ? `Planned across ${n} GWs and allowed to take hits, so it can name more moves than the free-transfer suggestions above.`
          : `Planned across ${n} GWs using free transfers only.`}
      </p>
    </div>
  );
}

/** Index into the beam's `transfers.moves` for a verdict move, by player ids. */
const findBeamIndex = (beam: FplTransferMove[] | undefined, m: FplTransferVerdictMove) =>
  beam ? beam.findIndex((b) => b.sell.id === m.sell.id && b.buy.id === m.buy.id) : -1;

interface DecisionCardProps {
  plan: FplTransferPlanHorizon;
  appliedTransferCount?: number;
  isApplying?: boolean;
  /** Plan moves lead `transfers.moves`, so applying k plan moves = index k-1. */
  onApplyTransferAtIndex?: (index: number) => void;
  onResetAppliedTransfers?: () => void;
  /** Squad players' horizon xPts by player id — drives the out/in comparison bars. */
  horizonXptsById?: Record<number, number>;
  /** The beam's `transfers.moves`; lets a rejected (roll) move still be applied by index. */
  beamMoves?: FplTransferMove[];
}

export function DecisionCard({
  plan,
  appliedTransferCount = 0,
  isApplying = false,
  onApplyTransferAtIndex,
  onResetAppliedTransfers,
  horizonXptsById,
  beamMoves,
}: DecisionCardProps) {
  const d: FplTransferVerdictDetail | undefined = plan.verdict_detail;
  if (!d) return <LegacyVerdictBanner plan={plan} />;
  const k = d.moves.length;
  const applied = k > 0 && appliedTransferCount >= k;
  // The bank the plan leaves behind — the ITB badge the alternatives list used
  // to carry, now attached to the thing that actually spends the money.
  const bankAfter = plan.plan?.[0]?.bank_after;
  const hasBank = typeof bankAfter === "number" && Number.isFinite(bankAfter);
  const canApply = Boolean(onApplyTransferAtIndex);

  // Each move past the free transfers is a hit; the plan's hit_cost is the bill
  // for all of them, so split it evenly to show what each one nets on its own.
  const hitMoves = Math.max(0, k - d.ft_before);
  const hitEach = hitMoves > 0 ? d.hit_cost / hitMoves : 0;

  const actionFor = (i: number): MoveAction => {
    if (!canApply) return { kind: "none" };
    if (i < appliedTransferCount) return { kind: "applied", undo: i === appliedTransferCount - 1 && Boolean(onResetAppliedTransfers) };
    if (i === appliedTransferCount) return { kind: "apply", label: "Apply this move", variant: "accent", index: i };
    return { kind: "apply", label: `Apply moves 1–${i + 1}`, variant: "outline", index: i };
  };

  const header = (
    <div className="flex items-center gap-2">
      <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-wider">{LABEL[d.action]}</Badge>
      <span className="ml-auto text-xs text-muted-foreground">FT {d.ft_before}→{d.ft_after}</span>
    </div>
  );

  if (d.action === "roll") {
    const alt = d.roll_alternative;
    return (
      <div data-testid="plan-verdict-banner" className={`rounded-lg border p-3 flex flex-col gap-3 ${TONE[d.action]}`}>
        {header}
        {alt && alt.moves.length > 0 && alt.moves.map((m, i) => {
          const beamIndex = findBeamIndex(beamMoves, m);
          const free = d.ft_before > 0;
          const action: MoveAction =
            !canApply || beamIndex < 0
              ? { kind: "none" }
              : appliedTransferCount > beamIndex
                ? { kind: "applied", undo: Boolean(onResetAppliedTransfers) }
                : { kind: "apply", label: free ? "Make the move anyway" : "Take the hit anyway", variant: "outline", index: beamIndex };
          return (
            <TransferMoveCard
              key={i}
              m={m}
              cost={free ? "free" : "hit"}
              net={i === 0 ? alt.net - d.plan_net : m.horizon_gain}
              horizon={d.horizon}
              sellerHorizonXpts={horizonXptsById?.[m.sell.id]}
              action={action}
              isApplying={isApplying}
              onApply={onApplyTransferAtIndex}
              onUndo={onResetAppliedTransfers}
            />
          );
        })}
        <Tip>
          <p>
            {alt ? (
              <>Moving now ({movesText(alt.moves) || "no move"}) would net {fmtGain(alt.net)} over <GwRange h={d.horizon} />; rolling nets {fmtGain(d.plan_net)}.</>
            ) : (
              <>Bank the free transfer. No move clears {fmtGain(d.threshold)} over <GwRange h={d.horizon} />.</>
            )}
          </p>
          {d.next_move && (
            <p className="text-muted-foreground">
              Next planned move: {movesText(d.next_move.moves)} in GW{d.next_move.gw} (
              {fmtGain(d.next_move.horizon_gain)} over <GwRange h={{ start_gw: d.next_move.gw, end_gw: d.horizon.end_gw }} />)
            </p>
          )}
        </Tip>
        <RunnerUps d={d} />
      </div>
    );
  }

  return (
    <div data-testid="plan-verdict-banner" className={`rounded-lg border p-3 flex flex-col gap-3 ${TONE[d.action]}`}>
      {header}
      {d.moves.map((m, i) => {
        const hit = i >= d.ft_before;
        return (
          <TransferMoveCard
            key={i}
            m={m}
            cost={hit ? "hit" : "free"}
            net={m.horizon_gain - (hit ? hitEach : 0)}
            horizon={d.horizon}
            sellerHorizonXpts={horizonXptsById?.[m.sell.id]}
            action={actionFor(i)}
            isApplying={isApplying}
            onApply={onApplyTransferAtIndex}
            onUndo={onResetAppliedTransfers}
          />
        );
      })}
      <p className="text-sm text-foreground" data-testid="decision-gains">
        {d.horizon.n === 1 ? (
          <><b>{fmtGain(d.horizon_gain)}</b> this GW</>
        ) : (
          <><b>{fmtGain(d.this_gw_gain)}</b> this GW · <b>{fmtGain(d.horizon_gain)}</b> over <GwRange h={d.horizon} /></>
        )}
        {d.hit_cost > 0 && <> · <b className="text-red-600 dark:text-red-400">{fmtGain(-d.hit_cost)} hit</b></>}
      </p>
      <Tip>
        <p>
          Plan <GwRange h={d.horizon} /> nets {fmtGain(d.plan_net)}
          {d.roll_alternative ? ` · rolling instead nets ${fmtGain(d.roll_alternative.net)}` : ""}
          {hasBank ? ` · ITB after £${bankAfter.toFixed(1)}m` : ""}
          {applied ? " · applied to the pitch" : ""}
        </p>
      </Tip>
      <RunnerUps d={d} />
    </div>
  );
}
