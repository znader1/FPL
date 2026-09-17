# Chip Planner — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing deterministic chip engine (`src/chip_advisor.py`) into a full chip-timing planner — expiry-aware, config-tunable, transfer-plan-aware — exposed via `GET /chips/plan`, grounded into the chat chip agent, and snapshotted to Supabase for a future ML dataset.

**Architecture:** Pure EV functions in `src/chip_advisor.py` (all four chips already scored there) gain expiry windows, config priors, a wildcard baseline that competes against the horizon transfer plan, budget-aware free-hit comparison, a structural zone beyond the model horizon, and a `build_chip_plan()` assembler producing the API payload. A thin new router (`api/chips.py`) reuses `api/chat.py`'s context builder. A new Supabase table `chip_plan_snapshots` mirrors the `player_gw_snapshots` job pattern.

**Tech Stack:** FastAPI, pandas, pytest, Supabase (PostgREST), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-01-chip-planner-design.md` (copied into this repo alongside this plan; canonical copy lives in the frontend repo).

## Global Constraints

- All tunable constants go in `src/config.py`; logic reads them via `getattr(config, "NAME", default)`. Never hardcode numbers in logic files.
- Canonical chip names everywhere in this repo and in API payloads: `wildcard`, `free_hit`, `bench_boost`, `triple_captain`. FPL API names (`freehit`, `bboost`, `3xc`) are normalized at the FPL boundary only.
- API changes are additive — existing endpoint response shapes never change.
- Pure logic separated from I/O so tests run without network (pattern: `scripts/snapshot_to_db.py` + `tests/test_snapshot_db.py`).
- Test command: `python -m pytest tests/test_chip_advisor.py -q` (or the file under test). Full suite `python -m pytest -q` must pass before each commit.
- Dev server: `uvicorn api.main:app --reload --port 8001`.
- Season phase defaults: split at GW19, season ends GW38 — config values, since rules change yearly.

---

### Task 1: Chip windows (availability + expiry) in `src/chip_advisor.py`

**Files:**
- Modify: `src/chip_advisor.py` (add imports + two module-level constants + one function)
- Modify: `api/chat.py:45-84` (`_derive_chips_remaining` delegates to the new function)
- Test: `tests/test_chip_advisor.py` (new file)

**Interfaces:**
- Consumes: nothing new — `chips_played` is the raw `history["chips"]` list from `fpl_client.get_entry_history`, e.g. `[{"name": "bboost", "event": 4, ...}]`.
- Produces: `chip_windows(chips_played, current_gw, phase_split_gw=None, season_end_gw=None) -> dict[str, dict]` returning `{chip: {"available": bool, "half": 1|2, "expires_gw": int}}` for all four canonical chips. Also module constants `ALL_CHIPS: list[str]` and `FPL_CHIP_NAME_MAP: dict[str, str]`. Tasks 4, 5, 8 consume `chip_windows`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chip_advisor.py`:

```python
from src.chip_advisor import chip_windows


def test_chip_windows_all_available_when_none_played():
    w = chip_windows([], current_gw=5)
    assert set(w) == {"wildcard", "free_hit", "bench_boost", "triple_captain"}
    assert all(v["available"] for v in w.values())
    assert all(v["half"] == 1 and v["expires_gw"] == 19 for v in w.values())


def test_chip_windows_played_chip_unavailable_in_phase():
    played = [{"name": "bboost", "event": 4}]
    w = chip_windows(played, current_gw=6)
    assert w["bench_boost"]["available"] is False
    assert w["wildcard"]["available"] is True


def test_chip_windows_phase1_play_resets_in_phase2():
    played = [{"name": "3xc", "event": 10}]
    w = chip_windows(played, current_gw=25)
    assert w["triple_captain"]["available"] is True
    assert w["triple_captain"]["half"] == 2
    assert w["triple_captain"]["expires_gw"] == 38


def test_chip_windows_current_gw_play_still_counts_as_available():
    # Advising FOR current_gw: a chip logged in current_gw isn't "gone" yet
    # (mirrors the strictly-before rule in the old _derive_chips_remaining).
    played = [{"name": "wildcard", "event": 7}]
    w = chip_windows(played, current_gw=7)
    assert w["wildcard"]["available"] is True


def test_chip_windows_normalizes_fpl_names():
    played = [{"name": "freehit", "event": 3}, {"name": "BBOOST", "event": 4}]
    w = chip_windows(played, current_gw=8)
    assert w["free_hit"]["available"] is False
    assert w["bench_boost"]["available"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: FAIL with `ImportError: cannot import name 'chip_windows'`

- [ ] **Step 3: Implement `chip_windows`**

In `src/chip_advisor.py`, add below the existing imports (`from src import config` goes with the imports at the top):

```python
from src import config

ALL_CHIPS = ["wildcard", "free_hit", "bench_boost", "triple_captain"]

# FPL API chip identifiers → canonical names used throughout this repo.
FPL_CHIP_NAME_MAP = {
    "wildcard": "wildcard",
    "freehit": "free_hit",
    "bboost": "bench_boost",
    "3xc": "triple_captain",
}


def chip_windows(chips_played, current_gw, phase_split_gw=None, season_end_gw=None):
    """Availability + expiry per chip, honoring the two-per-season phase rule.

    chips_played: raw `history["chips"]` list from the FPL entry history API.
    A chip logged in current_gw itself still counts as available — we advise
    FOR current_gw, so only strictly-earlier plays consume the chip.
    """
    split = int(phase_split_gw or getattr(config, "CHIP_PLAN_PHASE_SPLIT_GW", 19))
    end = int(season_end_gw or getattr(config, "CHIP_PLAN_SEASON_END_GW", 38))
    current_gw = int(current_gw)
    in_phase_1 = current_gw <= split
    lo, hi = (1, split) if in_phase_1 else (split + 1, end)

    used = set()
    for c in chips_played or []:
        gw = int(c.get("event", 0) or 0)
        name = FPL_CHIP_NAME_MAP.get(str(c.get("name", "")).lower())
        if name and lo <= gw <= hi and gw < current_gw:
            used.add(name)

    return {
        chip: {
            "available": chip not in used,
            "half": 1 if in_phase_1 else 2,
            "expires_gw": hi,
        }
        for chip in ALL_CHIPS
    }
```

Add to `src/config.py` under the existing "Chip strategy tuning" section:

```python
# -----------------------------
# Chip plan tuning (src/chip_advisor.py — chip timing planner)
# -----------------------------
CHIP_PLAN_PHASE_SPLIT_GW = 19   # last GW of the first-half chip set
CHIP_PLAN_SEASON_END_GW = 38
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: 5 passed

- [ ] **Step 5: Delegate `_derive_chips_remaining` to `chip_windows`**

In `api/chat.py`, replace the body of `_derive_chips_remaining` (keep the signature and docstring):

```python
def _derive_chips_remaining(entry_id: int, current_gw: int) -> list[str]:
    """
    Returns the list of chip types still available, taking Phase 1/2 into account.
    2025/26: 2 of each chip — Phase 1 (GW1-19), Phase 2 (GW20-38).
    """
    from src import fpl_client
    from src.chip_advisor import chip_windows, ALL_CHIPS

    try:
        history = fpl_client.get_entry_history(entry_id)
    except Exception:
        # On failure, assume all chips remaining (safe default)
        return sorted(ALL_CHIPS)

    windows = chip_windows(history.get("chips"), current_gw)
    return sorted(c for c, w in windows.items() if w["available"])
```

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest -q`
Expected: all pass (no existing test covers `_derive_chips_remaining` directly; the suite guards against import breakage).

```bash
git add src/chip_advisor.py src/config.py api/chat.py tests/test_chip_advisor.py
git commit -m "feat(chips): expiry-aware chip windows with phase 1/2 rule"
```

---

### Task 2: Real per-team fixture counts (DGW/BGW detection)

**Files:**
- Modify: `src/chip_advisor.py` (one function)
- Modify: `api/chat.py:158-168` (`_build_context_for_entry` market build — replace hardcoded `"fixture_count": 1`)
- Test: `tests/test_chip_advisor.py`

**Interfaces:**
- Consumes: fixtures DataFrame from `transforms.fixtures_df` (columns include `event: int`, `team_h: int`, `team_a: int`).
- Produces: `team_fixture_counts(fixtures, gw) -> dict[int, int]` mapping team id → number of fixtures in `gw` (absent team id = blank). Tasks 5 (structural zone) and the context builder consume it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chip_advisor.py`:

```python
import pandas as pd

from src.chip_advisor import team_fixture_counts


def _fixtures(rows):
    return pd.DataFrame(rows, columns=["event", "team_h", "team_a"])


def test_team_fixture_counts_single_and_double():
    fx = _fixtures([
        (12, 1, 2),
        (12, 1, 3),   # team 1 doubles in GW12
        (13, 2, 3),
    ])
    counts = team_fixture_counts(fx, 12)
    assert counts == {1: 2, 2: 1, 3: 1}


def test_team_fixture_counts_blank_gw_team_absent():
    fx = _fixtures([(12, 1, 2)])
    counts = team_fixture_counts(fx, 12)
    assert 3 not in counts
    assert counts.get(3, 0) == 0


def test_team_fixture_counts_empty_fixtures():
    assert team_fixture_counts(pd.DataFrame(columns=["event", "team_h", "team_a"]), 5) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: FAIL with `ImportError: cannot import name 'team_fixture_counts'`

- [ ] **Step 3: Implement `team_fixture_counts`**

In `src/chip_advisor.py`:

```python
def team_fixture_counts(fixtures, gw):
    """Team id → fixture count in `gw`. Missing id means a blank GW for that team."""
    if fixtures is None or fixtures.empty or "event" not in fixtures.columns:
        return {}
    f = fixtures[fixtures["event"] == int(gw)]
    counts: dict[int, int] = {}
    for col in ("team_h", "team_a"):
        if col not in f.columns:
            continue
        for t in f[col].dropna().tolist():
            counts[int(t)] = counts.get(int(t), 0) + 1
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: all pass

- [ ] **Step 5: Wire real counts into the chat context builder**

In `api/chat.py` `_build_context_for_entry`, the per-GW market build currently sets `"fixture_count": 1`. Replace that loop body:

```python
    from src.chip_advisor import team_fixture_counts

    gw_projections = {}
    for g in range(current_gw, current_gw + horizon):
        col = f"xpts_gw{g}"
        if col not in proj.columns:
            continue
        counts = team_fixture_counts(fixtures, g)
        team_ids = pd.to_numeric(proj["team"], errors="coerce")
        market_g = pd.DataFrame({
            "player_id": proj["id"].astype(int).values,
            "name": proj["web_name"].values,
            "pos": (proj["pos"] if "pos" in proj.columns
                    else proj["element_type"].map(pos_map)).values,
            "team": proj["team"].map(team_name_map).values,
            "price_m": (pd.to_numeric(proj["now_cost"], errors="coerce") / 10.0).values,
            "xpts": pd.to_numeric(proj[col], errors="coerce").fillna(0).values,
            "fixture_count": team_ids.map(lambda t: counts.get(int(t), 0) if pd.notna(t) else 0).values,
        })
        gw_projections[g] = market_g
```

(Note: `proj["team"]` here is still the numeric team id — the name mapping happens in the same statement for the `team` column, so the id series must be captured before/independently, as above.)

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest -q`
Expected: all pass

```bash
git add src/chip_advisor.py api/chat.py tests/test_chip_advisor.py
git commit -m "feat(chips): real per-team fixture counts — DGW/BGW detection works"
```

---

### Task 3: Config priors — min-EV thresholds + expiry urgency ramp

**Files:**
- Modify: `src/config.py`
- Modify: `src/chip_advisor.py` (one function)
- Test: `tests/test_chip_advisor.py`

**Interfaces:**
- Produces: `effective_min_ev(chip, target_gw, expires_gw) -> float` — the play/hold threshold for a chip at a candidate GW, decaying linearly to 0 inside the expiry ramp. Task 4 consumes it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chip_advisor.py`:

```python
from src.chip_advisor import effective_min_ev


def test_effective_min_ev_full_far_from_expiry():
    # bench_boost base threshold is 5.0; GW5 vs expiry GW19 is outside the ramp
    assert effective_min_ev("bench_boost", target_gw=5, expires_gw=19) == 5.0


def test_effective_min_ev_decays_inside_ramp():
    # ramp is 5 GWs: at 2 GWs left the threshold is base * 2/5
    v = effective_min_ev("bench_boost", target_gw=17, expires_gw=19)
    assert abs(v - 5.0 * 2 / 5) < 1e-9


def test_effective_min_ev_zero_at_expiry_gw():
    assert effective_min_ev("triple_captain", target_gw=19, expires_gw=19) == 0.0


def test_effective_min_ev_monotonic_toward_expiry():
    vals = [effective_min_ev("wildcard", target_gw=g, expires_gw=19) for g in range(13, 20)]
    assert all(a >= b for a, b in zip(vals, vals[1:]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: FAIL with `ImportError: cannot import name 'effective_min_ev'`

- [ ] **Step 3: Add config values and implement**

In `src/config.py`, extend the chip plan block:

```python
CHIP_PLAN_HORIZON_GWS = 8       # model zone: full EV math over this many GWs
CHIP_PLAN_MIN_EV = {            # below this, "hold" beats playing the chip
    "triple_captain": 3.0,
    "bench_boost": 5.0,
    "free_hit": 8.0,
    "wildcard": 6.0,
}
CHIP_PLAN_EXPIRY_RAMP_GWS = 5   # threshold decays linearly to 0 over the last N GWs
CHIP_PLAN_NUDGE_MIN_EV = 4.0    # floor for the next-GW nudge surface
```

In `src/chip_advisor.py`:

```python
def effective_min_ev(chip, target_gw, expires_gw):
    """Play/hold threshold for `chip` at `target_gw`, with use-it-or-lose-it decay.

    Outside the ramp the base threshold applies; inside the last
    CHIP_PLAN_EXPIRY_RAMP_GWS gameweeks before expiry it decays linearly to 0,
    so a modest-EV chip gets recommended rather than expiring unused.
    """
    base = float(getattr(config, "CHIP_PLAN_MIN_EV", {}).get(chip, 0.0))
    ramp = int(getattr(config, "CHIP_PLAN_EXPIRY_RAMP_GWS", 5))
    gws_left = max(0, int(expires_gw) - int(target_gw))
    if ramp <= 0 or gws_left >= ramp:
        return base
    return base * gws_left / ramp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/chip_advisor.py tests/test_chip_advisor.py
git commit -m "feat(chips): config-tunable min-EV thresholds with expiry urgency ramp"
```

---

### Task 4: Wildcard vs transfer plan + budget-aware free hit

**Files:**
- Modify: `src/chip_advisor.py` (`score_wildcard` gains a baseline adjustment; `score_free_hit` gains a budget-aware comparison)
- Test: `tests/test_chip_advisor.py`

**Interfaces:**
- Consumes: `transfer_plan` — the dict returned by `src/transfer_planner.plan_transfers` (uses only `total_net_gain: float`). `optimizer.build_chip_squad(elements_all, score_col, budget_m)` → `{"ok": bool, "squad_df": DataFrame | None, ...}`.
- Produces: `score_wildcard(squad, gw_projections, candidate_gws, horizon=4, transfer_plan_net_gain=0.0)` — same return type, EV now net of what ordinary planned transfers would already capture. `score_free_hit(squad, gw_projections, candidate_gws, budget_m)` — unchanged signature, better comparison squad. Task 5 consumes both via `recommend_chips`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chip_advisor.py`:

```python
from src.chip_advisor import score_free_hit, score_wildcard


def _market(players):
    """players: list of (player_id, name, pos, team, price_m, xpts, fixture_count)."""
    return pd.DataFrame(
        players,
        columns=["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"],
    )


def _squad_15(prefix="own", xpts=2.0):
    rows, pid = [], 1
    for pos, n in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for i in range(n):
            rows.append((pid, f"{prefix}{pid}", pos, f"T{pid % 10}", 5.0, xpts, 1))
            pid += 1
    return _market(rows)


def test_score_wildcard_net_of_transfer_plan_gain():
    squad = _squad_15(xpts=2.0)
    # Market of stars the squad doesn't own: big raw uplift
    stars = _squad_15(prefix="star", xpts=6.0)
    stars["player_id"] = stars["player_id"] + 100
    market = pd.concat([squad[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"]], stars])
    gw_projections = {5: market, 6: market, 7: market, 8: market}

    raw = score_wildcard(squad[["player_id", "name", "pos", "team", "price_m"]],
                         gw_projections, [5], horizon=4)
    net = score_wildcard(squad[["player_id", "name", "pos", "team", "price_m"]],
                         gw_projections, [5], horizon=4, transfer_plan_net_gain=10.0)
    assert raw and net
    assert abs(raw[0].expected_value - net[0].expected_value - 10.0) < 1e-6


def test_score_free_hit_respects_budget():
    squad = _squad_15(xpts=2.0)
    # Unaffordable stars: price 15.0m each, budget only allows the cheap pool
    stars = _squad_15(prefix="star", xpts=9.0)
    stars["player_id"] = stars["player_id"] + 100
    stars["price_m"] = 15.0
    market = pd.concat([squad[["player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"]], stars])
    gw_projections = {5: market}

    recs = score_free_hit(squad[["player_id", "name", "pos", "team", "price_m"]],
                          gw_projections, [5], budget_m=80.0)
    # With an 80m budget nothing beats the (identical) cheap pool → no uplift
    assert recs == [] or recs[0].expected_value < 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: FAIL — `score_wildcard() got an unexpected keyword argument 'transfer_plan_net_gain'`, and the FH test fails because the budget is ignored (stars inflate the uplift).

- [ ] **Step 3: Implement both changes**

In `src/chip_advisor.py`:

`score_wildcard` — add the parameter and subtract the baseline improvement (the wildcard must beat what ordinary transfers would already achieve, not a frozen squad):

```python
def score_wildcard(
    squad: pd.DataFrame,
    gw_projections: dict[int, pd.DataFrame],
    candidate_gws: list[int],
    horizon: int = 4,
    transfer_plan_net_gain: float = 0.0,
) -> list[ChipRecommendation]:
```

Inside the loop, after `uplift = max(0, wc_total - normal_total)`:

```python
        # The no-chip baseline isn't a frozen squad — the horizon transfer plan
        # already improves it. Wildcard EV is net of that improvement.
        plan_gain = max(0.0, float(transfer_plan_net_gain))
        uplift = max(0.0, uplift - plan_gain)
```

And extend the reasoning list:

```python
        if plan_gain > 0:
            reasoning.append(
                f"Net of +{plan_gain:.0f} xPts the normal transfer plan already captures"
            )
```

`score_free_hit` — replace the "top players ignoring budget" proxy with `optimizer.build_chip_squad`, falling back to the old proxy when the optimizer can't build (missing columns, thin market):

```python
        # Best FH squad within budget (squad value + bank). Falls back to the
        # unbudgeted proxy only if the optimizer can't build a legal squad.
        from src import optimizer as _optimizer
        fh_xi_xpts = None
        try:
            built = _optimizer.build_chip_squad(market, score_col="xpts", budget_m=budget_m)
            if built.get("ok") and built.get("squad_df") is not None:
                fh_xi = _pick_best_xi(built["squad_df"])
                fh_xi_xpts = float(fh_xi["xpts"].sum())
        except Exception:
            fh_xi_xpts = None
        if fh_xi_xpts is None:
            market_with_xi = _pick_best_xi(market)
            fh_xi_xpts = float(market_with_xi["xpts"].sum())
```

In `recommend_chips`, pass the new arguments through:

```python
    if "free_hit" in chips_remaining:
        all_recs.extend(score_free_hit(squad, gw_projections, candidate_gws, bank_m))
    if "wildcard" in chips_remaining:
        all_recs.extend(score_wildcard(
            squad, gw_projections, candidate_gws,
            horizon=int(getattr(config, "CHIP_WILDCARD_DEFAULT_HORIZON_GWS", 4)),
            transfer_plan_net_gain=transfer_plan_net_gain,
        ))
```

and add `transfer_plan_net_gain: float = 0.0` to `recommend_chips`'s signature. `score_free_hit`'s `budget_m` caller passes squad value + bank (Task 5 does this; `bank_m` alone remains the default here).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: all pass. If `build_chip_squad` needs a column the market fixture lacks, the fallback keeps the old behavior — the FH test then needs the market to satisfy `_prepare_chip_market` (it requires `pos`, `price_m`, and the score col, which the fixture has).

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest -q`
Expected: all pass (backtest scripts call `recommend_chips`/`score_wildcard` positionally — new kwargs have defaults, nothing breaks).

```bash
git add src/chip_advisor.py tests/test_chip_advisor.py
git commit -m "feat(chips): wildcard EV net of transfer plan; budget-aware free hit"
```

---

### Task 5: `build_chip_plan` — curves, structural zone, nudge, assembly

**Files:**
- Modify: `src/chip_advisor.py` (one top-level function)
- Test: `tests/test_chip_advisor.py`

**Interfaces:**
- Consumes: `chip_windows`, `recommend_chips`, `effective_min_ev`, `team_fixture_counts` (Tasks 1–4).
- Produces: `build_chip_plan(squad, current_gw, gw_projections, chips_played, itb_m=0.0, fixtures=None, transfer_plan=None, horizon_gws=None) -> dict` — the exact `/chips/plan` payload body (everything except `entry_id`). Tasks 6, 8, and the chat agent (Task 7) consume it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chip_advisor.py`:

```python
from src.chip_advisor import build_chip_plan


def _gw_projections_with_dgw(gws, dgw_gw, dgw_team="T1"):
    """Own squad (cheap) + a market; on dgw_gw players of dgw_team get fixture_count 2 and 2x xpts."""
    out = {}
    for g in gws:
        m = _squad_15(xpts=3.0)
        if g == dgw_gw:
            mask = m["team"] == dgw_team
            m.loc[mask, "fixture_count"] = 2
            m.loc[mask, "xpts"] = 6.0
        out[g] = m
    return out


def test_build_chip_plan_shape_and_keys():
    gws = [5, 6, 7, 8]
    plan = build_chip_plan(
        squad=_squad_15()[["player_id", "name", "pos", "team", "price_m"]],
        current_gw=5,
        gw_projections=_gw_projections_with_dgw(gws, dgw_gw=6),
        chips_played=[],
        horizon_gws=4,
    )
    assert set(plan) >= {"current_gw", "chips_remaining", "horizon_model_gws",
                         "recommendations", "nudge", "transfer_context"}
    assert plan["current_gw"] == 5
    names = {c["name"] for c in plan["chips_remaining"]}
    assert names == {"wildcard", "free_hit", "bench_boost", "triple_captain"}
    for rec in plan["recommendations"]:
        assert set(rec) >= {"chip", "event_id", "ev_gain", "provisional", "reasons", "ev_curve"}


def test_build_chip_plan_played_chip_absent_from_recommendations():
    gws = [5, 6, 7, 8]
    plan = build_chip_plan(
        squad=_squad_15()[["player_id", "name", "pos", "team", "price_m"]],
        current_gw=5,
        gw_projections=_gw_projections_with_dgw(gws, dgw_gw=6),
        chips_played=[{"name": "bboost", "event": 3}],
        horizon_gws=4,
    )
    assert all(r["chip"] != "bench_boost" for r in plan["recommendations"])
    bb = next(c for c in plan["chips_remaining"] if c["name"] == "bench_boost")
    assert bb["available"] is False


def test_build_chip_plan_structural_dgw_beyond_horizon_is_provisional():
    fx = _fixtures([(30, 1, 2), (30, 1, 3)])  # team 1 doubles in GW30, far beyond model zone
    plan = build_chip_plan(
        squad=_squad_15()[["player_id", "name", "pos", "team", "price_m"]],
        current_gw=25,
        gw_projections=_gw_projections_with_dgw([25, 26, 27, 28], dgw_gw=None),
        chips_played=[],
        fixtures=fx,
        horizon_gws=4,
    )
    provisional = [r for r in plan["recommendations"] if r["provisional"]]
    assert any(r["event_id"] == 30 for r in provisional)
    assert all(r["ev_gain"] is None for r in provisional)


def test_build_chip_plan_nudge_only_for_current_gw_above_floor():
    gws = [5, 6, 7, 8]
    plan = build_chip_plan(
        squad=_squad_15()[["player_id", "name", "pos", "team", "price_m"]],
        current_gw=5,
        gw_projections=_gw_projections_with_dgw(gws, dgw_gw=7),
        chips_played=[],
        horizon_gws=4,
    )
    if plan["nudge"] is not None:
        assert plan["nudge"]["event_id"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: FAIL with `ImportError: cannot import name 'build_chip_plan'`

- [ ] **Step 3: Implement `build_chip_plan`**

In `src/chip_advisor.py`:

```python
def build_chip_plan(
    squad: pd.DataFrame,
    current_gw: int,
    gw_projections: dict[int, pd.DataFrame],
    chips_played: list[dict],
    itb_m: float = 0.0,
    fixtures: pd.DataFrame | None = None,
    transfer_plan: dict | None = None,
    horizon_gws: int | None = None,
) -> dict:
    """Assemble the full chip plan payload: model-zone EV recommendations,
    structural provisional windows, next-GW nudge, and transfer context."""
    current_gw = int(current_gw)
    horizon = int(horizon_gws or getattr(config, "CHIP_PLAN_HORIZON_GWS", 8))
    windows = chip_windows(chips_played, current_gw)
    remaining = [c for c, w in windows.items() if w["available"]]
    plan_net_gain = float((transfer_plan or {}).get("total_net_gain", 0.0) or 0.0)

    squad_value = float(pd.to_numeric(squad.get("price_m"), errors="coerce").fillna(0).sum())
    budget_m = squad_value + float(itb_m or 0.0)

    all_recs = recommend_chips(
        squad=squad,
        current_gw=current_gw,
        gw_projections=gw_projections,
        chips_remaining=remaining,
        gws_ahead=horizon - 1,
        bank_m=budget_m,
        transfer_plan_net_gain=plan_net_gain,
    )

    recommendations = []
    nudge = None
    nudge_floor = float(getattr(config, "CHIP_PLAN_NUDGE_MIN_EV", 4.0))

    for chip in remaining:
        chip_recs = [r for r in all_recs if r.chip == chip]
        if not chip_recs:
            continue
        expires_gw = windows[chip]["expires_gw"]
        # Model-zone candidates only run to the chip's expiry.
        in_window = [r for r in chip_recs if r.gw <= expires_gw]
        if not in_window:
            continue
        best = max(in_window, key=lambda r: r.expected_value)
        curve = [{"gw": r.gw, "ev": round(float(r.expected_value), 2)}
                 for r in sorted(in_window, key=lambda r: r.gw)]
        if best.expected_value < effective_min_ev(chip, best.gw, expires_gw):
            continue  # hold — nothing in the model zone clears the bar
        rec = {
            "chip": chip,
            "event_id": int(best.gw),
            "ev_gain": round(float(best.expected_value), 2),
            "provisional": False,
            "reasons": list(best.reasoning) + [f"Risk: {r}" for r in best.risks],
            "ev_curve": curve,
        }
        recommendations.append(rec)
        if rec["event_id"] == current_gw and rec["ev_gain"] >= nudge_floor:
            if nudge is None or rec["ev_gain"] > nudge["ev_gain"]:
                nudge = {"chip": chip, "event_id": current_gw, "ev_gain": rec["ev_gain"]}

    # Structural zone: announced DGWs/BGWs beyond the model horizon, up to expiry.
    if fixtures is not None and not fixtures.empty:
        model_end = current_gw + horizon - 1
        season_end = int(getattr(config, "CHIP_PLAN_SEASON_END_GW", 38))
        recommended_chips = {r["chip"] for r in recommendations}
        for g in range(model_end + 1, season_end + 1):
            counts = team_fixture_counts(fixtures, g)
            if not counts:
                continue
            n_teams = len(counts)
            has_dgw = any(v >= 2 for v in counts.values())
            is_blank_heavy = n_teams <= 14  # several teams missing → blank GW
            for chip, wants in (("bench_boost", has_dgw), ("triple_captain", has_dgw),
                                ("free_hit", is_blank_heavy)):
                if not wants or chip not in remaining or chip in recommended_chips:
                    continue
                if g > windows[chip]["expires_gw"]:
                    continue
                label = "double gameweek" if wants is has_dgw and has_dgw else "blank-heavy gameweek"
                recommendations.append({
                    "chip": chip,
                    "event_id": g,
                    "ev_gain": None,
                    "provisional": True,
                    "reasons": [f"GW{g} is a {label} (from announced fixtures) — "
                                f"candidate window, EV computable once in the model horizon"],
                    "ev_curve": [],
                })
                recommended_chips.add(chip)

    return {
        "current_gw": current_gw,
        "chips_remaining": [
            {"name": c, **windows[c]} for c in ALL_CHIPS
        ],
        "horizon_model_gws": horizon,
        "recommendations": recommendations,
        "nudge": nudge,
        "transfer_context": {
            "planned_transfers_net_gain": round(plan_net_gain, 2),
            "wc_alternative_gw": next(
                (r["event_id"] for r in recommendations if r["chip"] == "wildcard"), None),
        },
    }
```

Note the structural `label` line: compute it plainly — `"double gameweek" if has_dgw else "blank-heavy gameweek"` per chip branch (BB/TC branches are DGW-driven, FH is blank-driven); simplify to a literal per branch rather than the awkward conditional shown, e.g. pass the label alongside the flag in the tuple: `(("bench_boost", has_dgw, "double gameweek"), ("triple_captain", has_dgw, "double gameweek"), ("free_hit", is_blank_heavy, "blank-heavy gameweek"))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: all pass

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest -q`

```bash
git add src/chip_advisor.py tests/test_chip_advisor.py
git commit -m "feat(chips): build_chip_plan — EV curves, structural zone, nudge"
```

---

### Task 6: `GET /chips/plan` route

**Files:**
- Create: `api/chips.py`
- Modify: `api/main.py` (include the router, next to the chat router at `api/main.py:78-79`)
- Modify: `api/chat.py` (`_build_context_for_entry` gains `horizon` param and returns `proj` + `fixtures`)
- Test: `tests/test_chips_route.py` (new file)

**Interfaces:**
- Consumes: `_build_context_for_entry(entry_id, current_gw, horizon=5)` (extended here), `fpl_client.get_entry_history`, `transfer_planner.plan_transfers`, `build_chip_plan` (Task 5).
- Produces: `GET /chips/plan?entry_id=<int>&horizon=<int optional>` → `{"entry_id": ..., **build_chip_plan(...)}`, auth'd with the same `require_user` dependency as `/chat`. The frontend consumes this contract.

- [ ] **Step 1: Extend `_build_context_for_entry`**

In `api/chat.py`, change the signature and two lines, and extend the return dict (all existing callers keep working — the new param defaults to the old constant):

```python
def _build_context_for_entry(entry_id: int, current_gw: int, horizon: int = 5):
```

replace `horizon = 5` with `horizon = int(horizon)`, and extend the return:

```python
    return {
        "squad": squad,
        "market": market,
        "starting_xi": starting_xi,
        "gw_projections": gw_projections,
        "bank_m": bank_m,
        "free_transfers": derived_ft,
        "captain_id": captain_id,
        "proj": proj,
        "fixtures": fixtures,
        "teams_short_map": teams_short_map,
    }
```

- [ ] **Step 2: Write the failing route test**

Create `tests/test_chips_route.py`:

```python
import pandas as pd
from fastapi.testclient import TestClient


def _fake_context(entry_id, current_gw, horizon=5):
    rows, pid = [], 1
    for pos, n in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(n):
            rows.append((pid, f"p{pid}", pos, f"T{pid % 5}", 5.0, 3.0, 1))
            pid += 1
    market = pd.DataFrame(rows, columns=[
        "player_id", "name", "pos", "team", "price_m", "xpts", "fixture_count"])
    squad = market[["player_id", "name", "pos", "team", "price_m"]]
    gw_projections = {g: market for g in range(current_gw, current_gw + horizon)}
    proj = pd.DataFrame({
        "id": market["player_id"], "web_name": market["name"], "pos": market["pos"],
        "team_short": market["team"], "price_m": market["price_m"],
        **{f"xpts_gw{g}": market["xpts"] for g in range(current_gw, current_gw + horizon)},
    })
    return {
        "squad": squad, "market": market, "starting_xi": market.head(11),
        "gw_projections": gw_projections, "bank_m": 1.5, "free_transfers": 2,
        "captain_id": 1, "proj": proj,
        "fixtures": pd.DataFrame(columns=["event", "team_h", "team_a"]),
        "teams_short_map": {},
    }


def test_chips_plan_route(monkeypatch):
    from api.main import app
    from api import chips as chips_module

    monkeypatch.setattr(chips_module, "_build_context_for_entry", _fake_context)
    monkeypatch.setattr(chips_module, "_get_entry_chips", lambda entry_id: [])
    monkeypatch.setattr(chips_module, "_resolve_current_gw", lambda: 5)
    app.dependency_overrides = {}
    # require_user is applied at include_router time; override it
    from src.auth import require_user
    app.dependency_overrides[require_user] = lambda: {"sub": "test-user"}

    client = TestClient(app)
    r = client.get("/chips/plan?entry_id=123")
    assert r.status_code == 200
    body = r.json()
    assert body["entry_id"] == 123
    assert body["current_gw"] == 5
    assert {c["name"] for c in body["chips_remaining"]} == {
        "wildcard", "free_hit", "bench_boost", "triple_captain"}
    assert isinstance(body["recommendations"], list)
    app.dependency_overrides = {}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_chips_route.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.chips'`

- [ ] **Step 4: Implement the router**

Create `api/chips.py`:

```python
"""GET /chips/plan — chip timing recommendations over the projection horizon."""
from __future__ import annotations
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.chat import _build_context_for_entry
from src import config, fpl_client, transfer_planner
from src.chip_advisor import build_chip_plan

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_current_gw() -> int:
    """Next unfinished GW from bootstrap events."""
    bootstrap = fpl_client.get_bootstrap()
    for e in bootstrap.get("events", []):
        if e.get("is_next"):
            return int(e["id"])
    for e in bootstrap.get("events", []):
        if not e.get("finished"):
            return int(e["id"])
    raise HTTPException(status_code=503, detail="No upcoming gameweek found")


def _get_entry_chips(entry_id: int) -> list[dict]:
    try:
        history = fpl_client.get_entry_history(entry_id)
        return history.get("chips") or []
    except Exception as e:  # noqa: BLE001 - degrade to "all chips available"
        logger.warning("entry history fetch failed for %s: %s", entry_id, e)
        return []


@router.get("/chips/plan")
def chips_plan(
    entry_id: int = Query(..., ge=1),
    horizon: Optional[int] = Query(None, ge=2, le=12),
):
    current_gw = _resolve_current_gw()
    model_horizon = int(horizon or getattr(config, "CHIP_PLAN_HORIZON_GWS", 8))
    ctx = _build_context_for_entry(entry_id, current_gw, horizon=model_horizon)

    # No-chip baseline: the horizon transfer plan. Planning must never fail the plan.
    transfer_plan = None
    try:
        proj_plan = ctx["proj"].copy()
        gws = sorted(ctx["gw_projections"].keys())
        squad_ids = [int(x) for x in ctx["squad"]["player_id"].tolist()]
        transfer_plan = transfer_planner.plan_transfers(
            proj_plan, squad_ids, gws,
            itb_m=float(ctx["bank_m"]), start_ft=int(ctx["free_transfers"]),
            ft_cap=5, allow_hits=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("transfer plan baseline failed: %s", e)

    plan = build_chip_plan(
        squad=ctx["squad"],
        current_gw=current_gw,
        gw_projections=ctx["gw_projections"],
        chips_played=_get_entry_chips(entry_id),
        itb_m=float(ctx["bank_m"]),
        fixtures=ctx.get("fixtures"),
        transfer_plan=transfer_plan,
        horizon_gws=model_horizon,
    )
    return {"entry_id": entry_id, **plan}
```

Note `plan_transfers`'s `proj` needs `price_m`/`team_short`/`pos` columns; `_build_context_for_entry`'s `proj` comes straight from `project_elements_next_gws`. Mirror `api/main.py:1380-1395`'s defensive pattern before the call:

```python
        import pandas as pd
        if "price_m" not in proj_plan.columns and "now_cost" in proj_plan.columns:
            proj_plan["price_m"] = pd.to_numeric(proj_plan["now_cost"], errors="coerce") / 10.0
        if "team_short" not in proj_plan.columns and "team" in proj_plan.columns:
            proj_plan["team_short"] = proj_plan["team"].map(ctx.get("teams_short_map") or {})
```

In `api/main.py`, next to the chat router include (`api/main.py:78-79`):

```python
    from api.chips import router as chips_router
    app.include_router(chips_router, dependencies=[Depends(require_user)])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_chips_route.py tests/test_chip_advisor.py -q`
Expected: all pass

- [ ] **Step 6: Smoke test against live data, run full suite, commit**

Run: `uvicorn api.main:app --port 8001` in one shell; in another, with a valid Supabase JWT: `curl -s "localhost:8001/chips/plan?entry_id=<your_entry>" -H "Authorization: Bearer $TOKEN" | python -m json.tool | head -50`
Expected: JSON with `chips_remaining`, `recommendations` (may be empty early season — thresholds), no 500.

Run: `python -m pytest -q`

```bash
git add api/chips.py api/main.py api/chat.py tests/test_chips_route.py
git commit -m "feat(api): GET /chips/plan chip timing endpoint"
```

---

### Task 7: `/recommendations` accepts `bench_boost` / `triple_captain`

**Files:**
- Modify: `src/utils.py:72-80` (`normalize_chip_strategy`)
- Test: `tests/test_chip_advisor.py` (or a small dedicated block in an existing utils test file if one exists — it does not, so keep it here)

**Interfaces:**
- Produces: `normalize_chip_strategy` additionally returns `"bench_boost"` and `"triple_captain"`. `api/main.py`'s chip logic is untouched: every existing comparison is `== "wildcard"` / `== "free_hit"`, so the new values behave exactly like `none` for optimization while `chip_strategy.selected` echoes them — which is precisely the design (BB/TC don't change the squad build).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chip_advisor.py`:

```python
from src.utils import normalize_chip_strategy


def test_normalize_chip_strategy_new_chips():
    assert normalize_chip_strategy("bench_boost") == "bench_boost"
    assert normalize_chip_strategy("bboost") == "bench_boost"
    assert normalize_chip_strategy("bb") == "bench_boost"
    assert normalize_chip_strategy("triple_captain") == "triple_captain"
    assert normalize_chip_strategy("3xc") == "triple_captain"
    assert normalize_chip_strategy("tc") == "triple_captain"


def test_normalize_chip_strategy_existing_unchanged():
    assert normalize_chip_strategy("wildcard") == "wildcard"
    assert normalize_chip_strategy("fh") == "free_hit"
    assert normalize_chip_strategy("") == "none"
    assert normalize_chip_strategy("garbage") == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: FAIL — `bench_boost` currently normalizes to `"none"`.

- [ ] **Step 3: Implement**

In `src/utils.py`, extend `normalize_chip_strategy` before the final `return "none"`:

```python
    if s in ("bench_boost", "bboost", "bb"):
        return "bench_boost"
    if s in ("triple_captain", "3xc", "tc"):
        return "triple_captain"
```

- [ ] **Step 4: Run tests, verify the no-behavior-change claim, commit**

Run: `python -m pytest -q`
Expected: all pass. Verify with `grep -n 'chip_strategy ==' api/main.py` that every comparison targets `"wildcard"`/`"free_hit"`/`"none"` only — the new values fall through to no-chip optimization by construction.

```bash
git add src/utils.py tests/test_chip_advisor.py
git commit -m "feat(api): accept bench_boost/triple_captain chip_strategy values"
```

---

### Task 8: Chat chip agent grounded on the full plan

**Files:**
- Modify: `agents/chip_agent.py` (tool handler + tool description)
- Modify: `api/chat.py:296-325` (`chat_chip` passes the extra data through)
- Test: `tests/test_chip_advisor.py`

**Interfaces:**
- Consumes: `build_chip_plan` (Task 5).
- Produces: the `get_chip_recommendations` tool result becomes the `build_chip_plan` payload (windows + provisional + nudge included), so the LLM's chip answers are grounded on the same plan the UI shows.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chip_advisor.py`:

```python
def test_chip_agent_tool_returns_full_plan(monkeypatch):
    from agents import chip_agent

    sentinel = {"recommendations": [], "nudge": None, "chips_remaining": [],
                "current_gw": 5, "horizon_model_gws": 8, "transfer_context": {}}
    monkeypatch.setattr(chip_agent, "build_chip_plan", lambda **kw: sentinel)

    squad = _squad_15()[["player_id", "name", "pos", "team", "price_m"]]
    result = chip_agent._handle_tool_call(
        "get_chip_recommendations", {"current_gw": 5},
        squad, {5: _squad_15()}, ["wildcard"],
    )
    assert result == sentinel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_chip_advisor.py -q`
Expected: FAIL — `chip_agent` has no `build_chip_plan` attribute.

- [ ] **Step 3: Implement**

In `agents/chip_agent.py`:

- Change the import: `from src.chip_advisor import build_chip_plan`
- `_handle_tool_call` gains a `chips_played` argument (default `None`) and the branch becomes:

```python
    if name == "get_chip_recommendations":
        return build_chip_plan(
            squad=squad,
            current_gw=int(args["current_gw"]),
            gw_projections=gw_projections,
            chips_played=chips_played or [],
            horizon_gws=int(args.get("gws_ahead", 5)) + 1,
        )
```

Backward-compat note: `chips_remaining` (the list of names) is no longer the tool's availability source — `build_chip_plan` derives availability from `chips_played`. `run_chip_agent` gains `chips_played: list | None = None` and threads it to `_handle_tool_call`; its `chips_remaining` parameter stays (still used in the user message text). In `api/chat.py:chat_chip`, fetch and pass the raw plays:

```python
    try:
        chips_played = fpl_client.get_entry_history(req.entry_id).get("chips") or []
    except Exception:
        chips_played = []
```

and pass `chips_played=chips_played` to `run_chip_agent`. Update the tool `description` string to mention windows/expiry/provisional fields.

- [ ] **Step 4: Run the full suite and commit**

Run: `python -m pytest -q`
Expected: all pass

```bash
git add agents/chip_agent.py api/chat.py tests/test_chip_advisor.py
git commit -m "feat(agents): ground chip chat agent on full build_chip_plan output"
```

---

### Task 9: `chip_plan_snapshots` — migration + snapshot job

**Files:**
- Create: `supabase/migrations/20260901_chip_plan_snapshots.sql`
- Create: `scripts/chip_snapshot_to_db.py`
- Create: `api/main.py` addition — `GET /admin/chip-plan` (admin-key, next to `/admin/model-snapshot` at `api/main.py:1717`)
- Modify: `.github/workflows/snapshot-db.yml` (second job step)
- Test: `tests/test_chip_snapshot_db.py` (new file)

**Interfaces:**
- Consumes: `build_chip_plan` payload via the new admin endpoint; `fpl_client.get_entry_history` + `get_entry_picks` + FPL `/event/{gw}/live/` for actuals.
- Produces: table `chip_plan_snapshots` (PK `(season, gw, entry_id)`); pure row builders `chip_plan_rows(payload, now_utc)` and `chip_actuals_rows(entry_id, season, gw, chips_played, picks, live_points_by_id, now_iso)`; env var `CHIP_SNAPSHOT_ENTRY_IDS` (comma-separated entry ids).

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/20260901_chip_plan_snapshots.sql`:

```sql
create table if not exists public.chip_plan_snapshots (
  season text not null,
  gw int not null,
  entry_id bigint not null,
  chips_remaining jsonb,
  recommendations jsonb,
  ev_curves jsonb,
  transfer_context jsonb,
  model_meta jsonb,
  captured_at timestamptz,
  chip_played text,
  actual_points int,
  realized_chip_ev jsonb,
  actuals_captured_at timestamptz,
  primary key (season, gw, entry_id)
);

alter table public.chip_plan_snapshots enable row level security;
-- service-role writes only (no anon policies), same posture as player_gw_snapshots
```

Apply manually via the Supabase dashboard SQL editor (same procedure as `20260825_player_gw_snapshots.sql`).

- [ ] **Step 2: Write the failing row-builder tests**

Create `tests/test_chip_snapshot_db.py`:

```python
from datetime import datetime, timezone

from scripts.chip_snapshot_to_db import chip_plan_rows, chip_actuals_rows

PLAN_PAYLOAD = {
    "season": "2026-27", "next_gw": 4, "deadline_utc": "2026-09-12T17:30:00Z",
    "entry_id": 123,
    "plan": {
        "current_gw": 4,
        "chips_remaining": [{"name": "wildcard", "available": True, "half": 1, "expires_gw": 19}],
        "horizon_model_gws": 8,
        "recommendations": [{"chip": "wildcard", "event_id": 8, "ev_gain": 9.1,
                             "provisional": False, "reasons": [], "ev_curve": [{"gw": 4, "ev": 2.0}]}],
        "nudge": None,
        "transfer_context": {"planned_transfers_net_gain": 3.0, "wc_alternative_gw": 8},
    },
    "model_meta": {"horizon": 8, "min_ev": {"wildcard": 6.0}},
}


def test_chip_plan_rows_before_deadline():
    now = datetime(2026, 9, 12, 16, 0, tzinfo=timezone.utc)
    rows = chip_plan_rows(PLAN_PAYLOAD, now)
    assert len(rows) == 1
    r = rows[0]
    assert (r["season"], r["gw"], r["entry_id"]) == ("2026-27", 4, 123)
    assert r["recommendations"][0]["chip"] == "wildcard"
    assert r["ev_curves"] == {"wildcard": [{"gw": 4, "ev": 2.0}]}
    assert r["model_meta"]["horizon"] == 8


def test_chip_plan_rows_empty_after_deadline():
    now = datetime(2026, 9, 12, 18, 0, tzinfo=timezone.utc)
    assert chip_plan_rows(PLAN_PAYLOAD, now) == []


def test_chip_actuals_rows_bench_and_captain():
    chips_played = [{"name": "bboost", "event": 4}]
    picks = [{"element": i, "position": i, "is_captain": i == 1} for i in range(1, 16)]
    live_points = {i: 2 for i in range(1, 16)}
    live_points[1] = 10  # captain hauled
    rows = chip_actuals_rows(
        entry_id=123, season="2026-27", gw=4, chips_played=chips_played,
        picks=picks, live_points_by_id=live_points, now_iso="2026-09-15T09:00:00+00:00",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["chip_played"] == "bench_boost"          # normalized to canonical
    # bench = positions 12-15 → 4 players x 2 pts
    assert r["realized_chip_ev"]["bench_boost"] == 8
    # TC realized = captain's actual points (the extra x1)
    assert r["realized_chip_ev"]["triple_captain"] == 10
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_chip_snapshot_db.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.chip_snapshot_to_db'`

- [ ] **Step 4: Implement the admin endpoint**

In `api/main.py`, next to `admin_model_snapshot` (`api/main.py:1717`):

```python
@app.get("/admin/chip-plan")
def admin_chip_plan(
    entry_id: int,
    api_key=None,
    x_api_key=Header(None),
    authorization=Header(None),
):
    err = check_admin_key(x_api_key=x_api_key, authorization=authorization, api_key=api_key)
    if err:
        return err
    from api.chips import chips_plan, _resolve_current_gw
    from src.season_history import season_label_from_bootstrap
    from src import config as _config

    bootstrap = fpl_client.get_bootstrap()
    next_gw = _resolve_current_gw()
    deadline = next(
        (e.get("deadline_time") for e in bootstrap.get("events", []) if int(e["id"]) == next_gw),
        None,
    )
    body = chips_plan(entry_id=entry_id, horizon=None)
    return {
        "season": season_label_from_bootstrap(bootstrap),
        "next_gw": next_gw,
        "deadline_utc": deadline,
        "entry_id": entry_id,
        "plan": {k: v for k, v in body.items() if k != "entry_id"},
        "model_meta": {
            "horizon": getattr(_config, "CHIP_PLAN_HORIZON_GWS", 8),
            "min_ev": getattr(_config, "CHIP_PLAN_MIN_EV", {}),
            "expiry_ramp_gws": getattr(_config, "CHIP_PLAN_EXPIRY_RAMP_GWS", 5),
        },
    }
```

- [ ] **Step 5: Implement the job script**

Create `scripts/chip_snapshot_to_db.py` (mirrors `scripts/snapshot_to_db.py` structure — pure builders, then I/O shell):

```python
"""Chip-plan snapshot job: pre-deadline plan + post-GW chip actuals -> Supabase.

Run alongside snapshot_to_db.py by .github/workflows/snapshot-db.yml.
Env: FPL_API_BASE_URL, FPL_ADMIN_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY,
     CHIP_SNAPSHOT_ENTRY_IDS (comma-separated FPL entry ids).
"""
import os
import sys
from datetime import datetime, timezone

import requests

FPL_CHIP_NAME_MAP = {
    "wildcard": "wildcard", "freehit": "free_hit",
    "bboost": "bench_boost", "3xc": "triple_captain",
}


def chip_plan_rows(payload, now_utc):
    deadline = datetime.fromisoformat(str(payload["deadline_utc"]).replace("Z", "+00:00"))
    if now_utc >= deadline:
        return []
    plan = payload["plan"]
    curves = {r["chip"]: r.get("ev_curve") or [] for r in plan.get("recommendations", [])}
    return [{
        "season": str(payload["season"]),
        "gw": int(payload["next_gw"]),
        "entry_id": int(payload["entry_id"]),
        "chips_remaining": plan.get("chips_remaining"),
        "recommendations": plan.get("recommendations"),
        "ev_curves": curves,
        "transfer_context": plan.get("transfer_context"),
        "model_meta": payload.get("model_meta"),
        "captured_at": now_utc.isoformat(),
    }]


def chip_actuals_rows(entry_id, season, gw, chips_played, picks, live_points_by_id, now_iso):
    chip_raw = next(
        (c.get("name") for c in chips_played or [] if int(c.get("event", 0) or 0) == int(gw)),
        None,
    )
    chip = FPL_CHIP_NAME_MAP.get(str(chip_raw).lower()) if chip_raw else None

    bench = [p for p in picks or [] if int(p.get("position", 0)) >= 12]
    bench_pts = sum(int(live_points_by_id.get(int(p["element"]), 0)) for p in bench)
    cap = next((p for p in picks or [] if p.get("is_captain")), None)
    cap_pts = int(live_points_by_id.get(int(cap["element"]), 0)) if cap else 0
    total = sum(int(live_points_by_id.get(int(p["element"]), 0)) for p in picks or [])

    return [{
        "season": season, "gw": int(gw), "entry_id": int(entry_id),
        "chip_played": chip,
        "actual_points": total,
        # Counterfactual realized EVs computable from actuals alone; FH/WC need
        # counterfactual squads and stay out of the labels.
        "realized_chip_ev": {"bench_boost": bench_pts, "triple_captain": cap_pts},
        "actuals_captured_at": now_iso,
    }]


# ---------------------------------------------------------------- I/O shell

def _headers(service_key):
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def upsert(supabase_url, service_key, rows):
    if not rows:
        return
    r = requests.post(
        f"{supabase_url.rstrip('/')}/rest/v1/chip_plan_snapshots"
        "?on_conflict=season,gw,entry_id",
        headers=_headers(service_key), json=rows, timeout=60,
    )
    r.raise_for_status()


def gws_missing_actuals(supabase_url, service_key, season, entry_id):
    r = requests.get(
        f"{supabase_url.rstrip('/')}/rest/v1/chip_plan_snapshots"
        f"?select=gw&season=eq.{season}&entry_id=eq.{entry_id}"
        f"&actuals_captured_at=is.null&limit=100000",
        headers=_headers(service_key), timeout=60,
    )
    r.raise_for_status()
    return sorted({int(row["gw"]) for row in r.json()})


def main():
    api_base = os.environ["FPL_API_BASE_URL"].rstrip("/")
    admin_key = os.environ["FPL_ADMIN_KEY"]
    sb_url = os.environ["SUPABASE_URL"]
    sb_key = os.environ["SUPABASE_SERVICE_KEY"]
    entry_ids = [int(x) for x in os.environ.get("CHIP_SNAPSHOT_ENTRY_IDS", "").split(",") if x.strip()]
    if not entry_ids:
        print("CHIP_SNAPSHOT_ENTRY_IDS empty — nothing to do")
        return
    now = datetime.now(timezone.utc)

    finished_gws = set()
    rboot = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=60)
    rboot.raise_for_status()
    for e in rboot.json().get("events", []):
        if e.get("finished"):
            finished_gws.add(int(e["id"]))

    for entry_id in entry_ids:
        snap = requests.get(
            f"{api_base}/admin/chip-plan?entry_id={entry_id}",
            headers={"X-API-Key": admin_key}, timeout=180,
        )
        snap.raise_for_status()
        payload = snap.json()
        season = str(payload["season"])

        rows = chip_plan_rows(payload, now)
        upsert(sb_url, sb_key, rows)
        print(f"chip plan: entry={entry_id} gw={payload['next_gw']} rows={len(rows)}")

        rh = requests.get(
            f"https://fantasy.premierleague.com/api/entry/{entry_id}/history/", timeout=60)
        rh.raise_for_status()
        chips_played = rh.json().get("chips") or []

        for gw in gws_missing_actuals(sb_url, sb_key, season, entry_id):
            if gw not in finished_gws:
                continue
            rp = requests.get(
                f"https://fantasy.premierleague.com/api/entry/{entry_id}/event/{gw}/picks/",
                timeout=60)
            rp.raise_for_status()
            picks = rp.json().get("picks") or []
            rl = requests.get(
                f"https://fantasy.premierleague.com/api/event/{gw}/live/", timeout=60)
            rl.raise_for_status()
            live_points = {
                int(e["id"]): int((e.get("stats") or {}).get("total_points") or 0)
                for e in rl.json().get("elements") or []
            }
            rows = chip_actuals_rows(entry_id, season, gw, chips_played, picks, live_points, now.isoformat())
            upsert(sb_url, sb_key, rows)
            print(f"chip actuals: entry={entry_id} gw={gw}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_chip_snapshot_db.py -q`
Expected: 3 passed

- [ ] **Step 7: Extend the workflow**

In `.github/workflows/snapshot-db.yml`, after the existing snapshot step add (matching the existing step's env style):

```yaml
      - name: Chip plan snapshot
        if: always()
        env:
          FPL_API_BASE_URL: ${{ secrets.FPL_API_BASE_URL }}
          FPL_ADMIN_KEY: ${{ secrets.FPL_ADMIN_KEY }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          CHIP_SNAPSHOT_ENTRY_IDS: ${{ secrets.CHIP_SNAPSHOT_ENTRY_IDS }}
        run: python scripts/chip_snapshot_to_db.py
```

Add the `CHIP_SNAPSHOT_ENTRY_IDS` GitHub secret manually (your entry id).

- [ ] **Step 8: Run the full suite and commit**

Run: `python -m pytest -q`

```bash
git add supabase/migrations/20260901_chip_plan_snapshots.sql scripts/chip_snapshot_to_db.py api/main.py .github/workflows/snapshot-db.yml tests/test_chip_snapshot_db.py
git commit -m "feat(db): chip_plan_snapshots table + twice-daily snapshot job"
```

---

### Task 10: Live spot-check + threshold tuning

**Files:**
- Create: `scripts/spotcheck_chip_plan.py` (pattern: `scripts/spotcheck_league_ev.py`)
- Modify (as tuning dictates): `src/config.py` `CHIP_PLAN_*` values

**Interfaces:**
- Consumes: `api/chips.py` internals against live FPL data.
- Produces: a console table for eyeballing; tuned config defaults.

- [ ] **Step 1: Write the spot-check script**

Create `scripts/spotcheck_chip_plan.py`:

```python
"""Spot-check the chip plan against live data.

Usage: PYTHONPATH=. python -m scripts.spotcheck_chip_plan <entry_id> [horizon]
"""
import json
import sys

from api.chat import _build_context_for_entry
from api.chips import _get_entry_chips, _resolve_current_gw
from src import config
from src.chip_advisor import build_chip_plan


def main():
    entry_id = int(sys.argv[1])
    horizon = int(sys.argv[2]) if len(sys.argv) > 2 else getattr(config, "CHIP_PLAN_HORIZON_GWS", 8)
    current_gw = _resolve_current_gw()
    ctx = _build_context_for_entry(entry_id, current_gw, horizon=horizon)
    plan = build_chip_plan(
        squad=ctx["squad"], current_gw=current_gw,
        gw_projections=ctx["gw_projections"],
        chips_played=_get_entry_chips(entry_id),
        itb_m=float(ctx["bank_m"]), fixtures=ctx.get("fixtures"),
        horizon_gws=horizon,
    )
    print(json.dumps(plan, indent=2, default=str))
    print("\n--- summary ---")
    for r in plan["recommendations"]:
        tag = "PROVISIONAL" if r["provisional"] else f"+{r['ev_gain']} xPts"
        print(f"{r['chip']:16s} GW{r['event_id']:<3d} {tag}")
    if plan["nudge"]:
        print(f"NUDGE: {plan['nudge']['chip']} this GW (+{plan['nudge']['ev_gain']})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against your entry**

Run: `PYTHONPATH=. python -m scripts.spotcheck_chip_plan <your_entry_id>`
Expected: a readable plan. Sanity checks, in order:
1. Chips you have already played this half are absent.
2. No chip is recommended for a GW past its `expires_gw`.
3. Early season (no DGWs announced) the model zone usually recommends "hold" for BB/TC — non-empty BB/TC recommendations now would suggest thresholds are too low.
4. If any recommendation looks trigger-happy or dead-silent, adjust `CHIP_PLAN_MIN_EV` / `CHIP_PLAN_NUDGE_MIN_EV` in `src/config.py` and rerun until the output is defensible.

- [ ] **Step 3: Run the full suite and commit**

Run: `python -m pytest -q`

```bash
git add scripts/spotcheck_chip_plan.py src/config.py
git commit -m "chore(chips): live spot-check script + tuned CHIP_PLAN thresholds"
```

---

## Self-Review Notes

- Spec coverage: engine priors/expiry (Tasks 1, 3), DGW detection (Task 2), WC-vs-transfers + FH budget (Task 4), curves/structural/nudge/assembly (Task 5), REST route + auth + additive contract (Task 6), BB/TC chip_strategy acceptance (Task 7), agent grounding (Task 8), DB capture for Approach C (Task 9), backtest-informed tuning (Task 10 — live spot-check stands in for a full SP3 replay; a season replay via `scripts/backtest_season.py --chips-weekly` remains available for deeper tuning and is intentionally not blocking ship).
- Naming: canonical chip names verified against `src/chip_advisor.py` dataclass comment and `_derive_chips_remaining`. FPL-name normalization exists in exactly two places, both at FPL boundaries: `chip_windows` and `chip_snapshot_to_db.py`. The map is duplicated in the job script deliberately — like `snapshot_to_db.py`, it stays free of `src` imports so the CI job runs with `requests` alone.
- Frontend counterpart: `docs/superpowers/plans/2026-09-01-chip-planner-frontend.md` in the frontend repo consumes the Task 6 contract.
