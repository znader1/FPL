import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  FplTransferPlanHorizon,
  FplTransferRunnerUp,
  FplTransferVerdictDetail,
  FplTransferVerdictMove,
} from "@/lib/fplAssistantApi";

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

import { fmtGain, gwRange } from "@/lib/format";
export { fmtGain, gwRange };

/** `gwRange`, wrapped so it never wraps mid-string at phone width. */
function GwRange({ h }: { h: { start_gw: number | null; end_gw: number | null } }) {
  return <span className="whitespace-nowrap">{gwRange(h)}</span>;
}

const movesText = (moves: FplTransferVerdictMove[]) =>
  moves.map((m) => `${m.sell.name} → ${m.buy.name}`).join(" + ");

function MoveLine({ m }: { m: FplTransferVerdictMove }) {
  return (
    <span className="flex flex-wrap items-center gap-x-1">
      <span className="text-red-600 dark:text-red-400">{m.sell.name}</span>
      <span className="text-muted-foreground">({m.sell.team} £{m.sell.price.toFixed(1)})</span>
      <FitnessChip availability={m.sell_availability} />
      {m.forced_injury && (
        <Badge variant="outline" className="border-destructive/50 text-[10px] text-destructive">flagged</Badge>
      )}
      <span>→</span>
      <span className="font-semibold text-emerald-700 dark:text-emerald-300">{m.buy.name}</span>
      <span className="text-muted-foreground">({m.buy.team} £{m.buy.price.toFixed(1)})</span>
      <ConflictChip names={m.h2h_conflicts} />
    </span>
  );
}

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

interface DecisionCardProps {
  plan: FplTransferPlanHorizon;
  appliedTransferCount?: number;
  isApplying?: boolean;
  /** Plan moves lead `transfers.moves`, so applying k plan moves = index k-1. */
  onApplyTransferAtIndex?: (index: number) => void;
  onResetAppliedTransfers?: () => void;
}

export function DecisionCard({
  plan,
  appliedTransferCount = 0,
  isApplying = false,
  onApplyTransferAtIndex,
  onResetAppliedTransfers,
}: DecisionCardProps) {
  const d: FplTransferVerdictDetail | undefined = plan.verdict_detail;
  if (!d) return <LegacyVerdictBanner plan={plan} />;
  const k = d.moves.length;
  const applied = k > 0 && appliedTransferCount >= k;
  // The bank the plan leaves behind — the ITB badge the alternatives list used
  // to carry, now attached to the thing that actually spends the money.
  const bankAfter = plan.plan?.[0]?.bank_after;
  const hasBank = typeof bankAfter === "number" && Number.isFinite(bankAfter);

  return (
    <div data-testid="plan-verdict-banner" className={`rounded-lg border p-3 flex flex-col gap-1.5 ${TONE[d.action]}`}>
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-wider">{LABEL[d.action]}</Badge>
        <span className="ml-auto text-xs text-muted-foreground">FT {d.ft_before}→{d.ft_after}</span>
      </div>

      {d.action === "roll" ? (
        <>
          <p className="text-sm text-foreground">
            {d.roll_alternative ? (
              <>Moving now ({movesText(d.roll_alternative.moves) || "no move"}) would net {fmtGain(d.roll_alternative.net)} over <GwRange h={d.horizon} />; rolling nets {fmtGain(d.plan_net)}.</>
            ) : (
              <>Bank the free transfer. No move clears {fmtGain(d.threshold)} over <GwRange h={d.horizon} />.</>
            )}
          </p>
          {d.next_move && (
            <p className="text-[11px] text-muted-foreground">
              Next planned move: {movesText(d.next_move.moves)} in GW{d.next_move.gw} (
              {fmtGain(d.next_move.horizon_gain)} over <GwRange h={{ start_gw: d.next_move.gw, end_gw: d.horizon.end_gw }} />)
            </p>
          )}
        </>
      ) : (
        <>
          <ul className="text-sm space-y-0.5">
            {d.moves.map((m, i) => <li key={i}><MoveLine m={m} /></li>)}
          </ul>
          <p className="text-sm text-foreground" data-testid="decision-gains">
            {d.horizon.n === 1 ? (
              <><b>{fmtGain(d.horizon_gain)}</b> this GW</>
            ) : (
              <><b>{fmtGain(d.this_gw_gain)}</b> this GW · <b>{fmtGain(d.horizon_gain)}</b> over <GwRange h={d.horizon} /></>
            )}
            {d.hit_cost > 0 && <> · <b className="text-red-600 dark:text-red-400">{fmtGain(-d.hit_cost)} hit</b></>}
          </p>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span>
              Plan <GwRange h={d.horizon} /> nets {fmtGain(d.plan_net)}
              {d.roll_alternative ? ` · rolling instead nets ${fmtGain(d.roll_alternative.net)}` : ""}
              {hasBank ? ` · ITB after £${bankAfter.toFixed(1)}m` : ""}
            </span>
            {onApplyTransferAtIndex && k > 0 && (
              <Button
                type="button"
                size="sm"
                variant={applied ? "secondary" : "default"}
                className="ml-auto h-8 text-xs"
                disabled={isApplying || applied}
                onClick={() => onApplyTransferAtIndex(k - 1)}
              >
                {applied ? "Applied" : k > 1 ? `Apply ${k} moves` : "Apply"}
              </Button>
            )}
            {applied && onResetAppliedTransfers && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 text-xs"
                disabled={isApplying}
                onClick={onResetAppliedTransfers}
              >
                Undo
              </Button>
            )}
          </div>
        </>
      )}

      <RunnerUps d={d} />
    </div>
  );
}
