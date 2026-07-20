# Personal GW Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A personal, local-only frontend mode to replay any past GW of a completed FPL season and compare, per GW, the model's output vs. actual results vs. your real team.

**Architecture:** Precompute — two one-off producers (entry snapshot from frozen raw FPL JSON; per-GW model output via the leak-safe walk-forward engine) write static JSON under `data/replay/<season>/`. A `REPLAY_MODE`-gated FastAPI router serves merged payloads. A `VITE_REPLAY_MODE`-gated `/replay` frontend route renders four comparison panels. Historical data is immutable, so files are a correct cache; the live FPL API is touched once (already done — raw snapshot frozen).

**Tech Stack:** Python 3.10, pandas, FastAPI (backend, pytest); React + Vite + TypeScript (frontend, vitest). No new runtime deps.

## Global Constraints

- **Runtime deps unchanged** (pandas, FastAPI, React/Vite). pytest + vitest are dev-only.
- **Never shipped:** backend router mounts only when `os.environ["REPLAY_MODE"] == "1"`; frontend route registers only when `import.meta.env.VITE_REPLAY_MODE === "1"` (absent from `.env.production`). No edits to shipped League/Squad/Index pages or their endpoints.
- **Personal data never committed:** `data/replay/` is in `.gitignore` (already added). Verify before every commit.
- **No future leak:** per-GW model output uses only GWs `< target_gw`. Enforced by `backtest_adapter.build_history_df` (`player_actuals_through(target_gw - 1)`) and by patching `projections.load_latest_player_gw_history`.
- **Season is a parameter** everywhere; default `"2025-26"`. First (and only current) data set: `2025-26`, GW1–38 in `data/vaastav/2025-26/`.
- **Position ids:** 1=GKP, 2=DEF, 3=MID, 4=FWD.
- **GW1 is the setup GW** in the walk-forward (unscored, no `< 1` history); model output for it is marked `setup_gw: true`. Your real GW1 still appears from the entry snapshot.
- **Entry under test:** `588004` ("ZN Elite", 2338 pts). Raw snapshot already frozen at `data/replay/2025-26/raw/` (entry.json, history.json, picks_gw01..38.json).
- Follow existing patterns; read config via `getattr(config, "NAME", default)`.

## File structure

| File | Responsibility |
|------|----------------|
| `src/replay_snapshot.py` (new) | Pure: parse frozen raw FPL JSON → clean entry snapshot dict |
| `scripts/snapshot_entry.py` (new) | Thin CLI over `replay_snapshot` → writes `entry_<id>.json` |
| `src/replay_builder.py` (new) | Pure: per-GW model record (model xPts, model captain, optimal captain, suggested transfer, SP2 candidates, actuals) |
| `scripts/build_replay.py` (new) | Thin CLI over `replay_builder` → writes `gwNN.json` for a GW range |
| `api/replay_router.py` (new) | FastAPI `APIRouter`; reads JSON, merges entry + GW model; conditionally mounted |
| `api/main.py` (modify) | One guarded `include_router` |
| `tests/test_replay_snapshot.py` (new) | Unit: snapshot parser |
| `tests/test_replay_builder.py` (new) | Unit: builder (model xPts, optimal captain, no-leak, SP2 ownership) |
| `tests/test_replay_router.py` (new) | Unit: router via FastAPI TestClient (gating + merge + 404) |
| `fpl-decision-hub/src/lib/replayApi.ts` (new) | Types + fetch for replay endpoints |
| `fpl-decision-hub/src/pages/Replay.tsx` (new) | GW slider + 4 panels |
| `fpl-decision-hub/src/App.tsx` (modify) | Gated `/replay` route |
| `fpl-decision-hub/src/pages/Replay.test.tsx` (new) | Render panels from fixture; gating |

Data contracts are defined in the spec (`docs/superpowers/specs/2026-07-20-personal-gw-replay-design.md`) and repeated at the tasks that produce them.

---

### Task 1: Entry snapshot parser (`src/replay_snapshot.py` + CLI)

**Files:**
- Create: `src/replay_snapshot.py`
- Create: `scripts/snapshot_entry.py`
- Test: `tests/test_replay_snapshot.py`

**Interfaces:**
- Produces:
  - `replay_snapshot.build_entry_snapshot(raw_dir: str, season: str = "2025-26") -> dict` — reads `entry.json`, `history.json`, `picks_gwNN.json` from `raw_dir`; returns
    `{"entry_id": int, "season": str, "gws": {gw:int -> {"picks": [element_ids], "captain": int|None, "vice": int|None, "transfers": {"in": [int], "out": [int]}, "chip": str|None, "points": int|None, "bank": float|None}}}`.
  - `replay_snapshot.derive_transfers(prev_picks: list[int], picks: list[int]) -> dict` — `{"in": sorted(set(picks)-set(prev)), "out": sorted(set(prev)-set(picks))}`; `{"in": [], "out": []}` when `prev_picks` is empty.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_snapshot.py
import json
from pathlib import Path
from src import replay_snapshot


def _write_raw(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "entry.json").write_text(json.dumps({"id": 588004}))
    (raw / "history.json").write_text(json.dumps({"current": []}))
    (raw / "picks_gw01.json").write_text(json.dumps({
        "active_chip": None,
        "entry_history": {"points": 53, "bank": 0, "event_transfers": 0},
        "picks": [{"element": 351, "is_captain": True, "is_vice_captain": False, "multiplier": 2},
                  {"element": 233, "is_captain": False, "is_vice_captain": True, "multiplier": 1}],
    }))
    (raw / "picks_gw02.json").write_text(json.dumps({
        "active_chip": "wildcard",
        "entry_history": {"points": 44, "bank": 15, "event_transfers": 1},
        "picks": [{"element": 351, "is_captain": True, "is_vice_captain": False, "multiplier": 2},
                  {"element": 99, "is_captain": False, "is_vice_captain": True, "multiplier": 1}],
    }))
    return raw


def test_build_entry_snapshot_shape_and_transfers(tmp_path):
    raw = _write_raw(tmp_path)
    snap = replay_snapshot.build_entry_snapshot(str(raw), season="2025-26")
    assert snap["entry_id"] == 588004
    assert snap["season"] == "2025-26"
    g1, g2 = snap["gws"][1], snap["gws"][2]
    assert g1["captain"] == 351 and g1["vice"] == 233 and g1["points"] == 53
    assert g1["transfers"] == {"in": [], "out": []}       # first GW: no prior
    assert g1["chip"] is None
    # GW2 squad dropped 233, added 99 vs GW1
    assert g2["transfers"] == {"in": [99], "out": [233]}
    assert g2["chip"] == "wildcard"
    assert g2["bank"] == 1.5                                # 15 tenths -> £1.5m


def test_derive_transfers_empty_prev():
    assert replay_snapshot.derive_transfers([], [1, 2]) == {"in": [], "out": []}
    assert replay_snapshot.derive_transfers([1, 2], [2, 3]) == {"in": [3], "out": [1]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.replay_snapshot'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/replay_snapshot.py
"""Parse frozen raw FPL entry JSON (data/replay/<season>/raw/) into a clean,
per-GW entry snapshot. Pure: no network, no FastAPI."""
import json
from pathlib import Path


def derive_transfers(prev_picks, picks):
    if not prev_picks:
        return {"in": [], "out": []}
    prev, cur = set(prev_picks), set(picks)
    return {"in": sorted(cur - prev), "out": sorted(prev - cur)}


def _load(path):
    return json.loads(Path(path).read_text())


def build_entry_snapshot(raw_dir, season="2025-26"):
    raw = Path(raw_dir)
    entry = _load(raw / "entry.json")
    gws = {}
    prev_picks = []
    for pick_file in sorted(raw.glob("picks_gw*.json")):
        gw = int(pick_file.stem.replace("picks_gw", ""))
        d = _load(pick_file)
        picks_rows = d.get("picks", [])
        pick_ids = [int(p["element"]) for p in picks_rows]
        eh = d.get("entry_history", {}) or {}
        cap = next((int(p["element"]) for p in picks_rows if p.get("is_captain")), None)
        vice = next((int(p["element"]) for p in picks_rows if p.get("is_vice_captain")), None)
        bank = eh.get("bank")
        gws[gw] = {
            "picks": pick_ids,
            "captain": cap,
            "vice": vice,
            "transfers": derive_transfers(prev_picks, pick_ids),
            "chip": d.get("active_chip"),
            "points": eh.get("points"),
            "bank": (bank / 10.0) if isinstance(bank, (int, float)) else None,
        }
        prev_picks = pick_ids
    return {"entry_id": int(entry.get("id")), "season": season, "gws": gws}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_snapshot.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Add the CLI wrapper**

```python
# scripts/snapshot_entry.py
#!/usr/bin/env python3
"""Write a clean per-GW entry snapshot from frozen raw FPL JSON.

Raw files must already exist under data/replay/<season>/raw/
(entry.json, history.json, picks_gwNN.json). Capture them with the raw fetch
first; this script only parses local files (no network).

Usage:
  python -m scripts.snapshot_entry --entry 588004 --season 2025-26
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import replay_snapshot  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", type=int, required=True)
    ap.add_argument("--season", default="2025-26")
    args = ap.parse_args()
    base = Path("data/replay") / args.season
    raw = base / "raw"
    if not raw.exists():
        print(f"ERROR: raw dir missing: {raw}. Capture raw FPL JSON first.", file=sys.stderr)
        return 1
    snap = replay_snapshot.build_entry_snapshot(str(raw), season=args.season)
    out = base / f"entry_{args.entry}.json"
    out.write_text(json.dumps(snap, indent=2))
    print(f"Wrote {out} ({len(snap['gws'])} GWs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Generate the real snapshot + verify gitignored**

Run:
```bash
python -m scripts.snapshot_entry --entry 588004 --season 2025-26
git check-ignore data/replay/2025-26/entry_588004.json && echo "IGNORED OK"
```
Expected: `Wrote data/replay/2025-26/entry_588004.json (38 GWs)` then `IGNORED OK`

- [ ] **Step 7: Commit (code + tests only — NOT data)**

```bash
git add src/replay_snapshot.py scripts/snapshot_entry.py tests/test_replay_snapshot.py
git status --short   # confirm NO data/replay/ paths staged
git commit -m "feat: entry snapshot parser for personal GW replay"
```

---

### Task 2: Builder core — model xPts, captains, actuals (`src/replay_builder.py`)

**Files:**
- Create: `src/replay_builder.py`
- Test: `tests/test_replay_builder.py`

**Interfaces:**
- Consumes: `backtest_adapter.build_engine_inputs`, `backtest_data.player_actuals_at`, `projections.project_elements_next_gws`, `projections.load_latest_player_gw_history`.
- Produces:
  - `replay_builder.model_projection(gw: int, season: str, horizon: int = 3) -> pd.DataFrame` — leak-safe per-player projection; columns `player_id:int, model_xpts:float`. Mirrors `scripts/backtest_season.project_gw_engine` but self-contained in `src/`.
  - `replay_builder.optimal_captain(squad_ids: list[int], actuals: pd.DataFrame) -> int|None` — the `player_id` in `squad_ids` with the highest `total_points` in `actuals` (None if none present).
  - `replay_builder.build_gw_record(gw, season, entry_snapshot, horizon=3) -> dict` — assembles the per-GW record (players/model_captain/optimal_captain/actuals; transfer + SP2 added in Task 3). Uses `entry_snapshot["gws"].get(gw)` for the squad.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_builder.py
import pandas as pd
from src import replay_builder


def test_optimal_captain_picks_max_actual_in_squad():
    actuals = pd.DataFrame({"player_id": [1, 2, 3], "total_points": [4, 12, 7]})
    assert replay_builder.optimal_captain([1, 2, 3], actuals) == 2
    assert replay_builder.optimal_captain([1, 3], actuals) == 3   # 2 excluded
    assert replay_builder.optimal_captain([99], actuals) is None  # not present


def test_optimal_captain_empty():
    assert replay_builder.optimal_captain([], pd.DataFrame({"player_id": [], "total_points": []})) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.replay_builder'`

- [ ] **Step 3: Write minimal implementation (optimal_captain + model_projection)**

```python
# src/replay_builder.py
"""Pure per-GW model-vs-reality records for personal GW replay.

Reuses the leak-safe walk-forward engine (Vaastav data via backtest_adapter).
No network, no FastAPI."""
import pandas as pd

from src import projections, ownership_ev, backtest_data
from src.backtest_adapter import build_engine_inputs

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def optimal_captain(squad_ids, actuals):
    if not squad_ids or actuals.empty:
        return None
    a = actuals[actuals["player_id"].isin([int(x) for x in squad_ids])]
    a = a.dropna(subset=["total_points"])
    if a.empty:
        return None
    return int(a.loc[a["total_points"].astype(float).idxmax(), "player_id"])


def model_projection(gw, season="2025-26", horizon=3):
    """Leak-safe per-player projection. Mirrors backtest_season.project_gw_engine
    but kept in src/ so the builder does not import from scripts/."""
    elements, fixtures, teams_short, history_df = build_engine_inputs(gw, season, horizon)
    orig = projections.load_latest_player_gw_history
    projections.load_latest_player_gw_history = lambda **kw: history_df
    try:
        proj = projections.project_elements_next_gws(
            elements=elements, fixtures=fixtures, teams_short_map=teams_short,
            gw_start=gw, horizon_gws=horizon,
        )
    finally:
        projections.load_latest_player_gw_history = orig
    return pd.DataFrame({
        "player_id": proj["id"].astype(int),
        "model_xpts": pd.to_numeric(proj.get(f"xpts_gw{gw}"), errors="coerce").fillna(0.0),
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_replay_builder.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Add `build_gw_record` (core panels 1 + 2) + integration test**

Append to `src/replay_builder.py`:

```python
def _model_captain(squad_ids, proj):
    """Highest model_xpts player among the squad."""
    in_squad = proj[proj["player_id"].isin([int(x) for x in squad_ids])]
    if in_squad.empty:
        return None
    return int(in_squad.loc[in_squad["model_xpts"].idxmax(), "player_id"])


def build_gw_record(gw, season, entry_snapshot, horizon=3):
    gw_entry = (entry_snapshot.get("gws") or {}).get(gw) or {}
    squad_ids = gw_entry.get("picks", [])
    setup_gw = gw <= 1
    record = {"season": season, "gw": int(gw), "setup_gw": setup_gw,
              "players": [], "model_captain": None, "optimal_captain": None,
              "suggested_transfer": None, "sp2_candidates": []}
    if setup_gw:
        return record

    actuals = backtest_data.player_actuals_at(gw, season)[["player_id", "total_points", "minutes"]].copy()
    actuals["player_id"] = actuals["player_id"].astype(int)
    proj = model_projection(gw, season, horizon)

    merged = pd.DataFrame({"player_id": [int(x) for x in squad_ids]}).merge(
        proj, on="player_id", how="left").merge(
        actuals, on="player_id", how="left")
    merged["model_xpts"] = merged["model_xpts"].fillna(0.0)
    merged["total_points"] = merged["total_points"].fillna(0)
    record["players"] = [
        {"element": int(r.player_id), "model_xpts": round(float(r.model_xpts), 2),
         "actual_points": int(r.total_points)}
        for r in merged.itertuples()
    ]
    record["model_captain"] = _model_captain(squad_ids, proj)
    record["optimal_captain"] = optimal_captain(squad_ids, actuals)
    return record
```

Add integration test (real 2025-26 data, GW7):

```python
# tests/test_replay_builder.py  (append)
def test_build_gw_record_gw7_real_data():
    snap = {"season": "2025-26", "gws": {7: {"picks": [351, 233, 99], "captain": 351}}}
    rec = replay_builder.build_gw_record(7, "2025-26", snap, horizon=3)
    assert rec["gw"] == 7 and rec["setup_gw"] is False
    assert len(rec["players"]) == 3
    assert all(set(p) == {"element", "model_xpts", "actual_points"} for p in rec["players"])
    assert rec["optimal_captain"] in (351, 233, 99)


def test_build_gw_record_gw1_is_setup():
    snap = {"season": "2025-26", "gws": {1: {"picks": [351]}}}
    rec = replay_builder.build_gw_record(1, "2025-26", snap)
    assert rec["setup_gw"] is True and rec["players"] == []
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_replay_builder.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add src/replay_builder.py tests/test_replay_builder.py
git commit -m "feat: replay builder core (model xPts, captains, actuals)"
```

---

### Task 3: Builder — suggested transfer + SP2 candidates (real per-GW ownership)

**Files:**
- Modify: `src/replay_builder.py`
- Test: `tests/test_replay_builder.py`

**Interfaces:**
- Consumes: `ownership_ev.compute_position_templates`, `ownership_ev.annotate_candidates`, Vaastav `selected` column via a new `_gw_global_ownership`.
- Produces:
  - `replay_builder._gw_global_ownership(gw, season) -> dict[int, float]` — `player_id -> selected/selected.max()` (0..1) from the Vaastav GW file; empty dict if column absent.
  - Extends `build_gw_record` to fill `suggested_transfer` (may be `None`) and `sp2_candidates` (top 8 by `differential_ev`, each `{"element", "differential_ev", "template_xpts", "global_ownership", "ownership_basis": "global"}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_builder.py  (append)
def test_gw_global_ownership_normalized():
    own = replay_builder._gw_global_ownership(7, "2025-26")
    assert own                              # non-empty
    assert max(own.values()) == 1.0         # normalized to the most-selected
    assert all(0.0 <= v <= 1.0 for v in own.values())


def test_sp2_candidates_present_and_labeled():
    snap = {"season": "2025-26", "gws": {7: {"picks": [351, 233, 99], "captain": 351}}}
    rec = replay_builder.build_gw_record(7, "2025-26", snap, horizon=3)
    assert isinstance(rec["sp2_candidates"], list) and len(rec["sp2_candidates"]) > 0
    c = rec["sp2_candidates"][0]
    assert set(c) == {"element", "differential_ev", "template_xpts", "global_ownership", "ownership_basis"}
    assert c["ownership_basis"] == "global"
    # sorted descending by differential_ev
    evs = [x["differential_ev"] for x in rec["sp2_candidates"]]
    assert evs == sorted(evs, reverse=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_builder.py::test_gw_global_ownership_normalized -v`
Expected: FAIL — `AttributeError: module 'src.replay_builder' has no attribute '_gw_global_ownership'`

- [ ] **Step 3: Implement ownership + SP2 wiring**

Append `_gw_global_ownership` and a `_sp2_candidates` helper to `src/replay_builder.py`, and extend `build_gw_record`:

```python
def _gw_global_ownership(gw, season="2025-26", base="data/vaastav"):
    from pathlib import Path
    path = Path(base) / season / "gws" / f"gw{int(gw)}.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if "selected" not in df.columns or "element" not in df.columns:
        return {}
    sel = pd.to_numeric(df["selected"], errors="coerce").fillna(0.0)
    m = sel.max()
    if not m:
        return {}
    return {int(e): float(s) / float(m) for e, s in zip(df["element"], sel)}


def _sp2_candidates(gw, season, proj, actuals, ownership, top_n=8):
    """Global-ownership differential EV over the full player market that GW."""
    a = actuals.set_index("player_id")
    # element meta keyed by id for ownership_ev.compute_position_templates
    meta, cands = {}, []
    for r in proj.itertuples():
        pid = int(r.player_id)
        pos_row = a.loc[pid] if pid in a.index else None
        pos_id = int(pos_row["position_id"]) if pos_row is not None and "position_id" in a.columns else None
        m = {"position_id": pos_id, "model_xpts_horizon": float(r.model_xpts),
             "selected_by_percent": ownership.get(pid, 0.0) * 100.0}
        meta[pid] = m
        cands.append({"id": pid, "position_id": pos_id,
                      "model_xpts_horizon": float(r.model_xpts),
                      "league_ownership": ownership.get(pid, 0.0)})
    templates = ownership_ev.compute_position_templates(meta)
    annotated = ownership_ev.annotate_candidates(
        [c for c in cands if c["position_id"] is not None], templates)
    annotated.sort(key=lambda c: c.get("differential_ev", 0.0), reverse=True)
    return [{"element": int(c["id"]),
             "differential_ev": round(float(c["differential_ev"]), 2),
             "template_xpts": round(float(c["template_xpts"]), 2),
             "global_ownership": round(float(c["league_ownership"]), 4),
             "ownership_basis": "global"} for c in annotated[:top_n]]
```

Extend `build_gw_record` — before `return record`, after computing `proj`/`actuals` (add `position_id` to the actuals load and a transfer via `transfer_advisor.top_transfer` is out of scope for a pure builder; use a simple market-based suggestion). Replace the actuals load line in Task 2 with:

```python
    actuals = backtest_data.player_actuals_at(gw, season)[
        ["player_id", "total_points", "minutes"]].copy()
    actuals["player_id"] = actuals["player_id"].astype(int)
    # position_id from the Vaastav GW file for SP2 templates
    import pandas as _pd
    from pathlib import Path as _Path
    _gwf = _Path("data/vaastav") / season / "gws" / f"gw{int(gw)}.csv"
    if _gwf.exists():
        _pos = _pd.read_csv(_gwf)[["element", "position"]].copy()
        _pos["player_id"] = _pos["element"].astype(int)
        _pos["position_id"] = _pos["position"].map({"GKP": 1, "GK": 1, "DEF": 2, "MID": 3, "FWD": 4})
        actuals = actuals.merge(_pos[["player_id", "position_id"]], on="player_id", how="left")
```

And before `return record`:

```python
    ownership = _gw_global_ownership(gw, season)
    record["sp2_candidates"] = _sp2_candidates(gw, season, proj, actuals, ownership)
    # Suggested transfer: best single upgrade in the squad's weakest slot by model xPts.
    record["suggested_transfer"] = _suggest_transfer(squad_ids, proj)
```

Add `_suggest_transfer` (self-contained, market = full projection):

```python
def _suggest_transfer(squad_ids, proj, min_gain=0.6):
    """Weakest owned player vs. best non-owned player at the same implied rank.
    Simple, market-wide: swap the lowest-model owned player for the highest-model
    non-owned player when the gain clears min_gain."""
    owned = proj[proj["player_id"].isin([int(x) for x in squad_ids])]
    if owned.empty:
        return None
    sell = owned.loc[owned["model_xpts"].idxmin()]
    pool = proj[~proj["player_id"].isin([int(x) for x in squad_ids])]
    if pool.empty:
        return None
    buy = pool.loc[pool["model_xpts"].idxmax()]
    gain = float(buy["model_xpts"]) - float(sell["model_xpts"])
    if gain < min_gain:
        return None
    return {"sell": int(sell["player_id"]), "buy": int(buy["player_id"]),
            "expected_gain": round(gain, 2)}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_replay_builder.py -v`
Expected: PASS (all builder tests, incl. the two new SP2/ownership tests)

- [ ] **Step 5: Commit**

```bash
git add src/replay_builder.py tests/test_replay_builder.py
git commit -m "feat: replay builder transfer + SP2 (real per-GW global ownership)"
```

---

### Task 4: `build_replay.py` CLI + generate artifacts

**Files:**
- Create: `scripts/build_replay.py`

**Interfaces:**
- Consumes: `replay_builder.build_gw_record`, `replay_snapshot` output on disk (`entry_<id>.json` optional — builder reads it if passed).
- Produces: `data/replay/<season>/gwNN.json` for each GW in range.

- [ ] **Step 1: Write the CLI**

```python
# scripts/build_replay.py
#!/usr/bin/env python3
"""Precompute per-GW model-vs-reality records for personal GW replay.

Usage:
  python -m scripts.build_replay --season 2025-26 --start 2 --end 38 --entry 588004
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import replay_builder  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2025-26")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=38)
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--entry", type=int, default=None,
                    help="entry id whose snapshot supplies each GW's squad")
    args = ap.parse_args()

    base = Path("data/replay") / args.season
    snapshot = {"season": args.season, "gws": {}}
    if args.entry:
        snap_path = base / f"entry_{args.entry}.json"
        if snap_path.exists():
            raw = json.loads(snap_path.read_text())
            snapshot = {"season": args.season,
                        "gws": {int(k): v for k, v in raw.get("gws", {}).items()}}
        else:
            print(f"WARN: {snap_path} not found; squads will be empty.", file=sys.stderr)

    base.mkdir(parents=True, exist_ok=True)
    for gw in range(args.start, args.end + 1):
        rec = replay_builder.build_gw_record(gw, args.season, snapshot, horizon=args.horizon)
        out = base / f"gw{gw:02d}.json"
        out.write_text(json.dumps(rec, indent=2))
        print(f"  wrote {out} (players={len(rec['players'])}, setup={rec['setup_gw']})")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Generate the real artifacts**

Run:
```bash
python -m scripts.build_replay --season 2025-26 --start 1 --end 38 --entry 588004
ls data/replay/2025-26/gw*.json | wc -l   # expect 38
git check-ignore data/replay/2025-26/gw07.json && echo "IGNORED OK"
```
Expected: 38 files written; `IGNORED OK`

- [ ] **Step 3: Spot-check one GW**

Run: `python -c "import json; d=json.load(open('data/replay/2025-26/gw07.json')); print('players', len(d['players']), '| model_cap', d['model_captain'], '| opt_cap', d['optimal_captain'], '| sp2', len(d['sp2_candidates']))"`
Expected: non-zero players, captains set, sp2 populated.

- [ ] **Step 4: Commit (code only — data is gitignored)**

```bash
git add scripts/build_replay.py
git status --short   # confirm NO data/replay/ staged
git commit -m "feat: build_replay CLI generates per-GW replay records"
```

---

### Task 5: `api/replay_router.py` + gated mount

**Files:**
- Create: `api/replay_router.py`
- Modify: `api/main.py`
- Test: `tests/test_replay_router.py`

**Interfaces:**
- Produces (FastAPI routes):
  - `GET /replay/seasons -> {"seasons": [str]}`
  - `GET /replay/{season}/gw/{gw}?entry_id= -> merged record` (`gwNN.json` fields + `"your": {captain, transfers, chip, points}` from `entry_<id>.json`; `your: null` if no entry).
  - `GET /replay/{season}/summary?entry_id= -> {"season", "gws": [{gw, your_points}], "your_total"}`.
  - 404 (naming season/gw) when a file is missing; never falls back to live API.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay_router.py
import json
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = tmp_path / "data" / "replay" / "2025-26"
    base.mkdir(parents=True)
    (base / "gw07.json").write_text(json.dumps({
        "season": "2025-26", "gw": 7, "setup_gw": False,
        "players": [{"element": 351, "model_xpts": 6.4, "actual_points": 12}],
        "model_captain": 351, "optimal_captain": 351,
        "suggested_transfer": None, "sp2_candidates": []}))
    (base / "entry_588004.json").write_text(json.dumps({
        "entry_id": 588004, "season": "2025-26",
        "gws": {"7": {"captain": 233, "transfers": {"in": [], "out": []},
                      "chip": None, "points": 61}}}))
    from api.replay_router import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_gw_endpoint_merges_your_side(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    r = client.get("/replay/2025-26/gw/7", params={"entry_id": 588004})
    assert r.status_code == 200
    body = r.json()
    assert body["model_captain"] == 351
    assert body["your"]["captain"] == 233 and body["your"]["points"] == 61


def test_missing_gw_is_404(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    r = client.get("/replay/2025-26/gw/99", params={"entry_id": 588004})
    assert r.status_code == 404
    assert "2025-26" in r.json()["detail"] and "99" in r.json()["detail"]


def test_seasons_lists_available(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    assert client.get("/replay/seasons").json()["seasons"] == ["2025-26"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_replay_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.replay_router'`

- [ ] **Step 3: Implement the router**

```python
# api/replay_router.py
"""Personal GW-replay API. Serves precomputed static JSON from data/replay/.
Mounted ONLY when REPLAY_MODE=1 (see api/main.py). Never falls back to the live
FPL API — a missing file is a 404, by design."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/replay", tags=["replay"])

_BASE = Path("data/replay")


def _season_dir(season):
    return _BASE / season


@router.get("/seasons")
def seasons():
    if not _BASE.exists():
        return {"seasons": []}
    return {"seasons": sorted(p.name for p in _BASE.iterdir()
                              if p.is_dir() and any(p.glob("gw*.json")))}


def _load_entry(season, entry_id):
    if not entry_id:
        return None
    p = _season_dir(season) / f"entry_{entry_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


@router.get("/{season}/gw/{gw}")
def gw(season: str, gw: int, entry_id: int = Query(None)):
    p = _season_dir(season) / f"gw{gw:02d}.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"No replay record for season {season} GW {gw}")
    record = json.loads(p.read_text())
    entry = _load_entry(season, entry_id)
    record["your"] = (entry.get("gws", {}) or {}).get(str(gw)) if entry else None
    return record


@router.get("/{season}/summary")
def summary(season: str, entry_id: int = Query(None)):
    entry = _load_entry(season, entry_id)
    gws = (entry.get("gws", {}) if entry else {}) or {}
    rows = [{"gw": int(k), "your_points": v.get("points")} for k, v in sorted(gws.items(), key=lambda x: int(x[0]))]
    total = sum(r["your_points"] or 0 for r in rows)
    return {"season": season, "gws": rows, "your_total": total}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_replay_router.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Gated mount in `api/main.py`**

Find where other routers/routes are registered (search `app.include_router` or the `app = FastAPI(` block). Add, after `app` is created:

```python
# --- personal GW replay (local-only; never enabled in production) ---
if os.environ.get("REPLAY_MODE") == "1":
    from api.replay_router import router as replay_router
    app.include_router(replay_router)
```

Verify `import os` exists at the top of `api/main.py` (add it if missing).

- [ ] **Step 6: Verify gated mount both ways**

Run:
```bash
REPLAY_MODE=1 python -c "from api.main import app; print('replay' in [r.path.split('/')[1] for r in app.routes])"
python -c "from api.main import app; print('replay' in [getattr(r,'path','') for r in app.routes if '/replay' in getattr(r,'path','')])"
```
Expected: first prints `True` (mounted); second prints `False` (absent without env).

- [ ] **Step 7: Commit**

```bash
git add api/replay_router.py api/main.py tests/test_replay_router.py
git commit -m "feat: REPLAY_MODE-gated replay API router"
```

---

### Task 6: Frontend replay API client (`replayApi.ts`)

**Files:**
- Create: `fpl-decision-hub/src/lib/replayApi.ts`
- Test: `fpl-decision-hub/src/lib/replayApi.test.ts`

**Interfaces:**
- Produces:
  - Types `ReplayPlayer`, `ReplaySp2Candidate`, `ReplayYourSide`, `ReplayGwRecord`.
  - `replayEnabled(): boolean` — `import.meta.env.VITE_REPLAY_MODE === "1"`.
  - `fetchReplayGw(season: string, gw: number, entryId: number, signal?: AbortSignal): Promise<ReplayGwRecord>` — GETs `${apiBase}/replay/${season}/gw/${gw}?entry_id=${entryId}`, reusing the existing API base resolution.

- [ ] **Step 1: Write the failing test**

```ts
// fpl-decision-hub/src/lib/replayApi.test.ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchReplayGw } from "./replayApi";

afterEach(() => vi.restoreAllMocks());

describe("fetchReplayGw", () => {
  it("calls the replay endpoint with entry_id and returns the record", async () => {
    const record = { season: "2025-26", gw: 7, setup_gw: false, players: [],
      model_captain: 351, optimal_captain: 351, suggested_transfer: null,
      sp2_candidates: [], your: { captain: 233, points: 61 } };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(record), { status: 200, headers: { "Content-Type": "application/json" } }));
    const out = await fetchReplayGw("2025-26", 7, 588004);
    expect(out.your?.captain).toBe(233);
    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toContain("/replay/2025-26/gw/7");
    expect(calledUrl).toContain("entry_id=588004");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `fpl-decision-hub/`): `npx vitest run src/lib/replayApi.test.ts`
Expected: FAIL — cannot resolve `./replayApi`.

- [ ] **Step 3: Implement the client**

Check how `src/lib/fplAssistantApi.ts` resolves the API base (it reads `VITE_FPL_API_BASE_URL` via a `getEnvString` helper). Reuse the same base.

```ts
// fpl-decision-hub/src/lib/replayApi.ts
export interface ReplayPlayer { element: number; model_xpts: number; actual_points: number; }
export interface ReplaySp2Candidate {
  element: number; differential_ev: number; template_xpts: number;
  global_ownership: number; ownership_basis: "global";
}
export interface ReplayYourSide {
  picks?: number[]; captain?: number | null; vice?: number | null;
  transfers?: { in: number[]; out: number[] }; chip?: string | null;
  points?: number | null; bank?: number | null;
}
export interface ReplayGwRecord {
  season: string; gw: number; setup_gw: boolean;
  players: ReplayPlayer[];
  model_captain: number | null; optimal_captain: number | null;
  suggested_transfer: { sell: number; buy: number; expected_gain: number } | null;
  sp2_candidates: ReplaySp2Candidate[];
  your: ReplayYourSide | null;
}

export function replayEnabled(): boolean {
  return import.meta.env.VITE_REPLAY_MODE === "1";
}

function apiBase(): string {
  return (import.meta.env.VITE_FPL_API_BASE_URL as string | undefined) ?? "";
}

export async function fetchReplayGw(
  season: string, gw: number, entryId: number, signal?: AbortSignal,
): Promise<ReplayGwRecord> {
  const base = apiBase();
  const path = `/replay/${season}/gw/${gw}?entry_id=${entryId}`;
  const url = base ? new URL(path, base).toString() : path;
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`Replay GW ${gw} failed: ${res.status}`);
  return (await res.json()) as ReplayGwRecord;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/replayApi.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/replayApi.ts src/lib/replayApi.test.ts
git commit -m "feat(replay): frontend replay API client + types"
```

---

### Task 7: Frontend `/replay` page + gated route + panels

**Files:**
- Create: `fpl-decision-hub/src/pages/Replay.tsx`
- Modify: `fpl-decision-hub/src/App.tsx`
- Test: `fpl-decision-hub/src/pages/Replay.test.tsx`

**Interfaces:**
- Consumes: `fetchReplayGw`, `replayEnabled`, `ReplayGwRecord`.
- Produces: a `Replay` page component with a GW slider (1–38) and four panel sections; a `/replay` route registered only when `replayEnabled()`.

- [ ] **Step 1: Write the failing test**

```tsx
// fpl-decision-hub/src/pages/Replay.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import Replay from "./Replay";

afterEach(() => vi.restoreAllMocks());

const RECORD = {
  season: "2025-26", gw: 7, setup_gw: false,
  players: [{ element: 351, model_xpts: 6.4, actual_points: 12 }],
  model_captain: 351, optimal_captain: 351,
  suggested_transfer: { sell: 233, buy: 99, expected_gain: 1.2 },
  sp2_candidates: [{ element: 99, differential_ev: 2.1, template_xpts: 4.0, global_ownership: 0.08, ownership_basis: "global" }],
  your: { captain: 233, points: 61 },
};

describe("Replay page", () => {
  it("renders the four panels from a fetched record", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(RECORD), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<Replay />);
    await waitFor(() => expect(screen.getByTestId("panel-players")).toBeInTheDocument());
    expect(screen.getByTestId("panel-captain")).toBeInTheDocument();
    expect(screen.getByTestId("panel-transfer")).toBeInTheDocument();
    expect(screen.getByTestId("panel-sp2")).toBeInTheDocument();
    expect(screen.getByText(/global/i)).toBeInTheDocument();   // SP2 basis label
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/pages/Replay.test.tsx`
Expected: FAIL — cannot resolve `./Replay`.

- [ ] **Step 3: Implement the page (four panels, GW slider)**

```tsx
// fpl-decision-hub/src/pages/Replay.tsx
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
    fetchReplayGw(SEASON, gw, ENTRY_ID, ctrl.signal)
      .then(setRec)
      .catch((e) => setErr(String(e)));
    return () => ctrl.abort();
  }, [gw]);

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center gap-4">
        <h1 className="text-xl font-semibold">Replay — {SEASON}</h1>
        <label className="flex items-center gap-2">
          GW <input type="range" min={1} max={38} value={gw}
            onChange={(e) => setGw(Number(e.target.value))} />
          <span className="tabular-nums w-8">{gw}</span>
        </label>
      </header>

      {err && <p className="text-red-500">{err}</p>}
      {rec?.setup_gw && <p className="text-muted-foreground">GW{gw} is the setup GW — no model projection.</p>}
      {rec && !rec.setup_gw && (
        <div className="grid gap-6 md:grid-cols-2">
          <section data-testid="panel-players">
            <h2 className="font-medium mb-2">Model xPts vs actual</h2>
            <table className="w-full text-sm"><tbody>
              {rec.players.map((p) => (
                <tr key={p.element}>
                  <td>#{p.element}</td>
                  <td className="text-right tabular-nums">{p.model_xpts.toFixed(1)}</td>
                  <td className="text-right tabular-nums font-medium">{p.actual_points}</td>
                </tr>
              ))}
            </tbody></table>
          </section>

          <section data-testid="panel-captain">
            <h2 className="font-medium mb-2">Captain</h2>
            <p>Model: #{rec.model_captain ?? "—"}</p>
            <p>You: #{rec.your?.captain ?? "—"}</p>
            <p>Optimal: #{rec.optimal_captain ?? "—"}</p>
          </section>

          <section data-testid="panel-transfer">
            <h2 className="font-medium mb-2">Suggested transfer</h2>
            {rec.suggested_transfer
              ? <p>Sell #{rec.suggested_transfer.sell} → Buy #{rec.suggested_transfer.buy} (+{rec.suggested_transfer.expected_gain})</p>
              : <p className="text-muted-foreground">No transfer suggested.</p>}
          </section>

          <section data-testid="panel-sp2">
            <h2 className="font-medium mb-2">SP2 differential EV <span className="text-xs text-muted-foreground">(global ownership)</span></h2>
            <table className="w-full text-sm"><tbody>
              {rec.sp2_candidates.map((c) => (
                <tr key={c.element}>
                  <td>#{c.element}</td>
                  <td className="text-right tabular-nums">{c.differential_ev.toFixed(2)}</td>
                  <td className="text-right tabular-nums">{(c.global_ownership * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody></table>
          </section>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/pages/Replay.test.tsx`
Expected: PASS

- [ ] **Step 5: Register the gated route**

In `fpl-decision-hub/src/App.tsx`, find the router (`<Routes>` block). Add a lazy, env-gated route so prod builds drop it:

```tsx
import { lazy, Suspense } from "react";
import { replayEnabled } from "@/lib/replayApi";
const Replay = lazy(() => import("./pages/Replay"));

// inside <Routes>:
{replayEnabled() && (
  <Route path="/replay" element={<Suspense fallback={null}><Replay /></Suspense>} />
)}
```

- [ ] **Step 6: Add the dev env flag**

In `fpl-decision-hub/.env` (dev only — confirm `.env.production` does NOT get these):

```
VITE_REPLAY_MODE=1
VITE_REPLAY_ENTRY_ID=588004
```

- [ ] **Step 7: Commit**

```bash
git add src/pages/Replay.tsx src/pages/Replay.test.tsx src/App.tsx .env
git commit -m "feat(replay): gated /replay page with four comparison panels"
```

---

### Task 8: End-to-end local wire-up

**Files:** none (verification only).

- [ ] **Step 1: Start backend with replay enabled**

Run (repo root, venv active):
```bash
REPLAY_MODE=1 uvicorn api.main:app --reload --port 8001
```

- [ ] **Step 2: Verify endpoints**

Run:
```bash
curl -s "http://localhost:8001/replay/seasons"
curl -s "http://localhost:8001/replay/2025-26/gw/7?entry_id=588004" | python -m json.tool | head -30
```
Expected: seasons lists `2025-26`; GW7 record with `players`, captains, `sp2_candidates`, and a `your` block (captain + points).

- [ ] **Step 3: Verify frontend route**

Run (from `fpl-decision-hub/`): `bun dev` (or `npm run dev`), open `/replay`, drag the GW slider, confirm all four panels populate and change per GW; confirm GW1 shows the setup-GW note.

- [ ] **Step 4: Verify production isolation**

Run:
```bash
# backend: no env -> router absent
python -c "from api.main import app; print(any('/replay' in getattr(r,'path','') for r in app.routes))"   # False
# frontend: prod build has no replay chunk referencing the route
cd fpl-decision-hub && npm run build && ! grep -rq "replay/${SEASON}" dist/ && echo "no replay route in prod build"
```
Expected: backend prints `False`; prod build check passes.

- [ ] **Step 5: Final full-suite check**

Run: `python -m pytest -q` (repo root) and `npx vitest run` (frontend).
Expected: all green.
