# Squad Picker — Full Player List + Manual Swaps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full ~557-player list to the dev-only Squad Picker with live manual add/remove/swap, where the backend re-optimizes the XI from the edited 15.

**Architecture:** Two new backend endpoints on the `SQUAD_PICKER_MODE`-gated router — `/squad-picker/players` (full projected pool) and `/squad-picker/lineup` (validate a 15-man id list + auto-optimize XI) — sharing a refactored `project_pool` with the existing `/build`. The frontend holds the 15-man squad in client state, fetches the pool once, and calls `/lineup` (debounced) on every edit.

**Tech Stack:** Backend — FastAPI, pandas (repo `FPL/`). Frontend — React + TypeScript, @tanstack/react-query, shadcn/ui (repo `FPL-Assistant-Front/fpl-decision-hub/`).

## Global Constraints

- Dev-only: backend routes exist only under `SQUAD_PICKER_MODE=1`; frontend route gated `import.meta.env.DEV && VITE_SQUAD_PICKER === "1"`. Never production.
- All tunables via `getattr(config, "NAME", default)` — never hardcode numbers in logic files.
- `/build` behavior must not change — the existing `tests/test_squad_draft.py` + `tests/test_squad_router.py` assertions must still pass after the refactor.
- Position quota is exactly GKP 2 / DEF 5 / MID 5 / FWD 3; default `max_per_team` = 3; default `budget_m` = 100.0.
- Backend commits land on worktree branch `worktree-squad-picker-manual-swap`. Frontend commits land in the separate `FPL-Assistant-Front` repo.
- Run backend tests from the worktree with the original venv: `PYTHONPATH=. /Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL/.venv/bin/python -m pytest <path> -q`.

---

## Task 1: Extract `project_pool` from `build_squad_from_frames` (no behavior change)

**Files:**
- Modify: `src/squad_draft.py` (`build_squad_from_frames`, lines ~151-183 → new `project_pool`)
- Test: `tests/test_squad_draft.py`

**Interfaces:**
- Produces: `project_pool(elements, fixtures, teams_short, params) -> (proj: pd.DataFrame, gw_start: int, horizon: int, gws: list[int], notes: list[str])`. `proj` has columns `id, web_name, pos, team, team_short, price_m, points_per_game, total_points, selected_by_percent, xpts_gw{N}…, xpts_horizon, wildcard_score`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_squad_draft.py
def test_project_pool_returns_projected_columns():
    from src import squad_draft, transforms
    b, f = _minimal_bootstrap(), _minimal_fixtures_raw()
    elements, teams, _ = transforms.tables_from_bootstrap(b)
    fixtures = transforms.fixtures_df(f)
    teams_short = teams.set_index("id")["short_name"].to_dict()
    proj, gw_start, horizon, gws, notes = squad_draft.project_pool(
        elements, fixtures, teams_short,
        {**squad_draft.DEFAULT_PARAMS, "gw_start": 1, "horizon_gws": 5, "projection_basis": "ppg"})
    assert horizon == 5 and gws == [1, 2, 3, 4, 5]
    for col in ["id", "pos", "price_m", "total_points", "xpts_horizon", "xpts_gw1"]:
        assert col in proj.columns
    assert (proj["xpts_horizon"] >= 0).all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv-python -m pytest tests/test_squad_draft.py::test_project_pool_returns_projected_columns -q`
Expected: FAIL — `module 'src.squad_draft' has no attribute 'project_pool'`.

- [ ] **Step 3: Extract the function**

In `src/squad_draft.py`, add `project_pool` by lifting the projection block out of `build_squad_from_frames`:

```python
def project_pool(elements, fixtures, teams_short, params):
    """Shared projection pipeline for /build, /players, /lineup. Returns the
    fully projected pool DataFrame plus the resolved gw window and notes.
    No optimizer / squad-building — pure per-player projection."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    notes = _notable_exclusion_notes(elements)
    gw_start = int(p["gw_start"])
    horizon = int(p["horizon_gws"]) if p["horizon_gws"] is not None \
        else int(getattr(config, "CHIP_WILDCARD_DEFAULT_HORIZON_GWS", 5) or 5)
    horizon = max(1, min(8, horizon))
    gws = list(range(gw_start, gw_start + horizon))

    avail = _filter_availability(elements, p["include_flagged"], p["min_chance_of_playing"])
    avail = _apply_minutes_shrink(avail, p["minutes_prior_k"])
    mins = pd.to_numeric(avail.get("minutes"), errors="coerce").fillna(0.0)
    if float(p["min_fwd_minutes"]) > 0:
        drop = (avail["pos"] == "FWD") & (mins < float(p["min_fwd_minutes"]))
        avail = avail[~drop].copy()

    basis = str(p["projection_basis"])
    ppg_proj = projections.project_elements_next_gws(
        elements=avail, fixtures=fixtures, teams_short_map=teams_short,
        gw_start=gw_start, horizon_gws=horizon, fdr_strength=p["fdr_strength"])
    if basis in ("xg", "blend"):
        from src import squad_draft_xg
        proj = squad_draft_xg.xg_projection(
            avail, fixtures, teams_short, gw_start, horizon,
            blend_weight=(float(p["blend_weight"]) if basis == "blend" else 1.0),
            ppg_proj=ppg_proj, team_nudges=p["team_nudges"])
    else:
        proj = ppg_proj
    proj = projections.add_wildcard_scores(proj, gw_start=gw_start, horizon_gws=horizon)

    xpts_cols = [f"xpts_gw{g}" for g in gws if f"xpts_gw{g}" in proj.columns]
    proj["xpts_horizon"] = proj[xpts_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1) \
        if xpts_cols else 0.0
    return proj, gw_start, horizon, gws, notes
```

Then replace those lines in `build_squad_from_frames` with:

```python
def build_squad_from_frames(elements, fixtures, teams_short, params):
    p = {**DEFAULT_PARAMS, **(params or {})}
    proj, gw_start, horizon, gws, notes = project_pool(elements, fixtures, teams_short, p)
    # ...unchanged from here: objective/budget/optimizer/lineup/result...
```

(Everything from `objective = str(p["objective"])` onward stays identical.)

- [ ] **Step 4: Run the new test + the full squad suite**

Run: `PYTHONPATH=. .venv-python -m pytest tests/test_squad_draft.py tests/test_squad_router.py tests/test_squad_draft_xg.py -q`
Expected: PASS — new test passes AND all pre-existing tests still pass (proves no `/build` behavior change).

- [ ] **Step 5: Commit**

```bash
git add src/squad_draft.py tests/test_squad_draft.py
git commit -m "refactor: extract project_pool from build_squad_from_frames (no behavior change)"
```

---

## Task 2: `POST /squad-picker/players` — full projected pool

**Files:**
- Modify: `src/squad_draft.py` (add `player_pool` live wrapper + `_pool_records` helper)
- Modify: `api/squad_router.py` (add route)
- Test: `tests/test_squad_router.py`

**Interfaces:**
- Consumes: `project_pool` (Task 1).
- Produces: `squad_draft.player_pool(bootstrap, fixtures_raw, params) -> dict` with keys `gw_start, horizon_gws, projection_basis, players`. Each player: `player_id, web_name, pos, team_short, team_id, price_m, points_per_game, total_points, selected_by_percent, xpts_horizon, xpts_per_gw`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_squad_router.py
def test_players_endpoint_returns_full_pool(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/squad-picker/players", json={"horizon_gws": 5, "projection_basis": "ppg"})
    assert r.status_code == 200
    body = r.json()
    assert body["gw_start"] == 1 and body["horizon_gws"] == 5
    assert len(body["players"]) > 0
    row = body["players"][0]
    for k in ["player_id", "pos", "team_id", "price_m", "total_points",
              "xpts_horizon", "xpts_per_gw"]:
        assert k in row
    assert len(row["xpts_per_gw"]) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv-python -m pytest tests/test_squad_router.py::test_players_endpoint_returns_full_pool -q`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Add `_pool_records` + `player_pool` to `src/squad_draft.py`**

```python
def _pool_records(proj, gws):
    def num(v, d=0.0):
        n = pd.to_numeric(v, errors="coerce")
        return d if pd.isna(n) else float(n)
    out = []
    for _, r in proj.iterrows():
        out.append({
            "player_id": int(r["id"]),
            "web_name": r.get("web_name"),
            "pos": r.get("pos"),
            "team_short": r.get("team_short"),
            "team_id": int(num(r.get("team"), 0)),
            "price_m": num(r.get("price_m")),
            "points_per_game": num(r.get("points_per_game")),
            "total_points": num(r.get("total_points")),
            "selected_by_percent": num(r.get("selected_by_percent")),
            "xpts_horizon": num(r.get("xpts_horizon")),
            "xpts_per_gw": [num(r.get(f"xpts_gw{g}")) for g in gws],
        })
    return out


def player_pool(bootstrap, fixtures_raw, params=None):
    """Live wrapper: full projected player pool (no optimizer)."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    if params is None or params.get("gw_start") is None:
        p["gw_start"] = _next_gw(bootstrap)
    elements, teams, _etypes = transforms.tables_from_bootstrap(bootstrap)
    fixtures = transforms.fixtures_df(fixtures_raw)
    teams_short = teams.set_index("id")["short_name"].to_dict()
    proj, gw_start, horizon, gws, _notes = project_pool(elements, fixtures, teams_short, p)
    return {
        "gw_start": gw_start,
        "horizon_gws": horizon,
        "projection_basis": str(p["projection_basis"]),
        "players": _pool_records(proj, gws),
    }
```

- [ ] **Step 4: Add the route to `api/squad_router.py`**

```python
@router.post("/players")
def players(params: dict):
    try:
        bootstrap = fpl_client.get_bootstrap()
        fixtures_raw = fpl_client.get_fixtures()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Live FPL fetch failed: {e}")
    try:
        result = squad_draft.player_pool(bootstrap, fixtures_raw, params or {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Player pool failed: {e}")
    return _sanitize(result)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONPATH=. .venv-python -m pytest tests/test_squad_router.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/squad_draft.py api/squad_router.py tests/test_squad_router.py
git commit -m "feat: POST /squad-picker/players — full projected player pool"
```

---

## Task 3: `POST /squad-picker/lineup` — validate 15 + optimize XI

**Files:**
- Modify: `src/squad_draft.py` (add `build_lineup` + `_validate_squad` helpers)
- Modify: `api/squad_router.py` (add route)
- Test: `tests/test_squad_router.py`

**Interfaces:**
- Consumes: `project_pool` (Task 1), `optimizer.optimize_lineup`, `_parse_formation`, `_projected_points`.
- Produces: `squad_draft.build_lineup(bootstrap, fixtures_raw, player_ids, params) -> dict`. Legal → `/build`-shaped result + `"valid": True`. Illegal → `{"ok": False, "valid": False, "violations": [str, ...]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_squad_router.py
def _legal_15(client):
    # Team-aware greedy: fills the position quota while respecting the
    # 3-per-team cap (the 24-player/6-team fixture would otherwise yield an
    # illegal squad and the /lineup "legal" test would see valid=False).
    pool = client.post("/squad-picker/players", json={"projection_basis": "ppg"}).json()["players"]
    need = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    chosen, team_ct = [], {}
    for pl in sorted(pool, key=lambda x: -x["xpts_horizon"]):
        pos = pl["pos"]
        if need.get(pos, 0) <= 0:
            continue
        if team_ct.get(pl["team_id"], 0) >= 3:
            continue
        chosen.append(pl["player_id"])
        need[pos] -= 1
        team_ct[pl["team_id"]] = team_ct.get(pl["team_id"], 0) + 1
    return chosen  # 15 ids: 2/5/5/3, ≤3 per team

def test_lineup_legal_squad_optimizes(monkeypatch):
    client = _client(monkeypatch)
    ids = _legal_15(client)
    r = client.post("/squad-picker/lineup",
                    json={"player_ids": ids, "params": {"budget_m": 1000.0, "projection_basis": "ppg"}})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert len(body["starting_xi"]) == 11
    assert body["captain_player_id"] is not None

def test_lineup_bad_quota_reports_violation(monkeypatch):
    client = _client(monkeypatch)
    ids = _legal_15(client)[:-1]  # 14 players, FWD short
    r = client.post("/squad-picker/lineup",
                    json={"player_ids": ids, "params": {"budget_m": 1000.0}})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert any("15" in v or "FWD" in v for v in body["violations"])

def test_lineup_over_budget_reports_violation(monkeypatch):
    client = _client(monkeypatch)
    ids = _legal_15(client)
    r = client.post("/squad-picker/lineup",
                    json={"player_ids": ids, "params": {"budget_m": 1.0}})
    assert r.json()["valid"] is False
    assert any("budget" in v.lower() for v in r.json()["violations"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. .venv-python -m pytest tests/test_squad_router.py -k lineup -q`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Add `_validate_squad` + `build_lineup` to `src/squad_draft.py`**

```python
POSITION_QUOTA = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


def _validate_squad(picked, params):
    """picked: rows of the pool filtered to the chosen ids. Returns violations."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    budget_m = float(p["budget_m"])
    max_per_team = int(p["max_per_team"]) if p["max_per_team"] is not None \
        else int(getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3)
    v = []
    if len(picked) != 15:
        v.append(f"Squad must have 15 players (has {len(picked)}).")
    counts = picked["pos"].value_counts().to_dict()
    for pos, need in POSITION_QUOTA.items():
        have = int(counts.get(pos, 0))
        if have != need:
            v.append(f"{pos}: need {need}, have {have}.")
    team_counts = picked["team"].value_counts()
    over = team_counts[team_counts > max_per_team]
    for team_id, n in over.items():
        v.append(f"More than {max_per_team} from team {int(team_id)} (has {int(n)}).")
    cost = float(pd.to_numeric(picked.get("price_m"), errors="coerce").fillna(0.0).sum())
    if cost > budget_m + 1e-6:
        v.append(f"Over budget: £{cost:.1f}m > £{budget_m:.1f}m.")
    return v


def build_lineup(bootstrap, fixtures_raw, player_ids, params=None):
    p = {**DEFAULT_PARAMS, **(params or {})}
    if params is None or params.get("gw_start") is None:
        p["gw_start"] = _next_gw(bootstrap)
    elements, teams, _etypes = transforms.tables_from_bootstrap(bootstrap)
    fixtures = transforms.fixtures_df(fixtures_raw)
    teams_short = teams.set_index("id")["short_name"].to_dict()
    proj, gw_start, horizon, gws, notes = project_pool(elements, fixtures, teams_short, p)

    ids = [int(x) for x in (player_ids or [])]
    picked = proj[proj["id"].isin(ids)].copy()
    known = set(int(x) for x in picked["id"].tolist())
    missing = [i for i in ids if i not in known]
    violations = _validate_squad(picked, p)
    if missing:
        violations.append(f"Unknown player ids: {missing}.")
    if violations:
        return {"ok": False, "valid": False, "violations": violations, "notes": notes}

    squad_df = picked[["id", "pos", "team"]].rename(columns={"id": "player_id"})
    fixed_formations = _parse_formation(p["formation"], notes)
    lineup = optimizer.optimize_lineup(
        squad_df, proj, score_col=f"xpts_gw{gw_start}", formations=fixed_formations)
    if lineup is None and fixed_formations is not None:
        notes.append(f"Formation '{p['formation']}' not possible; using auto.")
        lineup = optimizer.optimize_lineup(squad_df, proj, score_col=f"xpts_gw{gw_start}")

    disp = proj[[c for c in ["id", "web_name", "pos", "team_short", "price_m",
                             "points_per_game", "xpts_horizon", f"xpts_gw{gw_start}"] if c in proj.columns]]
    view = squad_df.merge(disp, left_on="player_id", right_on="id", how="left", suffixes=("", "_p"))
    cost = float(pd.to_numeric(view.get("price_m"), errors="coerce").fillna(0.0).sum())
    budget_m = float(p["budget_m"])
    return {
        "ok": True,
        "valid": True,
        "violations": [],
        "notes": notes,
        "gw_start": gw_start,
        "horizon_gws": horizon,
        "projection_basis": str(p["projection_basis"]),
        "formation": lineup["formation"] if lineup else None,
        "captain_player_id": lineup["captain_player_id"] if lineup else None,
        "vice_player_id": lineup["vice_player_id"] if lineup else None,
        "budget_m": round(budget_m, 2),
        "squad_cost_m": round(cost, 2),
        "remaining_budget_m": round(max(0.0, budget_m - cost), 2),
        "squad": view.to_dict("records"),
        "starting_xi": lineup["starting_xi"].to_dict("records") if lineup else [],
        "bench": lineup["bench"].to_dict("records") if lineup else [],
        "projected_points": _projected_points(lineup, proj, gws, gw_start),
    }
```

- [ ] **Step 4: Add the route to `api/squad_router.py`**

```python
@router.post("/lineup")
def lineup(payload: dict):
    try:
        bootstrap = fpl_client.get_bootstrap()
        fixtures_raw = fpl_client.get_fixtures()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Live FPL fetch failed: {e}")
    try:
        result = squad_draft.build_lineup(
            bootstrap, fixtures_raw,
            payload.get("player_ids", []), payload.get("params", {}))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lineup failed: {e}")
    return _sanitize(result)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=. .venv-python -m pytest tests/test_squad_router.py -q`
Expected: PASS (all, including pre-existing).

- [ ] **Step 6: Commit**

```bash
git add src/squad_draft.py api/squad_router.py tests/test_squad_router.py
git commit -m "feat: POST /squad-picker/lineup — validate 15 + optimize XI"
```

---

## Task 4: Frontend API client — `getPlayers` + `optimizeLineup`

**Files:** (repo `FPL-Assistant-Front/fpl-decision-hub/`)
- Modify: `src/lib/squadPickerApi.ts`
- Test: `src/lib/squadPickerApi.test.ts`

**Interfaces:**
- Produces: `getPlayers(params) -> Promise<PlayerPool>`, `optimizeLineup(playerIds, params) -> Promise<LineupResult>`; types `PoolPlayer`, `PlayerPool`, `LineupResult`.

- [ ] **Step 1: Write the failing test**

```ts
// src/lib/squadPickerApi.test.ts
import { getPlayers, optimizeLineup } from "./squadPickerApi";

it("getPlayers posts params and returns players", async () => {
  const pool = { gw_start: 1, horizon_gws: 5, projection_basis: "ppg",
    players: [{ player_id: 1, web_name: "X", pos: "MID", team_short: "ARS",
      team_id: 1, price_m: 5, points_per_game: 4, total_points: 100,
      selected_by_percent: 10, xpts_horizon: 12, xpts_per_gw: [2,2,2,3,3] }] };
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => pool });
  const r = await getPlayers({ projection_basis: "ppg" });
  expect(r.players[0].team_id).toBe(1);
  expect((global.fetch as any).mock.calls[0][0]).toContain("/squad-picker/players");
});

it("optimizeLineup posts ids + params", async () => {
  const res = { ok: true, valid: true, violations: [], starting_xi: [], squad: [] };
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => res });
  const r = await optimizeLineup([1,2,3], { budget_m: 100 });
  const body = JSON.parse((global.fetch as any).mock.calls[0][1].body);
  expect(body.player_ids).toEqual([1,2,3]);
  expect(r.valid).toBe(true);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- squadPickerApi` (or `npx vitest run src/lib/squadPickerApi.test.ts`)
Expected: FAIL — `getPlayers`/`optimizeLineup` not exported.

- [ ] **Step 3: Implement in `src/lib/squadPickerApi.ts`**

```ts
export interface PoolPlayer {
  player_id: number; web_name: string; pos: "GKP"|"DEF"|"MID"|"FWD";
  team_short: string; team_id: number; price_m: number; points_per_game: number;
  total_points: number; selected_by_percent: number; xpts_horizon: number;
  xpts_per_gw: number[];
}
export interface PlayerPool {
  gw_start: number; horizon_gws: number; projection_basis: string; players: PoolPlayer[];
}
export type LineupResult = SquadBuildResult & { valid: boolean; violations?: string[] };

export async function getPlayers(params: SquadBuildParams): Promise<PlayerPool> {
  const res = await fetch(`${apiBase()}/squad-picker/players`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params ?? {}),
  });
  if (!res.ok) throw new Error(`Players fetch failed: HTTP ${res.status}`);
  return (await res.json()) as PlayerPool;
}

export async function optimizeLineup(
  playerIds: number[], params: SquadBuildParams): Promise<LineupResult> {
  const res = await fetch(`${apiBase()}/squad-picker/lineup`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ player_ids: playerIds, params: params ?? {} }),
  });
  if (!res.ok) throw new Error(`Lineup failed: HTTP ${res.status}`);
  return (await res.json()) as LineupResult;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/squadPickerApi.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit** (in the `FPL-Assistant-Front` repo)

```bash
git add src/lib/squadPickerApi.ts src/lib/squadPickerApi.test.ts
git commit -m "feat: squadPickerApi getPlayers + optimizeLineup clients"
```

---

## Task 5: `PlayerListPanel` component

**Files:**
- Create: `src/components/PlayerListPanel.tsx`
- Test: manual (rendered via SquadPicker in Task 6); no unit test — it's presentational.

**Interfaces:**
- Consumes: `PoolPlayer` (Task 4).
- Produces: `<PlayerListPanel players squadIds canAdd onAdd onRemove />` where `canAdd(p: PoolPlayer) -> { ok: boolean; reason?: string }`, `onAdd(id)`, `onRemove(id)`.

- [ ] **Step 1: Implement the component**

```tsx
import { useMemo, useState } from "react";
import type { PoolPlayer } from "@/lib/squadPickerApi";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type Sort = "xpts" | "tp" | "value" | "price";
const POS = ["ALL","GKP","DEF","MID","FWD"] as const;

export function PlayerListPanel({ players, squadIds, canAdd, onAdd, onRemove }: {
  players: PoolPlayer[]; squadIds: number[];
  canAdd: (p: PoolPlayer) => { ok: boolean; reason?: string };
  onAdd: (id: number) => void; onRemove: (id: number) => void;
}) {
  const [q, setQ] = useState(""); const [pos, setPos] = useState<typeof POS[number]>("ALL");
  const [maxPrice, setMaxPrice] = useState<number | "">(""); const [sort, setSort] = useState<Sort>("xpts");
  const inSquad = useMemo(() => new Set(squadIds), [squadIds]);

  const rows = useMemo(() => {
    let r = players.filter((p) =>
      (pos === "ALL" || p.pos === pos) &&
      (!q || p.web_name.toLowerCase().includes(q.toLowerCase())) &&
      (maxPrice === "" || p.price_m <= Number(maxPrice)));
    const key = (p: PoolPlayer) => sort === "tp" ? p.total_points
      : sort === "value" ? (p.price_m ? p.xpts_horizon / p.price_m : 0)
      : sort === "price" ? -p.price_m : p.xpts_horizon;
    return r.sort((a, b) => key(b) - key(a)).slice(0, 300);
  }, [players, q, pos, maxPrice, sort]);

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
        <select className="rounded-md border bg-background p-2 text-sm" value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}>
          <option value="xpts">xPts</option><option value="tp">TP</option>
          <option value="value">Value</option><option value="price">Price</option>
        </select>
      </div>
      <div className="text-xs text-muted-foreground">{rows.length} shown</div>
      <div className="max-h-[520px] overflow-y-auto">
        <table className="w-full text-xs">
          <tbody>
            {rows.map((p) => {
              const owned = inSquad.has(p.player_id);
              const add = canAdd(p);
              return (
                <tr key={p.player_id} className={owned ? "bg-accent/40 border-t" : "border-t"}>
                  <td className="p-1">{p.web_name} <span className="text-muted-foreground">{p.team_short} {p.pos}</span></td>
                  <td className="text-right">£{p.price_m.toFixed(1)}</td>
                  <td className="text-right">{p.total_points}</td>
                  <td className="text-right">{p.xpts_horizon.toFixed(1)}</td>
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
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors in `PlayerListPanel.tsx`.

- [ ] **Step 3: Commit**

```bash
git add src/components/PlayerListPanel.tsx
git commit -m "feat: PlayerListPanel — searchable/sortable player pool with add/remove"
```

---

## Task 6: Wire manual-swap state into `SquadPicker.tsx`

**Files:**
- Modify: `src/pages/SquadPicker.tsx`

**Interfaces:**
- Consumes: `getPlayers`, `optimizeLineup`, `PoolPlayer`, `LineupResult` (Task 4); `PlayerListPanel` (Task 5).

- [ ] **Step 1: Add pool query + squad state + lineup mutation**

After the existing `mutation` (auto-build), add:

```tsx
const [squadIds, setSquadIds] = useState<number[]>([]);
const poolQuery = useQuery({
  queryKey: ["squad-pool", params],
  queryFn: () => getPlayers({ ...params, team_nudges: teamNudges }),
  enabled: false, // fetched on first build
});
const lineupMutation = useMutation<LineupResult, Error, number[]>({
  mutationFn: (ids) => optimizeLineup(ids, { ...params, team_nudges: teamNudges }),
});
```

- [ ] **Step 2: Seed squad + pool on successful build**

Change the build button handler to, on success, seed the manual squad and load the pool:

```tsx
onClick={() => mutation.mutate({ ...params, team_nudges: teamNudges }, {
  onSuccess: (r) => {
    if (r.ok) {
      setSquadIds(r.squad.map((p) => p.player_id));
      poolQuery.refetch();
    }
  },
})}
```

- [ ] **Step 3: Debounced re-optimize on squad edits**

```tsx
useEffect(() => {
  if (squadIds.length === 0) return;
  const t = setTimeout(() => lineupMutation.mutate(squadIds), 250);
  return () => clearTimeout(t);
}, [squadIds]);
```

- [ ] **Step 4: `canAdd` guard + add/remove handlers**

```tsx
const pool = poolQuery.data?.players ?? [];
const byId = useMemo(() => new Map(pool.map((p) => [p.player_id, p])), [pool]);
const current = squadIds.map((id) => byId.get(id)).filter(Boolean) as PoolPlayer[];
const QUOTA = { GKP: 2, DEF: 5, MID: 5, FWD: 3 } as const;

const canAdd = (p: PoolPlayer) => {
  if (squadIds.includes(p.player_id)) return { ok: false, reason: "Already in squad" };
  if (current.filter((x) => x.pos === p.pos).length >= QUOTA[p.pos])
    return { ok: false, reason: `${p.pos} full` };
  if (current.filter((x) => x.team_id === p.team_id).length >= (params.max_per_team ?? 3))
    return { ok: false, reason: "3 from team" };
  const cost = current.reduce((s, x) => s + x.price_m, 0) + p.price_m;
  if (cost > (params.budget_m ?? 100)) return { ok: false, reason: "Over budget" };
  return { ok: true };
};
const addPlayer = (id: number) => setSquadIds((s) => s.length < 15 ? [...s, id] : s);
const removePlayer = (id: number) => setSquadIds((s) => s.filter((x) => x !== id));
```

- [ ] **Step 5: Render the panel + drive the result view from `lineupMutation`**

- Add `<PlayerListPanel players={pool} squadIds={squadIds} canAdd={canAdd} onAdd={addPlayer} onRemove={removePlayer} />` in a two-column layout beside the squad table.
- Replace `const res = mutation.data;` usage in the result section with `const res = lineupMutation.data ?? mutation.data;` so the table/projected-points reflect the latest lineup.
- Add a violations banner: `{lineupMutation.data && !lineupMutation.data.valid && (<Card className="p-3 border-destructive"><ul>{lineupMutation.data.violations?.map((v,i)=><li key={i}>{v}</li>)}</ul></Card>)}`.
- Add a `× ` remove control to each squad-table row (calls `removePlayer(p.player_id)`).
- Show 15/15 + bank from `res.squad_cost_m` / `res.remaining_budget_m`.

- [ ] **Step 6: Typecheck + manual smoke**

Run: `npx tsc --noEmit`
Then with backend running from this branch (`SQUAD_PICKER_MODE=1 uvicorn api.main:app --port 8001`) and `npm run dev`: build a squad, confirm the list populates, add/remove updates bank + XI + projected pts, and illegal adds are blocked/greyed.

- [ ] **Step 7: Commit**

```bash
git add src/pages/SquadPicker.tsx
git commit -m "feat: manual add/remove/swap + full player list in Squad Picker"
```

---

## Self-Review

- **Spec coverage:** `/players` (Task 2), `/lineup` + validation (Task 3), `project_pool` refactor (Task 1), API client (Task 4), list panel with search/filter/sort/add-remove (Task 5), squad state + seed + debounced re-optimize + bank/counter + violations (Task 6). All spec sections mapped.
- **Placeholders:** none — every code step is concrete.
- **Type consistency:** `player_id`/`team_id`/`xpts_per_gw`/`xpts_horizon` names match across backend records (`_pool_records`), TS `PoolPlayer`, and the panel/guard. `optimize_lineup` gets `squad_df` with `player_id`+`pos` and `proj` with `id`+`xpts_gw{N}` — matches `merge_scores`' contract.
- **Note:** `_minimal_bootstrap` must yield ≥2 GKP / 5 DEF / 5 MID / 3 FWD for `_legal_15` in Task 3; if the synthetic fixture is smaller, extend it in that task's Step 1.
