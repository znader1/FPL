# Chip Strategy Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chip planner learns three strategy signals (international breaks, tough-fixture free-hit weeks, fixture swings), gets a position-aware dream-squad clamp + TC haul probability, and the chip UI finally ships to production.

**Architecture:** All engine changes are additive kwargs threaded from `api/chips.py` into `src/chip_advisor.py` — every new input defaults to `None` and preserves today's behavior when absent. New pure helpers: `src/breaks.py` (break detection) and `compute_fixture_swings` in `src/fixture_difficulty.py`. Frontend merges the existing `feature/chip-planner-frontend` branch and adds one badge.

**Tech Stack:** Python/FastAPI/pandas backend (repo `FPL-Assistant/FPL`, branch `feature/xpts-components`), React/TypeScript/Vite frontend (repo `FPL-Assistant-Front/fpl-decision-hub`).

**Spec:** `docs/superpowers/specs/2026-09-08-chip-strategy-upgrades-design.md`

## Global Constraints

- All tunables go in `src/config.py`; logic files read them via `getattr(config, "NAME", default)` — never hardcode numbers in logic files.
- Every new `build_chip_plan` / scorer input is optional with default `None`; missing input ⇒ output identical to current behavior.
- `/chips/plan` payload changes are additive only: new optional keys `wait_for_team_news` (nudge) and `haul_prob` (TC recs). No renames/removals.
- Backend tests: `python -m pytest tests/test_chip_advisor.py tests/test_chips_route.py -q` must pass after every task; full suite `python -m pytest -q` before deploy.
- Backend work on branch `feature/xpts-components`. Frontend work on a new branch `release/chip-strategy` cut from `main`.
- Frontend deploys to Vercel team **ziad-naders-projects** only (never Augura).

---

### Task 1: Break detection module (`src/breaks.py`)

**Files:**
- Create: `src/breaks.py`
- Modify: `src/config.py` (add `BREAK_GAP_DAYS`, `CHIP_PLAN_BREAK_CONFIDENCE_MULT`)
- Test: `tests/test_breaks.py` (create)

**Interfaces:**
- Consumes: FPL bootstrap `events` list (dicts with `id`, `deadline_time` ISO strings).
- Produces: `international_break_gws(events, gap_days=None) -> dict[int, dict]` mapping event_id → `{"gap_days": float, "prev_event": int}` for every GW whose deadline is more than `gap_days` after the previous GW's deadline. Task 4 consumes this map.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_breaks.py
from src.breaks import international_break_gws


def _events(deadlines):
    return [{"id": i + 1, "deadline_time": d} for i, d in enumerate(deadlines)]


def test_normal_weekly_cadence_no_breaks():
    ev = _events([
        "2026-08-15T17:30:00Z", "2026-08-22T17:30:00Z", "2026-08-29T17:30:00Z",
    ])
    assert international_break_gws(ev) == {}


def test_fourteen_day_gap_flags_post_break_gw():
    ev = _events([
        "2026-08-29T17:30:00Z", "2026-09-12T17:30:00Z", "2026-09-19T17:30:00Z",
    ])
    out = international_break_gws(ev)
    assert set(out) == {2}
    assert out[2]["prev_event"] == 1
    assert out[2]["gap_days"] == 14.0


def test_gap_days_parameter_overrides_config():
    ev = _events(["2026-08-29T17:30:00Z", "2026-09-06T17:30:00Z"])  # 8-day gap
    assert set(international_break_gws(ev, gap_days=7.5)) == {2}
    assert international_break_gws(ev, gap_days=10.0) == {}


def test_malformed_deadlines_yield_empty_map():
    ev = [{"id": 1, "deadline_time": None}, {"id": 2, "deadline_time": "not-a-date"},
          {"id": 3}]
    assert international_break_gws(ev) == {}


def test_events_sorted_by_id_not_input_order():
    ev = [
        {"id": 2, "deadline_time": "2026-09-12T17:30:00Z"},
        {"id": 1, "deadline_time": "2026-08-29T17:30:00Z"},
    ]
    assert set(international_break_gws(ev)) == {2}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_breaks.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.breaks'`

- [ ] **Step 3: Add config constants**

In `src/config.py`, inside the `# Chip plan tuning` block (after `CHIP_PLAN_BLANK_TEAM_THRESHOLD`):

```python
BREAK_GAP_DAYS = 10.0           # deadline-to-deadline gap marking a post-international-break GW
CHIP_PLAN_BREAK_CONFIDENCE_MULT = 0.85  # confidence haircut on recs targeting a post-break GW
```

- [ ] **Step 4: Implement `src/breaks.py`**

```python
"""International-break detection from the FPL events calendar.

No hardcoded dates: a GW whose deadline sits unusually long after the previous
GW's deadline (normal cadence ~7 days; international windows produce ~14) is
flagged as the first GW after a break. Downstream, chip recommendations for
such GWs carry an uncertainty haircut and a "wait for team news" nudge flag.
"""
from __future__ import annotations
import pandas as pd
from src import config


def international_break_gws(events: list[dict], gap_days: float | None = None) -> dict[int, dict]:
    """Map event_id -> {"gap_days", "prev_event"} for post-break GWs.

    Malformed rows are skipped; any failure mode degrades to an empty map,
    which downstream treats as "no breaks known".
    """
    gap = float(gap_days if gap_days is not None else getattr(config, "BREAK_GAP_DAYS", 10.0))
    parsed = []
    for e in events or []:
        try:
            eid = int(e.get("id"))
            ts = pd.Timestamp(e.get("deadline_time"))
        except (TypeError, ValueError):
            continue
        if pd.isna(ts):
            continue
        parsed.append((eid, ts))
    parsed.sort(key=lambda x: x[0])

    out: dict[int, dict] = {}
    for (prev_id, prev_ts), (eid, ts) in zip(parsed, parsed[1:]):
        delta_days = (ts - prev_ts).total_seconds() / 86400.0
        if delta_days > gap:
            out[eid] = {"gap_days": round(delta_days, 1), "prev_event": prev_id}
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_breaks.py -q`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/breaks.py src/config.py tests/test_breaks.py
git commit -m "feat(chips): calendar-derived international break detection"
```

---

### Task 2: Fixture-swing detection (`compute_fixture_swings`)

**Files:**
- Modify: `src/fixture_difficulty.py` (add function after `build_fixture_ticker`, ~line 704)
- Modify: `src/config.py` (add `SWING_WINDOW_GWS`, `SWING_MIN_DELTA`)
- Test: `tests/test_fixture_difficulty.py` (append)

**Interfaces:**
- Consumes: the ticker dict `build_fixture_ticker` returns — `{"gws": [ints], "teams": [{"team_id", "team_short", "gws": {gw: {"difficulty": float|None, "blank": bool, ...}}}]}`.
- Produces: `compute_fixture_swings(ticker, window=None, min_delta=None) -> list[dict]` of swing events `{"team_id": int, "team_short": str, "gw": int, "delta": float, "direction": "easier"|"harder"}` — at most one strongest event per team per direction. Task 4 consumes this list.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fixture_difficulty.py`:

```python
from src.fixture_difficulty import compute_fixture_swings


def _ticker(team_cells):
    """team_cells: {team_short: {gw: difficulty|None}} — None means blank."""
    gws = sorted({gw for cells in team_cells.values() for gw in cells})
    teams = []
    for i, (short, cells) in enumerate(team_cells.items()):
        teams.append({
            "team_id": i + 1,
            "team_short": short,
            "gws": {gw: {"difficulty": d, "blank": d is None, "count": 0 if d is None else 1}
                    for gw, d in cells.items()},
        })
    return {"gw_start": gws[0], "horizon_gws": len(gws), "gws": gws, "teams": teams}


def test_swing_detected_when_run_turns_easier():
    t = _ticker({"ARS": {10: 4.5, 11: 4.2, 12: 4.4, 13: 2.0, 14: 2.2, 15: 2.1}})
    out = compute_fixture_swings(t, window=3, min_delta=0.8)
    assert len(out) == 1
    ev = out[0]
    assert (ev["team_short"], ev["gw"], ev["direction"]) == ("ARS", 13, "easier")
    assert ev["delta"] > 2.0


def test_no_swing_below_min_delta():
    t = _ticker({"CHE": {10: 3.2, 11: 3.0, 12: 3.1, 13: 2.9, 14: 2.8, 15: 3.0}})
    assert compute_fixture_swings(t, window=3, min_delta=0.8) == []


def test_harder_swing_direction():
    t = _ticker({"SUN": {10: 2.0, 11: 2.1, 12: 2.0, 13: 4.4, 14: 4.5, 15: 4.2}})
    out = compute_fixture_swings(t, window=3, min_delta=0.8)
    assert out[0]["direction"] == "harder"


def test_blank_cells_count_as_neutral_three():
    # Blank (None) → 3.0: 3 tough GWs then [3.0, 2.0, 2.0] avg 2.33 → delta ≈ 2.04
    t = _ticker({"MCI": {10: 4.4, 11: 4.3, 12: 4.4, 13: None, 14: 2.0, 15: 2.0}})
    out = compute_fixture_swings(t, window=3, min_delta=0.8)
    assert len(out) == 1 and out[0]["gw"] == 13


def test_partial_windows_at_edges_are_skipped():
    # Only 4 GWs: no gw has 3 before AND 3 after → no events even with huge delta
    t = _ticker({"LIV": {10: 5.0, 11: 5.0, 12: 1.0, 13: 1.0}})
    assert compute_fixture_swings(t, window=3, min_delta=0.5) == []


def test_one_strongest_event_per_team_per_direction():
    # Long easing run would flag several adjacent GWs — keep only the strongest
    t = _ticker({"AVL": {10: 4.8, 11: 4.6, 12: 4.7, 13: 2.0, 14: 2.1, 15: 1.9,
                          16: 2.0, 17: 2.2, 18: 2.1}})
    out = compute_fixture_swings(t, window=3, min_delta=0.8)
    easier = [e for e in out if e["direction"] == "easier"]
    assert len(easier) == 1 and easier[0]["gw"] == 13
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fixture_difficulty.py -q -k swing`
Expected: FAIL with `ImportError: cannot import name 'compute_fixture_swings'`

- [ ] **Step 3: Add config constants**

In `src/config.py`, next to the chip-plan block:

```python
SWING_WINDOW_GWS = 3            # fixture-swing comparison window (before vs after)
SWING_MIN_DELTA = 0.8           # min avg-difficulty delta to call a swing
```

- [ ] **Step 4: Implement `compute_fixture_swings`**

Add to `src/fixture_difficulty.py` directly after `build_fixture_ticker`:

```python
def compute_fixture_swings(ticker, window=None, min_delta=None):
    """Detect per-team fixture swings in a ``build_fixture_ticker`` payload.

    A swing at GW t means the team's average difficulty over [t, t+window)
    differs from its average over [t-window, t) by at least ``min_delta``.
    Blank cells count as neutral 3.0 (mirrors the ticker's own convention).
    GWs without a full window on both sides are skipped. Only the strongest
    event per team per direction is kept, so a long run doesn't spam
    near-identical adjacent events.

    Returns [{team_id, team_short, gw, delta, direction}] with delta > 0
    meaning the run gets easier ("easier") and < 0 harder ("harder");
    the emitted delta is the absolute magnitude, direction carries the sign.
    """
    window = int(window if window is not None else getattr(config, "SWING_WINDOW_GWS", 3))
    min_delta = float(min_delta if min_delta is not None
                      else getattr(config, "SWING_MIN_DELTA", 0.8))
    gws = list(ticker.get("gws") or [])
    events = []
    for row in ticker.get("teams") or []:
        cells = row.get("gws") or {}
        vals = {}
        for gw in gws:
            cell = cells.get(gw) or {}
            d = cell.get("difficulty")
            vals[gw] = 3.0 if d is None else float(d)
        best = {}  # direction -> event
        for t in gws:
            before = [vals[g] for g in range(t - window, t) if g in vals]
            after = [vals[g] for g in range(t, t + window) if g in vals]
            if len(before) < window or len(after) < window:
                continue
            delta = float(np.mean(before) - np.mean(after))
            if abs(delta) < min_delta:
                continue
            direction = "easier" if delta > 0 else "harder"
            ev = {
                "team_id": row.get("team_id"),
                "team_short": row.get("team_short"),
                "gw": t,
                "delta": round(abs(delta), 2),
                "direction": direction,
            }
            if direction not in best or ev["delta"] > best[direction]["delta"]:
                best[direction] = ev
        events.extend(best.values())
    return events
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_fixture_difficulty.py -q`
Expected: all pass (new swing tests + existing ticker tests untouched)

- [ ] **Step 6: Commit**

```bash
git add src/fixture_difficulty.py src/config.py tests/test_fixture_difficulty.py
git commit -m "feat(fdr): per-team fixture-swing detection over the ticker"
```

---

### Task 3: Position-aware dream-squad clamp

**Files:**
- Modify: `src/chip_advisor.py:139-159` (`_clip_market_xpts`)
- Modify: `src/config.py` (add `CHIP_PLAN_XPTS_CLAMP_BY_POS`)
- Test: `tests/test_chip_advisor.py` (append)

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `_clip_market_xpts(market, col="xpts")` unchanged signature; per-position caps when the market has a `pos` column, flat `CHIP_PLAN_XPTS_CLAMP` fallback otherwise. All existing callers (`score_free_hit`, `score_wildcard`) pick this up automatically.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chip_advisor.py`:

```python
from src.chip_advisor import _clip_market_xpts


def test_clip_position_aware_caps():
    market = pd.DataFrame({
        "player_id": [1, 2, 3, 4],
        "pos": ["GKP", "DEF", "MID", "FWD"],
        "xpts": [13.5, 11.0, 11.5, 12.5],
    })
    out = _clip_market_xpts(market)
    got = dict(zip(out["player_id"], out["xpts"]))
    assert got[1] == 7.0     # cheap-GKP outlier capped hard
    assert got[2] == 8.0     # DEF spike capped
    assert got[3] == 11.5    # premium MID survives under 12.0 cap
    assert got[4] == 12.5    # premium FWD survives under 13.0 cap


def test_clip_flat_fallback_without_pos_column():
    market = pd.DataFrame({"player_id": [1, 2], "xpts": [13.5, 5.0]})
    out = _clip_market_xpts(market)
    assert out["xpts"].tolist() == [9.0, 5.0]


def test_clip_unknown_pos_uses_flat_clamp():
    market = pd.DataFrame({"player_id": [1], "pos": ["???"], "xpts": [12.0]})
    out = _clip_market_xpts(market)
    assert out["xpts"].tolist() == [9.0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chip_advisor.py -q -k clip`
Expected: FAIL — `test_clip_position_aware_caps` gets 9.0-capped values

- [ ] **Step 3: Add config + implement**

In `src/config.py`, directly under `CHIP_PLAN_XPTS_CLAMP`:

```python
# Position-aware dream-squad clamp. The flat CHIP_PLAN_XPTS_CLAMP treated a
# promoted-team DEF outlier pinned at 9.0 as equal to a genuinely elite FWD
# also pinned at 9.0, so WC drafts picked the junk on price. Legit single-GW
# ceilings differ sharply by position; flat clamp remains the fallback when a
# market has no `pos` column.
CHIP_PLAN_XPTS_CLAMP_BY_POS = {"GKP": 7.0, "DEF": 8.0, "MID": 12.0, "FWD": 13.0}
```

Replace the body of `_clip_market_xpts` (keep the docstring, update its last
paragraph to mention position-aware caps):

```python
    if market is None or col not in market.columns:
        return market
    flat = float(getattr(config, "CHIP_PLAN_XPTS_CLAMP", 9.0))
    by_pos = getattr(config, "CHIP_PLAN_XPTS_CLAMP_BY_POS", None)
    out = market.copy()
    xp = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if by_pos and "pos" in out.columns:
        caps = out["pos"].map(by_pos).fillna(flat).astype(float)
        out[col] = np.minimum(xp, caps)
    else:
        out[col] = xp.clip(upper=flat)
    return out
```

- [ ] **Step 4: Run the module's full test file**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: all pass — existing WC/FH budget tests still green (their fixtures
use realistic sub-cap xpts)

- [ ] **Step 5: Commit**

```bash
git add src/chip_advisor.py src/config.py tests/test_chip_advisor.py
git commit -m "feat(chips): position-aware dream-squad xpts clamp"
```

---

### Task 4: Thread new signals through the chip engine

The core task: `score_free_hit` tough-pileup OR-gate, TC haul probability, break
haircut + reasons, swing reasons, `wait_for_team_news` nudge flag.

**Files:**
- Modify: `src/chip_advisor.py` (dataclass, `score_triple_captain`, `score_free_hit`, `recommend_chips`, `build_chip_plan`)
- Modify: `src/config.py` (add `CHIP_PLAN_FH_MIN_TOUGH`, `CHIP_PLAN_FH_TOUGH_DIFFICULTY`, `CHIP_PLAN_TC_DIFF_MULT`)
- Test: `tests/test_chip_advisor.py` (append)

**Interfaces:**
- Consumes: `international_break_gws` map (Task 1 shape), swing-event list (Task 2 shape, but keyed by full team name — see below), plus two new wiring inputs Task 5 builds:
  - `team_difficulty_by_gw: dict[int, dict[str, float]]` — gw → {full team name → cell difficulty} (blank teams absent).
  - `xgi_per90: dict[int, float]` — player_id → expected goals+assists per 90.
  - `swings: list[dict]` — Task 2 events with an added `"team"` key holding the full team name (matching `squad["team"]` / market `team`).
- Produces (consumed by Task 5/6):
  - `ChipRecommendation` gains optional `haul_prob: float | None = None`; `to_dict()` includes it only when not None.
  - `score_free_hit(..., team_difficulty_by_gw=None)`; `score_triple_captain(..., xgi_per90=None, team_difficulty_by_gw=None)`.
  - `recommend_chips(..., breaks=None, xgi_per90=None, team_difficulty_by_gw=None)`.
  - `build_chip_plan(..., breaks=None, team_difficulty_by_gw=None, swings=None, xgi_per90=None)`; payload: TC rec dicts may carry `haul_prob`, nudge dict always carries `wait_for_team_news: bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chip_advisor.py`. Reuse this file's existing style; add a
shared builder at the end of the file:

```python
import math

from src.chip_advisor import (
    build_chip_plan, score_free_hit, score_triple_captain, recommend_chips,
)


def _squad_15(team="Arsenal"):
    """Minimal legal 15: 2 GKP / 5 DEF / 5 MID / 3 FWD, one team name."""
    pos = ["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return pd.DataFrame({
        "player_id": range(1, 16),
        "name": [f"P{i}" for i in range(1, 16)],
        "pos": pos,
        "team": [team] * 15,
        "price_m": [5.0] * 15,
    })


def _market_for(squad, gw_xpts=4.0, fixture_count=1, extra_rows=40):
    """Market containing the squad plus a filler pool of outside players."""
    rows = squad.copy()
    rows["xpts"] = gw_xpts
    rows["fixture_count"] = fixture_count
    pool_pos = (["GKP", "DEF", "MID", "FWD"] * (extra_rows // 4 + 1))[:extra_rows]
    pool = pd.DataFrame({
        "player_id": range(100, 100 + extra_rows),
        "name": [f"M{i}" for i in range(extra_rows)],
        "pos": pool_pos,
        "team": [f"T{i % 8}" for i in range(extra_rows)],
        "price_m": [5.0] * extra_rows,
        "xpts": [6.0] * extra_rows,
        "fixture_count": [1] * extra_rows,
    })
    return pd.concat([rows, pool], ignore_index=True)


# ---- FH tough-pileup gate ----

def test_fh_tough_pileup_opens_gate_without_blanks():
    squad = _squad_15(team="Arsenal")
    market = _market_for(squad, gw_xpts=2.0)  # squad weak this GW, market strong
    diff = {5: {"Arsenal": 4.5}}              # all 15 face difficulty 4.5
    recs = score_free_hit(squad, {5: market}, [5], budget_m=100.0,
                          team_difficulty_by_gw=diff)
    assert len(recs) == 1
    assert any("difficulty" in r for r in recs[0].reasoning)


def test_fh_gate_still_closed_on_ordinary_week():
    squad = _squad_15(team="Arsenal")
    market = _market_for(squad, gw_xpts=2.0)
    diff = {5: {"Arsenal": 2.5}}              # easy fixtures — no trigger
    recs = score_free_hit(squad, {5: market}, [5], budget_m=100.0,
                          team_difficulty_by_gw=diff)
    assert recs == []


def test_fh_no_difficulty_map_falls_back_to_blank_gate_only():
    squad = _squad_15(team="Arsenal")
    market = _market_for(squad, gw_xpts=2.0)
    recs = score_free_hit(squad, {5: market}, [5], budget_m=100.0,
                          team_difficulty_by_gw=None)
    assert recs == []  # no blanks, no map → today's behavior


# ---- TC haul probability ----

def test_tc_haul_prob_poisson_math():
    squad = _squad_15(team="Arsenal")
    market = _market_for(squad, gw_xpts=6.0)
    xgi = {i: 0.0 for i in range(1, 16)}
    xgi[13] = 0.9  # a FWD; neutral difficulty → lambda = 0.9
    recs = score_triple_captain(squad, {5: market}, [5], xgi_per90=xgi,
                                team_difficulty_by_gw={5: {"Arsenal": 3.0}})
    lam = 0.9
    expected = 1 - math.exp(-lam) * (1 + lam)
    assert recs[0].haul_prob is not None
    assert abs(recs[0].haul_prob - expected) < 1e-6
    assert any("haul" in r for r in recs[0].reasoning)


def test_tc_haul_prob_missing_xgi_omits_field():
    squad = _squad_15(team="Arsenal")
    market = _market_for(squad, gw_xpts=6.0)
    recs = score_triple_captain(squad, {5: market}, [5])
    assert recs[0].haul_prob is None
    assert "haul_prob" not in recs[0].to_dict()


def test_tc_haul_prob_dgw_sums_lambdas():
    squad = _squad_15(team="Arsenal")
    market = _market_for(squad, gw_xpts=6.0, fixture_count=2)
    xgi = {13: 0.9}
    recs = score_triple_captain(squad, {5: market}, [5], xgi_per90=xgi,
                                team_difficulty_by_gw={5: {"Arsenal": 3.0}})
    lam = 0.9 * 2
    expected = 1 - math.exp(-lam) * (1 + lam)
    assert abs(recs[0].haul_prob - expected) < 1e-6


# ---- break haircut + nudge flag ----

def test_break_haircut_and_reason_applied():
    squad = _squad_15(team="Arsenal")
    market = _market_for(squad, gw_xpts=6.0)
    base = recommend_chips(squad, 5, {5: market}, ["triple_captain"], gws_ahead=0)
    hair = recommend_chips(squad, 5, {5: market}, ["triple_captain"], gws_ahead=0,
                           breaks={5: {"gap_days": 14.0, "prev_event": 4}})
    assert hair[0].confidence < base[0].confidence
    assert abs(hair[0].confidence - base[0].confidence * 0.85) < 1e-6
    assert any("international break" in r for r in hair[0].reasoning)


def test_nudge_wait_for_team_news_flag(monkeypatch):
    squad = _squad_15(team="Arsenal")
    market = _market_for(squad, gw_xpts=8.0)
    # Force TC over the min-EV bar for a current-GW nudge
    monkeypatch.setattr(config, "CHIP_PLAN_MIN_EV",
                        {**config.CHIP_PLAN_MIN_EV, "triple_captain": 1.0})
    plan_no_break = build_chip_plan(
        squad, 5, {5: market}, chips_played=[], breaks={})
    plan_break = build_chip_plan(
        squad, 5, {5: market}, chips_played=[],
        breaks={5: {"gap_days": 14.0, "prev_event": 4}})
    assert plan_no_break["nudge"]["wait_for_team_news"] is False
    assert plan_break["nudge"]["wait_for_team_news"] is True


# ---- swing reasons ----

def test_wildcard_rec_names_easier_swings(monkeypatch):
    squad = _squad_15(team="Arsenal")
    markets = {g: _market_for(squad, gw_xpts=2.0) for g in range(5, 9)}
    monkeypatch.setattr(config, "CHIP_PLAN_MIN_EV",
                        {**config.CHIP_PLAN_MIN_EV, "wildcard": 1.0})
    swings = [{"team": "T1", "team_short": "T1", "gw": 5, "delta": 1.2,
               "direction": "easier"}]
    plan = build_chip_plan(squad, 5, markets, chips_played=[], swings=swings)
    wc = next((r for r in plan["recommendations"] if r["chip"] == "wildcard"), None)
    assert wc is not None
    assert any("swing" in reason.lower() for reason in wc["reasons"])
```

Note: `config` is imported in this test file via `from src import config` — add
that import at the top if missing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: new tests FAIL with `TypeError: ... unexpected keyword argument` /
`AttributeError: 'ChipRecommendation' object has no attribute 'haul_prob'`

- [ ] **Step 3: Add config constants**

In `src/config.py`, chip-plan block:

```python
CHIP_PLAN_FH_MIN_TOUGH = 6      # squad players on tough fixtures that open the FH gate
CHIP_PLAN_FH_TOUGH_DIFFICULTY = 4.0  # ticker difficulty counting as "tough"
# Difficulty→multiplier for the TC haul-prob lambda (mirrors the projection
# engine's FDR multipliers; keyed on round(difficulty)).
CHIP_PLAN_TC_DIFF_MULT = {1: 1.25, 2: 1.12, 3: 1.0, 4: 0.88, 5: 0.75}
```

- [ ] **Step 4: Implement the `chip_advisor.py` changes**

4a. Dataclass — add field + conditional dict key:

```python
@dataclass
class ChipRecommendation:
    chip: str
    gw: int
    expected_value: float
    confidence: float
    reasoning: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    haul_prob: float | None = None   # TC only: P(captain gets 2+ goal involvements)

    def to_dict(self) -> dict:
        out = {
            "chip": self.chip,
            "gw": self.gw,
            "expected_value": round(float(self.expected_value), 2),
            "confidence": round(float(self.confidence), 2),
            "reasoning": list(self.reasoning),
            "risks": list(self.risks),
        }
        if self.haul_prob is not None:
            out["haul_prob"] = round(float(self.haul_prob), 3)
        return out
```

4b. Captain-row helper — fixes a latent inconsistency: `score_triple_captain`
currently takes `captain_row = xi.sort_values("xpts", ascending=False).iloc[0]`,
which ignores the position multipliers `_pick_captain_xpts` uses — on ties the
"captain" named in reasons can even be a GKP. Extract one source of truth in
`src/chip_advisor.py`:

```python
def _pick_captain_row(starting_xi: pd.DataFrame):
    """Row of the best captain candidate (position-weighted, favor FWD/MID)."""
    if starting_xi.empty:
        return None
    cap_mult = {"FWD": 1.16, "MID": 1.12, "DEF": 0.92, "GKP": 0.70}
    s = starting_xi.copy()
    s["_score"] = s["xpts"] * s["pos"].map(cap_mult).fillna(1.0)
    return s.sort_values("_score", ascending=False).iloc[0]


def _pick_captain_xpts(starting_xi: pd.DataFrame) -> float:
    row = _pick_captain_row(starting_xi)
    return 0.0 if row is None else float(row["xpts"])
```

and in `score_triple_captain` replace the `captain_row = xi.sort_values(...)`
line with `captain_row = _pick_captain_row(xi)`.

`score_triple_captain` — new signature and haul block. New signature:

```python
def score_triple_captain(
    squad: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    candidate_gws: list[int],
    xgi_per90: dict[int, float] | None = None,
    team_difficulty_by_gw: dict[int, dict[str, float]] | None = None,
) -> list[ChipRecommendation]:
```

After `captain_row` / `is_dgw` are computed, add:

```python
        haul_prob = None
        if xgi_per90:
            import math
            per90 = float(xgi_per90.get(int(captain_row["player_id"]), 0.0) or 0.0)
            if per90 > 0:
                dmap = (team_difficulty_by_gw or {}).get(gw) or {}
                d = dmap.get(captain_row.get("team"))
                mult_map = getattr(config, "CHIP_PLAN_TC_DIFF_MULT", {})
                mult = float(mult_map.get(int(round(d)), 1.0)) if d is not None else 1.0
                n_fix = max(1, int(captain_row.get("fixture_count", 1)))
                lam = per90 * mult * n_fix
                haul_prob = 1.0 - math.exp(-lam) * (1.0 + lam)
                reasoning.append(
                    f"~{haul_prob:.0%} chance of a 2+ goal-involvement haul")
```

and pass `haul_prob=haul_prob` into the `ChipRecommendation(...)` constructor.
(Move the `import math` to the module top with the other imports.)

4c. `score_free_hit` — new signature adds `team_difficulty_by_gw: dict[int, dict[str, float]] | None = None`. Replace the gate block (currently lines 350-354):

```python
        # Detect BGW: many squad players with no fixture
        n_blanking = int((squad_with_xpts["fixture_count"] == 0).sum())

        # Tough-pileup OR-path: many squad players facing hard fixtures this GW
        n_tough = 0
        if team_difficulty_by_gw:
            dmap = team_difficulty_by_gw.get(gw) or {}
            tough_at = float(getattr(config, "CHIP_PLAN_FH_TOUGH_DIFFICULTY", 4.0))
            n_tough = int(sum(
                1 for t in squad_with_xpts["team"].tolist()
                if dmap.get(t) is not None and float(dmap[t]) >= tough_at))

        min_blanking = int(getattr(config, "CHIP_PLAN_FH_MIN_BLANKING", 3))
        min_tough = int(getattr(config, "CHIP_PLAN_FH_MIN_TOUGH", 6))
        blank_trigger = n_blanking >= min_blanking
        tough_trigger = n_tough >= min_tough
        if not blank_trigger and not tough_trigger:
            continue  # ordinary week — hold FH for a blank- or tough-heavy GW
```

and replace the hardcoded blanking reason line with trigger-specific ones:

```python
        if blank_trigger:
            reasoning.append(f"{n_blanking} squad players blanking — strong FH candidate")
        if tough_trigger:
            tough_at = float(getattr(config, "CHIP_PLAN_FH_TOUGH_DIFFICULTY", 4.0))
            reasoning.append(
                f"{n_tough} of your 15 face difficulty ≥{tough_at:.1f} in GW{gw}")
```

(`reasoning` is built before these appends as today: normal XI line, FH XI line,
uplift line.) Keep the confidence formula but base its blank bonus on
`blank_trigger or tough_trigger`:

```python
            confidence=0.4 + (0.4 if (blank_trigger or tough_trigger) else 0)
                       + (0.2 if uplift > 15 else 0),
```

4d. `recommend_chips` — new signature:

```python
def recommend_chips(
    squad: pd.DataFrame,
    current_gw: int,
    gw_projections: dict[int, pd.DataFrame],
    chips_remaining: list[str],
    gws_ahead: int = 10,
    bank_m: float = 0.0,
    transfer_plan_net_gain: float = 0.0,
    breaks: dict[int, dict] | None = None,
    xgi_per90: dict[int, float] | None = None,
    team_difficulty_by_gw: dict[int, dict[str, float]] | None = None,
) -> list[ChipRecommendation]:
```

Thread `xgi_per90`/`team_difficulty_by_gw` into `score_triple_captain`, and
`team_difficulty_by_gw` into `score_free_hit`. After `all_recs` is assembled and
before the final sort, apply the break haircut:

```python
    if breaks:
        mult = float(getattr(config, "CHIP_PLAN_BREAK_CONFIDENCE_MULT", 0.85))
        for r in all_recs:
            if r.gw in breaks:
                r.confidence *= mult
                r.reasoning.append(
                    "First GW after international break — elevated injury/rotation uncertainty")
                if r.chip == "triple_captain":
                    r.risks.append(
                        "Late fitness flags after the break hit TC hardest — confirm lineups first")
```

4e. `build_chip_plan` — new signature adds
`breaks: dict[int, dict] | None = None`,
`team_difficulty_by_gw: dict[int, dict[str, float]] | None = None`,
`swings: list[dict] | None = None`,
`xgi_per90: dict[int, float] | None = None`.
Pass `breaks`/`xgi_per90`/`team_difficulty_by_gw` into `recommend_chips`. In the
model-zone loop, after `rec` is built:

```python
        if best.haul_prob is not None:
            rec["haul_prob"] = round(float(best.haul_prob), 3)
        if swings and chip in ("wildcard", "triple_captain"):
            near = [s for s in swings
                    if s.get("direction") == "easier"
                    and abs(int(s.get("gw", 0)) - rec["event_id"]) <= 1]
            if near:
                names = ", ".join(sorted(
                    s.get("team_short") or s.get("team", "?") for s in near)[:3])
                rec["reasons"].append(
                    f"Fixture swing: {names} turn easier around GW{rec['event_id']}")
```

And the nudge line becomes:

```python
            if nudge is None or rec["ev_gain"] > nudge["ev_gain"]:
                nudge = {"chip": chip, "event_id": current_gw, "ev_gain": rec["ev_gain"],
                         "wait_for_team_news": bool(breaks and current_gw in breaks)}
```

- [ ] **Step 5: Run the full backend chip tests**

Run: `python -m pytest tests/test_chip_advisor.py tests/test_chips_route.py -q`
Expected: all pass (route tests unchanged — payload only gained optional keys)

- [ ] **Step 6: Commit**

```bash
git add src/chip_advisor.py src/config.py tests/test_chip_advisor.py
git commit -m "feat(chips): break haircut, FH tough-pileup gate, TC haul prob, swing reasons"
```

---

### Task 5: Wire live signals in the API layer

**Files:**
- Modify: `api/chips.py` (`_build_plan_response`)
- Test: `tests/test_chips_route.py` (append)

**Interfaces:**
- Consumes: Task 1 `international_break_gws`, Task 2 `compute_fixture_swings`, Task 4 `build_chip_plan` kwargs.
- Produces: the live `/chips/plan` payload with the new optional keys. Task 6 (chat context) and Task 7+ (frontend) consume it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chips_route.py` (match the file's existing monkeypatch
style for `_build_context_for_entry`; extend the fake context if needed):

```python
def test_plan_response_carries_new_optional_keys(monkeypatch, client):
    # Reuse this file's existing fake-context fixture pattern. Assert only shape:
    resp = client.get("/chips/plan", params={"entry_id": 1})
    assert resp.status_code == 200
    body = resp.json()
    nudge = body.get("nudge")
    if nudge is not None:
        assert isinstance(nudge.get("wait_for_team_news"), bool)
    for rec in body["recommendations"]:
        if "haul_prob" in rec:
            assert 0.0 <= rec["haul_prob"] <= 1.0
```

(Adapt fixture names to what `tests/test_chips_route.py` already defines — the
existing tests there stub the context builder and FPL client; follow the same
stubs and add `events`-bearing bootstrap data to them.)

- [ ] **Step 2: Run to verify it fails or errors**

Run: `python -m pytest tests/test_chips_route.py -q`
Expected: new test fails (no `wait_for_team_news` on nudge yet) or errors on
missing stub data — fix stubs as part of this task, never by weakening asserts.

- [ ] **Step 3: Implement the wiring in `api/chips.py`**

In `_build_plan_response`, before the `build_chip_plan` call:

```python
    # --- strategy signals: breaks, fixture difficulty, swings, per-player xGI ---
    breaks = None
    team_difficulty_by_gw = None
    swings = None
    xgi_per90 = None
    try:
        from src.breaks import international_break_gws
        bootstrap = fpl_client.get_bootstrap()
        breaks = international_break_gws(bootstrap.get("events", []))

        id_to_name = {int(t["id"]): t["name"] for t in bootstrap.get("teams", [])}
        el = pd.DataFrame(bootstrap.get("elements", []))
        if not el.empty and "expected_goals_per_90" in el.columns:
            xg = pd.to_numeric(el["expected_goals_per_90"], errors="coerce").fillna(0.0)
            xa = pd.to_numeric(el.get("expected_assists_per_90"), errors="coerce").fillna(0.0)
            xgi_per90 = dict(zip(el["id"].astype(int), (xg + xa).astype(float)))

        # Ticker spans horizon + swing window so edge GWs get a forward window.
        from api.main import build_fixture_difficulty_payload  # lazy: avoids import cycle
        from src.fixture_difficulty import compute_fixture_swings
        window = int(getattr(config, "SWING_WINDOW_GWS", 3))
        ticker = build_fixture_difficulty_payload(
            gw_start=current_gw, horizon_gws=model_horizon + window)
        team_difficulty_by_gw = {}
        for row in ticker.get("teams", []):
            name = id_to_name.get(int(row.get("team_id", 0)))
            if not name:
                continue
            for gw, cell in (row.get("gws") or {}).items():
                d = (cell or {}).get("difficulty")
                if d is None:
                    continue
                team_difficulty_by_gw.setdefault(int(gw), {})[name] = float(d)
        swings = [
            {**s, "team": id_to_name.get(int(s.get("team_id", 0)), s.get("team_short"))}
            for s in compute_fixture_swings(ticker)
        ]
    except Exception as e:  # noqa: BLE001 — signals must never fail the plan
        logger.warning("chip strategy signals unavailable: %s", e)

    plan = build_chip_plan(
        squad=ctx["squad"],
        current_gw=current_gw,
        gw_projections=ctx["gw_projections"],
        chips_played=_get_entry_chips(entry_id),
        itb_m=float(ctx["bank_m"]),
        fixtures=ctx.get("fixtures"),
        transfer_plan=transfer_plan,
        horizon_gws=model_horizon,
        breaks=breaks,
        team_difficulty_by_gw=team_difficulty_by_gw,
        swings=swings,
        xgi_per90=xgi_per90,
    )
```

Note: `ctx.get("fixtures")` — confirm `_build_context_for_entry` returns a
`fixtures` key; it builds `fixtures` internally (api/chat.py:83) — if the ctx
dict does not currently include it, add `"fixtures": fixtures` to the returned
context dict in the same commit (check `api/chat.py` around line 170-220 where
the ctx dict is assembled; the existing `_build_plan_response` already calls
`ctx.get("fixtures")`, so it is almost certainly present).

- [ ] **Step 4: Run route + advisor tests**

Run: `python -m pytest tests/test_chips_route.py tests/test_chip_advisor.py -q`
Expected: all pass

- [ ] **Step 5: Live spot-check (dev machine, real data)**

Run: `PYTHONPATH=. python -m scripts.spotcheck_chip_plan <your_entry_id>`
Expected: plan builds; current September-break state shows the post-break
reason on next-GW recs and `wait_for_team_news: true` if a nudge fires. Paste
the output into the PR/commit message notes.

- [ ] **Step 6: Commit**

```bash
git add api/chips.py tests/test_chips_route.py
git commit -m "feat(api): wire breaks/difficulty/swings/xGI into /chips/plan"
```

---

### Task 6: Thread break context into the chip chat agent

**Files:**
- Modify: `api/chat.py` (`_build_context_for_entry` or the chip-chat handler around line 287)
- Modify: `agents/chip_agent.md` (one paragraph)
- Test: `tests/test_chip_advisor.py` orchestrator tests area (only if the agent contract changes — see step 2)

**Interfaces:**
- Consumes: Task 1 `international_break_gws`.
- Produces: the chip chat agent's grounding context includes `breaks` so `/chat/chip` answers explain break timing.

- [ ] **Step 1: Add breaks to the chip-chat grounding**

In `api/chat.py`, where the chip handler builds its context for the agent
(`POST /chat/chip`, ~line 287, which ends up calling the chip agent with the
`build_chip_plan` payload): compute `breaks = international_break_gws(bootstrap.get("events", []))`
(bootstrap already fetched in `_build_context_for_entry`) and include
`"breaks": {str(k): v for k, v in breaks.items()}` in the payload dict passed to
the agent tool. Follow the exact shape of how `chips_remaining` is currently
threaded (api/chat.py:59-69).

- [ ] **Step 2: Update the agent prompt**

Append to `agents/chip_agent.md` (keep its existing voice):

```markdown
## International breaks
The context may include a `breaks` map (gameweek → gap info) marking the first
gameweek after an international break. When a recommendation targets such a
gameweek, tell the user to hold the final decision until post-break team news
(late fitness flags are common), and never present a post-break triple captain
as a confident pick.
```

- [ ] **Step 3: Run the agent/orchestrator tests**

Run: `python -m pytest tests/test_chip_advisor.py -q -k "agent or orchestrator"`
Expected: pass (the existing tests assert the plan payload is threaded; the
added key is additive). If a test asserts the exact payload key set, extend it
to include `breaks`.

- [ ] **Step 4: Commit**

```bash
git add api/chat.py agents/chip_agent.md
git commit -m "feat(chat): ground chip agent on international-break calendar"
```

---

### Task 7: Frontend — merge chip UI + release branch

Work in the frontend repo `/Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub`.

**Files:**
- Branch ops only (no code edits in this task).

**Interfaces:**
- Produces: branch `release/chip-strategy` = `main` + `feature/chip-planner-frontend` (21 commits, `main` is its ancestor so this merges clean). Contains `ChipRoadmapPanel.tsx`, `ChipNudgeCard.tsx`, chips tab in `RecommendationsPanel.tsx`, `fetchChipPlan` + chip types in `src/lib/fplAssistantApi.ts:1320-1367`, `useQuery(["chipPlan", ...])` in `Index.tsx`. Tasks 8-9 build on this branch.
- NOT included: `feature/transfer-clarity` (31 further commits — separate in-flight work, ships on its own schedule).

- [ ] **Step 1: Create the release branch and merge**

```bash
cd /Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub
git fetch origin
git checkout -b release/chip-strategy origin/main
git merge --no-ff feature/chip-planner-frontend -m "merge: chip planner UI (roadmap panel, nudge card, chips tab)"
```

Expected: clean merge (`main` is an ancestor of the branch). If conflicts
appear, `main` moved — resolve favoring `feature/chip-planner-frontend` for the
chip files listed above and current `main` for everything else.

- [ ] **Step 2: Install and run the frontend test suite**

```bash
npm install
npx vitest run src/components/ChipRoadmapPanel.test.tsx src/components/ChipNudgeCard.test.tsx
npx vitest run
```

Expected: chip component tests pass; full suite green.

- [ ] **Step 3: Commit is the merge itself — push the branch**

```bash
git push -u origin release/chip-strategy
```

---

### Task 8: Frontend — `wait_for_team_news` badge + haul type

On branch `release/chip-strategy` in the frontend repo.

**Files:**
- Modify: `src/lib/fplAssistantApi.ts` (ChipNudge + ChipPlanRecommendation types)
- Modify: `src/components/ChipNudgeCard.tsx`
- Test: `src/components/ChipNudgeCard.test.tsx` (append)

**Interfaces:**
- Consumes: `/chips/plan` payload from Task 5 (`nudge.wait_for_team_news`, optional `rec.haul_prob`).
- Produces: nudge card renders a "wait for team news" pill and softens copy when the flag is true. Haul % arrives in `reasons[]` strings and renders through the existing reason list — the type field is added for completeness only.

- [ ] **Step 1: Write the failing test**

Append to `src/components/ChipNudgeCard.test.tsx` (match its existing render
helpers/imports):

```tsx
it("shows the team-news pill and softened copy when wait_for_team_news is set", () => {
  render(
    <ChipNudgeCard
      nudge={{ chip: "triple_captain", event_id: 5, ev_gain: 6.2, wait_for_team_news: true }}
      activeChipStrategy="none"
      onApplyChip={() => {}}
    />
  );
  expect(screen.getByText(/wait for team news/i)).toBeInTheDocument();
});

it("no pill when wait_for_team_news is absent", () => {
  render(
    <ChipNudgeCard
      nudge={{ chip: "triple_captain", event_id: 5, ev_gain: 6.2 }}
      activeChipStrategy="none"
      onApplyChip={() => {}}
    />
  );
  expect(screen.queryByText(/wait for team news/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/components/ChipNudgeCard.test.tsx`
Expected: FAIL (type error on `wait_for_team_news` / missing pill)

- [ ] **Step 3: Extend the types**

In `src/lib/fplAssistantApi.ts`:

```ts
export type ChipNudge = {
  chip: ChipName;
  event_id: number;
  ev_gain: number;
  wait_for_team_news?: boolean;
};
```

and add to `ChipPlanRecommendation` (after `ev_curve`):

```ts
  haul_prob?: number; // triple_captain only: P(captain gets 2+ goal involvements)
```

- [ ] **Step 4: Render the pill in `ChipNudgeCard.tsx`**

Inside the card's flex row, after the `<p>` copy block:

```tsx
      {nudge.wait_for_team_news && (
        <span className="shrink-0 rounded-full border border-amber-500/50 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
          post-break — wait for team news
        </span>
      )}
```

(Keep the Apply button; the pill informs, the user still decides.)

- [ ] **Step 5: Run tests**

Run: `npx vitest run src/components/ChipNudgeCard.test.tsx && npx vitest run`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/lib/fplAssistantApi.ts src/components/ChipNudgeCard.tsx src/components/ChipNudgeCard.test.tsx
git commit -m "feat(chips): post-break wait-for-team-news pill on the nudge card"
```

---

### Task 9: Release — deploy backend then frontend

**Files:** none (ops task).

**Interfaces:**
- Consumes: everything above. Backend deploys first so the new payload keys exist when the UI lands.

- [ ] **Step 1: Backend full verification**

```bash
cd /Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL
python -m pytest -q
```

Expected: full suite green. Then a final live spot-check:
`PYTHONPATH=. python -m scripts.spotcheck_chip_plan <entry_id>` — read every
reason string for sanity (September-break state should show post-break notes).

- [ ] **Step 2: Deploy backend**

`master` auto-deploys via `.github/workflows/fly-deploy.yml`. Follow the repo's
established flow for `feature/xpts-components` (fast-forward to `master`, per
CLAUDE.md branch table) — **pause here and confirm with the user before
touching `master`**, then:

```bash
git checkout master && git merge --ff-only feature/xpts-components && git push origin master
```

Verify: `curl -s "$FPL_API_BASE_URL/health"` then hit `/chips/plan` for a known
entry and confirm `wait_for_team_news` appears on the nudge (or recs carry
break reasons).

- [ ] **Step 3: Deploy frontend**

Merge `release/chip-strategy` → `main` in the frontend repo (confirm with the
user first), push, and let the Vercel integration build. Confirm the active
Vercel scope is **ziad-naders-projects** before any manual `vercel` CLI use.
Smoke-test in prod: chips tab renders the roadmap, nudge card shows when
applicable.

- [ ] **Step 4: Post-release note**

Update memory: chip strategy upgrades shipped (date, what landed), and flag the
follow-up backlog: WC min-EV retune after the position-aware clamp beds in, and
the full event-level xPts decomposition project.
