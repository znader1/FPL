// Dev-only Squad Picker: full player pool with search / filter / sort and
// add-remove controls. Presentational — the parent owns squad state + the
// canAdd legality guard.
import { useMemo, useState } from "react";
import type { PoolPlayer } from "@/lib/squadPickerApi";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type Sort = "xpts" | "tp" | "value" | "price" | "mins" | "fix";
const POS = ["ALL", "GKP", "DEF", "MID", "FWD"] as const;

// FDR-style colour by fixture difficulty (1 easiest .. 5 hardest).
function diffColor(diff: number): string {
  if (diff <= 2) return "bg-emerald-600/80 text-white";
  if (diff === 3) return "bg-zinc-500/60 text-white";
  if (diff === 4) return "bg-orange-600/80 text-white";
  return "bg-red-700/80 text-white";
}

function FixtureTicker({ fixtures }: { fixtures: { opp: string; home: boolean; diff: number }[] }) {
  return (
    <div className="flex gap-0.5 flex-wrap">
      {fixtures.map((f, i) => (
        <span key={i} className={`px-1 rounded text-[10px] leading-4 ${diffColor(f.diff)}`}
          title={`${f.home ? "Home" : "Away"} vs ${f.opp} (difficulty ${f.diff})`}>
          {f.home ? f.opp : f.opp.toLowerCase()}
        </span>
      ))}
    </div>
  );
}

export function PlayerListPanel({ players, squadIds, canAdd, onAdd, onRemove }: {
  players: PoolPlayer[];
  squadIds: number[];
  canAdd: (p: PoolPlayer) => { ok: boolean; reason?: string };
  onAdd: (id: number) => void;
  onRemove: (id: number) => void;
}) {
  const [q, setQ] = useState("");
  const [pos, setPos] = useState<typeof POS[number]>("ALL");
  const [maxPrice, setMaxPrice] = useState<number | "">("");
  const [minMins, setMinMins] = useState<number | "">("");
  const [maxDiff, setMaxDiff] = useState<number | "">("");
  const [minHome, setMinHome] = useState<number | "">("");
  const [sort, setSort] = useState<Sort>("xpts");
  const inSquad = useMemo(() => new Set(squadIds), [squadIds]);

  const rows = useMemo(() => {
    const filtered = players.filter((p) =>
      (pos === "ALL" || p.pos === pos) &&
      (!q || p.web_name.toLowerCase().includes(q.toLowerCase())) &&
      (maxPrice === "" || p.price_m <= Number(maxPrice)) &&
      (minMins === "" || p.minutes >= Number(minMins)) &&
      (maxDiff === "" || (p.avg_diff !== null && p.avg_diff <= Number(maxDiff))) &&
      (minHome === "" || p.home_games >= Number(minHome)));
    const key = (p: PoolPlayer) =>
      sort === "tp" ? p.total_points
        : sort === "value" ? (p.price_m ? p.xpts_horizon / p.price_m : 0)
          : sort === "price" ? -p.price_m
            : sort === "mins" ? p.minutes
              : sort === "fix" ? -(p.avg_diff ?? 99) // easiest fixtures first
                : p.xpts_horizon;
    return [...filtered].sort((a, b) => key(b) - key(a)).slice(0, 300);
  }, [players, q, pos, maxPrice, minMins, maxDiff, minHome, sort]);

  return (
    <Card className="p-3 space-y-2">
      <div className="flex flex-wrap gap-2">
        <Input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} className="w-40" />
        <select className="rounded-md border bg-background p-2 text-sm" value={pos}
          onChange={(e) => setPos(e.target.value as typeof POS[number])}>
          {POS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <Input type="number" placeholder="Max £" value={maxPrice} className="w-24"
          onChange={(e) => setMaxPrice(e.target.value === "" ? "" : Number(e.target.value))} />
        <Input type="number" placeholder="Min mins" value={minMins} className="w-28"
          onChange={(e) => setMinMins(e.target.value === "" ? "" : Number(e.target.value))} />
        <Input type="number" step={0.1} placeholder="Max avg diff" value={maxDiff} className="w-32"
          onChange={(e) => setMaxDiff(e.target.value === "" ? "" : Number(e.target.value))} />
        <Input type="number" placeholder="Min home" value={minHome} className="w-28"
          onChange={(e) => setMinHome(e.target.value === "" ? "" : Number(e.target.value))} />
        <select className="rounded-md border bg-background p-2 text-sm" value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}>
          <option value="xpts">xPts</option>
          <option value="tp">TP</option>
          <option value="value">Value</option>
          <option value="price">Price</option>
          <option value="mins">Minutes</option>
          <option value="fix">Easiest fixtures</option>
        </select>
      </div>
      <div className="text-xs text-muted-foreground">{rows.length} shown</div>
      <div className="max-h-[520px] overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground sticky top-0 bg-background">
            <tr><th className="p-1">Player</th><th className="text-right">£m</th>
              <th className="text-right">Min</th><th className="text-right">TP</th>
              <th className="text-right">xPts</th><th className="p-1">Fixtures</th><th /></tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const owned = inSquad.has(p.player_id);
              const add = canAdd(p);
              return (
                <tr key={p.player_id} className={owned ? "bg-accent/40 border-t" : "border-t"}>
                  <td className="p-1">{p.web_name}{" "}
                    <span className="text-muted-foreground">{p.team_short} {p.pos}</span>
                    {p.pk_availability === 0 && (
                      <span className="ml-1 px-1 rounded bg-red-700/80 text-white text-[10px]"
                        title={p.pk_note ?? "unavailable"}>OUT</span>
                    )}
                    {p.pk_availability !== null && p.pk_availability > 0 && p.pk_availability < 1 && (
                      <span className="ml-1 px-1 rounded bg-orange-600/80 text-white text-[10px]"
                        title={p.pk_note ?? "doubt/rotation"}>?</span>
                    )}</td>
                  <td className="text-right">£{p.price_m.toFixed(1)}</td>
                  <td className="text-right tabular-nums">{p.minutes}</td>
                  <td className="text-right">{p.total_points}</td>
                  <td className="text-right">{p.xpts_horizon.toFixed(1)}</td>
                  <td className="p-1"><FixtureTicker fixtures={p.fixtures} /></td>
                  <td className="p-1 w-8">
                    {owned
                      ? <Button size="sm" variant="ghost" onClick={() => onRemove(p.player_id)}>×</Button>
                      : <Button size="sm" variant="ghost" disabled={!add.ok} title={add.reason}
                        onClick={() => onAdd(p.player_id)}>+</Button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
