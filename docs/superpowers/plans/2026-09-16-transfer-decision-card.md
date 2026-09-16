# Transfer Decision Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the prose transfer verdict with a structured decision card that shows this-GW and horizon gains with explicit GW ranges, and make "Apply" apply the plan's move instead of the beam's.

**Architecture:** Backend `plan_transfers` gains a `verdict_detail` dict (derived from data it already computes; decision logic untouched) and a one-clause `reasoning`. A new pure module `src/plan_merge.py` moves the plan's first-GW moves to the front of `transfers.moves` so the existing step machinery applies the recommendation. Frontend renders `verdict_detail` in a new `DecisionCard` (falls back to the old banner when absent), relabels the staircase with GW ranges, and demotes beam options to a collapsed "Alternatives" list.

**Tech Stack:** Python 3 / pandas / pytest (backend, `FPL/`), React 18 + TypeScript + Vite + vitest + @testing-library/react + shadcn/ui + Tailwind (frontend, `FPL-Assistant-Front/fpl-decision-hub/`).

**Spec:** `FPL/docs/superpowers/specs/2026-09-16-transfer-decision-card-design.md`

## Global Constraints

- Backend repo root: `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL`. Tests: `python -m pytest -q` (venv at `.venv`). Baseline: full suite green before Task 1 (435 tests).
- Frontend repo root: `/Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub`. Checks: `npm run typecheck && npm run lint && npm test`.
- Branches: backend `feature/decision-card` off `feature/xpts-components`; frontend `feature/decision-card` off `feature/stack-odds`.
- No change to thresholds, horizons, `_best_swap`, `suggest_transfers`, chip logic, or config values.
- `verdict_detail` field names exactly as in the spec: `action, horizon{start_gw,end_gw,n}, ft_before, ft_after, threshold, moves[], this_gw_gain, horizon_gain, hit_cost, plan_net, roll_alternative, next_move`.
- Frontend `data-testid="plan-verdict-banner"` must survive on the new card (existing tests anchor on it).
- Payload is additive: an old frontend ignores `verdict_detail`/`in_plan`; a new frontend on an old backend falls back to `reasoning`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Deviation from spec, deliberate: the alternatives label reads "best single swaps over N GW(s)" (N = beam `transfer_plan.horizon_gws`), not "this GW only" — the beam scores over the display horizon, so "this GW only" would be the same lie the card is fixing.

---

## File map

Backend
- Modify `src/transfer_planner.py` — add `_detail_move`, `_verdict_detail`; rewrite `_verdict_and_reasoning` (takes `gws`); attach `verdict_detail` in `plan_transfers`; drop the appended counterfactual clause.
- Create `src/plan_merge.py` — `merge_plan_moves_into_preview(preview, plan_horizon)`.
- Modify `api/main.py:26` (import), `:1449-1456` (move annotate + `out["transfers"]` after the plan block), `:1497` (call merge).
- Modify `CLAUDE.md:110-113` — one line each for `verdict_detail` and the merge.
- Create `tests/test_verdict_detail.py`, `tests/test_plan_merge.py`.
- Modify `tests/test_plan_one_move.py:43-49, 78-84` — assert on `verdict_detail` instead of prose.

Frontend
- Modify `src/lib/fplAssistantApi.ts:138-145, 157-192` — `in_plan`, `this_gw_gain`, `FplTransferVerdictMove`, `FplTransferVerdictDetail`, `verdict_detail`.
- Create `src/components/DecisionCard.tsx` (+ `DecisionCard.test.tsx`) — card + legacy fallback + `fmtGain`/`gwRange`.
- Modify `src/components/RecommendationsPanel.tsx:321-323, 330-480` — remove `VerdictBanner`, use `DecisionCard`, relabel `HorizonTransferPlan`, thread apply props.
- Modify `src/components/TransferPlanner.tsx` — collapsed alternatives, `in plan` chip, drop top-level Apply and "not in plan" badge, drop `planHorizon`/`planVerdict`/`onApplyNextTransfer`/`canApplyNextTransfer` props.
- Modify `src/components/TransferPlanner.test.tsx`, `src/components/RecommendationsPanel.test.tsx`.

---

### Task 1: `verdict_detail` + short `reasoning` in `plan_transfers`

**Files:**
- Modify: `src/transfer_planner.py:134-153` (after `_move_record`), `:304-326` (result build), `:330-360` (counterfactual), `:363-397` (`_verdict_and_reasoning`)
- Create: `tests/test_verdict_detail.py`
- Modify: `tests/test_plan_one_move.py:43-49`, `:78-84`

**Interfaces:**
- Consumes: `plan_transfers(...)` result dict as it exists today (`plan`, `gws`, `verdict`, `total_net_gain`, `first_gw_ft_before/after`, `roll_alternative_net_gain`).
- Produces: `result["verdict_detail"]` (schema in Global Constraints). Task 2 reads `verdict_detail.action` and `verdict_detail.moves[*].{sell,buy,position,this_gw_gain,horizon_gain}`. Task 4/5 mirror the schema in TS.

- [ ] **Step 1: Create the branch and confirm the baseline is green**

```bash
cd /Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL
git checkout -b feature/decision-card
python -m pytest -q 2>&1 | tail -3
```
Expected: `435 passed` (or the current count; note it).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_verdict_detail.py`:

```python
"""verdict_detail: the structured twin of the prose `reasoning`."""
import pandas as pd

from src import transfer_planner as tp


def _frame(players, gws=(10, 11)):
    """players: dicts with id, pos, xpts (float or {gw: float}), optional price/team/status/chance."""
    recs = []
    for p in players:
        r = {
            "id": p["id"],
            "web_name": f"P{p['id']}",
            "pos": p["pos"],
            "team_short": p.get("team", f"T{p['id']}"),
            "price_m": p.get("price", 5.0),
            "status": p.get("status", "a"),
            "chance_of_playing_next_round": p.get("chance", 100),
        }
        xp = p["xpts"]
        for g in gws:
            r[f"xpts_gw{g}"] = xp[g] if isinstance(xp, dict) else xp
        recs.append(r)
    return pd.DataFrame(recs)


def _spend_market():
    return [
        {"id": 1, "pos": "MID", "xpts": 2.0},
        {"id": 2, "pos": "MID", "xpts": 2.0},
        {"id": 3, "pos": "MID", "xpts": 9.0},
        {"id": 4, "pos": "MID", "xpts": 8.0},
    ]


def test_spend_detail_carries_both_gains_and_horizon():
    plan = tp.plan_transfers(_frame(_spend_market()), squad_ids=[1, 2], gws=[10, 11],
                             itb_m=0.0, start_ft=1, allow_hits=False, min_gain=2.0,
                             max_moves_per_gw=1)
    d = plan["verdict_detail"]
    assert d["action"] == "spend"
    assert d["horizon"] == {"start_gw": 10, "end_gw": 11, "n": 2}
    assert d["ft_before"] == 1 and d["ft_after"] == 0
    assert d["threshold"] == 2.0
    assert len(d["moves"]) == 1
    m = d["moves"][0]
    assert m["buy"]["id"] == 3
    assert m["this_gw_gain"] == 7.0          # 9 - 2 in GW10
    assert m["horizon_gain"] == 14.0         # (9+9) - (2+2)
    assert m["forced_injury"] is False
    assert d["this_gw_gain"] == 7.0 and d["horizon_gain"] == 14.0
    assert d["hit_cost"] == 0.0
    assert d["plan_net"] == plan["total_net_gain"]
    assert d["next_move"] is None
    # The counterfactual ran and lost; it is reported, not folded into prose.
    assert d["roll_alternative"] is not None
    assert d["roll_alternative"]["net"] == plan["roll_alternative_net_gain"]
    assert d["roll_alternative"]["gw"] == 11
    assert len(d["roll_alternative"]["moves"]) >= 1
    assert "beats rolling" not in plan["reasoning"]
    assert "threshold" not in plan["reasoning"]
    assert "this GW" in plan["reasoning"] and "GW10-11" in plan["reasoning"]


def test_roll_detail_when_nothing_clears_the_bar():
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "DEF", "price": 4.0, "xpts": 3.0},
        {"id": 2, "pos": "DEF", "price": 4.0, "xpts": 3.5},
    ]), squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    d = plan["verdict_detail"]
    assert d["action"] == "roll"
    assert d["moves"] == []
    assert d["this_gw_gain"] == 0.0 and d["horizon_gain"] == 0.0
    assert d["ft_before"] == 1 and d["ft_after"] == 2
    assert d["roll_alternative"] is None       # no spend to compare against
    assert d["next_move"] is None
    assert "roll" in plan["reasoning"].lower()


def test_roll_detail_names_the_next_planned_move():
    # GW10: buying 2 gains nothing (1 vs 5). GW11: gains 4 -> plan moves then.
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "MID", "xpts": {10: 5.0, 11: 5.0}},
        {"id": 2, "pos": "MID", "xpts": {10: 1.0, 11: 9.0}},
    ]), squad_ids=[1], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    d = plan["verdict_detail"]
    assert d["action"] == "roll"
    assert d["next_move"] is not None
    assert d["next_move"]["gw"] == 11
    assert d["next_move"]["moves"][0]["buy"]["id"] == 2
    assert d["next_move"]["horizon_gain"] == 4.0
    assert "GW11" in plan["reasoning"]


def test_counterfactual_flip_reports_rejected_spend():
    # Spend now: (1+9)-(2+2)=6 at GW10, then +7 at GW11 = 13.
    # Roll: two swaps at GW11 = 7+7 = 14 > 13 -> verdict flips to roll.
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "MID", "xpts": 2.0},
        {"id": 2, "pos": "MID", "xpts": 2.0},
        {"id": 3, "pos": "MID", "xpts": {10: 1.0, 11: 9.0}},
        {"id": 4, "pos": "MID", "xpts": {10: 1.0, 11: 9.0}},
    ]), squad_ids=[1, 2], gws=[10, 11], itb_m=0.0, start_ft=1, allow_hits=False,
        min_gain=2.0, max_moves_per_gw=1)
    assert plan["verdict"] == "roll"
    d = plan["verdict_detail"]
    assert d["action"] == "roll"
    assert d["plan_net"] == 14.0
    assert d["roll_alternative"]["net"] == 13.0
    assert d["roll_alternative"]["gw"] == 10
    assert len(d["roll_alternative"]["moves"]) == 1
    assert d["next_move"]["gw"] == 11
    assert len(d["next_move"]["moves"]) == 2
    assert "roll" in plan["reasoning"].lower()


def test_forced_injury_detail():
    plan = tp.plan_transfers(_frame([
        {"id": 1, "pos": "DEF", "price": 4.0, "xpts": 0.2, "status": "i"},
        {"id": 2, "pos": "DEF", "price": 4.0, "xpts": 1.0},
        {"id": 3, "pos": "MID", "price": 8.0, "xpts": 6.0},
    ]), squad_ids=[1, 3], gws=[10, 11], itb_m=0.0, start_ft=1, min_gain=2.0)
    d = plan["verdict_detail"]
    assert d["action"] == "spend_forced_injury"
    assert d["moves"][0]["forced_injury"] is True
    assert d["moves"][0]["sell"]["id"] == 1
    assert d["roll_alternative"] is None       # urgency skips the comparison


def test_hits_detail_quotes_hit_cost():
    players = [{"id": i, "pos": "MID", "xpts": 2.0} for i in range(1, 13)]
    market = players + [
        {"id": 13, "pos": "MID", "xpts": 9.0},
        {"id": 14, "pos": "MID", "xpts": 9.0},
    ]
    plan = tp.plan_transfers(_frame(market), squad_ids=list(range(1, 13)), gws=[10, 11],
                             itb_m=0.0, start_ft=1, allow_hits=True, min_gain=2.0)
    first = plan["plan"][0]
    d = plan["verdict_detail"]
    assert d["hit_cost"] == first["hit_cost"]
    assert d["horizon_gain"] == first["gw_gain"]
    assert len(d["moves"]) == len(first["moves"])
    if first["hits"] > 0:
        assert "hit" in plan["reasoning"]
```

Then edit `tests/test_plan_one_move.py`:

Replace lines 43-49 (`test_spend_reasoning_quotes_roll_alternative`) with:

```python
def test_spend_carries_roll_alternative_detail():
    plan = tp.plan_transfers(_proj_frame(_two_upgrade_market()), squad_ids=[1, 2],
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0, max_moves_per_gw=1)
    assert plan["verdict"] == "spend"
    alt = plan["verdict_detail"]["roll_alternative"]
    assert alt is not None
    assert alt["net"] == plan["roll_alternative_net_gain"]
```

Replace lines 78-84 (`test_reasoning_names_the_counterfactual_double`) with:

```python
def test_detail_names_the_counterfactual_double():
    plan = tp.plan_transfers(_proj_frame(_two_upgrade_market()), squad_ids=[1, 2],
                             gws=[10, 11], itb_m=0.0, start_ft=1,
                             allow_hits=False, min_gain=2.0, max_moves_per_gw=1)
    assert plan["verdict"] == "spend"
    # The counterfactual's actual moves are reported, not just a net.
    alt_moves = plan["verdict_detail"]["roll_alternative"]["moves"]
    assert len(alt_moves) == 2
    assert {m["buy"]["id"] for m in alt_moves} == {3, 4}
```

- [ ] **Step 3: Run the new tests to verify they fail**

```bash
python -m pytest tests/test_verdict_detail.py tests/test_plan_one_move.py -q 2>&1 | tail -5
```
Expected: FAIL with `KeyError: 'verdict_detail'`.

- [ ] **Step 4: Implement `_detail_move` and `_verdict_detail`**

In `src/transfer_planner.py`, insert after `_move_record` (after line 153):

```python
def _detail_move(m):
    """Compact move for verdict_detail from a `_move_record` output."""
    return {
        "sell": m["sell"],
        "buy": m["buy"],
        "position": m.get("position"),
        "this_gw_gain": round(float(m.get("this_gw_gain", 0.0)), 2),
        "horizon_gain": round(float(m["score_gain"]), 2),
        "forced_injury": bool(m.get("forced_injury", False)),
        "h2h_conflicts": list(m.get("h2h_conflicts") or []),
    }


def _verdict_detail(result, min_gain, rejected=None):
    """Structured twin of `reasoning`, built from the finished plan.

    `rejected` is the plan the roll-vs-move counterfactual lost: the roll
    walk when the verdict is spend, or the spend walk when the verdict was
    flipped to roll. None when no comparison ran (injury urgency, roll with
    nothing to compare, single-GW horizon)."""
    plan = result.get("plan") or []
    gws = list(result.get("gws") or [])
    first = plan[0] if plan else None
    moves = ([_detail_move(m) for m in first["moves"]]
             if first and first["action"] == "transfer" else [])
    detail = {
        "action": result["verdict"],
        "horizon": {
            "start_gw": gws[0] if gws else None,
            "end_gw": gws[-1] if gws else None,
            "n": len(gws),
        },
        "ft_before": int(result["first_gw_ft_before"]),
        "ft_after": int(result["first_gw_ft_after"]),
        "threshold": float(min_gain),
        "moves": moves,
        "this_gw_gain": round(sum(m["this_gw_gain"] for m in moves), 2),
        "horizon_gain": round(sum(m["horizon_gain"] for m in moves), 2),
        "hit_cost": float(first["hit_cost"]) if first else 0.0,
        "plan_net": float(result["total_net_gain"]),
        "roll_alternative": None,
        "next_move": None,
    }
    if result["verdict"] == "roll":
        later = next((p for p in plan[1:] if p["action"] == "transfer"), None)
        if later is not None:
            detail["next_move"] = {
                "gw": int(later["gw"]),
                "moves": [_detail_move(m) for m in later["moves"]],
                "horizon_gain": round(float(later["gw_gain"]), 2),
            }
    if rejected is not None:
        alt_first = next((p for p in (rejected.get("plan") or [])
                          if p["action"] == "transfer"), None)
        detail["roll_alternative"] = {
            "net": float(rejected["total_net_gain"]),
            "gw": int(alt_first["gw"]) if alt_first else None,
            "moves": [_detail_move(m) for m in alt_first["moves"]] if alt_first else [],
        }
    return detail
```

- [ ] **Step 5: Rewrite `_verdict_and_reasoning` to take `gws` and emit one clause**

Replace the whole function (lines 363-397) with:

```python
def _gw_range(gws):
    if not gws:
        return "the horizon"
    return f"GW{gws[0]}" if gws[0] == gws[-1] else f"GW{gws[0]}-{gws[-1]}"


def _verdict_and_reasoning(plan, min_gain, ft_cap, gws):
    """Top-level verdict for the first horizon GW: an injury-forced sell always
    wins (it isn't optional), otherwise it's whichever the greedy walk chose
    (spend now vs roll the FT). One clause; the numbers live in verdict_detail."""
    first = plan[0] if plan else None
    rng = _gw_range(gws)
    forced_moves = [m for m in first["moves"] if m.get("forced_injury")] if first else []
    if forced_moves:
        flagged = ", ".join(m["sell"]["name"] for m in forced_moves)
        reasoning = (f"Flagged player ({flagged}) in your likely XI -- replacing "
                     f"them takes priority over rolling, even below the usual gain bar.")
        return "spend_forced_injury", reasoning

    if first and first["action"] == "transfer":
        names = ", ".join(f"{m['sell']['name']} -> {m['buy']['name']}" for m in first["moves"])
        this_gw = round(sum(float(m.get("this_gw_gain", 0.0)) for m in first["moves"]), 1)
        if first.get("hits"):
            reasoning = (f"Move now: {names} (net +{first['net_gain']} over {rng} "
                         f"after -{first['hit_cost']:g} in hits).")
        else:
            reasoning = (f"Move now: {names} (+{this_gw} this GW, "
                         f"+{first['gw_gain']} over {rng}).")
        return "spend", reasoning

    if first:
        ft_after = min(int(ft_cap), first["free_transfers_before"] + 1)
        nxt = next((p for p in plan[1:] if p["action"] == "transfer"), None)
        if nxt:
            names = ", ".join(f"{m['sell']['name']} -> {m['buy']['name']}" for m in nxt["moves"])
            follow = f" Next planned move: {names} in GW{nxt['gw']} (+{nxt['gw_gain']})."
        else:
            follow = f" No move clears +{min_gain} over {rng}."
        reasoning = (f"Roll: bank the FT ({first['free_transfers_before']}->{ft_after})."
                     f"{follow}")
        return "roll", reasoning

    return "roll", "No horizon GWs."
```

- [ ] **Step 6: Wire `verdict_detail` into `plan_transfers` and drop the appended clause**

At line ~304 change the call to `verdict, reasoning = _verdict_and_reasoning(plan, min_gain, ft_cap, gws)`.

After the `result = {...}` literal (ends ~line 325) add:

```python
    result["verdict_detail"] = _verdict_detail(result, min_gain)
```

In the counterfactual block replace from `if alt_net > float(result["total_net_gain"]) + 1e-9:` to the end of the block with:

```python
        if alt_net > float(result["total_net_gain"]) + 1e-9:
            alt["roll_alternative_net_gain"] = float(alt_net)
            alt["verdict"] = "roll"
            alt["reasoning"] = (
                f"Roll: banking beats moving now (+{alt_net} vs "
                f"+{result['total_net_gain']} over {_gw_range(gws)}); "
                f"next move {alt_moves_txt} in GW{alt_first['gw'] if alt_first else gws[-1]}."
            )
            alt["verdict_detail"] = _verdict_detail(alt, min_gain, rejected=result)
            return alt
        result["verdict_detail"] = _verdict_detail(result, min_gain, rejected=alt)

    return result
```

(The old `base_reasoning ... beats rolling ...` two statements are deleted.)

- [ ] **Step 7: Run the planner test modules**

```bash
python -m pytest tests/test_verdict_detail.py tests/test_plan_one_move.py tests/test_transfer_planner.py tests/test_plan_xi_awareness.py tests/test_transfer_pos_bar.py -q 2>&1 | tail -5
```
Expected: all PASS. If `test_roll_detail_names_the_next_planned_move` fails on `horizon_gain`, check `gw_gain` rounding (`round(..., 2)` in the plan entry) — assert against `plan["plan"][1]["gw_gain"]` instead.

- [ ] **Step 8: Full suite, then commit**

```bash
python -m pytest -q 2>&1 | tail -3
git add src/transfer_planner.py tests/test_verdict_detail.py tests/test_plan_one_move.py
git commit -m "feat(transfers): structured verdict_detail beside a one-clause reasoning

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `plan_merge` — plan moves lead `transfers.moves`

**Files:**
- Create: `src/plan_merge.py`
- Create: `tests/test_plan_merge.py`
- Modify: `api/main.py:26` (import), `:1449-1456`, `:1497` (after the plan `try/except`)
- Modify: `CLAUDE.md:110-113`

**Interfaces:**
- Consumes: `transfer_preview` dict from `recommender.suggest_transfers` (`moves[]` in `move_from_seller_buyer` shape, `moves_by_position`, `transfer_plan.transfer_count_built`, `remaining_itb`) and `out["transfer_plan_horizon"]` with `verdict_detail` from Task 1.
- Produces: `merge_plan_moves_into_preview(preview: dict | None, plan_horizon: dict | None) -> dict | None` — mutates and returns `preview`. Every move gains `in_plan: bool`; plan moves gain `this_gw_gain`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plan_merge.py`:

```python
from src import plan_merge


def _p(pid, name="X", team="TTT", price=5.0):
    return {"id": pid, "name": name, "team": team, "price": price}


def _beam(*pairs):
    return {
        "moves": [
            {"position": "MID", "sell": _p(s), "buy": _p(b), "score_gain": 3.0,
             "buy_hot_score": 1.5, "buy_set_piece_score": 0.2}
            for s, b in pairs
        ],
        "moves_by_position": {"MID": len(pairs)},
        "transfer_plan": {"free_transfers": 1, "horizon_gws": 3, "hit_cap": 0,
                          "transfer_count_target": 1, "transfer_count_built": len(pairs)},
        "remaining_itb": 0.3,
    }


def _plan(action, moves, bank_after=1.2):
    return {
        "verdict": action,
        "plan": [{"gw": 5, "action": "transfer" if moves else "roll", "moves": [],
                  "bank_after": bank_after}],
        "verdict_detail": {
            "action": action,
            "moves": [
                {"position": "DEF", "sell": _p(s, "S"), "buy": _p(b, "B"),
                 "this_gw_gain": 0.9, "horizon_gain": 2.8, "forced_injury": False,
                 "h2h_conflicts": []}
                for s, b in moves
            ],
        },
    }


def test_spend_plan_moves_lead_and_beam_survivors_follow():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2), (3, 4)), _plan("spend", [(7, 8)]))
    ids = [(m["sell"]["id"], m["buy"]["id"]) for m in preview["moves"]]
    assert ids == [(7, 8), (1, 2), (3, 4)]
    assert [m["in_plan"] for m in preview["moves"]] == [True, False, False]
    assert preview["moves"][0]["score_gain"] == 2.8
    assert preview["moves"][0]["this_gw_gain"] == 0.9
    assert preview["moves"][0]["position"] == "DEF"
    assert preview["moves_by_position"] == {"DEF": 1, "MID": 2}
    assert preview["transfer_plan"]["transfer_count_built"] == 3
    assert preview["remaining_itb"] == 1.2


def test_duplicate_pair_reuses_the_beam_record():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2), (3, 4)), _plan("spend", [(3, 4)]))
    ids = [(m["sell"]["id"], m["buy"]["id"]) for m in preview["moves"]]
    assert ids == [(3, 4), (1, 2)]
    lead = preview["moves"][0]
    assert lead["in_plan"] is True
    assert lead["buy_hot_score"] == 1.5          # beam enrichment kept
    assert lead["this_gw_gain"] == 0.9           # plan slice added
    assert preview["transfer_plan"]["transfer_count_built"] == 2


def test_forced_injury_counts_as_spend():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2)), _plan("spend_forced_injury", [(7, 8)]))
    assert preview["moves"][0]["sell"]["id"] == 7


def test_roll_leaves_beam_order_and_flags_false():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2), (3, 4)), _plan("roll", []))
    ids = [(m["sell"]["id"], m["buy"]["id"]) for m in preview["moves"]]
    assert ids == [(1, 2), (3, 4)]
    assert all(m["in_plan"] is False for m in preview["moves"])
    assert preview["remaining_itb"] == 0.3


def test_missing_plan_or_detail_is_a_noop_with_flags():
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2)), None)
    assert preview["moves"][0]["in_plan"] is False
    preview = plan_merge.merge_plan_moves_into_preview(_beam((1, 2)), {"verdict": "spend"})
    assert preview["moves"][0]["in_plan"] is False


def test_non_dict_preview_returned_untouched():
    assert plan_merge.merge_plan_moves_into_preview(None, _plan("spend", [(7, 8)])) is None
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_plan_merge.py -q 2>&1 | tail -3
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.plan_merge'`.

- [ ] **Step 3: Implement `src/plan_merge.py`**

```python
"""Make the multi-GW plan's first-GW moves the applyable moves.

`build_recommendations` emits two transfer views: the single-GW beam list
(`transfers.moves`, which the frontend's Apply buttons step through via
`squad_with_transfers_steps`) and the multi-GW plan (`transfer_plan_horizon`,
the actual recommendation). Putting the plan's first-GW moves at the front of
the beam list makes "Apply" apply the recommendation; the beam survivors follow
as alternatives. Pure, no network, never raises on malformed input.
"""


def _pair(m):
    try:
        return int(m["sell"]["id"]), int(m["buy"]["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _as_beam_move(m):
    return {
        "position": m.get("position"),
        "sell": dict(m["sell"]),
        "buy": dict(m["buy"]),
        "score_gain": round(float(m.get("horizon_gain", 0.0)), 2),
    }


def merge_plan_moves_into_preview(preview, plan_horizon):
    """Mutates and returns `preview`. Every move gets `in_plan`; on a spend
    verdict the plan's first-GW moves lead the list (deduplicated by
    sell/buy pair, reusing the beam record when one matches so its hot/set-piece
    enrichment survives)."""
    if not isinstance(preview, dict):
        return preview
    beam = [m for m in (preview.get("moves") or []) if isinstance(m, dict)]
    for m in beam:
        m.setdefault("in_plan", False)
    preview["moves"] = beam

    detail = (plan_horizon or {}).get("verdict_detail") if isinstance(plan_horizon, dict) else None
    if not isinstance(detail, dict) or detail.get("action") not in ("spend", "spend_forced_injury"):
        return preview

    beam_by_pair = {_pair(m): m for m in beam}
    plan_moves, plan_pairs = [], set()
    for pm in detail.get("moves") or []:
        pair = _pair(pm) if isinstance(pm, dict) else None
        if pair is None or pair in plan_pairs:
            continue
        base = beam_by_pair.get(pair)
        mv = dict(base) if base else _as_beam_move(pm)
        mv["in_plan"] = True
        mv["this_gw_gain"] = round(float(pm.get("this_gw_gain", 0.0)), 2)
        plan_moves.append(mv)
        plan_pairs.add(pair)
    if not plan_moves:
        return preview

    merged = plan_moves + [m for m in beam if _pair(m) not in plan_pairs]
    preview["moves"] = merged

    by_pos = {}
    for m in merged:
        pos = m.get("position") or "UNK"
        by_pos[pos] = by_pos.get(pos, 0) + 1
    preview["moves_by_position"] = by_pos

    tp = preview.get("transfer_plan")
    if isinstance(tp, dict):
        tp["transfer_count_built"] = len(merged)

    first = next((p for p in (plan_horizon.get("plan") or []) if isinstance(p, dict)), None)
    if first is not None and first.get("bank_after") is not None:
        try:
            preview["remaining_itb"] = round(float(first["bank_after"]), 1)
        except (TypeError, ValueError):
            pass
    return preview
```

- [ ] **Step 4: Run merge tests**

```bash
python -m pytest tests/test_plan_merge.py -q 2>&1 | tail -3
```
Expected: 6 passed.

- [ ] **Step 5: Wire into `api/main.py`**

Line 26: add `plan_merge` to the `from src import ...` list (alphabetical, after `optimizer`).

Delete lines 1449-1456 (the `if include_transfers:` block that calls `annotate_moves_next_fixture` and sets `out["transfers"]`).

Immediately after the plan block's `except Exception as e: logger.warning("horizon transfer plan failed: %s", e)` (line ~1497) insert:

```python
    if include_transfers:
        # The plan is the recommendation: its first-GW moves lead the
        # applyable list so "Apply" applies what the verdict says.
        try:
            plan_merge.merge_plan_moves_into_preview(
                transfer_preview, out.get("transfer_plan_horizon"))
        except Exception as e:  # noqa: BLE001 - alternatives still render
            logger.warning("plan-move merge failed: %s", e)
        try:
            annotate_moves_next_fixture(
                transfer_preview, elements, fixtures, teams_short, int(optimize_event_id)
            )
        except Exception:
            pass  # fixture labels are cosmetic — never block the response
        out["transfers"] = transfer_preview
```

Check that nothing between the old and new position reads `out["transfers"]`:
```bash
sed -n 1440,1520p api/main.py | grep -n 'out\["transfers"\]'
```
Expected: only the new assignment.

- [ ] **Step 6: Document in `CLAUDE.md`**

After the "Roll-vs-move counterfactual" bullet (line ~113) add:

```markdown
- **Structured verdict** (2026-09-16): `verdict_detail` carries action, GW range, per-move `this_gw_gain`/`horizon_gain`, `plan_net`, the rejected `roll_alternative` and (on roll) `next_move`; `reasoning` is one clause. `src/plan_merge.py` then puts the plan's first-GW moves at the front of `transfers.moves` (`in_plan: true`) so `squad_with_transfers_steps[1]` applies the recommendation; beam survivors follow as alternatives.
```

- [ ] **Step 7: Compile check, full suite, commit**

```bash
python -m py_compile api/main.py src/plan_merge.py
python -m pytest -q 2>&1 | tail -3
git add src/plan_merge.py tests/test_plan_merge.py api/main.py CLAUDE.md
git commit -m "feat(transfers): plan moves lead the applyable list so Apply follows the verdict

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Backend smoke against real data

**Files:** none modified.

- [ ] **Step 1: Run the API locally and fetch a recommendation**

```bash
cd /Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL
grep -n "uvicorn\|REPLAY_MODE\|FPL_ENABLE_DOCS" CLAUDE.md | head
```
Follow the documented local run command (uvicorn with `.env`). Then call `/recommendations` for the test entry the way CLAUDE.md documents (JWT required in prod mode; local dev mode per `staging_test_env` memory), and inspect:

```bash
curl -s "$URL" | python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d['transfer_plan_horizon'].get('verdict_detail'), indent=1)); print([ (m['sell']['name'], m['buy']['name'], m.get('in_plan')) for m in d['transfers']['moves']])"
```
Expected: `verdict_detail` populated; on a spend verdict the first move is `in_plan: True` and matches `verdict_detail.moves[0]`.

- [ ] **Step 2: Record the observed payload in the commit-free scratchpad** (no commit). Note any field that came back `null` unexpectedly and fix before moving on.

---

### Task 4: Frontend types

**Files:**
- Modify: `src/lib/fplAssistantApi.ts:138-145` (`FplTransferMove`), `:157-164` (`FplTransferPlanMove`), `:178-192` (`FplTransferPlanHorizon`)

**Interfaces:**
- Produces (used by Tasks 5-7): `FplTransferVerdictMove`, `FplTransferVerdictDetail`, `FplTransferPlanHorizon.verdict_detail`, `FplTransferMove.in_plan`, `FplTransferMove.this_gw_gain`, `FplTransferPlanMove.this_gw_gain`.

- [ ] **Step 1: Create the branch**

```bash
cd /Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub
git checkout -b feature/decision-card
npm run typecheck && npm test 2>&1 | tail -3
```
Expected: clean baseline; note the test count.

- [ ] **Step 2: Add the types**

Replace `FplTransferMove` (lines 138-145) with:

```ts
export interface FplTransferMove {
  position?: FplPosition;
  sell: FplTransferPlayer;
  buy: FplTransferPlayer;
  score_gain?: number;
  /** Immediate-GW slice of score_gain; present on plan moves only. */
  this_gw_gain?: number;
  /** True when this is the multi-GW plan's first-GW move (leads the list). */
  in_plan?: boolean;
  buy_hot_score?: number;
  buy_set_piece_score?: number;
}
```

In `FplTransferPlanMove` add after `score_gain: number;`:

```ts
  /** Immediate-GW slice of score_gain (score_gain is the remaining-horizon total). */
  this_gw_gain?: number;
  forced_injury?: boolean;
```

Before `FplTransferPlanHorizon` add:

```ts
export interface FplTransferVerdictMove {
  sell: FplTransferPlayer;
  buy: FplTransferPlayer;
  position?: string;
  this_gw_gain: number;
  horizon_gain: number;
  forced_injury?: boolean;
  h2h_conflicts?: string[];
}

/** Structured twin of `reasoning`; emitted by plan_transfers as `verdict_detail`. */
export interface FplTransferVerdictDetail {
  action: "spend" | "roll" | "spend_forced_injury";
  horizon: { start_gw: number | null; end_gw: number | null; n: number };
  ft_before: number;
  ft_after: number;
  threshold: number;
  /** First-GW moves; empty on roll. */
  moves: FplTransferVerdictMove[];
  this_gw_gain: number;
  horizon_gain: number;
  hit_cost: number;
  /** total_net_gain of the returned plan. */
  plan_net: number;
  /** The path the counterfactual rejected: the roll walk on spend, the spend walk on a flipped roll. */
  roll_alternative: { net: number; gw: number | null; moves: FplTransferVerdictMove[] } | null;
  /** Roll only: the first later GW the plan transfers in. */
  next_move: { gw: number; moves: FplTransferVerdictMove[]; horizon_gain: number } | null;
}
```

In `FplTransferPlanHorizon` add after `reasoning?: string;`:

```ts
  verdict_detail?: FplTransferVerdictDetail;
```

- [ ] **Step 3: Typecheck and commit**

```bash
npm run typecheck
git add src/lib/fplAssistantApi.ts
git commit -m "feat(types): verdict_detail, in_plan and this_gw_gain on transfer payloads

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `DecisionCard` component with legacy fallback

**Files:**
- Create: `src/components/DecisionCard.tsx`, `src/components/DecisionCard.test.tsx`
- Modify: `src/components/RecommendationsPanel.tsx:321-323` (planSlot props), `:330-369` (delete `VerdictBanner`, `VERDICT_LABEL`, `VERDICT_TONE`), `:372-374` (`HorizonTransferPlan` signature + banner)

**Interfaces:**
- Consumes: Task 4 types.
- Produces: `DecisionCard({ plan, appliedTransferCount?, isApplying?, onApplyTransferAtIndex? })`, exported `fmtGain(n: number): string` (`+0.9` / `−1.2`, one decimal, U+2212 minus), exported `gwRange(h: {start_gw, end_gw}): string` (`GW5–7`, `GW5`, `the horizon`). `HorizonTransferPlan` gains the same three optional apply props.

- [ ] **Step 1: Write the failing tests**

Create `src/components/DecisionCard.test.tsx`:

```tsx
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DecisionCard, fmtGain, gwRange } from "./DecisionCard";
import type { FplTransferPlanHorizon, FplTransferVerdictDetail, FplTransferVerdictMove } from "@/lib/fplAssistantApi";

afterEach(cleanup);

const mv = (sellId: number, buyId: number, thisGw = 0.9, horizon = 2.8): FplTransferVerdictMove => ({
  sell: { id: sellId, name: `S${sellId}`, team: "LIV", price: 7.0 },
  buy: { id: buyId, name: `B${buyId}`, team: "BOU", price: 6.1 },
  position: "MID",
  this_gw_gain: thisGw,
  horizon_gain: horizon,
});

const detail = (over: Partial<FplTransferVerdictDetail>): FplTransferVerdictDetail => ({
  action: "spend",
  horizon: { start_gw: 5, end_gw: 7, n: 3 },
  ft_before: 1,
  ft_after: 0,
  threshold: 2.0,
  moves: [mv(1, 2)],
  this_gw_gain: 0.9,
  horizon_gain: 2.8,
  hit_cost: 0,
  plan_net: 6.5,
  roll_alternative: { net: 0, gw: 6, moves: [] },
  next_move: null,
  ...over,
});

const plan = (d?: FplTransferVerdictDetail, extra: Partial<FplTransferPlanHorizon> = {}): FplTransferPlanHorizon => ({
  verdict: d?.action ?? "spend",
  reasoning: "legacy prose",
  verdict_detail: d,
  horizon_gws: 3,
  allow_hits: false,
  ...extra,
});

describe("helpers", () => {
  it("formats gains with sign and one decimal", () => {
    expect(fmtGain(0.94)).toBe("+0.9");
    expect(fmtGain(-1.25)).toBe("−1.3");
    expect(fmtGain(0)).toBe("+0.0");
  });
  it("formats GW ranges", () => {
    expect(gwRange({ start_gw: 5, end_gw: 7 })).toBe("GW5–7");
    expect(gwRange({ start_gw: 5, end_gw: 5 })).toBe("GW5");
    expect(gwRange({ start_gw: null, end_gw: null })).toBe("the horizon");
  });
});

describe("DecisionCard spend", () => {
  it("shows the move, both gains with the GW range, and the roll comparison", () => {
    render(<DecisionCard plan={plan(detail({}))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toMatch(/make the move/i);
    expect(card.textContent).toContain("S1");
    expect(card.textContent).toContain("B2");
    expect(screen.getByTestId("decision-gains").textContent).toBe("+0.9 this GW · +2.8 over GW5–7");
    expect(card.textContent).toMatch(/Plan GW5–7 nets \+6\.5/);
    expect(card.textContent).toMatch(/rolling instead nets \+0\.0/);
    expect(card.textContent).toContain("FT 1→0");
    expect(card.textContent).not.toContain("legacy prose");
  });

  it("applies the plan's moves via onApplyTransferAtIndex(k-1)", () => {
    const onApply = vi.fn();
    render(<DecisionCard plan={plan(detail({ moves: [mv(1, 2), mv(3, 4)] }))} onApplyTransferAtIndex={onApply} appliedTransferCount={0} />);
    fireEvent.click(screen.getByRole("button", { name: /apply 2 moves/i }));
    expect(onApply).toHaveBeenCalledWith(1);
  });

  it("marks applied once appliedTransferCount covers the plan moves", () => {
    render(<DecisionCard plan={plan(detail({}))} onApplyTransferAtIndex={() => {}} appliedTransferCount={1} />);
    const btn = screen.getByRole("button", { name: /applied/i });
    expect(btn.hasAttribute("disabled")).toBe(true);
  });

  it("hides the apply button when no handler is given", () => {
    render(<DecisionCard plan={plan(detail({}))} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the hit cost when hits were taken", () => {
    render(<DecisionCard plan={plan(detail({ hit_cost: 4, this_gw_gain: 3.2, horizon_gain: 9.1 }))} />);
    expect(screen.getByTestId("decision-gains").textContent).toContain("−4 hit");
  });

  it("uses the injury tone and flags the seller on a forced sell", () => {
    render(<DecisionCard plan={plan(detail({ action: "spend_forced_injury", moves: [{ ...mv(1, 2), forced_injury: true }], roll_alternative: null }))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toMatch(/injury: act now/i);
    expect(card.textContent).toMatch(/flagged/i);
    expect(card.className).toContain("destructive");
  });
});

describe("DecisionCard roll", () => {
  it("explains the bank and names the next planned move", () => {
    render(<DecisionCard plan={plan(detail({
      action: "roll", moves: [], this_gw_gain: 0, horizon_gain: 0, ft_before: 1, ft_after: 2,
      roll_alternative: null, plan_net: 3.7,
      next_move: { gw: 6, moves: [mv(5, 6, 3.7, 3.7)], horizon_gain: 3.7 },
    }))} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toMatch(/roll it/i);
    expect(card.textContent).toMatch(/No move clears \+2\.0 over GW5–7/);
    expect(card.textContent).toMatch(/Next planned move: S5 → B6 in GW6 \(\+3\.7 over GW6–7\)/);
    expect(card.textContent).toContain("FT 1→2");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("quotes the rejected spend when the counterfactual flipped the verdict", () => {
    render(<DecisionCard plan={plan(detail({
      action: "roll", moves: [], this_gw_gain: 0, horizon_gain: 0, ft_before: 1, ft_after: 2,
      plan_net: 14, roll_alternative: { net: 13, gw: 5, moves: [mv(1, 3)] },
      next_move: { gw: 6, moves: [mv(1, 3), mv(2, 4)], horizon_gain: 14 },
    }))} />);
    expect(screen.getByTestId("plan-verdict-banner").textContent)
      .toMatch(/Moving now \(S1 → B3\) would net \+13\.0 over GW5–7; rolling nets \+14\.0/);
  });
});

describe("DecisionCard fallback", () => {
  it("renders the legacy reasoning banner when verdict_detail is absent", () => {
    render(<DecisionCard plan={plan(undefined, { verdict: "spend", first_gw_ft_before: 1, first_gw_ft_after: 0 })} />);
    const card = screen.getByTestId("plan-verdict-banner");
    expect(card.textContent).toContain("legacy prose");
    expect(card.textContent).toMatch(/Planned across 3 GWs/);
  });

  it("renders nothing without a verdict", () => {
    const { container } = render(<DecisionCard plan={{}} />);
    expect(container.querySelector('[data-testid="plan-verdict-banner"]')).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npx vitest run src/components/DecisionCard.test.tsx 2>&1 | tail -5
```
Expected: FAIL, cannot resolve `./DecisionCard`.

- [ ] **Step 3: Implement `src/components/DecisionCard.tsx`**

```tsx
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  FplTransferPlanHorizon,
  FplTransferVerdictDetail,
  FplTransferVerdictMove,
} from "@/lib/fplAssistantApi";

type Verdict = NonNullable<FplTransferPlanHorizon["verdict"]>;

const LABEL: Record<Verdict, string> = {
  roll: "Roll it",
  spend: "Make the move",
  spend_forced_injury: "Injury: act now",
};

// 300/400-weight shades on dark per the 2026-09-12 audit (U5); 600/700 on light.
const TONE: Record<Verdict, string> = {
  roll: "border-border bg-muted/10 text-muted-foreground",
  spend: "border-emerald-600/30 bg-emerald-600/[0.08] text-emerald-700 dark:text-emerald-300",
  spend_forced_injury: "border-destructive/30 bg-destructive/[0.08] text-destructive",
};

/** `+0.9` / `−1.3`; one decimal, typographic minus. */
export const fmtGain = (n: number) => `${n < 0 ? "−" : "+"}${Math.abs(n).toFixed(1)}`;

/** `GW5–7`, `GW5`, or `the horizon` when unknown. */
export const gwRange = (h: { start_gw: number | null; end_gw: number | null }) => {
  if (h.start_gw == null) return "the horizon";
  if (h.end_gw == null || h.end_gw === h.start_gw) return `GW${h.start_gw}`;
  return `GW${h.start_gw}–${h.end_gw}`;
};

const movesText = (moves: FplTransferVerdictMove[]) =>
  moves.map((m) => `${m.sell.name} → ${m.buy.name}`).join(" + ");

function MoveLine({ m }: { m: FplTransferVerdictMove }) {
  return (
    <span className="flex flex-wrap items-center gap-x-1">
      <span className="text-red-600 dark:text-red-400">{m.sell.name}</span>
      <span className="text-muted-foreground">({m.sell.team} £{m.sell.price})</span>
      {m.forced_injury && (
        <Badge variant="outline" className="border-destructive/50 text-[10px] text-destructive">flagged</Badge>
      )}
      <span>→</span>
      <span className="font-semibold text-emerald-700 dark:text-emerald-300">{m.buy.name}</span>
      <span className="text-muted-foreground">({m.buy.team} £{m.buy.price})</span>
    </span>
  );
}

/** Pre-verdict_detail backends: the prose banner, unchanged. */
function LegacyVerdictBanner({ plan }: { plan: FplTransferPlanHorizon }) {
  if (!plan.verdict) return null;
  const showFt =
    typeof plan.first_gw_ft_before === "number" && typeof plan.first_gw_ft_after === "number";
  const n = plan.horizon_gws ?? plan.gws?.length ?? 1;
  return (
    <div data-testid="plan-verdict-banner" className={`rounded-lg border p-3 flex flex-col gap-1 ${TONE[plan.verdict]}`}>
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-wider">{LABEL[plan.verdict]}</Badge>
        {showFt && <span className="ml-auto text-xs text-muted-foreground">FT {plan.first_gw_ft_before}→{plan.first_gw_ft_after}</span>}
      </div>
      {plan.reasoning && <p className="text-xs leading-relaxed">{plan.reasoning}</p>}
      <p className="text-[11px] opacity-70 leading-relaxed">
        {plan.allow_hits
          ? `Planned across ${n} GWs and allowed to take hits, so it can name more moves than the free-transfer suggestions above.`
          : `Planned across ${n} GWs using free transfers only.`}
      </p>
    </div>
  );
}

interface DecisionCardProps {
  plan: FplTransferPlanHorizon;
  appliedTransferCount?: number;
  isApplying?: boolean;
  /** Plan moves lead `transfers.moves`, so applying k plan moves = index k-1. */
  onApplyTransferAtIndex?: (index: number) => void;
}

export function DecisionCard({ plan, appliedTransferCount = 0, isApplying = false, onApplyTransferAtIndex }: DecisionCardProps) {
  const d: FplTransferVerdictDetail | undefined = plan.verdict_detail;
  if (!d) return <LegacyVerdictBanner plan={plan} />;
  const range = gwRange(d.horizon);
  const k = d.moves.length;
  const applied = k > 0 && appliedTransferCount >= k;

  return (
    <div data-testid="plan-verdict-banner" className={`rounded-lg border p-3 flex flex-col gap-1.5 ${TONE[d.action]}`}>
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-wider">{LABEL[d.action]}</Badge>
        <span className="ml-auto text-xs text-muted-foreground">FT {d.ft_before}→{d.ft_after}</span>
      </div>

      {d.action === "roll" ? (
        <>
          <p className="text-sm text-foreground">
            {d.roll_alternative
              ? `Moving now (${movesText(d.roll_alternative.moves) || "no move"}) would net ${fmtGain(d.roll_alternative.net)} over ${range}; rolling nets ${fmtGain(d.plan_net)}.`
              : `Bank the free transfer. No move clears ${fmtGain(d.threshold)} over ${range}.`}
          </p>
          {d.next_move && (
            <p className="text-[11px] text-muted-foreground">
              Next planned move: {movesText(d.next_move.moves)} in GW{d.next_move.gw} (
              {fmtGain(d.next_move.horizon_gain)} over {gwRange({ start_gw: d.next_move.gw, end_gw: d.horizon.end_gw })})
            </p>
          )}
        </>
      ) : (
        <>
          <ul className="text-sm space-y-0.5">
            {d.moves.map((m, i) => <li key={i}><MoveLine m={m} /></li>)}
          </ul>
          <p className="text-sm text-foreground" data-testid="decision-gains">
            <b>{fmtGain(d.this_gw_gain)}</b> this GW · <b>{fmtGain(d.horizon_gain)}</b> over {range}
            {d.hit_cost > 0 && <> · <b className="text-red-600 dark:text-red-400">−{d.hit_cost} hit</b></>}
          </p>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span>
              Plan {range} nets {fmtGain(d.plan_net)}
              {d.roll_alternative ? ` · rolling instead nets ${fmtGain(d.roll_alternative.net)}` : ""}
            </span>
            {onApplyTransferAtIndex && k > 0 && (
              <Button
                type="button"
                size="sm"
                variant={applied ? "secondary" : "default"}
                className="ml-auto h-8 text-xs"
                disabled={isApplying || applied}
                onClick={() => onApplyTransferAtIndex(k - 1)}
              >
                {applied ? "Applied" : k > 1 ? `Apply ${k} moves` : "Apply"}
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
```

Note on the `decision-gains` test: the JSX above renders `+0.9 this GW · +2.8 over GW5–7` as one text node sequence; `textContent` joins without extra whitespace because there are no line-break text nodes inside the `<p>`. If the assertion fails on whitespace, collapse with `.replace(/\s+/g, " ").trim()` in the test rather than restructuring the markup.

- [ ] **Step 4: Run the card tests**

```bash
npx vitest run src/components/DecisionCard.test.tsx 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 5: Swap `VerdictBanner` for `DecisionCard` in `RecommendationsPanel.tsx`**

Delete lines 330-369 (`VERDICT_LABEL`, `VERDICT_TONE`, `VerdictBanner`). Add import:

```ts
import { DecisionCard } from "./DecisionCard";
```

Change `HorizonTransferPlan`'s signature and first line to:

```tsx
export function HorizonTransferPlan({
  plan,
  appliedTransferCount,
  isApplying,
  onApplyTransferAtIndex,
}: {
  plan?: FplTransferPlanHorizon;
  appliedTransferCount?: number;
  isApplying?: boolean;
  onApplyTransferAtIndex?: (index: number) => void;
}) {
  const verdictBanner = plan?.verdict ? (
    <DecisionCard
      plan={plan}
      appliedTransferCount={appliedTransferCount}
      isApplying={isApplying}
      onApplyTransferAtIndex={onApplyTransferAtIndex}
    />
  ) : null;
```

In `TransfersTab` (line 321) change the planSlot to:

```tsx
        planSlot={
          <HorizonTransferPlan
            plan={recommendation.transfer_plan_horizon}
            appliedTransferCount={appliedTransferCount}
            isApplying={isApplyingTransfer}
            onApplyTransferAtIndex={onApplyTransferAtIndex}
          />
        }
```

Leave `planVerdict`/`planHorizon` props on the `TransferPlanner` call for now; Task 7 removes them.

- [ ] **Step 6: Run the panel tests, typecheck, commit**

```bash
npx vitest run src/components/RecommendationsPanel.test.tsx src/components/DecisionCard.test.tsx 2>&1 | tail -5
npm run typecheck
git add src/components/DecisionCard.tsx src/components/DecisionCard.test.tsx src/components/RecommendationsPanel.tsx
git commit -m "feat(transfers): DecisionCard renders verdict_detail with this-GW and horizon gains

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
Expected: existing banner tests still pass through the legacy fallback (they pass `reasoning` without `verdict_detail`).

---

### Task 6: Staircase relabel with GW ranges

**Files:**
- Modify: `src/components/RecommendationsPanel.tsx` (`HorizonTransferPlan` body: header, net label, move rows)
- Modify: `src/components/RecommendationsPanel.test.tsx` (append tests)

**Interfaces:**
- Consumes: `fmtGain`, `gwRange` from Task 5; `FplTransferPlanMove.this_gw_gain` from Task 4.

- [ ] **Step 1: Write the failing tests** — append to `RecommendationsPanel.test.tsx`:

```tsx
describe("HorizonTransferPlan labels", () => {
  const spendPlan: FplTransferPlanHorizon = {
    ...basePlan,
    gws: [5, 6, 7],
    horizon_gws: 3,
    total_net_gain: 6.5,
    verdict: "spend",
    reasoning: "Move now.",
    plan: [
      {
        gw: 5, action: "transfer", free_transfers_before: 1, free_transfers_after: 0,
        hits: 0, hit_cost: 0, gw_gain: 2.8, net_gain: 2.8, bank_after: 1.0,
        moves: [{
          sell: { id: 1, name: "Szoboszlai", team: "LIV", price: 7 },
          buy: { id: 2, name: "Tavernier", team: "BOU", price: 6.1 },
          score_gain: 2.8, this_gw_gain: 0.9,
        }],
        note: "Szoboszlai → Tavernier",
      },
      { gw: 6, action: "roll", free_transfers_before: 1, free_transfers_after: 2, hits: 0, hit_cost: 0,
        gw_gain: 0, net_gain: 0, bank_after: 1.0, moves: [], note: "Roll." },
      { gw: 7, action: "roll", free_transfers_before: 2, free_transfers_after: 3, hits: 0, hit_cost: 0,
        gw_gain: 0, net_gain: 0, bank_after: 1.0, moves: [], note: "Roll." },
    ],
  };

  it("names the GW range in the header and the net line", () => {
    render(<HorizonTransferPlan plan={spendPlan} />);
    expect(screen.getByText("Plan GW5–7")).toBeTruthy();
    // Exact string: the legacy banner also says "...using free transfers only."
    expect(screen.getByText("free transfers only")).toBeTruthy();
    // The net line mixes text nodes and a <b>, so read the element, not getByText.
    expect(screen.getByTestId("plan-net").textContent).toBe("Net +6.5 over GW5–7");
  });

  it("shows this-GW and horizon gains on a move row", () => {
    render(<HorizonTransferPlan plan={spendPlan} />);
    expect(screen.getByText(/\+0\.9 this GW · \+2\.8/)).toBeTruthy();
  });

  it("labels a hits plan with the move and hit counts", () => {
    const hits = { ...spendPlan, plan: [{ ...spendPlan.plan![0], hits: 1, hit_cost: 4, net_gain: -1.2 }] };
    render(<HorizonTransferPlan plan={hits} />);
    expect(screen.getByText(/1 move, 1 hit/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npx vitest run src/components/RecommendationsPanel.test.tsx 2>&1 | tail -5
```
Expected: the three new tests FAIL (old "Multi-GW plan (free transfers only)" text).

- [ ] **Step 3: Relabel the staircase**

Import `fmtGain, gwRange` from `./DecisionCard`. Inside `HorizonTransferPlan`, after `const totalMoves = ...` add:

```tsx
  const gws = plan.gws ?? plan.plan.map((g) => g.gw);
  const range = gwRange({ start_gw: gws[0] ?? null, end_gw: gws[gws.length - 1] ?? null });
```

Replace the header block (`<span className="text-sm font-semibold">…</span>` through the net `<span>`) with:

```tsx
          <span className="text-sm font-semibold">Plan {range}</span>
          <Badge variant="outline" className="text-[10px]">
            {totalHits > 0
              ? `${totalMoves} move${totalMoves === 1 ? "" : "s"}, ${totalHits} hit${totalHits === 1 ? "" : "s"}`
              : "free transfers only"}
          </Badge>
          {typeof plan.total_net_gain === "number" && (
            <span className="ml-auto text-xs" data-testid="plan-net">
              Net{" "}
              <b className={plan.total_net_gain >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-red-600 dark:text-red-400"}>
                {fmtGain(plan.total_net_gain)}
              </b>{" "}
              over {range}
            </span>
          )}
```

Replace the hits bill sentence `Costs {totalHitCost} pts in hits across {plan.horizon_gws} GWs.` with `Costs {totalHitCost} pts in hits across {range}.`

Replace the move-row gain `<span className="ml-auto text-emerald-600">+{m.score_gain.toFixed(1)}</span>` with:

```tsx
                    <span className="ml-auto text-emerald-600 dark:text-emerald-300" title="this GW · over the remaining plan">
                      {typeof m.this_gw_gain === "number" ? `${fmtGain(m.this_gw_gain)} this GW · ` : ""}{fmtGain(m.score_gain)}
                    </span>
```

- [ ] **Step 4: Run tests, typecheck, commit**

```bash
npx vitest run src/components/RecommendationsPanel.test.tsx 2>&1 | tail -5
npm run typecheck
git add src/components/RecommendationsPanel.tsx src/components/RecommendationsPanel.test.tsx
git commit -m "feat(transfers): staircase names its GW range and per-move this-GW gain

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Demote beam options to collapsed alternatives

**Files:**
- Modify: `src/components/TransferPlanner.tsx` (props 9-25, derived values 158-166, block 203-410)
- Modify: `src/components/TransferPlanner.test.tsx` (rewrite)
- Modify: `src/components/RecommendationsPanel.tsx:322-323` (drop `planVerdict`/`planHorizon`/`onApplyNextTransfer`/`canApplyNextTransfer` on the `TransferPlanner` call)

**Interfaces:**
- Consumes: `FplTransferMove.in_plan`, `this_gw_gain` (Task 4); `fmtGain` (Task 5).
- Produces: `TransferPlanner` props without `planVerdict`, `planHorizon`, `onApplyNextTransfer`, `canApplyNextTransfer`.

- [ ] **Step 1: Rewrite `TransferPlanner.test.tsx`** (replace the whole file):

```tsx
// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TransferPlanner } from "./TransferPlanner";
import type { FplTransfersRecommendation } from "@/lib/fplAssistantApi";

afterEach(cleanup);

const transfers = {
  moves: [
    {
      position: "DEF",
      sell: { id: 1, name: "Seller", team: "AAA", price: 4.9 },
      buy: { id: 2, name: "Buyer", team: "BBB", price: 4.1 },
      score_gain: 7.1,
      this_gw_gain: 2.2,
      in_plan: true,
    },
    {
      position: "MID",
      sell: { id: 3, name: "Other", team: "CCC", price: 6.0 },
      buy: { id: 4, name: "Punt", team: "DDD", price: 5.5 },
      score_gain: 3.0,
      in_plan: false,
    },
  ],
  transfer_plan: { free_transfers: 1, horizon_gws: 3, hit_cap: 0, transfer_count_target: 1, transfer_count_built: 2 },
  remaining_itb: 0.5,
} as unknown as FplTransfersRecommendation;

describe("TransferPlanner alternatives", () => {
  it("collapses the alternatives behind a closed disclosure labelled with the beam horizon", () => {
    const { container } = render(<TransferPlanner transfers={transfers} planSlot={<div>PLAN</div>} />);
    const details = container.querySelector("details");
    expect(details).toBeTruthy();
    expect(details?.hasAttribute("open")).toBe(false);
    expect(screen.getByText(/Alternatives \(2\) — best single swaps over 3 GWs, not the recommendation/i)).toBeTruthy();
  });

  it("renders the plan slot before the alternatives and their controls", () => {
    render(<TransferPlanner transfers={transfers} planSlot={<div data-testid="plan-slot">PLAN</div>} />);
    const slot = screen.getByTestId("plan-slot");
    const summary = screen.getByText(/alternatives/i);
    expect(slot.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const reset = screen.getByRole("button", { name: /reset applied/i });
    expect(slot.compareDocumentPosition(reset) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("has no top-level 'Apply next transfer' button", () => {
    render(<TransferPlanner transfers={transfers} planSlot={<div>PLAN</div>} />);
    expect(screen.queryByRole("button", { name: /apply next transfer/i })).toBeNull();
  });

  it("chips a move that is in the plan and never says 'not in plan'", () => {
    render(<TransferPlanner transfers={transfers} planSlot={<div>PLAN</div>} />);
    expect(screen.getAllByText(/^in plan$/i)).toHaveLength(1);
    expect(screen.queryByText(/not in plan/i)).toBeNull();
  });

  it("shows this-GW gain alongside the horizon gain when present", () => {
    render(<TransferPlanner transfers={transfers} planSlot={<div>PLAN</div>} />);
    expect(screen.getByText(/\+2\.2 this GW · \+7\.1 pts/)).toBeTruthy();
    expect(screen.getByText(/^\+3\.0 pts$/)).toBeTruthy();
  });

  it("labels ITB as post-move remainder", () => {
    render(<TransferPlanner transfers={transfers} />);
    expect(screen.getByText(/ITB after moves/i)).toBeTruthy();
  });

  it("uses a singular horizon label", () => {
    const oneGw = { ...transfers, transfer_plan: { ...(transfers as { transfer_plan: object }).transfer_plan, horizon_gws: 1 } } as unknown as FplTransfersRecommendation;
    render(<TransferPlanner transfers={oneGw} planSlot={<div>PLAN</div>} />);
    expect(screen.getByText(/over 1 GW, not the recommendation/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npx vitest run src/components/TransferPlanner.test.tsx 2>&1 | tail -5
```
Expected: FAIL on the alternatives label, the missing `in plan` chip and the still-present "Apply next transfer" button.

- [ ] **Step 3: Edit `TransferPlanner.tsx`**

Props (lines 9-25): remove `planVerdict`, `planHorizon`, `canApplyNextTransfer`, `onApplyNextTransfer` from the interface and from the destructuring. Remove the `FplTransferPlanHorizon` import.

Derived values: delete the `plannedPairs`/`hasPlan` block (lines 158-166). Add after `hasMoveGain`:

```tsx
  const beamHorizon = transferPlan?.horizon_gws;
  const horizonLabel =
    typeof beamHorizon === "number" ? `over ${beamHorizon} GW${beamHorizon === 1 ? "" : "s"}` : "single-week";
```

Import `fmtGain` from `./DecisionCard`.

Inside the quick-options block:
- Delete the `<p …>Quick options</p>` heading (lines 206-209) and its comment.
- Delete the `Apply next transfer` `<Button>` (lines 237-247). Keep `Reset applied`.
- Delete the `<p>` reading "This gameweek, free transfers only — the multi-GW plan above is the recommendation" (lines 271-277).
- Replace the `not in plan — plan says hold` badge block (lines 295-302) with:

```tsx
                {move.in_plan && (
                  <Badge variant="outline" className="border-emerald-500/50 text-emerald-600 dark:text-emerald-400">
                    in plan
                  </Badge>
                )}
```

- Replace the `score_gain` badge (lines ~344-348) with:

```tsx
                {typeof move.score_gain === "number" && (
                  <Badge variant="secondary" className="text-xs shrink-0">
                    {typeof move.this_gw_gain === "number" ? `${fmtGain(move.this_gw_gain)} this GW · ` : ""}
                    {formatPoints(move.score_gain, true)} pts
                  </Badge>
                )}
```

- Replace the `<summary>` text (line ~402) with:

```tsx
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Alternatives ({moves.length}) — best single swaps {horizonLabel}, not the recommendation
              </summary>
```

In `RecommendationsPanel.tsx` `TransfersTab`, remove `planVerdict={…}`, `planHorizon={…}`, `canApplyNextTransfer={…}` and `onApplyNextTransfer={…}` from the `<TransferPlanner …/>` call. (Keep them in `RecommendationsPanelProps` and `TransfersTab`'s own props so `Index.tsx` needs no change; eslint's unused-vars rule does not flag unused destructured props only if they are not destructured — so also drop `canApplyNextTransfer` and `onApplyNextTransfer` from `TransfersTab`'s destructuring and parameter type.)

- [ ] **Step 4: Run tests, lint, typecheck**

```bash
npx vitest run src/components/TransferPlanner.test.tsx src/components/RecommendationsPanel.test.tsx 2>&1 | tail -5
npm run lint && npm run typecheck
```
Expected: all green. If lint flags `onApplyNextTransfer` unused in `RecommendationsPanel`, remove it from that destructuring too.

- [ ] **Step 5: Commit**

```bash
git add src/components/TransferPlanner.tsx src/components/TransferPlanner.test.tsx src/components/RecommendationsPanel.tsx
git commit -m "feat(transfers): beam options become collapsed alternatives; Apply lives on the decision card

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: End-to-end verification

**Files:** none.

- [ ] **Step 1: Full frontend checks**

```bash
cd /Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub
npm run typecheck && npm run lint && npm test 2>&1 | tail -5
```
Expected: green; test count = baseline + 15 (12 DecisionCard, 3 staircase; the 7 planner tests replace the 7 old ones).

- [ ] **Step 2: Full backend checks**

```bash
cd /Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL
python -m pytest -q 2>&1 | tail -3
```
Expected: baseline + 12 (6 verdict_detail, 6 plan_merge), 0 failures.

- [ ] **Step 3: Manual smoke, both viewports**

Run backend locally (Task 3 command) with the frontend `npm run dev` pointed at it (`VITE_API_BASE_URL` per the frontend README). Load `/app`, run Recommend, open Transfers:
- Card reads action, move, `+x this GW · +y over GWa–b`, plan/roll nets, FT.
- Click Apply on the card: pitch updates to the plan move; "Applied" state sticks; Reset inside Alternatives clears it.
- Alternatives closed by default; first alternative (if it duplicates the plan) carries `in plan`.
- Repeat at 375px width: no horizontal overflow on the card or the staircase rows.

Record what you saw (one line each) in the final report. Fix anything that fails before declaring done.

- [ ] **Step 4: Hand off**

Do not merge or deploy. Report the two branch names and last commit SHAs. Deployment order per spec: backend first (additive), then frontend.
