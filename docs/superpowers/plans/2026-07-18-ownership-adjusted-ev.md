# Ownership-Adjusted EV + Captain-Differential — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rank mini-league strategy candidates by an ownership-adjusted differential EV `(xPts − template) × (1 − league_ownership)` and add a captain-differential flag, both behind a default-ON config flag.

**Architecture:** A new pure module `src/ownership_ev.py` computes per-position templates (global-ownership-weighted) and the differential EV. `src/league_strategy.py` uses it to rank candidates (all 3 modes) and to detect a captain differential; both surface in the response and the LLM narrative.

**Tech Stack:** Python 3.10, pandas 1.5.1. Tests via pytest (dev-only). No new runtime deps.

## Global Constraints

- **Runtime deps unchanged** (pandas 1.5.1, Python 3.10). pytest is dev-only.
- **Reversibility:** `LEAGUE_EV_RANKING = False` restores the exact legacy `ep()` (raw-xPts) candidate order. Default is `True`.
- **Formula (exact):** `template_xpts[pos] = Σ(selected_by_percent_i · xpts_i) / Σ(selected_by_percent_i)` over players at position `pos` (fallback: simple mean when Σ weights = 0). `differential_ev = (xpts_horizon − template_xpts[pos]) × (1 − clip(league_ownership,0,1))`. `xpts_horizon = model_xpts_horizon` else `ep_next` else `0.0`.
- **Ownership sources:** template uses GLOBAL `selected_by_percent`; the `(1 − ownership)` multiplier uses LEAGUE ownership (`analysis["league_ownership"]`).
- **Config defaults exactly:** `LEAGUE_EV_RANKING = True`, `LEAGUE_EV_CAPTAIN_PREMIUM_FLOOR = 85` (now_cost tenths = £8.5m), `LEAGUE_EV_CAPTAIN_DIFF_MAX_OWNERSHIP = 0.10`.
- **Position ids:** 1=GKP, 2=DEF, 3=MID, 4=FWD (FPL `element_type`, stored as `position_id` in elements_meta).
- **No hallucinated numbers:** the narrative must cite only provided `differential_ev`/`league_ownership` values.
- Follow existing patterns; read tunables via `getattr(config, "NAME", default)`.

---

### Task 1: `src/ownership_ev.py` module + config

**Files:**
- Create: `src/ownership_ev.py`
- Modify: `src/config.py` (add 3 constants)
- Create: `tests/test_ownership_ev.py`

**Interfaces:**
- Produces:
  - `ownership_ev.xpts_of(meta) -> float` — `model_xpts_horizon` else `ep_next` else `0.0`.
  - `ownership_ev.compute_position_templates(elements_meta: dict) -> dict[int, float]` keyed by position_id.
  - `ownership_ev.differential_ev(xpts_horizon: float, template_xpts_pos: float, league_ownership: float) -> float`.
  - `ownership_ev.annotate_candidates(candidates: list[dict], templates: dict) -> list[dict]` — returns new list; each row gains `differential_ev` + `template_xpts` (reads `position_id`, `league_ownership` from the row).

- [ ] **Step 1: Add config constants**

In `src/config.py`, append at end of file:
```python

# --- mini-league ownership-adjusted EV (src/ownership_ev.py + league_strategy.py) ---
LEAGUE_EV_RANKING = True                      # rank candidates by differential EV (False = legacy raw-xPts sort)
LEAGUE_EV_CAPTAIN_PREMIUM_FLOOR = 85          # now_cost (tenths) floor for a "premium" captain (£8.5m)
LEAGUE_EV_CAPTAIN_DIFF_MAX_OWNERSHIP = 0.10   # alternative must be under this league ownership to flag
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ownership_ev.py`:
```python
from src import ownership_ev


def _meta(pid, xpts, own_pct, ep_next=None, league_own=None):
    m = {"position_id": pid, "model_xpts_horizon": xpts, "selected_by_percent": own_pct}
    if ep_next is not None:
        m["ep_next"] = ep_next
    if league_own is not None:
        m["league_ownership"] = league_own
    return m


def test_xpts_of_fallback_chain():
    assert ownership_ev.xpts_of({"model_xpts_horizon": 12.0}) == 12.0
    assert ownership_ev.xpts_of({"model_xpts_horizon": None, "ep_next": "3.5"}) == 3.5
    assert ownership_ev.xpts_of({"model_xpts_horizon": None, "ep_next": None}) == 0.0


def test_position_template_is_global_ownership_weighted():
    # Two MIDs: high-owned 10pt, low-owned 2pt. Weighted avg tilts toward the high-owned.
    elements = {
        1: _meta(3, 10.0, "50.0"),
        2: _meta(3, 2.0, "5.0"),
        3: _meta(4, 8.0, "20.0"),
    }
    t = ownership_ev.compute_position_templates(elements)
    # MID: (50*10 + 5*2)/(55) = 510/55 = 9.2727...
    assert abs(t[3] - (510.0 / 55.0)) < 1e-6
    assert abs(t[4] - 8.0) < 1e-6


def test_position_template_zero_ownership_falls_back_to_mean():
    elements = {1: _meta(2, 4.0, "0"), 2: _meta(2, 6.0, "0")}
    t = ownership_ev.compute_position_templates(elements)
    assert abs(t[2] - 5.0) < 1e-6


def test_differential_ev_formula():
    # above template, low ownership -> high EV
    assert abs(ownership_ev.differential_ev(10.0, 6.0, 0.0) - 4.0) < 1e-9
    # owned by whole league -> ~0 regardless of xpts
    assert abs(ownership_ev.differential_ev(10.0, 6.0, 1.0) - 0.0) < 1e-9
    # below template -> negative
    assert ownership_ev.differential_ev(3.0, 6.0, 0.0) < 0
    # ownership clipped: >1 treated as 1
    assert abs(ownership_ev.differential_ev(10.0, 6.0, 1.5) - 0.0) < 1e-9


def test_annotate_candidates_adds_ev_and_template():
    templates = {3: 6.0}
    cands = [{"id": 1, "position_id": 3, "model_xpts_horizon": 10.0, "league_ownership": 0.25}]
    out = ownership_ev.annotate_candidates(cands, templates)
    assert out[0]["template_xpts"] == 6.0
    assert abs(out[0]["differential_ev"] - (10.0 - 6.0) * 0.75) < 1e-9
    # original list not mutated
    assert "differential_ev" not in cands[0]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ownership_ev.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ownership_ev'`.

- [ ] **Step 4: Implement the module**

Create `src/ownership_ev.py`:
```python
"""
Ownership-adjusted differential EV for mini-league strategy.

differential_ev = (xpts_horizon - template_xpts[pos]) * (1 - league_ownership)

template_xpts[pos] is the GLOBAL-ownership-weighted (selected_by_percent) average
projected points at a position — "what the field effectively gets" — so the EV
measures points gained over the template, scaled by how differentiated the pick is
within your specific mini-league (league_ownership).

Pure module: no I/O, no global state. All tunables live in ``config``.
"""
from __future__ import annotations

try:
    from . import config
except Exception:  # pragma: no cover - flat script usage
    import config  # type: ignore


def _to_float(v, default=0.0):
    try:
        return float(v if v is not None else default)
    except (TypeError, ValueError):
        return default


def xpts_of(meta):
    """model_xpts_horizon, else ep_next, else 0.0."""
    v = meta.get("model_xpts_horizon")
    if v is None:
        v = meta.get("ep_next")
    return _to_float(v, 0.0)


def compute_position_templates(elements_meta):
    """
    {position_id: global-ownership-weighted average xpts at that position}.
    Falls back to the simple mean for a position whose total ownership is 0.
    """
    sums = {}    # pos -> [weighted_xpts_sum, weight_sum, xpts_sum, count]
    for meta in (elements_meta or {}).values():
        pos = meta.get("position_id")
        if pos is None:
            continue
        w = _to_float(meta.get("selected_by_percent"), 0.0)
        x = xpts_of(meta)
        acc = sums.setdefault(int(pos), [0.0, 0.0, 0.0, 0])
        acc[0] += w * x
        acc[1] += w
        acc[2] += x
        acc[3] += 1
    out = {}
    for pos, (wx, w, sx, n) in sums.items():
        out[pos] = (wx / w) if w > 0 else (sx / n if n else 0.0)
    return out


def differential_ev(xpts_horizon, template_xpts_pos, league_ownership):
    """(xpts - template) * (1 - clip(league_ownership, 0, 1))."""
    own = _to_float(league_ownership, 0.0)
    own = min(1.0, max(0.0, own))
    return (_to_float(xpts_horizon) - _to_float(template_xpts_pos)) * (1.0 - own)


def annotate_candidates(candidates, templates):
    """Return a new list of candidate rows, each with differential_ev + template_xpts."""
    out = []
    for c in candidates or []:
        row = dict(c)
        pos = c.get("position_id")
        template = _to_float((templates or {}).get(int(pos) if pos is not None else -1, 0.0))
        row["template_xpts"] = round(template, 3)
        row["differential_ev"] = round(
            differential_ev(xpts_of(c), template, c.get("league_ownership")), 3
        )
        out.append(row)
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ownership_ev.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add src/ownership_ev.py src/config.py tests/test_ownership_ev.py
git commit -m "feat: add ownership_ev module (differential EV + position templates)"
```

---

### Task 2: EV ranking in `_candidate_targets`

**Files:**
- Modify: `src/league_strategy.py` (imports; extract `_ep`; add `_rank_and_slice`; `templates` param; `build_strategy` computes/passes templates)
- Create: `tests/test_league_strategy_ranking.py`

**Interfaces:**
- Consumes: `ownership_ev.compute_position_templates`, `ownership_ev.annotate_candidates` (Task 1); `config.LEAGUE_EV_RANKING`.
- Produces: `_candidate_targets(analysis, elements_meta, mode, templates)` (new 4th param) returns candidates ranked by `differential_ev` when the flag is on (each row annotated), else by legacy `ep()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_league_strategy_ranking.py`:
```python
from src import config, league_strategy


def _analysis(ownership):
    return {
        "differentials": {"owned_by_me_not_rivals": [], "owned_by_rivals_not_me": [], "shared": []},
        "league_ownership": ownership,
        "rivals_above": [], "rivals_below": [],
        "rival_squads": {}, "my_squad": {"picks": []},
    }


def _meta(pid, name, xpts, own_pct, pos=3):
    return {"id": pid, "web_name": name, "position_id": pos,
            "model_xpts_horizon": xpts, "ep_next": xpts, "selected_by_percent": own_pct,
            "now_cost": 70, "team_short": "XYZ"}


def test_differential_mode_ev_ranking_beats_raw_xpts(monkeypatch):
    monkeypatch.setattr(config, "LEAGUE_EV_RANKING", True, raising=False)
    # A: 12 xPts but 0% league-owned (great differential). B: 13 xPts but 0% league-owned too.
    # Template is global-owned-weighted; make B highly global-owned so template ~ B, shrinking B's EV.
    elements = {
        1: _meta(1, "A", 12.0, "3.0"),
        2: _meta(2, "B", 13.0, "60.0"),
    }
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.0, 2: 0.0})
    out = league_strategy._candidate_targets(analysis, elements, "differential", templates)
    # B's xpts (13) is near the (global-owned) template it dominates, so its EV is small;
    # A sits well above the template -> A ranks first despite lower raw xPts.
    assert out[0]["web_name"] == "A"
    assert "differential_ev" in out[0]


def test_flag_off_uses_legacy_raw_xpts_order(monkeypatch):
    monkeypatch.setattr(config, "LEAGUE_EV_RANKING", False, raising=False)
    elements = {1: _meta(1, "A", 12.0, "3.0"), 2: _meta(2, "B", 13.0, "60.0")}
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.0, 2: 0.0})
    out = league_strategy._candidate_targets(analysis, elements, "differential", templates)
    # Legacy sort is by raw xPts -> B (13) first.
    assert out[0]["web_name"] == "B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_league_strategy_ranking.py -v`
Expected: FAIL — `_candidate_targets()` takes 3 args, not 4 (TypeError).

- [ ] **Step 3: Update imports**

In `src/league_strategy.py`, change the top import:
```python
from src import league
```
to:
```python
from src import league, ownership_ev
from src import config
```

- [ ] **Step 4: Extract `_ep` and add `_rank_and_slice`**

In `src/league_strategy.py`, immediately **above** `def _candidate_targets(` insert:
```python
def _ep(p):
    v = p.get("model_xpts_horizon")
    if v is None:
        v = p.get("ep_next")
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _rank_and_slice(candidates, templates, top_n=10):
    """Rank by differential EV (flag on) or legacy raw xPts (flag off), then slice."""
    if bool(getattr(config, "LEAGUE_EV_RANKING", True)) and templates:
        ranked = ownership_ev.annotate_candidates(candidates, templates)
        ranked.sort(key=lambda c: c.get("differential_ev", 0.0), reverse=True)
    else:
        ranked = sorted(candidates, key=_ep, reverse=True)
    return ranked[:top_n]
```

- [ ] **Step 5: Rewrite `_candidate_targets` to use them**

In `src/league_strategy.py`, replace the entire `_candidate_targets` function (currently `def _candidate_targets(analysis, elements_meta, mode):` through its final `return enriched[:10]`) with:
```python
def _candidate_targets(analysis, elements_meta, mode, templates=None):
    ownership = analysis["league_ownership"]

    if mode == "chase":
        rivals_above_ids = set()
        for rid in [r["entry_id"] for r in analysis["rivals_above"] if r.get("entry_id") in analysis["rival_squads"]]:
            for p in analysis["rival_squads"][rid].get("picks") or []:
                if p.get("element") is not None:
                    rivals_above_ids.add(p["element"])
        my_ids = {p.get("element") for p in analysis["my_squad"].get("picks") or []}
        targets = sorted(rivals_above_ids - my_ids)
        enriched = _enrich_ids(targets, elements_meta, ownership)
        return _rank_and_slice(enriched, templates)

    if mode == "defend":
        rivals_below_ids = set()
        for rid in [r["entry_id"] for r in analysis["rivals_below"] if r.get("entry_id") in analysis["rival_squads"]]:
            for p in analysis["rival_squads"][rid].get("picks") or []:
                if p.get("element") is not None:
                    rivals_below_ids.add(p["element"])
        my_ids = {p.get("element") for p in analysis["my_squad"].get("picks") or []}
        targets = sorted(rivals_below_ids - my_ids)
        enriched = _enrich_ids(targets, elements_meta, ownership)
        return _rank_and_slice(enriched, templates)

    enriched = []
    for pid, meta in elements_meta.items():
        own = ownership.get(int(pid), 0.0)
        if own >= 0.20:
            continue
        if _ep(meta) <= 0:
            continue
        row = dict(meta)
        row["league_ownership"] = round(own, 3)
        enriched.append(row)
    return _rank_and_slice(enriched, templates)
```

- [ ] **Step 6: Compute + pass templates in `build_strategy`**

In `src/league_strategy.py` `build_strategy`, find:
```python
    elements_meta = _player_meta(bootstrap, projections_df=projections_df)
    candidates = _candidate_targets(analysis, elements_meta, mode)
```
Replace with:
```python
    elements_meta = _player_meta(bootstrap, projections_df=projections_df)
    templates = ownership_ev.compute_position_templates(elements_meta)
    candidates = _candidate_targets(analysis, elements_meta, mode, templates)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_league_strategy_ranking.py -v`
Expected: PASS (2 tests).

- [ ] **Step 8: Commit**

```bash
git add src/league_strategy.py tests/test_league_strategy_ranking.py
git commit -m "feat: rank league candidates by differential EV behind LEAGUE_EV_RANKING"
```

---

### Task 3: `detect_captain_differential` + response wiring

**Files:**
- Modify: `src/league_strategy.py` (add `detect_captain_differential`; call in `build_strategy`; add to output)
- Create: `tests/test_captain_differential.py`

**Interfaces:**
- Consumes: `_fixture_run_lookup` (existing), `_ep` (Task 2), `ownership_ev.differential_ev`, config floors.
- Produces: `detect_captain_differential(analysis, elements_meta, templates, fixture_ticker) -> dict | None`; `build_strategy` output gains `captain_differential`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_captain_differential.py`:
```python
from src import league_strategy


def _meta(pid, name, xpts, own_pct, cost, team, pos=4):
    return {"id": pid, "web_name": name, "position_id": pos, "model_xpts_horizon": xpts,
            "ep_next": xpts, "selected_by_percent": own_pct, "now_cost": cost, "team_short": team}


def _ticker(bands):  # bands: {team_short: band}
    return {"teams": [{"team_short": t, "avg_difficulty": 3.5, "band": b} for t, b in bands.items()]}


def _analysis(ownership):
    return {"league_ownership": ownership}


def test_flag_emitted_on_hard_fixture_with_alt():
    # Cap = premium (cost 130) MID/FWD, 80% league-owned, team AAA has a hard run.
    # Alt = 5% owned, high xPts differential on team BBB.
    elements = {
        1: _meta(1, "Cap", 9.0, "55.0", 130, "AAA"),
        2: _meta(2, "Alt", 8.0, "6.0", 95, "BBB"),
        3: _meta(3, "Filler", 4.0, "40.0", 70, "CCC"),
    }
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.80, 2: 0.05, 3: 0.40})
    ticker = _ticker({"AAA": "hard", "BBB": "easy"})
    flag = league_strategy.detect_captain_differential(analysis, elements, templates, ticker)
    assert flag is not None
    assert flag["consensus_captain"]["web_name"] == "Cap"
    assert flag["alternative"]["web_name"] == "Alt"


def test_no_flag_when_fixture_easy():
    elements = {1: _meta(1, "Cap", 9.0, "55.0", 130, "AAA"),
                2: _meta(2, "Alt", 8.0, "6.0", 95, "BBB")}
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.80, 2: 0.05})
    ticker = _ticker({"AAA": "easy", "BBB": "easy"})
    assert league_strategy.detect_captain_differential(analysis, elements, templates, ticker) is None


def test_no_flag_when_no_low_owned_alt():
    elements = {1: _meta(1, "Cap", 9.0, "55.0", 130, "AAA"),
                2: _meta(2, "Alt", 8.0, "50.0", 95, "BBB")}  # alt is 50% owned -> not a differential
    templates = league_strategy.ownership_ev.compute_position_templates(elements)
    analysis = _analysis({1: 0.80, 2: 0.50})
    ticker = _ticker({"AAA": "hard", "BBB": "easy"})
    assert league_strategy.detect_captain_differential(analysis, elements, templates, ticker) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_captain_differential.py -v`
Expected: FAIL — `AttributeError: module 'src.league_strategy' has no attribute 'detect_captain_differential'`.

- [ ] **Step 3: Implement `detect_captain_differential`**

In `src/league_strategy.py`, add after `_rank_and_slice` (or after `_attach_fixture_runs`):
```python
def detect_captain_differential(analysis, elements_meta, templates, fixture_ticker):
    """
    Flag when the league's consensus captain (highest league-owned premium MID/FWD)
    faces a hard fixture run AND a low-owned high-EV alternative exists. Returns the
    flag dict, or None when any condition is unmet.
    """
    ownership = analysis.get("league_ownership") or {}
    premium_floor = float(getattr(config, "LEAGUE_EV_CAPTAIN_PREMIUM_FLOOR", 85))
    max_own = float(getattr(config, "LEAGUE_EV_CAPTAIN_DIFF_MAX_OWNERSHIP", 0.10))
    runs = _fixture_run_lookup(fixture_ticker)

    consensus, best_own = None, -1.0
    for pid, meta in elements_meta.items():
        if meta.get("position_id") not in (3, 4):
            continue
        try:
            if float(meta.get("now_cost") or 0) < premium_floor:
                continue
        except (TypeError, ValueError):
            continue
        own = float(ownership.get(int(pid), 0.0) or 0.0)
        if own > best_own:
            consensus, best_own = meta, own
    if consensus is None or best_own <= 0:
        return None

    band = (runs.get(str(consensus.get("team_short") or "")) or {}).get("band")
    if band not in ("hard", "very_hard"):
        return None

    alt, best_ev = None, 0.0
    for pid, meta in elements_meta.items():
        if meta.get("position_id") not in (3, 4):
            continue
        own = float(ownership.get(int(pid), 0.0) or 0.0)
        if own >= max_own:
            continue
        ev = ownership_ev.differential_ev(
            ownership_ev.xpts_of(meta), (templates or {}).get(meta.get("position_id"), 0.0), own
        )
        if ev > best_ev:
            alt, best_ev = (meta, own, ev), ev
    if alt is None:
        return None
    alt_meta, alt_own, alt_ev = alt

    return {
        "consensus_captain": {
            "id": consensus.get("id"), "web_name": consensus.get("web_name"),
            "team_short": consensus.get("team_short"), "league_ownership": round(best_own, 3),
            "fixture_run_band": band, "model_xpts_horizon": consensus.get("model_xpts_horizon"),
        },
        "alternative": {
            "id": alt_meta.get("id"), "web_name": alt_meta.get("web_name"),
            "team_short": alt_meta.get("team_short"), "league_ownership": round(alt_own, 3),
            "differential_ev": round(alt_ev, 2), "model_xpts_horizon": alt_meta.get("model_xpts_horizon"),
            "fixture_run_band": (runs.get(str(alt_meta.get("team_short") or "")) or {}).get("band"),
        },
        "reason": (
            f"{consensus.get('web_name')} (consensus captain, {round(best_own * 100)}% league-owned) "
            f"faces a {band} run; {alt_meta.get('web_name')} is a "
            f"{round(alt_own * 100)}%-owned differential (+{round(alt_ev, 1)} diff-EV)."
        ),
    }
```

- [ ] **Step 4: Wire into `build_strategy` output**

In `src/league_strategy.py` `build_strategy`, find:
```python
    candidates = _attach_fixture_runs(candidates, fixture_ticker)
    narrative = _llm_narrative(analysis, mode, candidates, model=model, fixture_ticker=fixture_ticker)
```
Replace with:
```python
    candidates = _attach_fixture_runs(candidates, fixture_ticker)
    captain_differential = detect_captain_differential(analysis, elements_meta, templates, fixture_ticker)
    narrative = _llm_narrative(analysis, mode, candidates, model=model,
                               fixture_ticker=fixture_ticker, captain_differential=captain_differential)
```
Then find the `out = {` dict literal and add, after the `"candidates": candidates,` line:
```python
        "captain_differential": captain_differential,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_captain_differential.py -v`
Expected: PASS (3 tests). (Note: Step 4's `_llm_narrative` new kwarg is added in Task 4; until then `build_strategy` would raise, but these unit tests call `detect_captain_differential` directly and pass. Do Task 4 before running `build_strategy` end-to-end.)

- [ ] **Step 6: Commit**

```bash
git add src/league_strategy.py tests/test_captain_differential.py
git commit -m "feat: detect captain-differential (hard consensus-captain fixture + low-owned alt)"
```

---

### Task 4: Narrative integration

**Files:**
- Modify: `src/league_strategy.py` (`_short_candidate`, `_llm_narrative` signature + `USER_TEMPLATE`, `SYSTEM_PROMPT`)
- Create: `tests/test_narrative_prompt.py`

**Interfaces:**
- Consumes: `captain_differential` (Task 3), candidate rows with `differential_ev` (Task 2).
- Produces: `_llm_narrative(analysis, mode, candidates, model=None, fixture_ticker=None, captain_differential=None)` — extracts the user-message build into `build_user_message(...)` so it is testable without an API call.

- [ ] **Step 1: Write the failing test**

Create `tests/test_narrative_prompt.py`:
```python
from src import league_strategy


def test_user_message_includes_diff_ev_and_captain_differential():
    analysis = {
        "league": {"name": "L"}, "user": {"player_name": "Me", "rank": 3, "total": 100},
        "rivals_above": [], "rivals_below": [],
    }
    candidates = [{
        "id": 1, "web_name": "A", "team_short": "AAA", "model_xpts_horizon": 12.0,
        "model_xpts_per_gw": {"gw1": 4.0}, "fixtures": {"gw1": "BBB/h"},
        "league_ownership": 0.06, "differential_ev": 5.4,
    }]
    cap = {"reason": "Cap faces a hard run; A is a 6%-owned differential (+5.4 diff-EV)."}
    msg = league_strategy.build_user_message(analysis, "differential", candidates,
                                             fixture_ticker=None, captain_differential=cap)
    assert "diff_ev=5.4" in msg
    assert "league_own=0.06" in msg
    assert "Cap faces a hard run" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_narrative_prompt.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'build_user_message'`.

- [ ] **Step 3: Add `diff_ev` to `_short_candidate`**

In `src/league_strategy.py` `_short_candidate`, change the final return so the last line includes diff-EV:
```python
        return (
            f"id={c['id']} {c.get('web_name')} ({c.get('team_short')}) "
            f"xPts={c.get('model_xpts_horizon', '?')} [{per_gw}] fixtures: {fixes}{run} "
            f"league_own={c.get('league_ownership', '?')} diff_ev={c.get('differential_ev', '?')}"
        )
```

- [ ] **Step 4: Extract `build_user_message` and thread `captain_differential`**

In `src/league_strategy.py`, extract the user-message construction from `_llm_narrative` into a module-level function. Add this function **above** `_llm_narrative`:
```python
def build_user_message(analysis, mode, candidates, fixture_ticker=None, captain_differential=None):
    def _short_rival(r):
        return f"{r.get('player_name')} #{r.get('rank')} ({r.get('total')} pts, GW {r.get('event_total')})"

    fixture_outlook_short = "n/a"
    if fixture_ticker:
        easiest = ", ".join(fixture_ticker.get("easiest_runs") or []) or "?"
        hardest = ", ".join(fixture_ticker.get("hardest_runs") or []) or "?"
        fixture_outlook_short = (
            f"next {fixture_ticker.get('horizon_gws')} GWs — easiest runs: {easiest}; "
            f"hardest runs: {hardest} (lower fixture_run = easier)"
        )

    captain_line = "none"
    if captain_differential:
        captain_line = captain_differential.get("reason") or "present"

    return USER_TEMPLATE.format(
        mode=mode,
        fixture_outlook_short=fixture_outlook_short,
        captain_differential_short=captain_line,
        league_name=analysis["league"].get("name"),
        user_name=(analysis["user"] or {}).get("player_name"),
        user_rank=(analysis["user"] or {}).get("rank"),
        user_total=(analysis["user"] or {}).get("total"),
        rivals_above_short=" / ".join(_short_rival(r) for r in analysis["rivals_above"]) or "none",
        rivals_below_short=" / ".join(_short_rival(r) for r in analysis["rivals_below"]) or "none",
        horizon_gws=len(next(iter(candidates), {}).get("model_xpts_per_gw") or {}) or 3,
        candidates_short="\n".join(_short_candidate(c) for c in candidates) or "(none)",
    )
```
Note: `_short_candidate` is defined as a nested function inside `_llm_narrative` today. Move it to module level (place it directly above `build_user_message`, unindented, unchanged except the Step 3 edit) so `build_user_message` can call it.

- [ ] **Step 5: Update `USER_TEMPLATE` and `SYSTEM_PROMPT`**

In `src/league_strategy.py`, in `USER_TEMPLATE`, add a captain line after the `Fixture outlook (xG model): {fixture_outlook_short}` line:
```
Captain differential: {captain_differential_short}
```
And update the rules block in `USER_TEMPLATE` so a rule reads:
```
- Every rationale MUST quote diff_ev and league_own for the player (e.g. '+5.4 diff-EV at 6% league own') plus at least one fixture.
- If Captain differential is not 'none', mention it in the headline or watchouts.
```
In `SYSTEM_PROMPT`, change the "Use ONLY numbers from the input" clause to also list `differential_ev` and `league_ownership`:
```python
    "Use ONLY numbers from the input — model_xpts_horizon, differential_ev, league_ownership, fixtures, point gaps, ranks. "
```

- [ ] **Step 6: Make `_llm_narrative` call `build_user_message`**

In `src/league_strategy.py`, change `_llm_narrative`'s signature to accept `captain_differential=None`:
```python
def _llm_narrative(analysis, mode, candidates, model=None, fixture_ticker=None, captain_differential=None):
```
and replace its inline `user_msg = USER_TEMPLATE.format(...)` block (and the now-moved `_short_candidate`/`_short_rival`/`fixture_outlook_short` locals) with:
```python
    user_msg = build_user_message(analysis, mode, candidates,
                                  fixture_ticker=fixture_ticker,
                                  captain_differential=captain_differential)
```
Keep the rest of `_llm_narrative` (Anthropic client call, JSON parse) unchanged.

- [ ] **Step 7: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS (all — the new narrative test plus Tasks 1-3 and sub-project-1 tests). Confirms the `build_strategy` → `_llm_narrative` kwarg wiring from Task 3 Step 4 is now consistent.

- [ ] **Step 8: Commit**

```bash
git add src/league_strategy.py tests/test_narrative_prompt.py
git commit -m "feat: cite differential EV + captain-differential in league narrative"
```

---

### Task 5: Spot-check script

**Files:**
- Create: `scripts/spotcheck_league_ev.py`

**Interfaces:**
- Consumes: `build_strategy` / `_candidate_targets` under both flag states; live FPL data.
- Produces: a console comparison of legacy vs EV top-10 + the captain-differential; no importable API.

- [ ] **Step 1: Write the spot-check script**

Create `scripts/spotcheck_league_ev.py`:
```python
"""
Spot-check for ownership-adjusted EV ranking.

For a sample entry+league, prints the legacy raw-xPts top-10 vs the differential-EV
top-10 side by side, plus the captain-differential result. Review that highly
league-owned premiums drop and genuine low-owned differentials rise.

Usage:
    .venv/bin/python -m scripts.spotcheck_league_ev <entry_id> <league_id> [event_id]
"""
import sys

from src import config, fpl_client, transforms, projections, league_strategy


def main():
    if len(sys.argv) < 3:
        print("usage: python -m scripts.spotcheck_league_ev <entry_id> <league_id> [event_id]")
        return
    entry_id, league_id = int(sys.argv[1]), int(sys.argv[2])
    bootstrap = fpl_client.get_bootstrap()
    fixtures = transforms.fixtures_df(fpl_client.get_fixtures())
    elements_df, teams_df, _ = transforms.tables_from_bootstrap(bootstrap)
    teams_short = teams_df.set_index("id")["short_name"].to_dict()
    events = bootstrap.get("events", []) or []
    gw = int(sys.argv[3]) if len(sys.argv) > 3 else (
        next((e["id"] for e in events if e.get("is_next")), None)
        or next((e["id"] for e in events if not e.get("finished")), 1))

    proj = projections.project_elements_next_gws(elements_df, fixtures, teams_short, gw_start=gw, horizon_gws=3)
    analysis = league_strategy.analyze_league(entry_id, league_id, gw)
    if analysis.get("error"):
        print("analyze_league error:", analysis["error"])
        return
    meta = league_strategy._player_meta(bootstrap, projections_df=proj)
    templates = league_strategy.ownership_ev.compute_position_templates(meta)

    def top10(mode, flag):
        config.LEAGUE_EV_RANKING = flag
        rows = league_strategy._candidate_targets(analysis, meta, mode, templates)
        return [(r.get("web_name"), r.get("league_ownership"),
                 r.get("model_xpts_horizon"), r.get("differential_ev")) for r in rows]

    for mode in ("chase", "defend", "differential"):
        print(f"\n===== mode: {mode} =====")
        legacy = top10(mode, False)
        ev = top10(mode, True)
        print(f"{'LEGACY (raw xPts)':38} | EV (differential)")
        for i in range(max(len(legacy), len(ev))):
            l = legacy[i] if i < len(legacy) else ("", "", "", "")
            e = ev[i] if i < len(ev) else ("", "", "", "")
            print(f"{str(l[0]):20} own={str(l[1]):6} xpts={str(l[2]):6} | "
                  f"{str(e[0]):20} own={str(e[1]):6} ev={str(e[3]):6}")

    from src import fixture_difficulty  # ticker for captain differential, best-effort
    ticker = None
    try:
        match_df = fixture_difficulty.load_match_history()
        team_match_xg = fixture_difficulty.build_team_match_xg(match_df)
        ratings = fixture_difficulty.resolve_team_ratings(team_match_xg, teams_short_map=teams_short)
        ratings = fixture_difficulty.apply_knowledge_discount(ratings, teams_short_map=teams_short)
        ticker = fixture_difficulty.build_fixture_ticker(ratings, fixtures, teams_short, gw, horizon_gws=3)
    except Exception as exc:
        print(f"\n(ticker unavailable: {exc})")
    cap = league_strategy.detect_captain_differential(analysis, meta, templates, ticker)
    print("\n===== captain_differential =====")
    print(cap.get("reason") if cap else "none")


if __name__ == "__main__":
    main()
```
The ticker build mirrors `build_fixture_difficulty_payload` in `api/main.py` (real signature: `build_fixture_ticker(ratings, fixtures, teams_short_map, gw_start, horizon_gws=6)`). The captain-differential section is best-effort and must not crash the ranking comparison.

- [ ] **Step 2: Run the spot-check (with a real entry+league)**

Run: `.venv/bin/python -m scripts.spotcheck_league_ev <your_entry_id> <your_league_id>`
Expected: three mode tables (legacy vs EV) + a captain-differential line. Confirm highly league-owned premiums fall in the EV column and low-owned high-xPts players rise.

- [ ] **Step 3: Commit**

```bash
git add scripts/spotcheck_league_ev.py
git commit -m "feat: add ownership-EV spot-check script"
```

---

## Self-Review

**Spec coverage:**
- §3 ownership_ev module (templates, differential_ev, annotate) → Task 1. ✓
- §4 ranking wiring + flag + all 3 modes + reversibility → Task 2. ✓
- §5 captain-differential → Task 3. ✓
- §6 narrative integration → Task 4. ✓
- §7 output surface (`differential_ev`/`template_xpts` on candidates via annotate; `captain_differential` on response) → Tasks 2 + 3. ✓
- §8 config → Task 1 Step 1. ✓
- §9 spot-check → Task 5. ✓
- §10 tests → Tasks 1-4. ✓
- §11 rollout (default True) → Task 1 config. ✓

**Placeholder scan:** No TBD/TODO. The only "adjust if signature differs" note (Task 5 ticker) is a bounded, explained best-effort fallback, not a spec gap. ✓

**Type consistency:** `compute_position_templates`/`annotate_candidates`/`differential_ev`/`xpts_of` signatures consistent between Task 1 (define) and Tasks 2,3 (call). `_candidate_targets(...,templates)` consistent between Task 2 (define) and Task 5 (call). `_rank_and_slice`/`_ep` defined Task 2, used Task 2. `detect_captain_differential(analysis, elements_meta, templates, fixture_ticker)` consistent Task 3 (define) ↔ Task 3 Step 4 + Task 5 (call). `build_user_message(...)`/`_llm_narrative(...captain_differential=None)` consistent Task 4 (define) ↔ Task 3 Step 4 (call). ✓
```
