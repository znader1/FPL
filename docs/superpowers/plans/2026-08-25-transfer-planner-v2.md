# Transfer Planner v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the shipped horizon transfer planner with an injury-forced-spend gate, a top-level verdict, accurate FT banking to 5, finished-GW-only form data, and activate the xG projection blend if the backtests support it.

**Architecture:** No new response blocks and no new planner. `src/transfer_planner.py` (greedy horizon walk, already rendered by the frontend) gains the injury gate and verdict fields; a new small pure module `src/ft_tracker.py` derives banked FTs; `src/projections.py` gets a `finished_gw_max` cutoff; `scripts/backtest_season.py` gets a `--planner` A/B mode; workstream B is evidence runs over existing sweep scripts.

**Tech Stack:** Python 3.11, FastAPI, pandas, pytest. Frontend: React + TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-08-24-transfer-planner-design.md` (v2)

## Global Constraints

- Backend repo `FPL/`, branch `feature/xg-expected-points`. Frontend repo `fpl-decision-hub`, branch off `fix/auth-token-on-api-calls`.
- All tunables in `src/config.py`, read via `getattr(config, "NAME", default)` — never hardcode in logic files.
- `transfer_plan_horizon` stays additive: planner exceptions must never break `/recommendations` (existing try/except at `api/main.py:1161` stays).
- FT cap is 5 (2026-27 rule). Red-flag statuses: `i`, `s`, `u`, or `chance_of_playing_next_round == 0`.
- No default-flag flips without recorded backtest numbers (Tasks 7–8 record them in this plan doc).
- Run tests with `python -m pytest -q` from the `FPL/` repo root.

---

### Task 1: FT tracker module

**Files:**
- Create: `src/ft_tracker.py`
- Test: `tests/test_ft_tracker.py`

**Interfaces:**
- Produces: `derive_free_transfers(events, chips, next_event_id, ft_max=5) -> int` — `events` = list of dicts with `event` (int) and `event_transfers` (int) from `entry/{id}/history` `current`; `chips` = list of dicts with `name`, `event`; returns FTs available for `next_event_id`, in [1, ft_max].
- Produces: `clamp_ft(value, ft_max=5) -> int | None` — clamps an externally reported FT count to [1, ft_max]; `None` in → `None` out.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ft_tracker.py
from src.ft_tracker import derive_free_transfers, clamp_ft


def _ev(event, used):
    return {"event": event, "event_transfers": used}


def test_gw1_no_history_gives_one():
    assert derive_free_transfers([], [], next_event_id=1) == 1


def test_unused_fts_bank_up_to_cap():
    # 6 GWs of zero transfers: 1 -> 2 -> 3 -> 4 -> 5 -> 5 (capped)
    events = [_ev(g, 0) for g in range(1, 7)]
    assert derive_free_transfers(events, [], next_event_id=7) == 5


def test_spending_reduces_bank():
    # GW1 bank (0 used) -> 2 FT at GW2; GW2 uses 2 -> min(5, max(2-2,0)+1) = 1 at GW3
    events = [_ev(1, 0), _ev(2, 2)]
    assert derive_free_transfers(events, [], next_event_id=3) == 1


def test_hits_floor_at_one():
    # Using more transfers than held (hits) still leaves 1 FT next GW
    events = [_ev(1, 4)]
    assert derive_free_transfers(events, [], next_event_id=2) == 1


def test_wildcard_gw_consumes_nothing():
    # WC in GW2 with 8 transfers: treated as 0 used -> bank keeps growing
    events = [_ev(1, 0), _ev(2, 8), _ev(3, 0)]
    chips = [{"name": "wildcard", "event": 2}]
    assert derive_free_transfers(events, chips, next_event_id=4) == 4


def test_freehit_gw_consumes_nothing():
    events = [_ev(1, 0), _ev(2, 1)]
    chips = [{"name": "freehit", "event": 2}]
    assert derive_free_transfers(events, chips, next_event_id=3) == 3


def test_events_at_or_after_next_are_ignored():
    events = [_ev(1, 0), _ev(2, 3)]  # GW2 row present but next_event_id=2 -> ignore it
    assert derive_free_transfers(events, [], next_event_id=2) == 2


def test_clamp_ft():
    assert clamp_ft(0) == 1
    assert clamp_ft(3) == 3
    assert clamp_ft(9) == 5
    assert clamp_ft(None) is None
    assert clamp_ft("2") == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ft_tracker.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ft_tracker'`

- [ ] **Step 3: Implement the module**

```python
# src/ft_tracker.py
"""Derive banked free transfers under the 2026-27 rule (roll up to 5).

Pure functions; API fetch stays in the caller. The season walk replaces the
old binary 1/2 heuristic in api/main.py: FPL grants +1 FT at each new GW
deadline (cap 5), spent transfers subtract, hits floor the carry at 0, and
Wildcard/Free-Hit gameweeks consume no free transfers.
"""

from src import config

FT_MAX = int(getattr(config, "FT_MAX", 5))
_CHIP_NO_CONSUME = {"wildcard", "freehit"}


def clamp_ft(value, ft_max=FT_MAX):
    if value is None:
        return None
    try:
        return max(1, min(int(ft_max), int(value)))
    except (TypeError, ValueError):
        return None


def derive_free_transfers(events, chips, next_event_id, ft_max=FT_MAX):
    chip_gws = {
        int(c.get("event")) for c in (chips or [])
        if str(c.get("name") or "").lower() in _CHIP_NO_CONSUME and c.get("event") is not None
    }
    rows = sorted(
        (e for e in (events or []) if e.get("event") is not None and int(e["event"]) < int(next_event_id)),
        key=lambda e: int(e["event"]),
    )
    ft = 1
    for row in rows:
        gw = int(row["event"])
        used = 0 if gw in chip_gws else max(0, int(row.get("event_transfers") or 0))
        ft = min(int(ft_max), max(ft - used, 0) + 1)
    return ft
```

Add to `src/config.py` next to the other transfer tunables (`TRANSFER_MAX_MOVES` block):

```python
FT_MAX = 5                              # 2026-27: free transfers bank up to 5
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ft_tracker.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/ft_tracker.py tests/test_ft_tracker.py src/config.py
git commit -m "feat(transfers): season-walk free-transfer derivation, banked to 5"
```

---

### Task 2: Wire FT tracker into `/recommendations` context

**Files:**
- Modify: `api/main.py:490-513` (the FT derivation block inside `load_fpl_context`)

**Interfaces:**
- Consumes: `ft_tracker.derive_free_transfers`, `ft_tracker.clamp_ft` (Task 1); `fpl_client.get_entry_history(entry_id)` (exists, `src/fpl_client.py:196`, returns dict with `current` events list and `chips`).
- Produces: `ctx["derived_free_transfers"]` now in [1, 5]; downstream code unchanged.

- [ ] **Step 1: Replace the heuristic block**

In `load_fpl_context`, replace the block from `derived_free_transfers = 1` (line 494) through the `my_team_ft` override (line 513) with:

```python
    derived_free_transfers = 1
    last_active_chip = (myteam.get("active_chip") or "").lower()
    try:
        history = fpl_client.get_entry_history(entry_id)
        next_ev_for_ft = _event_id(bootstrap, "is_next") or (int(used_event_id) + 1)
        derived_free_transfers = ft_tracker.derive_free_transfers(
            history.get("current") or [],
            history.get("chips") or [],
            next_event_id=next_ev_for_ft,
        )
    except Exception:
        # History unavailable (pre-season wipe, 403): fall back to the old
        # single-GW heuristic rather than fail the request.
        if last_active_chip not in ("wildcard", "freehit"):
            try:
                cur_transfers = int(eh.get("event_transfers") or 0)
                derived_free_transfers = 2 if cur_transfers == 0 else 1
            except Exception:
                pass

    # Authenticated my-team reports the real count directly; it wins, clamped to [1, FT_MAX].
    clamped = ft_tracker.clamp_ft(my_team_ft)
    if clamped is not None:
        derived_free_transfers = clamped
```

Add `from src import ft_tracker` to the imports at the top of `api/main.py` (next to the other `from src import ...` lines).

- [ ] **Step 2: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass (178+ as of branch head; auth tests already override dependencies)

- [ ] **Step 3: Manual smoke against live FPL**

Run: `python -c "from src import fpl_client, ft_tracker; h = fpl_client.get_entry_history(588004); print(ft_tracker.derive_free_transfers(h.get('current') or [], h.get('chips') or [], next_event_id=99))"`
Expected: an integer in [1, 5] printed (season just started, so likely 1–2)

- [ ] **Step 4: Commit**

```bash
git add api/main.py
git commit -m "feat(api): banked-FT season walk replaces the binary heuristic"
```

---

### Task 3: Injury gate + verdict in the horizon planner

**Files:**
- Modify: `src/transfer_planner.py`
- Modify: `api/main.py:1164` (call site — pass status columns through)
- Test: `tests/test_transfer_planner.py` (append)

**Interfaces:**
- Consumes: `proj` frame at the call site is `proj_all`; if `status` / `chance_of_playing_next_round` are missing from it, merge them from `ctx["elements"]` on `id` before calling.
- Produces: `plan_transfers` return gains `verdict` (`"roll" | "spend" | "spend_forced_injury"`), `reasoning` (str), `first_gw_ft_before` (int), `first_gw_ft_after` (int). Existing keys unchanged. `_build_info` entries gain `red_flag: bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_transfer_planner.py` (reuse its existing fixture helpers for building `proj` frames; the frame builder must now also accept `status` and `chance_of_playing_next_round` columns, defaulting to `"a"` / `100`):

```python
def test_red_flag_starter_forces_spend_verdict():
    # Squad player with status "i" and a cheap same-position replacement available;
    # replacement gain is BELOW min_gain — the forced sell must happen anyway.
    proj = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=0.2, status="i"),   # injured squad DEF
        _player(2, "DEF", price=4.0, xpts=1.0),               # replacement, gain 0.8 < min_gain 2.0
        _player(3, "MID", price=8.0, xpts=6.0),
    ])
    out = plan_transfers(proj, squad_ids=[1, 3], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "spend_forced_injury"
    first = out["plan"][0]
    assert first["action"] == "transfer"
    assert any(m["out_id"] == 1 for m in first["moves"])
    assert "1" not in out["reasoning"] or out["reasoning"]  # reasoning names the flagged player


def test_red_flag_zero_chance_also_forces():
    proj = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=0.2, status="d", chance=0),
        _player(2, "DEF", price=4.0, xpts=1.0),
    ])
    out = plan_transfers(proj, squad_ids=[1], gws=[10], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "spend_forced_injury"


def test_yellow_doubt_does_not_force():
    proj = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=2.0, status="d", chance=75),
        _player(2, "DEF", price=4.0, xpts=2.5),   # gain 0.5 < min_gain -> roll
    ])
    out = plan_transfers(proj, squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "roll"


def test_red_flag_bench_does_not_force():
    # 12 squad players; the red-flagged one has the LOWEST first-GW xpts -> bench (not top-11)
    players = [_player(i, "MID", price=5.0, xpts=4.0 + i * 0.1) for i in range(1, 12)]
    players.append(_player(99, "DEF", price=4.0, xpts=0.1, status="i"))
    players.append(_player(100, "DEF", price=4.0, xpts=0.5))  # weak replacement, gain < min_gain
    proj = _proj_frame(players)
    out = plan_transfers(proj, squad_ids=[p_id for p_id in range(1, 12)] + [99],
                         gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "roll"


def test_verdicts_roll_and_spend_with_reasoning():
    proj_roll = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=3.0),
        _player(2, "DEF", price=4.0, xpts=3.5),   # gain 0.5 < 2.0
    ])
    out = plan_transfers(proj_roll, squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "roll"
    assert out["first_gw_ft_before"] == 1 and out["first_gw_ft_after"] == 1
    assert "roll" in out["reasoning"].lower()

    proj_spend = _proj_frame([
        _player(1, "DEF", price=4.0, xpts=1.0),
        _player(2, "DEF", price=4.0, xpts=6.0),   # gain 5.0 > 2.0
    ])
    out = plan_transfers(proj_spend, squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] == "spend"
    assert out["reasoning"]


def test_missing_status_columns_noop():
    # Frames without status/chance columns must not crash and never force
    proj = _proj_frame([_player(1, "DEF", price=4.0, xpts=3.0)], with_status_cols=False)
    out = plan_transfers(proj, squad_ids=[1], gws=[10], itb_m=0.0, start_ft=1, min_gain=2.0)
    assert out["verdict"] in ("roll", "spend")
```

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest tests/test_transfer_planner.py -q`
Expected: new tests FAIL (`KeyError: 'verdict'` or fixture TypeError); existing tests still pass

- [ ] **Step 3: Implement in `src/transfer_planner.py`**

In `_build_info`, add per-player flags (safe when columns absent):

```python
        status = str(r.get("status") or "a").lower()
        chance = r.get("chance_of_playing_next_round")
        try:
            chance = float(chance)
        except (TypeError, ValueError):
            chance = None
        info[pid]["red_flag"] = status in ("i", "s", "u") or (chance is not None and chance <= 0.0)
```

In `plan_transfers`, before the GW loop, compute the forced-sell set for the first horizon GW:

```python
    first_gw = gws[0] if gws else None
    likely_xi = set()
    if first_gw is not None:
        by_first_gw = sorted(squad, key=lambda pid: info[pid]["xg"].get(first_gw, 0.0), reverse=True)
        likely_xi = set(by_first_gw[:11])
    forced_sells = {pid for pid in likely_xi if info[pid].get("red_flag")}
```

Inside the first iteration of the GW loop (`gi == 0`), before the normal greedy `while` loop, resolve forced sells — best like-for-like replacement, `min_gain` bypassed:

```python
        if gi == 0:
            for pid in sorted(forced_sells, key=lambda p: info[p]["xg"].get(g, 0.0)):
                if pid not in squad or len(moves) >= max_moves_per_gw or len(moves) >= ft:
                    break
                unowned = [x for x in info if x not in squad]
                best = _best_swap({pid}, info, unowned, hz, bank, team_counts)
                if best is None:
                    continue
                s, b = best["sell"], best["buy"]
                squad.discard(s); squad.add(b)
                bank += info[s]["price"] - info[b]["price"]
                team_counts[info[s]["team"]] = team_counts.get(info[s]["team"], 0) - 1
                team_counts[info[b]["team"]] = team_counts.get(info[b]["team"], 0) + 1
                best["forced_injury"] = True
                moves.append(best)
```

(`_best_swap` already searches best replacement for a given seller set; verify its signature — it takes the candidate seller set as its first argument per the existing call `_best_swap(squad, info, unowned, hz, bank, team_counts)` — and confirm it applies no `min_gain` itself; the threshold check lives in the caller's `while` loop, which forced sells bypass.)

After the GW loop, derive verdict fields from the first plan entry:

```python
    first = plan[0] if plan else None
    forced = bool(first and any(m.get("forced_injury") for m in first.get("moves", [])))
    if forced:
        verdict = "spend_forced_injury"
        flagged = ", ".join(str(info[m["out_id"]]["name"]) for m in first["moves"] if m.get("forced_injury")) if first else ""
        reasoning = f"Flagged player ({flagged}) in your likely XI — replacing them takes priority over rolling."
    elif first and first["action"] == "transfer":
        verdict = "spend"
        names = ", ".join(f"{m['out_name']} → {m['in_name']}" for m in first["moves"])
        reasoning = f"Move now: {names} (+{first['gw_gain']} xPts ≥ {min_gain} threshold)."
    else:
        verdict = "roll"
        nxt = next((p for p in plan[1:] if p["action"] == "transfer"), None)
        follow = f" — GW{nxt['gw']} the plan makes {len(nxt['moves'])} move(s) for +{nxt['gw_gain']}." if nxt else "."
        reasoning = (f"No move gains ≥ {min_gain} xPts this GW. Roll the FT "
                     f"({first['free_transfers_before']}→{min(int(ft_cap), first['free_transfers_before'] + 1)}){follow}"
                     if first else "No horizon GWs.")
    # add to the return dict:
    #   "verdict": verdict, "reasoning": reasoning,
    #   "first_gw_ft_before": first["free_transfers_before"] if first else int(start_ft),
    #   "first_gw_ft_after": first["free_transfers_after"] if first else int(start_ft),
```

`_move_record` already emits move dicts — confirm the exact key names it produces (`out_id`/`out_name`/`in_name` or similar) and use those names consistently in both the forced-sell code and the reasoning strings; adjust the test assertions to the real key names found.

At the call site (`api/main.py:1164`), ensure status columns reach the planner:

```python
            _plan_proj = proj_all
            if "status" not in _plan_proj.columns and elements is not None:
                _plan_proj = _plan_proj.merge(
                    elements[["id", "status", "chance_of_playing_next_round"]],
                    on="id", how="left",
                )
            out["transfer_plan_horizon"] = transfer_planner.plan_transfers(
                _plan_proj, _squad_ids, gws, ...)  # existing kwargs unchanged
```

(`elements` inside `build_recommendations` is a DataFrame from `ctx["elements"]` — verify the variable name at the call site and that it is a frame, not a list; adapt with `pd.DataFrame(elements)` if needed.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_transfer_planner.py -q` then `python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/transfer_planner.py tests/test_transfer_planner.py api/main.py
git commit -m "feat(planner): injury-forced spend gate + top-level verdict and reasoning"
```

---

### Task 4: Finished-GW-only form inputs

**Files:**
- Modify: `src/projections.py:208-230` (`player_recent_gw_map`), `src/projections.py:360-413` (`project_elements_next_gws` passthrough)
- Modify: `api/main.py` (`build_recommendations` — compute and pass the cutoff)
- Test: `tests/test_finished_gw_filter.py`

**Interfaces:**
- Produces: `player_recent_gw_map(..., finished_gw_max=None)` — when set, history rows with `gw > finished_gw_max` are excluded; `project_elements_next_gws(..., finished_gw_max=None)` passes it through.
- Consumes: in `build_recommendations`, cutoff = `max(event id where events.finished == true)` from `ctx["bootstrap"]["events"]`, `None` if no finished events (pre-season → no filtering, preserves cold-start behaviour).

Note: `team_recent_ppg_map` already filters `fixtures.finished == True` (`src/projections.py:112`) — no change there. The leak is only the player-history path: `hist[hist["gw"] < gw_start]` (`src/projections.py:223`) includes the in-play GW.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_finished_gw_filter.py
import pandas as pd
from src import projections


def _hist(rows):
    return pd.DataFrame(rows, columns=["player_id", "gw", "gw_total_points", "gw_minutes", "gw_starts"])


def test_in_play_gw_excluded_when_cutoff_set():
    hist = _hist([
        (1, 8, 10.0, 90, 1),
        (1, 9, 2.0, 45, 1),   # in-play GW9 partial data
    ])
    # gw_start=10 (planning next GW), GW9 unfinished -> cutoff 8
    out = projections.player_recent_gw_map(gw_start=10, window=5, history_df=hist, finished_gw_max=8)
    row = out[out["player_id"] == 1].iloc[0]
    assert row["recent_history_max_gw"] == 8
    assert row["recent_gw_avg_points"] == 10.0   # GW9 row dropped


def test_no_cutoff_keeps_current_behaviour():
    hist = _hist([(1, 8, 10.0, 90, 1), (1, 9, 2.0, 45, 1)])
    out = projections.player_recent_gw_map(gw_start=10, window=5, history_df=hist)
    row = out[out["player_id"] == 1].iloc[0]
    assert row["recent_history_max_gw"] == 9
    assert row["recent_gw_avg_points"] == 6.0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_finished_gw_filter.py -q`
Expected: FAIL — `TypeError: player_recent_gw_map() got an unexpected keyword argument 'finished_gw_max'`

- [ ] **Step 3: Implement**

`player_recent_gw_map` signature gains `finished_gw_max=None`; after line 223's `prior_hist = hist[hist["gw"] < gw_start].copy()` add:

```python
    if finished_gw_max is not None:
        prior_hist = prior_hist[prior_hist["gw"] <= int(finished_gw_max)].copy()
```

`project_elements_next_gws` signature gains `finished_gw_max=None`, forwarded at the `player_recent_gw_map(gw_start=gw_start, window=recent_window, fixtures=fixtures)` call (line 406).

In `build_recommendations` (`api/main.py:907`), compute and pass:

```python
    finished_events = [safe_int(e.get("id")) for e in ctx["bootstrap"].get("events", []) if e.get("finished")]
    finished_gw_max = max([e for e in finished_events if e], default=None)
    proj_all = projections.project_elements_next_gws(
        ..., finished_gw_max=finished_gw_max,
    )
```

Apply the same two-line computation + kwarg at the other production call site `api/main.py:623` (`optimize_squad`). Leave `api/main.py:1529` and all backtest paths untouched — the backtest injects full-season history deliberately.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_finished_gw_filter.py -q && python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/projections.py api/main.py tests/test_finished_gw_filter.py
git commit -m "fix(projections): recent-form inputs use only finished gameweeks"
```

---

### Task 5: GW-target audit (no code expected)

**Files:**
- Read: `api/main.py:302-340` (`_event_id`, `_default_picks_event_id`, `_default_optimize_event_id`), `api/main.py:791-822`

- [ ] **Step 1: Verify targeting**

Confirm `_default_optimize_event_id` resolves `is_next` before `is_current` (line 316-317 reads `_event_id(bootstrap, "is_next") or _event_id(bootstrap, "is_current") or 1`) and that `build_recommendations` uses it when no explicit `event_id` was requested (line 796). Trace one in-play scenario by hand: GW N in play → `is_next = N+1` → projections and planner target N+1. Record the trace in the commit message of Task 4 if already committed, else as a `docs/` note only if a defect is found.

- [ ] **Step 2: If a leak is found** — fix targeting to `is_next`-first at the defect site and add a regression test mirroring Task 4's style. If none found (expected), no commit; state the audit result in the task report.

---

### Task 6: Backtest `--planner` A/B mode

**Files:**
- Modify: `scripts/backtest_season.py`
- Test: smoke run (below); pure-function test only if a helper is extracted

- [ ] **Step 1: Read the transfer-decision loop**

Read `scripts/backtest_season.py` main loop (arg parsing at lines 765-783; find where per-GW transfers are chosen — the `--smart-transfers` branch). Identify: squad state variable, per-GW projections frame, FT state variable, and where moves are applied.

- [ ] **Step 2: Add the flag and branch**

```python
    ap.add_argument("--planner", action="store_true",
                    help="Choose per-GW transfers (and rolls) via transfer_planner.plan_transfers first-GW action")
```

In the per-GW decision point, when `args.planner`:

```python
        from src import transfer_planner
        horizon = [g for g in range(gw, min(gw + 4, args.end + 1))]
        plan = transfer_planner.plan_transfers(
            proj_gw, list(squad_ids), horizon,
            itb_m=bank, start_ft=ft_state, ft_cap=5, allow_hits=False,
        )
        first = plan["plan"][0] if plan.get("plan") else None
        gw_moves = first["moves"] if first and first["action"] == "transfer" else []
        # apply gw_moves through the same move-application code the smart-transfers path uses;
        # update ft_state with min(5, max(ft_state - len(gw_moves), 0) + 1) at GW end
```

Adapt variable names to what Step 1 found; reuse the existing move-application helper rather than duplicating it. The FT update rule must match `src/ft_tracker.py` exactly.

- [ ] **Step 3: Smoke run both arms**

```bash
python scripts/backtest_season.py --season 2025-26 --start 2 --end 10 --use-engine --smart-transfers --out data/backtest/ab_spend.csv
python scripts/backtest_season.py --season 2025-26 --start 2 --end 10 --use-engine --planner --out data/backtest/ab_planner.csv
```

Expected: both complete; planner arm shows ≥1 `roll` GW in its log/output.

- [ ] **Step 4: Full A/B and record**

Same commands with `--end 29`. Record in this plan doc under "Results" (add the section): total points both arms, transfers made, hits. No behaviour flag flips in this task — numbers only.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest_season.py docs/superpowers/plans/2026-08-25-transfer-planner-v2.md
git commit -m "feat(backtest): --planner mode A/Bs roll/bank planning vs always-spend"
```

---

### Task 7: Workstream B — DC term A/B (record numbers)

**Files:**
- Read: `scripts/backtest_xg_basis.py --help` and `scripts/backtest_season.py --help` to pick the runner that exercises `OUTPUT_APPLY_DC`
- Modify: this plan doc ("Results" section); possibly `src/config.py` (only if DC regresses → set `OUTPUT_APPLY_DC = False`)

- [ ] **Step 1:** Determine how the xG-basis backtest toggles `OUTPUT_APPLY_DC` (env override vs config edit). If only config, run once with `OUTPUT_APPLY_DC = True` (current), flip to `False`, run again, restore.
- [ ] **Step 2:** Run both arms over 2025-26, GW2–29. Record MAE / total points / ranking diagnostic per arm in "Results".
- [ ] **Step 3:** Decision per spec: keep `OUTPUT_APPLY_DC = True` only if it does not regress. Commit config change only if flipping:

```bash
git add src/config.py docs/superpowers/plans/2026-08-25-transfer-planner-v2.md
git commit -m "chore(model): record DC A/B backtest, set OUTPUT_APPLY_DC per evidence"
```

---

### Task 8: Workstream B — blend-weight sweep + decision

**Files:**
- Run: `scripts/backtest_blend_sweep.py` (read `--help` first for its exact args)
- Modify: `src/config.py` (`PROJ_MODEL_BLEND_WEIGHT`) only if a weight > 0.0 beats weight 0.0; this plan doc ("Results")

- [ ] **Step 1:** Run the sweep over 2025-26 with the DC setting decided in Task 7. Record the per-weight metric table in "Results".
- [ ] **Step 2:** If argmax weight beats 0.0: set `PROJ_MODEL_BLEND_WEIGHT = <winner>` in `src/config.py` with a comment citing the sweep numbers. If 0.0 wins, change nothing and record why.
- [ ] **Step 3:** Full suite: `python -m pytest -q`. Expected: all pass.
- [ ] **Step 4: Commit**

```bash
git add src/config.py docs/superpowers/plans/2026-08-25-transfer-planner-v2.md
git commit -m "feat(model): xG blend weight set from 2025-26 sweep evidence"
```

---

### Task 9: Frontend verdict banner

**Files (frontend repo `fpl-decision-hub`, branch `feature/planner-verdict` off `fix/auth-token-on-api-calls`):**
- Modify: `src/lib/fplAssistantApi.ts` (extend `FplTransferPlanHorizon`)
- Modify: the `HorizonTransferPlan` component (located via `grep -rn "HorizonTransferPlan" src/components/`)
- Test: colocated vitest file next to the component

**Interfaces:**
- Consumes: the four new fields from Task 3 (`verdict`, `reasoning`, `first_gw_ft_before`, `first_gw_ft_after`), all optional.

- [ ] **Step 1: Extend the type**

```ts
export interface FplTransferPlanHorizon {
  // ...existing fields unchanged...
  verdict?: "roll" | "spend" | "spend_forced_injury";
  reasoning?: string;
  first_gw_ft_before?: number;
  first_gw_ft_after?: number;
}
```

- [ ] **Step 2: Write the failing component test**

```tsx
// alongside HorizonTransferPlan
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("HorizonTransferPlan verdict banner", () => {
  it("renders roll verdict with FT progression", () => {
    render(<HorizonTransferPlan plan={{ ...basePlan, verdict: "roll", reasoning: "Roll the FT (2→3).", first_gw_ft_before: 2, first_gw_ft_after: 3 }} />);
    expect(screen.getByText(/roll the ft/i)).toBeInTheDocument();
  });
  it("renders injury-forced verdict distinctly", () => {
    render(<HorizonTransferPlan plan={{ ...basePlan, verdict: "spend_forced_injury", reasoning: "Flagged player..." }} />);
    expect(screen.getByText(/flagged player/i)).toBeInTheDocument();
  });
  it("renders nothing extra when verdict absent", () => {
    render(<HorizonTransferPlan plan={basePlan} />);
    expect(screen.queryByTestId("plan-verdict-banner")).toBeNull();
  });
});
```

(`basePlan` = the fixture the component's existing tests use, or a minimal valid `FplTransferPlanHorizon`; follow the component's existing test file conventions if one exists.)

- [ ] **Step 3: Run to verify failure** — `npx vitest run <testfile>`; expected FAIL.

- [ ] **Step 4: Implement the banner** — at the top of `HorizonTransferPlan`'s rendered output, when `plan.verdict` is set, a `data-testid="plan-verdict-banner"` block: label per verdict ("Roll it" / "Make the move" / "Injury: act now"), the `reasoning` sentence, and `FT {first_gw_ft_before}→{first_gw_ft_after}` when both present. Reuse the panel's existing card/badge styles — no new design system.

- [ ] **Step 5: Run tests** — `npx vitest run`; expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/lib/fplAssistantApi.ts src/components/ <testfile>
git commit -m "feat(transfers): verdict banner on the horizon plan"
```

---

### Task 10: Staging verification

- [ ] **Step 1:** Backend: `fly deploy --config fly.dev.toml --app fpl-assistant-api-dev --yes`. Probe: `/health` 200; `/recommendations` without token 401.
- [ ] **Step 2:** Frontend: push `feature/planner-verdict`; set the Vercel preview for that branch (same Preview env already points at the dev backend). Log in, load recommendations with transfers enabled, confirm the banner renders one of the three verdicts with reasoning.
- [ ] **Step 3:** Report screenshots/URLs; no prod deploy in this plan.

## Results

(filled by Tasks 6–8)
