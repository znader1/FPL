import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Sparkles, ArrowRight } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  optimizeSquad,
  type FplPosition,
  type OptimizeSquadResponse,
  type OptimizeSquadSwap,
} from "@/lib/fplAssistantApi";

interface OptimizeSquadDialogProps {
  entryId: number;
  horizonGws: number;
  /** Fired after a successful Apply so the parent can refetch the squad + rec. */
  onApplied: () => void;
}

/* ── helpers ──────────────────────────────────────────────────────────────── */
const POSITION_ORDER: FplPosition[] = ["GKP", "DEF", "MID", "FWD"];
const POSITION_LABEL: Record<FplPosition, string> = {
  GKP: "Goalkeeper",
  DEF: "Defenders",
  MID: "Midfielders",
  FWD: "Forwards",
};

const fmt1 = (v?: number) => {
  if (typeof v !== "number" || !Number.isFinite(v)) return "—";
  return (Math.round(v * 10) / 10).toString();
};

const fmtGain = (v?: number) => {
  if (typeof v !== "number" || !Number.isFinite(v)) return "+0";
  const rounded = Math.round(v * 10) / 10;
  return `${rounded >= 0 ? "+" : ""}${rounded}`;
};

const fmtPrice = (v?: number) => {
  if (typeof v !== "number" || !Number.isFinite(v)) return "£—";
  return `£${(Math.round(v * 10) / 10).toFixed(1)}m`;
};

const errorMessage = (err: unknown): string | undefined => {
  if (!err) return undefined;
  return err instanceof Error ? err.message : String(err);
};

/* ── swap row ─────────────────────────────────────────────────────────────── */
// No per-swap gain shown on purpose: the moves are a budget-coupled SET (a cheap
// downgrade can fund a premium elsewhere), so only the squad-level total_gain is
// meaningful. Per row we show each player's own projection as context.
function SwapRow({ swap }: { swap: OptimizeSquadSwap }) {
  return (
    <div className="rounded-xl border border-border bg-card px-3 py-2.5">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground truncate">{swap.out.name}</p>
          <p className="text-[11px] text-muted-foreground truncate">
            {swap.out.team} · {fmtPrice(swap.out.price)} · {fmt1(swap.out.xpts_horizon)} xP
          </p>
        </div>
        <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-foreground truncate">{swap.in.name}</p>
          <p className="text-[11px] text-muted-foreground truncate">
            {swap.in.team} · {fmtPrice(swap.in.price)} · {fmt1(swap.in.xpts_horizon)} xP
          </p>
        </div>
      </div>
    </div>
  );
}

/* ── dialog ───────────────────────────────────────────────────────────────── */
export const OptimizeSquadDialog = ({ entryId, horizonGws, onApplied }: OptimizeSquadDialogProps) => {
  const [open, setOpen] = useState(false);
  const [allIn, setAllIn] = useState(false);

  // min_gain is the aggressiveness dial: 3 = high-conviction only (default),
  // 1 = "go all-in" (more, smaller-value swaps).
  const previewMutation = useMutation<OptimizeSquadResponse, unknown, boolean>({
    mutationFn: (nextAllIn) =>
      optimizeSquad({
        entry_id: entryId,
        horizon_gws: horizonGws,
        min_gain: nextAllIn ? 1 : 3,
        apply: false,
      }),
  });

  const applyMutation = useMutation<OptimizeSquadResponse, unknown, boolean>({
    mutationFn: (nextAllIn) =>
      optimizeSquad({
        entry_id: entryId,
        horizon_gws: horizonGws,
        min_gain: nextAllIn ? 1 : 3,
        apply: true,
      }),
    onSuccess: () => {
      setOpen(false);
      onApplied();
    },
  });

  const preview = previewMutation.data;

  const groupedSwaps = useMemo(() => {
    const groups: Partial<Record<FplPosition, OptimizeSquadSwap[]>> = {};
    for (const swap of preview?.swaps ?? []) {
      (groups[swap.position] ??= []).push(swap);
    }
    return groups;
  }, [preview]);

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) {
      // Each open resets to the high-conviction default and previews.
      setAllIn(false);
      applyMutation.reset();
      previewMutation.mutate(false);
    } else {
      previewMutation.reset();
      applyMutation.reset();
    }
  };

  const handleAllInChange = (checked: boolean) => {
    setAllIn(checked);
    applyMutation.reset();
    previewMutation.mutate(checked);
  };

  const hasSwaps = Boolean(preview && preview.num_swaps > 0);
  const applyDisabled =
    previewMutation.isPending || applyMutation.isPending || !hasSwaps;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          size="sm"
          className="gap-1.5 bg-primary text-white hover:bg-primary/90 font-semibold shadow-sm"
        >
          <Sparkles className="h-4 w-4" />
          Optimize my squad
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg gap-0 overflow-hidden p-0">
        <DialogHeader className="px-6 pb-4 pt-6">
          <DialogTitle className="flex items-center gap-2 text-foreground">
            <Sparkles className="h-5 w-5 text-primary" />
            Optimize my squad
          </DialogTitle>
          <DialogDescription>
            Apply all beneficial free swaps before the first deadline — no hits, no transfer cost.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] overflow-y-auto px-6 pb-2">
          {previewMutation.isPending ? (
            <div className="space-y-3 py-1">
              <Skeleton className="h-16 w-full rounded-xl" />
              <Skeleton className="h-12 w-full rounded-xl" />
              <Skeleton className="h-12 w-full rounded-xl" />
              <Skeleton className="h-12 w-full rounded-xl" />
            </div>
          ) : previewMutation.isError ? (
            <div className="space-y-3 py-1">
              <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                <p className="font-semibold">Couldn't optimize your squad.</p>
                <p className="mt-1 break-words text-xs opacity-80">
                  {errorMessage(previewMutation.error)}
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => previewMutation.mutate(allIn)}>
                Try again
              </Button>
            </div>
          ) : preview ? (
            <div className="py-1">
              {/* Aggressiveness toggle */}
              <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-border bg-muted/10 px-3 py-2.5">
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-foreground">Go all-in (max points)</p>
                  <p className="text-[11px] leading-snug text-muted-foreground">
                    {allIn
                      ? "Including smaller-value swaps for the highest projected total."
                      : "High-conviction swaps only. Toggle for more, smaller upgrades."}
                  </p>
                </div>
                <Switch
                  checked={allIn}
                  onCheckedChange={handleAllInChange}
                  disabled={applyMutation.isPending}
                />
              </div>

              {preview.num_swaps === 0 ? (
                <div className="rounded-xl border border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
                  Your squad is already optimal — no free upgrades found.
                </div>
              ) : (
                <>
                  {/* Projected points hero */}
                  <Card className="border-primary/30 bg-primary/[0.08] p-4 shadow-none">
                    <div className="flex items-center justify-between gap-4">
                      <div className="min-w-0">
                        <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-primary/70">
                          Projected points ({preview.horizon_gws} GW)
                        </p>
                        <div className="flex items-baseline gap-2">
                          <span className="text-2xl font-black leading-none text-muted-foreground line-through decoration-muted-foreground/40">
                            {fmt1(preview.xpts_before)}
                          </span>
                          <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                          <span className="text-4xl font-black leading-none text-primary">
                            {fmt1(preview.xpts_after)}
                          </span>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <Badge className="border-transparent bg-accent px-2.5 py-1 text-sm font-bold text-accent-foreground hover:bg-accent">
                          {fmtGain(preview.total_gain)}
                        </Badge>
                        <span className="text-[11px] text-muted-foreground">
                          {preview.num_swaps} change{preview.num_swaps === 1 ? "" : "s"}
                        </span>
                      </div>
                    </div>
                  </Card>

                  {/* Swap list, grouped by position */}
                  <div className="mt-3 space-y-3">
                    {POSITION_ORDER.filter((pos) => groupedSwaps[pos]?.length).map((pos) => (
                      <div key={pos} className="space-y-1.5">
                        <div className="flex items-center gap-2">
                          <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                            {POSITION_LABEL[pos]}
                          </p>
                          <Badge
                            variant="outline"
                            className="h-4 border-border px-1.5 py-0 text-[10px]"
                          >
                            {pos}
                          </Badge>
                        </div>
                        {groupedSwaps[pos]!.map((swap, i) => (
                          <SwapRow key={`${pos}-${i}`} swap={swap} />
                        ))}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          ) : null}
        </div>

        <DialogFooter className="flex-col gap-2 border-t border-border px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
          {applyMutation.isError ? (
            <p className="break-words text-xs text-destructive">{errorMessage(applyMutation.error)}</p>
          ) : (
            <span className="hidden sm:block" />
          )}
          <Button
            className="w-full bg-primary font-bold text-primary-foreground hover:bg-primary/90 sm:w-auto"
            onClick={() => applyMutation.mutate(allIn)}
            disabled={applyDisabled}
          >
            {applyMutation.isPending
              ? "Applying…"
              : hasSwaps
                ? `Apply ${preview!.num_swaps} change${preview!.num_swaps === 1 ? "" : "s"}`
                : "Apply changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
