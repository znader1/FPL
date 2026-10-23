import { useEffect, useState } from "react";
import { fetchReplayGw, type ReplayGwRecord } from "@/lib/replayApi";

const SEASON = "2025-26";
const ENTRY_ID = Number(import.meta.env.VITE_REPLAY_ENTRY_ID ?? 588004);

export default function Replay() {
  const [gw, setGw] = useState(7);
  const [rec, setRec] = useState<ReplayGwRecord | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setErr(null);
    setRec(null);
    fetchReplayGw(SEASON, gw, ENTRY_ID, ctrl.signal)
      .then((r) => { if (!ctrl.signal.aborted) setRec(r); })
      .catch((e) => { if (!ctrl.signal.aborted) setErr(String(e)); });
    return () => ctrl.abort();
  }, [gw]);

  // element id -> readable name (falls back to #id)
  const nameOf = (id: number | null | undefined) =>
    id == null ? "—" : rec?.names?.[String(id)] ?? `#${id}`;

  const yourCaptain = rec?.your?.captain ?? null;
  // your squad, best actual first, captain pinned to top
  const players = rec
    ? [...rec.players].sort((a, b) => {
        if (a.element === yourCaptain) return -1;
        if (b.element === yourCaptain) return 1;
        return b.actual_points - a.actual_points;
      })
    : [];

  return (
    <div className="p-6 space-y-6">
      <header className="flex flex-wrap items-center gap-4">
        <h1 className="text-xl font-semibold">Replay — {SEASON}</h1>
        <label className="flex items-center gap-2">
          GW <input type="range" min={1} max={38} value={gw}
            onChange={(e) => setGw(Number(e.target.value))} />
          <span className="tabular-nums w-8">{gw}</span>
        </label>
        {rec && !rec.setup_gw && rec.your?.points != null && (
          <span className="text-sm text-muted-foreground">
            Your GW{gw}: <span className="font-medium text-foreground tabular-nums">{rec.your.points} pts</span>
            {" · captain "}<span className="font-medium text-foreground">{nameOf(yourCaptain)}</span>
          </span>
        )}
      </header>

      {err && <p className="text-red-500">{err}</p>}
      {rec?.setup_gw && <p className="text-muted-foreground">GW{gw} is the setup GW — no model projection (your real total still counts).</p>}
      {rec && !rec.setup_gw && (
        <div className="grid gap-6 md:grid-cols-2">
          <section data-testid="panel-players">
            <h2 className="font-medium mb-2">Your squad — model xPts vs actual</h2>
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr><th className="text-left font-normal">Player</th>
                  <th className="text-right font-normal">model</th>
                  <th className="text-right font-normal">actual</th></tr>
              </thead>
              <tbody>
                {players.map((p) => (
                  <tr key={p.element} className="border-t border-border/40">
                    <td className="py-0.5">
                      {nameOf(p.element)}
                      {p.element === yourCaptain && <span className="ml-1 text-xs font-semibold text-primary">(C)</span>}
                    </td>
                    <td className="text-right tabular-nums text-muted-foreground">{p.model_xpts.toFixed(1)}</td>
                    <td className="text-right tabular-nums font-medium">{p.actual_points}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section data-testid="panel-captain">
            <h2 className="font-medium mb-2">Captain — model vs you vs optimal</h2>
            <p>Model: <span className="font-medium">{nameOf(rec.model_captain)}</span></p>
            <p>You: <span className="font-medium">{nameOf(yourCaptain)}</span></p>
            <p>Optimal: <span className="font-medium">{nameOf(rec.optimal_captain)}</span></p>
          </section>

          <section data-testid="panel-transfer">
            <h2 className="font-medium mb-2">Transfer — model vs you</h2>
            <p>Model suggests:{" "}
              {rec.suggested_transfer
                ? <span><span className="font-medium">{nameOf(rec.suggested_transfer.sell)}</span> → <span className="font-medium">{nameOf(rec.suggested_transfer.buy)}</span> <span className="text-muted-foreground">(+{rec.suggested_transfer.expected_gain})</span></span>
                : <span className="text-muted-foreground">no move</span>}
            </p>
            <p>You did:{" "}
              {rec.your?.transfers && (rec.your.transfers.in.length || rec.your.transfers.out.length)
                ? <span>{rec.your.transfers.out.map(nameOf).join(", ") || "—"} → {rec.your.transfers.in.map(nameOf).join(", ") || "—"}</span>
                : <span className="text-muted-foreground">no move</span>}
            </p>
          </section>

          <section data-testid="panel-sp2">
            <h2 className="font-medium mb-2">SP2 differential EV <span className="text-xs text-muted-foreground">(global ownership)</span></h2>
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr><th className="text-left font-normal">Player</th>
                  <th className="text-right font-normal">diff-EV</th>
                  <th className="text-right font-normal">own</th></tr>
              </thead>
              <tbody>
                {rec.sp2_candidates.map((c) => (
                  <tr key={c.element} className="border-t border-border/40">
                    <td className="py-0.5">{nameOf(c.element)}</td>
                    <td className="text-right tabular-nums">{c.differential_ev.toFixed(2)}</td>
                    <td className="text-right tabular-nums text-muted-foreground">{(c.global_ownership * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}
