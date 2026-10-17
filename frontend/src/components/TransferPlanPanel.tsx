// Dev-only Squad Picker: horizon transfer plan. Given the current 15, plan
// 1 FT/GW across the fixture window — use the best swap or roll/bank, with
// optional -4 hits when the remaining-horizon gain beats the cost.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { getTransferPlan, type SquadBuildParams, type TransferPlan, type TransferPlanGw }
  from "@/lib/squadPickerApi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

function GwRow({ g }: { g: TransferPlanGw }) {
  const roll = g.action === "roll";
  return (
    <div className="border-t py-2">
      <div className="flex items-center gap-2 text-xs">
        <span className="font-semibold w-12">GW{g.gw}</span>
        <span className={`px-1.5 rounded text-[10px] ${roll
          ? "bg-zinc-500/60 text-white" : g.hits > 0 ? "bg-orange-600/80 text-white" : "bg-emerald-600/80 text-white"}`}>
          {roll ? "roll" : g.hits > 0 ? `transfer +${g.hits} hit` : "transfer"}
        </span>
        <span className="text-muted-foreground">FT {g.free_transfers_before}→{g.free_transfers_after}</span>
        {!roll && (
          <span className={g.net_gain >= 0 ? "text-emerald-600 ml-auto" : "text-red-600 ml-auto"}>
            net {g.net_gain >= 0 ? "+" : ""}{g.net_gain.toFixed(1)} pts
            {g.hits > 0 && <span className="text-muted-foreground"> (−{g.hit_cost} hit)</span>}
          </span>
        )}
      </div>
      {roll ? (
        <div className="text-[11px] text-muted-foreground mt-1">{g.note}</div>
      ) : (
        <ul className="text-[11px] mt-1 space-y-0.5">
          {g.moves.map((m, i) => (
            <li key={i} className="flex gap-1">
              <span className="text-red-600">{m.sell.name}</span>
              <span className="text-muted-foreground">({m.sell.team} £{m.sell.price})</span>
              <span>→</span>
              <span className="text-emerald-700 font-medium">{m.buy.name}</span>
              <span className="text-muted-foreground">({m.buy.team} £{m.buy.price})</span>
              <span className="ml-auto text-emerald-600">+{m.score_gain.toFixed(1)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function TransferPlanPanel({ squadIds, params }: {
  squadIds: number[];
  params: SquadBuildParams;
}) {
  const [startFt, setStartFt] = useState(1);
  const [allowHits, setAllowHits] = useState(true);
  const plan = useMutation<TransferPlan, Error, void>({
    mutationFn: () => getTransferPlan(squadIds, {
      ...params, start_free_transfers: startFt, ft_cap: 5, allow_hits: allowHits,
    }),
  });
  const d = plan.data;

  return (
    <Card className="p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-xs font-semibold">Transfer plan (over the fixture horizon)</div>
        <label className="flex items-center gap-1 text-xs">Start FT
          <Input type="number" min={0} max={5} value={startFt} className="w-14 h-7"
            onChange={(e) => setStartFt(Math.max(0, Math.min(5, Number(e.target.value) || 0)))} />
        </label>
        <label className="flex items-center gap-1 text-xs">
          <input type="checkbox" checked={allowHits} onChange={(e) => setAllowHits(e.target.checked)} />
          allow −4 hits
        </label>
        <Button size="sm" variant="outline" disabled={plan.isPending || squadIds.length < 15}
          onClick={() => plan.mutate()}>
          {plan.isPending ? "Planning…" : "Plan transfers"}
        </Button>
        {d?.valid && typeof d.total_net_gain === "number" && (
          <span className="text-xs ml-auto">
            Net over {d.horizon_gws} GWs <b className={d.total_net_gain >= 0 ? "text-emerald-600" : "text-red-600"}>
              {d.total_net_gain >= 0 ? "+" : ""}{d.total_net_gain.toFixed(1)} pts</b>
          </span>
        )}
      </div>

      {plan.isError && <div className="text-xs text-red-600">{plan.error.message}</div>}
      {d && !d.valid && (
        <div className="text-xs text-red-600">
          Squad not valid: {(d.violations ?? []).join("; ")}
        </div>
      )}
      {d?.valid && d.plan && (
        <div>
          {d.plan.every((g) => g.action === "roll") && (
            <div className="text-[11px] text-muted-foreground">
              No transfer clears the bar — the squad is already strong for these fixtures; roll and bank.
            </div>
          )}
          {d.plan.map((g) => <GwRow key={g.gw} g={g} />)}
        </div>
      )}
      {!d && !plan.isPending && (
        <div className="text-[11px] text-muted-foreground">
          Plans 1 free transfer per GW (bank up to 5), rolling or spending on the best remaining-horizon swap; a −4 hit only when it's worth it.
        </div>
      )}
    </Card>
  );
}
