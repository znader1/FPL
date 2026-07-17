# Minutes / Rotation-Risk Model Activation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a surgical, tunable rotation-risk multiplier to the baseline projection so fit-but-rotated players are correctly discounted, behind a default-off flag that leaves current behavior byte-identical.

**Architecture:** Reuse the existing `minutes_model.minutes_projection()`. Expose its rotation vs. availability components, add a pure multiplier formula, add a per-GW mapping helper that fades only the injury component on future GWs, then wire it into the `projections.py` GW loop behind `PROJ_APPLY_MINUTES_MODEL`. When the flag is off, the legacy `play_prob` path runs unchanged.

**Tech Stack:** Python 3.10, pandas 1.5.1, numpy 1.23.4. Tests via pytest (dev-only). No new runtime dependencies.

## Global Constraints

- **Runtime deps unchanged.** pandas `1.5.1`, numpy `1.23.4`, Python `3.10`. pytest is dev-only (not added to `requirements.txt`).
- **Reversibility is a hard requirement.** With `PROJ_APPLY_MINUTES_MODEL = False` (the committed default), `project_elements_next_gws` output must be identical to pre-change — no new columns, no changed values.
- **Never break projections.** All new logic in `projections.py` is wrapped in `try/except` that falls back to the legacy `play_prob` path (mirror the existing blend hook at `projections.py:521-530`).
- **Relative multiplier, capped at 1.0.** Nailed starters stay ≈ 1.0; only below-nailed players are discounted. No global deflation.
- **Follow existing config pattern:** read tunables via `getattr(config, "NAME", default)`; reuse the `clamp(value, low, high)` helper at `projections.py:27`.
- **Config defaults:** `MINUTES_NAILED_START_REF = 0.85`, `MINUTES_CAMEO_POINT_VALUE = 0.30`, reuse `PROJ_INJURY_FUTURE_GW_FADE = 0.5`, `PROJ_APPLY_MINUTES_MODEL = False`.

---

### Task 1: Bootstrap pytest + expose rotation & availability from `minutes_projection`

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_minutes_model.py`
- Modify: `src/minutes_model.py` (`minutes_projection` return frame; empty-return columns)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `minutes_model.minutes_projection(elements_df, history_df, gw)` now returns, in addition to `prob_start, prob_appear, prob_60, exp_minutes`, two new columns:
  - `rotation_prob_start: float` — history-based start probability **before** availability is applied (i.e. `blended_start`).
  - `availability: float` — the `_availability_series` value in `[0,1]`.

- [ ] **Step 1: Install pytest into the project venv**

Run:
```bash
.venv/bin/python -m pip install pytest
```
Expected: `Successfully installed pytest-...` (or "already satisfied").

- [ ] **Step 2: Create the test package marker**

Create `tests/__init__.py` (empty file):
```python
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_minutes_model.py`:
```python
import pandas as pd

from src import minutes_model


def _elements(rows):
    return pd.DataFrame(rows)


def test_minutes_projection_exposes_rotation_and_availability():
    # p1: fit nailed starter. p2: fit but historically rotated. p3: injured (25%).
    elements = _elements([
        {"id": 1, "status": "a", "chance_of_playing_next_round": 100},
        {"id": 2, "status": "a", "chance_of_playing_next_round": 100},
        {"id": 3, "status": "d", "chance_of_playing_next_round": 25},
    ])
    # History: p1 always starts, p2 starts half the time, p3 always starts when fit.
    history = pd.DataFrame([
        {"player_id": 1, "gw": 1, "gw_minutes": 90, "gw_starts": 1},
        {"player_id": 1, "gw": 2, "gw_minutes": 90, "gw_starts": 1},
        {"player_id": 2, "gw": 1, "gw_minutes": 90, "gw_starts": 1},
        {"player_id": 2, "gw": 2, "gw_minutes": 0, "gw_starts": 0},
        {"player_id": 3, "gw": 1, "gw_minutes": 90, "gw_starts": 1},
        {"player_id": 3, "gw": 2, "gw_minutes": 90, "gw_starts": 1},
    ])

    out = minutes_model.minutes_projection(elements, history, gw=3)

    assert "rotation_prob_start" in out.columns
    assert "availability" in out.columns
    # Injured player's rotation (history) is high but availability is capped low.
    assert out.loc[3, "rotation_prob_start"] > 0.6
    assert out.loc[3, "availability"] <= 0.25 + 1e-9
    # prob_start folds availability in, so it is <= rotation for the injured player.
    assert out.loc[3, "prob_start"] <= out.loc[3, "rotation_prob_start"] + 1e-9
    # Fit nailed starter: rotation high, availability 1.0.
    assert out.loc[1, "rotation_prob_start"] > out.loc[2, "rotation_prob_start"]
    assert out.loc[1, "availability"] == 1.0
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_minutes_model.py::test_minutes_projection_exposes_rotation_and_availability -v`
Expected: FAIL — `assert "rotation_prob_start" in out.columns` (KeyError / AssertionError), because the columns don't exist yet.

- [ ] **Step 5: Add the columns to the empty-return guard**

In `src/minutes_model.py`, inside `minutes_projection`, find the early return when `id` is missing (currently `~L195`):
```python
    if "id" not in df.columns:
        return pd.DataFrame(columns=["prob_start", "prob_appear", "prob_60", "exp_minutes"])
```
Replace with:
```python
    if "id" not in df.columns:
        return pd.DataFrame(columns=[
            "prob_start", "prob_appear", "prob_60", "exp_minutes",
            "rotation_prob_start", "availability",
        ])
```

- [ ] **Step 6: Add the columns to the output frame**

In `src/minutes_model.py`, find the final output construction (currently `~L238-244`):
```python
    out = pd.DataFrame({
        "prob_start": prob_start.values,
        "prob_appear": prob_appear.values,
        "prob_60": prob_60.values,
        "exp_minutes": exp_minutes.values,
    }, index=df["id"].values)
```
Replace with:
```python
    out = pd.DataFrame({
        "prob_start": prob_start.values,
        "prob_appear": prob_appear.values,
        "prob_60": prob_60.values,
        "exp_minutes": exp_minutes.values,
        "rotation_prob_start": blended_start.clip(0.0, 1.0).values,
        "availability": avail.values,
    }, index=df["id"].values)
```
(`blended_start` and `avail` are already computed above in the same function.)

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_minutes_model.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/__init__.py tests/test_minutes_model.py src/minutes_model.py
git commit -m "feat: expose rotation_prob_start + availability from minutes_projection"
```

---

### Task 2: `rotation_minutes_multiplier` formula + config tunables

**Files:**
- Modify: `src/minutes_model.py` (add function)
- Modify: `src/config.py` (add tunables)
- Modify: `tests/test_minutes_model.py` (add tests)

**Interfaces:**
- Consumes: `config.MINUTES_NAILED_START_REF`, `config.MINUTES_CAMEO_POINT_VALUE`.
- Produces: `minutes_model.rotation_minutes_multiplier(prob_start_eff, prob_appear=None, nailed_ref=None, cameo_value=None) -> pd.Series`. Accepts scalars, lists, or Series (index preserved). Returns values in `[0,1]`; where `prob_start_eff` is NaN it returns `1.0` (no discount).

- [ ] **Step 1: Add config tunables**

In `src/config.py`, at the end of the file (after `PROJ_MODEL_BLEND_WEIGHT = 0.0`), append:
```python

# --- minutes/rotation-risk multiplier (surgical, applied in projections.py) ---
# Master flag: when True, project_elements_next_gws replaces the crude
# chance_of_playing discount with a rotation-risk multiplier. Default off so
# committed behavior is unchanged; flip True after scripts/spotcheck_minutes.py.
PROJ_APPLY_MINUTES_MODEL = False
MINUTES_NAILED_START_REF = 0.85   # prob_start at/above which a player is "nailed" (mult caps at 1.0)
MINUTES_CAMEO_POINT_VALUE = 0.30  # value of a likely cameo relative to a start
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_minutes_model.py`:
```python
def test_rotation_minutes_multiplier_values():
    m = minutes_model.rotation_minutes_multiplier

    # Nailed starter -> capped at 1.0.
    assert abs(float(m(0.95, 0.99).iloc[0]) - 1.0) < 1e-9
    # Rotation risk (0.55 start / 0.80 appear): 0.55/0.85 + 0.30*0.25 = 0.7221.
    assert abs(float(m(0.55, 0.80).iloc[0]) - 0.72205882) < 1e-6
    # Injured (0.10 start / 0.20 appear): 0.10/0.85 + 0.30*0.10 = 0.14765.
    assert abs(float(m(0.10, 0.20).iloc[0]) - 0.14764706) < 1e-6
    # Missing data -> no discount.
    assert float(m(float("nan"), float("nan")).iloc[0]) == 1.0


def test_rotation_minutes_multiplier_is_monotonic_and_clamped():
    m = minutes_model.rotation_minutes_multiplier
    vals = [float(m(x).iloc[0]) for x in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]]
    assert vals == sorted(vals)          # non-decreasing in prob_start
    assert all(0.0 <= v <= 1.0 for v in vals)
    assert vals[0] == 0.0 and vals[-1] == 1.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_minutes_model.py::test_rotation_minutes_multiplier_values -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'rotation_minutes_multiplier'`.

- [ ] **Step 4: Implement the function**

In `src/minutes_model.py`, add after `minutes_projection` (end of file):
```python
def rotation_minutes_multiplier(prob_start_eff, prob_appear=None,
                                nailed_ref=None, cameo_value=None):
    """
    Relative rotation-risk multiplier in [0, 1].

    Nailed starters (prob_start_eff >= nailed_ref) map to 1.0; below that they are
    linearly discounted, plus a small cameo bonus for likely bench appearances.
    NaN prob_start_eff -> 1.0 (no discount / missing data).

    Accepts scalars, lists, or Series; returns a Series (index preserved when the
    input is a Series).
    """
    nailed_ref = float(nailed_ref if nailed_ref is not None
                       else getattr(config, "MINUTES_NAILED_START_REF", 0.85))
    cameo_value = float(cameo_value if cameo_value is not None
                        else getattr(config, "MINUTES_CAMEO_POINT_VALUE", 0.30))
    nailed_ref = max(1e-6, nailed_ref)

    ps = pd.to_numeric(pd.Series(prob_start_eff), errors="coerce")
    if prob_appear is None:
        pa = ps.copy()
    else:
        pa = pd.to_numeric(pd.Series(prob_appear), errors="coerce")
        pa = pa.where(pa.notna(), ps)

    rot = (ps / nailed_ref).clip(0.0, 1.0)
    cameo = (pa - ps).clip(lower=0.0) * cameo_value
    mult = (rot + cameo).clip(0.0, 1.0)
    return mult.where(ps.notna(), 1.0)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_minutes_model.py -v`
Expected: PASS (all four tests).

- [ ] **Step 6: Commit**

```bash
git add src/minutes_model.py src/config.py tests/test_minutes_model.py
git commit -m "feat: add rotation_minutes_multiplier formula + config tunables"
```

---

### Task 3: `compute_gw_minutes_multiplier` — per-GW mapping with future-GW injury fade

**Files:**
- Modify: `src/minutes_model.py` (add function)
- Modify: `tests/test_minutes_model.py` (add tests)

**Interfaces:**
- Consumes: `rotation_minutes_multiplier` (Task 2); `config.PROJ_INJURY_FUTURE_GW_FADE`.
- Produces: `minutes_model.compute_gw_minutes_multiplier(mins_df, ids, gw_offset, injury_future_fade=None) -> pd.Series`. `mins_df` is a `minutes_projection` frame (indexed by player id). `ids` is an iterable of player ids. Returns a Series (RangeIndex, positionally aligned to `ids`) of multipliers in `[0,1]`; ids absent from `mins_df` → `1.0`. `gw_offset=0` = immediate GW (full availability); `gw_offset>=1` fades only the availability/injury component while keeping rotation at full strength.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_minutes_model.py`:
```python
def test_compute_gw_minutes_multiplier_fades_injury_not_rotation():
    # id 10: fit rotation risk (avail 1.0). id 20: injured (avail 0.25, fit history).
    mins_df = pd.DataFrame(
        {
            "prob_start": [0.55, 0.225],
            "prob_appear": [0.80, 0.30],
            "prob_60": [0.47, 0.19],
            "exp_minutes": [55.0, 20.0],
            "rotation_prob_start": [0.55, 0.90],
            "availability": [1.0, 0.25],
        },
        index=[10, 20],
    )

    now = minutes_model.compute_gw_minutes_multiplier(mins_df, [10, 20], gw_offset=0)
    later = minutes_model.compute_gw_minutes_multiplier(mins_df, [10, 20], gw_offset=1)

    # Rotation risk: availability is 1.0, so future fade changes nothing.
    assert abs(float(now.iloc[0]) - float(later.iloc[0])) < 1e-9
    # Injured player: future GW is discounted LESS (injury assumed to resolve).
    assert float(later.iloc[1]) > float(now.iloc[1])
    # Missing id -> no discount.
    missing = minutes_model.compute_gw_minutes_multiplier(mins_df, [999], gw_offset=0)
    assert float(missing.iloc[0]) == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_minutes_model.py::test_compute_gw_minutes_multiplier_fades_injury_not_rotation -v`
Expected: FAIL — `AttributeError: ... has no attribute 'compute_gw_minutes_multiplier'`.

- [ ] **Step 3: Implement the function**

In `src/minutes_model.py`, add after `rotation_minutes_multiplier`:
```python
def compute_gw_minutes_multiplier(mins_df, ids, gw_offset, injury_future_fade=None):
    """
    Map a minutes_projection frame onto `ids` and return the rotation-risk
    multiplier positionally aligned to `ids` (RangeIndex).

    gw_offset 0 = immediate GW (full availability). gw_offset >= 1 fades only the
    injury/availability component (injuries resolve) while the history-based
    rotation discount stays at full strength.
    """
    fade = float(injury_future_fade if injury_future_fade is not None
                 else getattr(config, "PROJ_INJURY_FUTURE_GW_FADE", 0.5))
    ids = pd.Series(list(ids)).reset_index(drop=True)
    if mins_df is None or mins_df.empty:
        return pd.Series([1.0] * len(ids))

    rot = ids.map(mins_df["rotation_prob_start"]).astype("float64")
    avail = ids.map(mins_df["availability"]).astype("float64")
    appear = ids.map(mins_df["prob_appear"]).astype("float64")

    if int(gw_offset) <= 0:
        avail_eff = avail
    else:
        avail_eff = 1.0 - (1.0 - avail) * fade

    prob_start_eff = rot * avail_eff
    mult = rotation_minutes_multiplier(prob_start_eff, appear)
    return mult.where(mult.notna(), 1.0).reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_minutes_model.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/minutes_model.py tests/test_minutes_model.py
git commit -m "feat: add compute_gw_minutes_multiplier with future-GW injury fade"
```

---

### Task 4: Wire the multiplier into `projections.py` behind the flag

**Files:**
- Modify: `src/projections.py` (`project_elements_next_gws`: load history, per-GW multiplier, apply, expose columns, whitelist)
- Create: `tests/test_projections_minutes.py`

**Interfaces:**
- Consumes: `minutes_model.load_minutes_history`, `minutes_model.minutes_projection`, `minutes_model.compute_gw_minutes_multiplier` (Tasks 1-3); `config.PROJ_APPLY_MINUTES_MODEL`.
- Produces: when the flag is on, `project_elements_next_gws` output gains `prob_start` (immediate GW) and `minutes_mult_gw{gw}` columns; per-GW `xpts_gw{gw}` is scaled by the multiplier instead of `play_prob`. When off, output is unchanged.

- [ ] **Step 1: Write the failing test (real-data integration, skips if offline)**

Create `tests/test_projections_minutes.py`:
```python
import importlib

import pytest

from src import config, projections


def _load_real_inputs():
    """Assemble (elements_df, fixtures, teams_short, gw) from the live FPL API.
    Returns None if anything is unavailable (offline / rate-limited)."""
    try:
        from src import fpl_client, transforms
        bootstrap = fpl_client.get_bootstrap()
        fixtures = transforms.fixtures_df(fpl_client.get_fixtures())
        elements_df, teams_df, _ = transforms.tables_from_bootstrap(bootstrap)
        teams_short = teams_df.set_index("id")["short_name"].to_dict()
        events = bootstrap.get("events", []) or []
        gw = next((e["id"] for e in events if e.get("is_next")), None)
        if gw is None:
            gw = next((e["id"] for e in events if not e.get("finished")), 1)
        return elements_df, fixtures, teams_short, int(gw)
    except Exception:
        return None


def test_flag_off_adds_no_columns_flag_on_discounts(monkeypatch):
    data = _load_real_inputs()
    if data is None:
        pytest.skip("no live FPL data available")
    elements_df, fixtures, teams_short, gw = data

    monkeypatch.setattr(config, "PROJ_APPLY_MINUTES_MODEL", False, raising=False)
    off = projections.project_elements_next_gws(
        elements_df, fixtures, teams_short, gw_start=gw, horizon_gws=3
    )
    assert not any(c.startswith("minutes_mult_gw") for c in off.columns)
    assert "prob_start" not in off.columns

    monkeypatch.setattr(config, "PROJ_APPLY_MINUTES_MODEL", True, raising=False)
    on = projections.project_elements_next_gws(
        elements_df, fixtures, teams_short, gw_start=gw, horizon_gws=3
    )
    assert any(c.startswith("minutes_mult_gw") for c in on.columns)
    assert "prob_start" in on.columns
    # Relative discount only lowers totals — never raises them.
    assert on["xpts_horizon"].sum() <= off["xpts_horizon"].sum() + 1e-6
    # At least one player is genuinely discounted.
    mult_cols = [c for c in on.columns if c.startswith("minutes_mult_gw")]
    assert (on[mult_cols].min().min()) < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_projections_minutes.py -v`
Expected: FAIL on `assert any(c.startswith("minutes_mult_gw") ...)` when data is available (flag-on adds nothing yet), or SKIP if offline. If it skips, temporarily confirm the wiring with the spot-check in Task 5 instead.

- [ ] **Step 3: Load minutes history once, before the GW loop**

In `src/projections.py`, find the `play_prob` block (currently `~L447-451`):
```python
    if "chance_of_playing_next_round" in df.columns:
        chance_next = pd.to_numeric(df["chance_of_playing_next_round"], errors="coerce")
        play_prob = (chance_next / 100.0).fillna(1.0).clip(lower=0.0, upper=1.0)
    else:
        play_prob = pd.Series(1.0, index=df.index)
```
Immediately **after** it, insert:
```python
    apply_minutes = bool(getattr(config, "PROJ_APPLY_MINUTES_MODEL", False))
    minutes_hist = None
    if apply_minutes:
        try:
            from . import minutes_model as _minutes
            minutes_hist = _minutes.load_minutes_history()
        except Exception:
            apply_minutes = False
```

- [ ] **Step 4: Compute the per-GW multiplier inside the loop**

In `src/projections.py`, inside the `for i, gw in enumerate(gws):` loop, find the end of the team-context multipliers block (the `team_form_mult = ann["team"].apply(...)` assignment, currently `~L474-478`). Immediately **after** that assignment and **before** `dgw_discount = float(...)` (`~L480`), insert:
```python
        minutes_mult = None
        if apply_minutes:
            try:
                mins_gw = _minutes.minutes_projection(df, minutes_hist, int(gw))
                mult_vals = _minutes.compute_gw_minutes_multiplier(
                    mins_gw, df["id"], i
                ).values
                minutes_mult = pd.Series(mult_vals, index=df.index)
                df[f"minutes_mult_gw{gw}"] = minutes_mult.values
                if i == 0:
                    df["prob_start"] = df["id"].map(mins_gw["prob_start"]).astype("float64").values
            except Exception:
                minutes_mult = None
```

- [ ] **Step 5: Apply the multiplier in the GW1 branch**

In `src/projections.py`, in the `if i == 0:` branch, find (currently `~L495`):
```python
            xpts = xpts * play_prob
```
Replace with:
```python
            if minutes_mult is not None:
                xpts = xpts * minutes_mult
            else:
                xpts = xpts * play_prob
```

- [ ] **Step 6: Apply the multiplier in the future-GW branch**

In `src/projections.py`, in the `else:` branch, find (currently `~L499-503`):
```python
            if i <= 2:
                # Partial injury discount for next 2 GWs (availability often resolves).
                injury_fade = float(getattr(config, "PROJ_INJURY_FUTURE_GW_FADE", 0.5))
                future_play_prob = 1.0 - (1.0 - play_prob) * injury_fade
                xpts = xpts * future_play_prob
```
Replace with:
```python
            if minutes_mult is not None:
                xpts = xpts * minutes_mult
            elif i <= 2:
                # Partial injury discount for next 2 GWs (availability often resolves).
                injury_fade = float(getattr(config, "PROJ_INJURY_FUTURE_GW_FADE", 0.5))
                future_play_prob = 1.0 - (1.0 - play_prob) * injury_fade
                xpts = xpts * future_play_prob
```

- [ ] **Step 7: Add the new columns to the output whitelist**

In `src/projections.py`, find `keep_base` and add `"prob_start"` right after `"chance_of_playing_next_round"` (currently `~L542`):
```python
        "status",
        "chance_of_playing_next_round",
        "prob_start",
        "form",
```
Then find the per-GW `keep.extend([...])` list (currently `~L570-581`) and add the multiplier column after `f"xpts_baseline_gw{gw}"`:
```python
                f"xpts_gw{gw}",
                f"xpts_baseline_gw{gw}",
                f"minutes_mult_gw{gw}",
                f"xpts_model_gw{gw}",
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_projections_minutes.py -v`
Expected: PASS (or SKIP if offline — in which case proceed to Task 5 and eyeball the spot-check output).

- [ ] **Step 9: Run the full test suite (reversibility guard)**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS. Confirms Tasks 1-3 still green and nothing else broke.

- [ ] **Step 10: Commit**

```bash
git add src/projections.py tests/test_projections_minutes.py
git commit -m "feat: wire rotation-risk multiplier into projections behind PROJ_APPLY_MINUTES_MODEL"
```

---

### Task 5: Spot-check script + flip the flag on

**Files:**
- Create: `scripts/spotcheck_minutes.py`

**Interfaces:**
- Consumes: `projections.project_elements_next_gws`, `config.PROJ_APPLY_MINUTES_MODEL`, live FPL data via `fpl_client`/`transforms`.
- Produces: a console report of the biggest projection movers (flag off → on) and pass/fail assertions on known cases. No importable API.

- [ ] **Step 1: Write the spot-check script**

Create `scripts/spotcheck_minutes.py`:
```python
"""
Ship-fast spot-check for the minutes/rotation multiplier.

Runs the current-GW projection with PROJ_APPLY_MINUTES_MODEL off vs on, prints
the biggest movers, and sanity-checks direction. Eyeball the movers, then flip
config.PROJ_APPLY_MINUTES_MODEL = True.

Usage:
    .venv/bin/python -m scripts.spotcheck_minutes
"""
import pandas as pd

from src import config, fpl_client, transforms, projections

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)


def _inputs():
    bootstrap = fpl_client.get_bootstrap()
    fixtures = transforms.fixtures_df(fpl_client.get_fixtures())
    elements_df, teams_df, _ = transforms.tables_from_bootstrap(bootstrap)
    teams_short = teams_df.set_index("id")["short_name"].to_dict()
    events = bootstrap.get("events", []) or []
    gw = next((e["id"] for e in events if e.get("is_next")), None)
    if gw is None:
        gw = next((e["id"] for e in events if not e.get("finished")), 1)
    return elements_df, fixtures, teams_short, int(gw)


def _project(elements_df, fixtures, teams_short, gw, apply_minutes):
    config.PROJ_APPLY_MINUTES_MODEL = apply_minutes
    return projections.project_elements_next_gws(
        elements_df, fixtures, teams_short, gw_start=gw, horizon_gws=3
    )


def main():
    elements_df, fixtures, teams_short, gw = _inputs()
    print(f"Projecting GW{gw} (horizon 3)...\n")

    off = _project(elements_df, fixtures, teams_short, gw, False)[
        ["id", "web_name", "team_short", "xpts_horizon"]
    ].rename(columns={"xpts_horizon": "xpts_off"})
    on = _project(elements_df, fixtures, teams_short, gw, True)[
        ["id", "web_name", "xpts_horizon", "prob_start", "minutes_mult_gw" + str(gw)]
    ].rename(columns={"xpts_horizon": "xpts_on",
                      "minutes_mult_gw" + str(gw): "mult_gw1"})

    merged = off.merge(on, on="id", how="inner")
    merged["delta"] = merged["xpts_on"] - merged["xpts_off"]
    merged["pct"] = (merged["delta"] / merged["xpts_off"].replace(0, pd.NA)) * 100.0

    print("=== 20 biggest DOWN movers (rotation/injury risk caught) ===")
    print(merged.sort_values("delta").head(20).to_string(index=False))

    # Sanity: relative multiplier never raises a projection.
    max_up = merged["delta"].max()
    print(f"\nMax upward move (should be ~0): {max_up:.4f}")
    assert max_up <= 1e-6, "Relative multiplier must not raise projections."
    # Sanity: someone is discounted.
    assert merged["delta"].min() < -1e-6, "Expected at least one discounted player."
    print("Spot-check assertions passed. Eyeball the movers above, then set "
          "config.PROJ_APPLY_MINUTES_MODEL = True in src/config.py.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the spot-check**

Run: `.venv/bin/python -m scripts.spotcheck_minutes`
Expected: a table of the 20 biggest down-movers, `Max upward move (should be ~0): 0.0000`, and `Spot-check assertions passed.` Manually confirm: nailed premiums (Haaland/Salah tier) are near the bottom of the movers list (barely moved), and known squad-rotation / flagged players are the big movers.

- [ ] **Step 3: Flip the flag on (human gate)**

Only after the movers list looks right, in `src/config.py` change:
```python
PROJ_APPLY_MINUTES_MODEL = False
```
to:
```python
PROJ_APPLY_MINUTES_MODEL = True
```

- [ ] **Step 4: Re-run the full suite with the flag on**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS. (The reversibility test uses `monkeypatch` to force the flag both ways, so it is independent of the committed default.)

- [ ] **Step 5: Commit**

```bash
git add scripts/spotcheck_minutes.py src/config.py
git commit -m "feat: add minutes spot-check script and enable PROJ_APPLY_MINUTES_MODEL"
```

---

## Self-Review

**Spec coverage:**
- §2 minutes model orphaned / expose components → Task 1. ✓
- §3 relative multiplier formula → Task 2. ✓
- §4 wiring, future-GW injury fade, flag, reversibility → Tasks 3 (fade) + 4 (wiring/flag). ✓
- §6 error handling / try-except fallback → Task 4 Steps 3-4. ✓
- §7 spot-check validation → Task 5. ✓
- §8 output whitelist (`prob_start`, `minutes_mult`) → Task 4 Step 7. Frontend badge is explicitly deferred (stretch) — no task, by design. ✓
- §9 tests (formula, fade, flag-off parity, missing-history fallback) → Tasks 1-4. Missing-history fallback is covered by `compute_gw_minutes_multiplier`'s empty-frame branch (Task 3 test `[999]` missing id) and the Task 4 try/except. ✓
- §10 config additions → Task 2 Step 1. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to". All code shown in full. ✓

**Type consistency:** `rotation_prob_start`, `availability`, `prob_start`, `prob_appear` column names consistent across Tasks 1→3→4. `rotation_minutes_multiplier(prob_start_eff, prob_appear=...)` signature consistent between Task 2 definition and Task 3 call. `compute_gw_minutes_multiplier(mins_df, ids, gw_offset, ...)` consistent between Task 3 definition and Task 4 call. `minutes_mult_gw{gw}` / `prob_start` output columns consistent between Task 4 (produce) and Task 5 (consume). ✓
```
