// Dev-only: edit the player-knowledge rail (news/injury availability +
// return-GW + minutes) that adjusts picker projections. Mirrors the team
// nudges panel but at the player axis.
import { useMemo, useState } from "react";
import {
  getPlayerKnowledge, savePlayerKnowledge, digestNews,
  type PlayerKnowledge, type PlayerKnowledgeEntry, type PoolPlayer, type DigestResult,
} from "@/lib/squadPickerApi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

const AVAIL = [
  { label: "fit", value: 1 },
  { label: "doubt", value: 0.5 },
  { label: "out", value: 0 },
];

export function PlayerKnowledgePanel({ pool, todayISO }: { pool: PoolPlayer[]; todayISO: string }) {
  const [pk, setPk] = useState<PlayerKnowledge>({ as_of: null, players: {} });
  const [loaded, setLoaded] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [digest, setDigest] = useState<DigestResult | null>(null);
  const [digesting, setDigesting] = useState(false);

  const nameById = useMemo(
    () => new Map(pool.map((p) => [String(p.player_id), `${p.web_name} (${p.team_short})`])),
    [pool]);

  const load = async () => { setBusy(true); try { setPk(await getPlayerKnowledge()); setLoaded(true); } finally { setBusy(false); } };
  const save = async () => {
    setBusy(true);
    try { setPk(await savePlayerKnowledge({ ...pk, as_of: pk.as_of ?? todayISO })); }
    finally { setBusy(false); }
  };

  const setEntry = (id: string, patch: Partial<PlayerKnowledgeEntry>) =>
    setPk((s) => ({ ...s, players: { ...s.players, [id]: { ...s.players[id], ...patch } } }));
  const removeEntry = (id: string) =>
    setPk((s) => { const players = { ...s.players }; delete players[id]; return { ...s, players }; });
  const addPlayer = (p: PoolPlayer) => {
    setEntry(String(p.player_id), { availability: 1, minutes_mult: 1, note: "" });
    setQ("");
  };
  const runDigest = async () => {
    setDigesting(true);
    try { setDigest(await digestNews()); } finally { setDigesting(false); }
  };
  const approveDigest = () => {
    if (!digest) return;
    setPk((s) => ({ ...s, players: { ...s.players, ...digest.proposals.players } }));
    setLoaded(true); // reveal the editable table so entries can be reviewed + saved
    setDigest(null);
  };

  const matches = q
    ? pool.filter((p) => p.web_name.toLowerCase().includes(q.toLowerCase())).slice(0, 8)
    : [];
  const entries = Object.entries(pk.players);

  return (
    <Card className="p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold">
          Player knowledge — news/injury {pk.as_of && <span className="text-muted-foreground">(as of {pk.as_of})</span>}
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={digesting} onClick={runDigest}>
            {digesting ? "Digesting…" : "Digest news"}
          </Button>
          {!loaded && <Button size="sm" variant="outline" disabled={busy} onClick={load}>Load</Button>}
          {(loaded || Object.keys(pk.players).length > 0) &&
            <Button size="sm" disabled={busy} onClick={save}>Save</Button>}
        </div>
      </div>

      {digest && (
        <Card className="p-2 border-primary/40">
          <div className="flex items-center justify-between mb-1">
            <div className="text-xs font-semibold">
              {Object.keys(digest.proposals.players).length} proposals · {digest.bootstrap_flags} live injuries · {digest.article_count} articles · {digest.matched_players} matched
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={approveDigest}
                disabled={Object.keys(digest.proposals.players).length === 0}>Approve all</Button>
              <Button size="sm" variant="ghost" onClick={() => setDigest(null)}>Dismiss</Button>
            </div>
          </div>
          {Object.keys(digest.proposals.players).length === 0
            ? <div className="text-xs text-muted-foreground">No availability/minutes signals found in the news.</div>
            : <ul className="text-xs space-y-0.5">
                {Object.entries(digest.proposals.players).map(([id, e]) => (
                  <li key={id}>
                    <span className={`mr-1 px-1 rounded text-[10px] ${e.source === "fpl_bootstrap"
                      ? "bg-red-700/80 text-white" : "bg-sky-700/70 text-white"}`}>
                      {e.source === "fpl_bootstrap" ? "injury" : "news"}
                    </span>
                    <b>{nameById.get(id) ?? id}</b>: avail {e.availability}
                    {e.available_from_gw ? `, from GW${e.available_from_gw}` : ""}
                    {e.minutes_mult !== undefined && e.minutes_mult !== 1 ? `, min×${e.minutes_mult}` : ""}
                    {e.note ? ` — ${e.note}` : ""}
                  </li>
                ))}
              </ul>}
        </Card>
      )}

      {loaded && (
        <>
          <div className="relative">
            <Input placeholder="Add player by name…" value={q} onChange={(e) => setQ(e.target.value)} className="w-64" />
            {matches.length > 0 && (
              <div className="absolute z-10 mt-1 w-64 rounded-md border bg-background shadow">
                {matches.map((p) => (
                  <button key={p.player_id} className="block w-full text-left px-2 py-1 text-xs hover:bg-accent"
                    onClick={() => addPlayer(p)}>
                    {p.web_name} <span className="text-muted-foreground">{p.team_short} {p.pos}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {entries.length === 0 && <div className="text-xs text-muted-foreground">No entries. Add a player above.</div>}
          {entries.length > 0 && (
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr><th className="p-1">Player</th><th>Avail</th><th>From GW</th><th>Min mult</th><th>Note</th><th /></tr>
              </thead>
              <tbody>
                {entries.map(([id, e]) => (
                  <tr key={id} className="border-t">
                    <td className="p-1">{nameById.get(id) ?? id}</td>
                    <td>
                      <select className="rounded border bg-background p-1" value={e.availability ?? 1}
                        onChange={(ev) => setEntry(id, { availability: Number(ev.target.value) })}>
                        {AVAIL.map((a) => <option key={a.label} value={a.value}>{a.label}</option>)}
                      </select>
                    </td>
                    <td>
                      <Input type="number" className="w-16 h-7" value={e.available_from_gw ?? ""}
                        onChange={(ev) => setEntry(id, { available_from_gw: ev.target.value === "" ? null : Number(ev.target.value) })} />
                    </td>
                    <td>
                      <Input type="number" step={0.1} className="w-16 h-7" value={e.minutes_mult ?? 1}
                        onChange={(ev) => setEntry(id, { minutes_mult: Number(ev.target.value) })} />
                    </td>
                    <td>
                      <Input className="w-40 h-7" value={e.note ?? ""}
                        onChange={(ev) => setEntry(id, { note: ev.target.value })} />
                    </td>
                    <td><Button size="sm" variant="ghost" onClick={() => removeEntry(id)}>×</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="text-[11px] text-muted-foreground">
            Applies per-GW: out before “From GW”, then availability × minutes-mult on projected points. Rebuild to see the effect.
          </p>
        </>
      )}
    </Card>
  );
}
