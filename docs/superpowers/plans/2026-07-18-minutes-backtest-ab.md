# Minutes A/B Backtest Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A walk-forward harness that A/B-compares the minutes model (`PROJ_APPLY_MINUTES_MODEL` off vs on) on 2025-26 Vaastav data and reports projection MAE, captain hit-rate, captain regret, and top-10 precision.

**Architecture:** Fix the adapter's fake `gw_starts` (use real per-GW `starts`); a pure `src/backtest_metrics.py` for the metrics (unit-tested); a `scripts/backtest_minutes_ab.py` harness that patches BOTH history loaders to the capped history (no future leak), projects off vs on per GW, scores vs actuals, and prints the comparison.

**Tech Stack:** Python 3.10, pandas 1.5.1. Tests via pytest (dev-only). No new runtime deps.

## Global Constraints

- **No production behavior change.** The harness restores both patched loaders and the `PROJ_APPLY_MINUTES_MODEL` flag in a `finally` every iteration; the committed config default (`False`) is never persisted-changed.
- **No future leak.** Patch BOTH `projections.load_latest_player_gw_history` AND `minutes_model.load_minutes_history` to the same capped `history_df` (history is `gw < target_gw` via the adapter).
- **Adapter fix is backward compatible:** real `starts` when present, else the `minutes>=60` proxy.
- Metrics module is PURE (no I/O). Walk-forward range = GW3 → max available (`backtest_data.available_gws()`; currently 29).
- Runtime deps unchanged (pandas 1.5.1). pytest dev-only.

---

### Task 1: Adapter — use real `starts` when present

**Files:**
- Modify: `src/backtest_adapter.py` (`build_history_df`, the `gw_starts` line)
- Create: `tests/test_backtest_adapter_starts.py`

**Interfaces:**
- Produces: `build_history_df(target_gw, season)` now sets `gw_starts` from the real `starts` column when the loaded history has it, else the `minutes>=60` proxy.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backtest_adapter_starts.py`:
```python
import pandas as pd

from src import backtest_adapter, backtest_data


def _patch_common(monkeypatch, history_long):
    monkeypatch.setattr(backtest_data, "player_actuals_through", lambda gw, season="2025-26": history_long)
    monkeypatch.setattr(backtest_data, "load_teams", lambda season="2025-26": pd.DataFrame(
        {"id": [1], "name": ["Team A"], "short_name": ["TMA"]}))
    monkeypatch.setattr(backtest_data, "load_fixtures", lambda season="2025-26": pd.DataFrame(
        {"event": [1], "team_h": [1], "team_a": [1], "team_h_difficulty": [3], "team_a_difficulty": [3]}))


def test_uses_real_starts_when_present(monkeypatch):
    # p1: 80 mins but starts=0 (came on early as sub); p2: 45 mins but starts=1.
    hist = pd.DataFrame({
        "element": [1, 2], "gw": [1, 1], "total_points": [3, 2],
        "minutes": [80, 45], "starts": [0, 1], "team": ["Team A", "Team A"],
    })
    _patch_common(monkeypatch, hist)
    out = backtest_adapter.build_history_df(target_gw=2)
    starts = dict(zip(out["player_id"], out["gw_starts"]))
    assert starts[1] == 0  # real starts overrides the minutes>=60 proxy
    assert starts[2] == 1


def test_falls_back_to_proxy_without_starts(monkeypatch):
    hist = pd.DataFrame({
        "element": [1, 2], "gw": [1, 1], "total_points": [3, 2],
        "minutes": [80, 45], "team": ["Team A", "Team A"],
    })
    _patch_common(monkeypatch, hist)
    out = backtest_adapter.build_history_df(target_gw=2)
    starts = dict(zip(out["player_id"], out["gw_starts"]))
    assert starts[1] == 1  # 80 >= 60
    assert starts[2] == 0  # 45 < 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_backtest_adapter_starts.py -v`
Expected: FAIL on `test_uses_real_starts_when_present` (proxy gives `starts[1]==1`, real is 0).

- [ ] **Step 3: Apply the fix**

In `src/backtest_adapter.py`, find (in `build_history_df`):
```python
    df["gw_minutes"] = pd.to_numeric(df["minutes"], errors="coerce").fillna(0)
    df["gw_starts"] = (df["gw_minutes"] >= 60).astype(int)  # rough proxy
```
Replace with:
```python
    df["gw_minutes"] = pd.to_numeric(df["minutes"], errors="coerce").fillna(0)
    if "starts" in history_long.columns:
        df["gw_starts"] = pd.to_numeric(history_long["starts"], errors="coerce").fillna(0).astype(int).values
    else:
        df["gw_starts"] = (df["gw_minutes"] >= 60).astype(int)  # fallback proxy
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_backtest_adapter_starts.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/backtest_adapter.py tests/test_backtest_adapter_starts.py
git commit -m "feat: backtest adapter uses real per-GW starts when present"
```

---

### Task 2: `src/backtest_metrics.py` — pure metric functions

**Files:**
- Create: `src/backtest_metrics.py`
- Create: `tests/test_backtest_metrics.py`

**Interfaces:**
- Each function takes `frames`: a list of per-GW DataFrames with columns `player_id`, `xpts` (projected this GW), `actual` (actual points), `position`, `minutes` (actual).
- Produces: `projection_mae(frames, top_n=40) -> float`; `mae_by_position(frames, top_n=40) -> dict[str,float]`; `captain_hit_rate(frames, top_k=5) -> float`; `captain_regret(frames) -> float`; `top_n_precision(frames, n=10) -> float`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backtest_metrics.py`:
```python
import pandas as pd

from src import backtest_metrics as m


def _frame(rows):
    # rows: list of (player_id, xpts, actual, position, minutes)
    return pd.DataFrame(rows, columns=["player_id", "xpts", "actual", "position", "minutes"])


def test_projection_mae_over_played_and_top_n():
    # top_n large so universe = all played (minutes>0). Errors: |5-4|=1, |2-6|=4 -> MAE 2.5.
    f = _frame([(1, 5.0, 4.0, "MID", 90), (2, 2.0, 6.0, "FWD", 90), (3, 9.0, 9.0, "DEF", 0)])
    # player 3 didn't play (minutes 0) but is top-1 by xpts -> included by top_n; |9-9|=0.
    # universe = {1,2,3}; errors 1,4,0 -> mean = 5/3.
    assert abs(m.projection_mae([f], top_n=40) - (5.0 / 3.0)) < 1e-9


def test_captain_hit_rate():
    # g1: top-proj p1 (xpts 9, actual 8); actual top-2 = {p2(10), p1(8)} -> p1 in -> hit.
    g1 = _frame([(1, 9.0, 8.0, "MID", 90), (2, 3.0, 10.0, "FWD", 90)])
    # g2: top-proj p1 (xpts 9, actual 2); actual top-1 = {p3(12)} -> p1 out -> miss.
    g2 = _frame([(1, 9.0, 2.0, "MID", 90), (3, 1.0, 12.0, "FWD", 90)])
    assert m.captain_hit_rate([g1], top_k=2) == 1.0
    assert m.captain_hit_rate([g2], top_k=1) == 0.0
    # g1 at top_k=1: actual top-1 is p2(10), top-proj p1 not in -> miss.
    assert m.captain_hit_rate([g1], top_k=1) == 0.0
    # both at top_k=1: g1 miss + g2 miss -> 0/2.
    assert m.captain_hit_rate([g1, g2], top_k=1) == 0.0


def test_captain_regret():
    # GW: top-proj p1 (actual 8); best actual 10 -> regret 2.
    g = _frame([(1, 9.0, 8.0, "MID", 90), (2, 3.0, 10.0, "FWD", 90)])
    assert abs(m.captain_regret([g]) - 2.0) < 1e-9


def test_top_n_precision():
    # top-2 proj = {p1,p2}; top-2 actual = {p2,p3}; overlap {p2} -> 1/2.
    g = _frame([(1, 9.0, 1.0, "MID", 90), (2, 8.0, 9.0, "FWD", 90), (3, 1.0, 10.0, "DEF", 90)])
    assert abs(m.top_n_precision([g], n=2) - 0.5) < 1e-9


def test_mae_by_position():
    f = _frame([(1, 5.0, 4.0, "MID", 90), (2, 2.0, 6.0, "MID", 90), (3, 3.0, 3.0, "DEF", 90)])
    out = m.mae_by_position([f], top_n=40)
    assert abs(out["MID"] - 2.5) < 1e-9  # (|5-4|+|2-6|)/2
    assert abs(out["DEF"] - 0.0) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backtest_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.backtest_metrics'`.

- [ ] **Step 3: Implement the module**

Create `src/backtest_metrics.py`:
```python
"""
Pure metrics for the minutes A/B backtest. Each function takes ``frames``: a list
of per-GW DataFrames with columns: player_id, xpts (projected this GW), actual
(actual points this GW), position, minutes (actual minutes this GW).
"""
from __future__ import annotations

import pandas as pd


def _frame_universe(df, top_n):
    """Rows in the top-``top_n`` by projected xpts OR that actually played."""
    d = df.copy()
    d["xpts"] = pd.to_numeric(d["xpts"], errors="coerce").fillna(0.0)
    d["actual"] = pd.to_numeric(d["actual"], errors="coerce").fillna(0.0)
    mins = pd.to_numeric(d.get("minutes", 0), errors="coerce").fillna(0.0)
    top_idx = set(d.nlargest(top_n, "xpts").index)
    played_idx = set(d.index[mins > 0])
    return d.loc[sorted(top_idx | played_idx)]


def _pooled_universe(frames, top_n):
    parts = [_frame_universe(f, top_n) for f in frames if f is not None and not f.empty]
    if not parts:
        return pd.DataFrame(columns=["player_id", "xpts", "actual", "position", "minutes"])
    return pd.concat(parts, ignore_index=True)


def projection_mae(frames, top_n=40):
    u = _pooled_universe(frames, top_n)
    if u.empty:
        return 0.0
    return float((u["xpts"] - u["actual"]).abs().mean())


def mae_by_position(frames, top_n=40):
    u = _pooled_universe(frames, top_n)
    out = {}
    for pos, g in u.groupby("position"):
        out[str(pos)] = float((g["xpts"] - g["actual"]).abs().mean())
    return out


def captain_hit_rate(frames, top_k=5):
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return 0.0
    hits = 0
    for f in frames:
        d = f.copy()
        d["xpts"] = pd.to_numeric(d["xpts"], errors="coerce").fillna(0.0)
        d["actual"] = pd.to_numeric(d["actual"], errors="coerce").fillna(0.0)
        top_proj_pid = d.loc[d["xpts"].idxmax(), "player_id"]
        actual_topk = set(d.nlargest(top_k, "actual")["player_id"])
        if top_proj_pid in actual_topk:
            hits += 1
    return hits / len(frames)


def captain_regret(frames):
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return 0.0
    regrets = []
    for f in frames:
        d = f.copy()
        d["xpts"] = pd.to_numeric(d["xpts"], errors="coerce").fillna(0.0)
        d["actual"] = pd.to_numeric(d["actual"], errors="coerce").fillna(0.0)
        best = float(d["actual"].max())
        picked = float(d.loc[d["xpts"].idxmax(), "actual"])
        regrets.append(best - picked)
    return float(sum(regrets) / len(regrets))


def top_n_precision(frames, n=10):
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return 0.0
    vals = []
    for f in frames:
        d = f.copy()
        d["xpts"] = pd.to_numeric(d["xpts"], errors="coerce").fillna(0.0)
        d["actual"] = pd.to_numeric(d["actual"], errors="coerce").fillna(0.0)
        tp = set(d.nlargest(n, "xpts")["player_id"])
        ta = set(d.nlargest(n, "actual")["player_id"])
        vals.append(len(tp & ta) / n)
    return float(sum(vals) / len(vals))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backtest_metrics.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/backtest_metrics.py tests/test_backtest_metrics.py
git commit -m "feat: add pure backtest_metrics (MAE, captain hit-rate/regret, top-N precision)"
```

---

### Task 3: Harness `scripts/backtest_minutes_ab.py` + run

**Files:**
- Create: `scripts/backtest_minutes_ab.py`

**Interfaces:**
- Consumes: `backtest_adapter.build_engine_inputs`, `backtest_data.player_actuals_at`/`available_gws`, `projections.project_elements_next_gws`, `minutes_model.load_minutes_history`, `backtest_metrics.*`, `config.PROJ_APPLY_MINUTES_MODEL`.

- [ ] **Step 1: Write the harness**

Create `scripts/backtest_minutes_ab.py`:
```python
"""
Minutes A/B backtest (guide, not a gate).

Walk-forward GW3 -> max available on 2025-26 Vaastav data: project each GW with
PROJ_APPLY_MINUTES_MODEL off vs on, score projected xpts against actual points,
and print MAE / captain hit-rate / captain regret / top-10 precision side by side.

Patches BOTH history loaders to the capped history so the minutes model never
peeks at the future. Restores loaders + the flag every iteration.

    .venv/bin/python -m scripts.backtest_minutes_ab
"""
import pandas as pd

from src import (
    config,
    projections,
    minutes_model,
    backtest_data,
    backtest_metrics as bm,
)
from src.backtest_adapter import build_engine_inputs

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def _project(target_gw, apply_minutes, horizon=3):
    elements, fixtures, teams_short, history_df = build_engine_inputs(target_gw, horizon=horizon)
    orig_recent = projections.load_latest_player_gw_history
    orig_minutes = minutes_model.load_minutes_history
    orig_flag = getattr(config, "PROJ_APPLY_MINUTES_MODEL", False)
    projections.load_latest_player_gw_history = lambda *a, **k: history_df
    minutes_model.load_minutes_history = lambda *a, **k: history_df
    config.PROJ_APPLY_MINUTES_MODEL = apply_minutes
    try:
        proj = projections.project_elements_next_gws(
            elements=elements, fixtures=fixtures, teams_short_map=teams_short,
            gw_start=target_gw, horizon_gws=horizon,
        )
    finally:
        projections.load_latest_player_gw_history = orig_recent
        minutes_model.load_minutes_history = orig_minutes
        config.PROJ_APPLY_MINUTES_MODEL = orig_flag

    col = f"xpts_gw{target_gw}"
    pos = proj["pos"] if "pos" in proj.columns else proj["element_type"].map(POS_NAME)
    return pd.DataFrame({
        "player_id": pd.to_numeric(proj["id"], errors="coerce").astype("Int64"),
        "position": pos.values,
        "xpts": pd.to_numeric(proj.get(col), errors="coerce").fillna(0.0).values,
    })


def _frame_for_gw(target_gw, apply_minutes):
    proj = _project(target_gw, apply_minutes)
    actuals = backtest_data.player_actuals_at(target_gw)
    act = pd.DataFrame({
        "player_id": pd.to_numeric(actuals["element"], errors="coerce").astype("Int64"),
        "actual": pd.to_numeric(actuals["total_points"], errors="coerce").fillna(0.0),
        "minutes": pd.to_numeric(actuals["minutes"], errors="coerce").fillna(0.0),
    })
    return proj.merge(act, on="player_id", how="inner")


def main():
    gws = [g for g in backtest_data.available_gws() if g >= 3]
    if not gws:
        print("No Vaastav GWs >= 3 available.")
        return
    print(f"Minutes A/B backtest — GW{min(gws)}..GW{max(gws)} ({len(gws)} GWs)\n")

    frames_off, frames_on = [], []
    for gw in gws:
        try:
            frames_off.append(_frame_for_gw(gw, False))
            frames_on.append(_frame_for_gw(gw, True))
        except Exception as exc:
            print(f"  ! GW{gw} skipped: {exc}")

    def _row(label, off_val, on_val, better="lower"):
        delta = on_val - off_val
        arrow = "better" if (delta < 0) == (better == "lower") and abs(delta) > 1e-9 else (
            "worse" if abs(delta) > 1e-9 else "flat")
        return f"{label:24} {off_val:8.3f} {on_val:8.3f} {delta:+8.3f}  {arrow}"

    print(f"{'metric':24} {'OFF':>8} {'ON':>8} {'delta':>8}")
    print(_row("projection MAE", bm.projection_mae(frames_off), bm.projection_mae(frames_on), "lower"))
    print(_row("captain hit-rate", bm.captain_hit_rate(frames_off), bm.captain_hit_rate(frames_on), "higher"))
    print(_row("captain regret", bm.captain_regret(frames_off), bm.captain_regret(frames_on), "lower"))
    print(_row("top-10 precision", bm.top_n_precision(frames_off), bm.top_n_precision(frames_on), "higher"))

    print("\nMAE by position (OFF -> ON):")
    off_pos, on_pos = bm.mae_by_position(frames_off), bm.mae_by_position(frames_on)
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        if pos in off_pos or pos in on_pos:
            print(f"  {pos:4} {off_pos.get(pos, float('nan')):7.3f} -> {on_pos.get(pos, float('nan')):7.3f}")

    print("\nGuide only — n_gws is small; read directionally. Ownership-EV (SP2) is NOT "
          "backtestable (no historical ownership).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the harness on real data**

Run: `.venv/bin/python -m scripts.backtest_minutes_ab`
Expected: a table (OFF/ON/delta for MAE, captain hit-rate, captain regret, top-10 precision) + MAE-by-position, over GW3..29. No exceptions. Record the numbers in the commit message body.

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest_minutes_ab.py
git commit -m "feat: minutes A/B backtest harness (patches both history loaders, no future leak)"
```

---

## Self-Review

**Spec coverage:**
- §3.A adapter real-starts fix → Task 1. ✓
- §3.B metrics module → Task 2. ✓
- §3.C harness (patches BOTH loaders, restores in finally) → Task 3 Step 1. ✓
- §3.D output table + verdict → Task 3 Step 1 (`_row`/print). ✓
- §4 testing → Tasks 1-2 tests. ✓
- §5/§6 ship-fast + ownership-not-backtestable note → Task 3 harness docstring + final print. ✓

**Placeholder scan:** No TBD/TODO. All code shown in full. ✓

**Type consistency:** `frames`-list signatures for all `backtest_metrics` fns consistent between Task 2 (define) and Task 3 (call). `build_engine_inputs(target_gw, horizon=...)` matches the adapter's real signature `(target_gw, season="2025-26", horizon=3)`. `player_actuals_at`/`available_gws` match `backtest_data`. `load_latest_player_gw_history`/`load_minutes_history` are the real loader names (verified). `test_captain_hit_rate` asserts are internally consistent (all misses at top_k=1 → 0.0; the single hit at top_k=2 → 1.0).
```
