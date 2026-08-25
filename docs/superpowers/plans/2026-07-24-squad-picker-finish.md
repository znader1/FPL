# Squad Picker — Finish (nudges + fdr_strength + grid + value menu)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Checkbox (`- [ ]`) steps.

**Goal:** Make the two remaining pre-season-functional knobs real and expose the team-strength grid + value menu, completing the squad-picker as a tuning tool. Backend: wire `team_nudges` (xg/blend) + `fdr_strength` (ppg). Frontend: team-strength grid, value-menu display, `fdr_strength` control.

**Deferred (documented, NOT in this plan):** `league_id` / mini-league differential — needs the user's + rivals' `event/{gw}/picks/`, which 404 pre-season (same limitation the /squad friendly-message fix addresses), and is a heavier ownership-fetch integration. Revisit at GW1.

**Repos:** Backend `FPL` (branch `feature/xg-expected-points`). Frontend `fpl-decision-hub` (branch `feature/squad-picker`).

## Global Constraints

- Tunables via `getattr(config, ...)`. Positions GKP/DEF/MID/FWD. No network in unit tests.
- `team_nudges` affect the **xg/blend** bases only (they nudge the fixture-difficulty attack/defense ratings, which the ppg baseline does not consume). The UI must say so.
- Backward compatible: new params default to today's behaviour (`fdr_strength=1.0` → no change; `team_nudges=None` → knowledge file only).
- Commit prefixes `feat:`/`test:`. End commit body with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task B1: Wire `team_nudges` into the xg/blend ratings

**Files:**
- Modify: `src/squad_draft_xg.py` (`_ratings` + `xg_projection` accept `team_nudges`)
- Modify: `src/squad_draft.py` (`DEFAULT_PARAMS` re-adds `team_nudges`; routing passes it to `xg_projection`)
- Test: `tests/test_squad_draft_xg.py`

**Interfaces:**
- `fixture_difficulty.apply_knowledge_discount(ratings, discount=None, teams_short_map=None, path=None)` — pass a `discount` dict directly to override the file.
- `_ratings(elements, teams_short, team_nudges=None)` → passes `discount=_nudges_to_discount(team_nudges)` when nudges given, else file default.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_squad_draft_xg.py
def test_team_nudges_shift_ratings():
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    base = squad_draft_xg.xg_projection(els, fx, ts, 1, 5, blend_weight=1.0, ppg_proj=None)
    # Nudge team T1's defense weaker (concedes more) — opponents' attackers should rise.
    nudged = squad_draft_xg.xg_projection(
        els, fx, ts, 1, 5, blend_weight=1.0, ppg_proj=None,
        team_nudges=[{"team_short": "T1", "attack": 1.0, "defense": 1.15}])
    # The projections must not be byte-identical (a nudge changed something).
    import pandas as pd
    b = base.set_index("id")["xpts_gw1"]
    n = nudged.set_index("id")["xpts_gw1"]
    assert not b.equals(n)
```

- [ ] **Step 2: Run — confirm it fails**

Run: `source .venv/bin/activate && PYTHONPATH=. python -m pytest tests/test_squad_draft_xg.py::test_team_nudges_shift_ratings -v`
Expected: FAIL — `xg_projection() got an unexpected keyword argument 'team_nudges'`.

- [ ] **Step 3: Implement**

In `src/squad_draft_xg.py`:
```python
def _nudges_to_discount(team_nudges):
    """Convert [{team_short, attack, defense}] to the knowledge_discount 'teams' dict."""
    if not team_nudges:
        return None
    teams = {}
    for n in team_nudges:
        if not isinstance(n, dict):
            continue
        key = n.get("team_short")
        if not key:
            continue
        entry = {}
        if n.get("attack") is not None:
            entry["attack"] = float(n["attack"])
        if n.get("defense") is not None:
            entry["defense"] = float(n["defense"])
        if entry:
            teams[str(key)] = entry
    return {"teams": teams} if teams else None
```
Change `_ratings` to accept and use nudges:
```python
def _ratings(elements, teams_short, team_nudges=None):
    ratings = fixture_difficulty.resolve_team_ratings(pd.DataFrame(), teams_short_map=teams_short)
    discount = _nudges_to_discount(team_nudges)
    ratings = fixture_difficulty.apply_knowledge_discount(
        ratings, discount=discount, teams_short_map=teams_short)
    return ratings
```
Add `team_nudges=None` to `xg_projection`'s signature and pass it to `_ratings(elements, teams_short, team_nudges)`.

Then in `src/squad_draft.py`: re-add `"team_nudges": None` to `DEFAULT_PARAMS` (remove it from the "NOT wired" comment, leaving `fdr_strength`/`league_id` there), and in the `basis in ("xg","blend")` branch pass `team_nudges=p["team_nudges"]` into `squad_draft_xg.xg_projection(...)`.

Verify `apply_knowledge_discount` accepts a `discount` shaped `{"teams": {short: {attack, defense}}}` — read `src/fixture_difficulty.py:383` to confirm the exact expected shape and adjust `_nudges_to_discount` to match it.

- [ ] **Step 4: Run — confirm pass**

Run: `PYTHONPATH=. python -m pytest tests/test_squad_draft_xg.py tests/test_squad_draft.py -v`
Expected: PASS (incl. the new test). Full suite `PYTHONPATH=. python -m pytest tests/ -q` green.

- [ ] **Step 5: Commit**

```bash
git add src/squad_draft_xg.py src/squad_draft.py tests/test_squad_draft_xg.py
git commit -m "feat: wire per-request team_nudges into xg/blend ratings"
```

---

### Task B2: Wire `fdr_strength` into the ppg projection path

**Files:**
- Modify: `src/projections.py` (`project_elements_next_gws` accepts `fdr_strength`, scales the difficulty multiplier)
- Modify: `src/squad_draft.py` (`DEFAULT_PARAMS` re-adds `fdr_strength`; ppg call passes it)
- Test: `tests/test_squad_draft.py`

**Interfaces:**
- `difficulty_multiplier(diff_avg)` returns a per-GW multiplier around 1.0. `fdr_strength` scales the deviation: `1.0 + (mult - 1.0) * fdr_strength`. `1.0` = unchanged; `0.0` = fixtures ignored; `>1` = amplified.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_squad_draft.py
def test_fdr_strength_amplifies_fixture_swing():
    els, fx, ts = _synthetic_elements(), _synthetic_fixtures(), _teams_short()
    weak = squad_draft.build_squad_from_frames(els, fx, ts,
        {"gw_start": 1, "horizon_gws": 5, "fdr_strength": 0.0})
    strong = squad_draft.build_squad_from_frames(els, fx, ts,
        {"gw_start": 1, "horizon_gws": 5, "fdr_strength": 2.0})
    # Same pool, different FDR weighting -> projected totals should differ.
    assert weak["projected_points"]["horizon_total"] != strong["projected_points"]["horizon_total"]
```

- [ ] **Step 2: Run — confirm it fails or is a no-op**

Run: `PYTHONPATH=. python -m pytest tests/test_squad_draft.py::test_fdr_strength_amplifies_fixture_swing -v`
Expected: FAIL — totals equal because `fdr_strength` is currently ignored. (If the synthetic fixtures all have difficulty 3 → multiplier 1.0 → no swing regardless, adjust `_synthetic_fixtures` to vary `team_h_difficulty`/`team_a_difficulty` across GWs so the multiplier is non-trivial, then the test is meaningful.)

- [ ] **Step 3: Implement**

In `src/projections.py`, add `fdr_strength=1.0` to `project_elements_next_gws`'s signature. Where the difficulty multiplier is applied (around line 470, `diff_mult = diff_avg.apply(difficulty_multiplier)`), scale it:
```python
    diff_mult = diff_avg.apply(difficulty_multiplier)
    fdr_strength = float(fdr_strength if fdr_strength is not None else 1.0)
    if fdr_strength != 1.0:
        diff_mult = 1.0 + (diff_mult - 1.0) * fdr_strength
```
(Read the surrounding code first — apply the scaling only to the fixture-difficulty multiplier, not the home/away or form multipliers.)

In `src/squad_draft.py`: re-add `"fdr_strength": 1.0` to `DEFAULT_PARAMS` (remove from the "NOT wired" comment), and pass `fdr_strength=p["fdr_strength"]` in BOTH `projections.project_elements_next_gws(...)` calls (the `ppg_proj` build).

- [ ] **Step 4: Run — confirm pass**

Run: `PYTHONPATH=. python -m pytest tests/test_squad_draft.py -v` then full suite `-q`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/projections.py src/squad_draft.py tests/test_squad_draft.py
git commit -m "feat: wire fdr_strength scalar into ppg fixture-difficulty multiplier"
```

---

### Task F1: Value menu + fdr_strength control in the page

**Files (frontend repo `fpl-decision-hub`, branch `feature/squad-picker`):**
- Modify: `src/pages/SquadPicker.tsx`

- [ ] **Step 1: Add the fdr_strength control + value-menu render**

Add to `DEFAULTS`: `fdr_strength: 1.0`. Add a `Field` control (number input, step 0.1, 0–2) bound to `params.fdr_strength`. Add `fdr_strength?: number` to `SquadBuildParams` in `src/lib/squadPickerApi.ts` if missing.

After the squad table, render the value menu when present:
```tsx
{res.value_menu && (
  <Card className="p-4">
    <div className="text-xs font-semibold mb-2">Value menu — top by 5-GW xPts</div>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
      {(["GKP","DEF","MID","FWD"] as const).map((pos) => (
        <div key={pos}>
          <div className="font-semibold mb-1">{pos}</div>
          <ul className="space-y-0.5">
            {(res.value_menu?.[pos] ?? []).map((p) => (
              <li key={p.player_id} className="flex justify-between gap-2">
                <span>{p.web_name} <span className="text-muted-foreground">{p.team_short}</span></span>
                <span className="text-muted-foreground">£{p.price_m?.toFixed(1)} · {p.xpts_horizon?.toFixed(1)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  </Card>
)}
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc -p tsconfig.app.json --noEmit` — no new errors (3 pre-existing TransferPlanner errors excluded).

- [ ] **Step 3: Commit**

```bash
git add src/pages/SquadPicker.tsx src/lib/squadPickerApi.ts
git commit -m "feat: value menu + fdr_strength control on squad picker page"
```

---

### Task F2: Team-strength grid

**Files (frontend repo):**
- Create: `src/components/TeamStrengthGrid.tsx`
- Modify: `src/pages/SquadPicker.tsx` (mount the grid; pass its nudges as `team_nudges` on build)
- Modify: `src/lib/squadPickerApi.ts` (ensure `getKnowledge`/`saveKnowledge` + `team_nudges` param exist — from the earlier F-plan they do)

**Interfaces:**
- Consumes `getKnowledge()` (returns `{as_of, teams}`), and produces `team_nudges: [{team_short, attack, defense}]` for the build call.

- [ ] **Step 1: Implement the grid**

`TeamStrengthGrid` fetches the current knowledge grid on mount (`getKnowledge`), renders one row per team with two number inputs/sliders (attack, defense, default 1.0), and calls an `onChange(nudges)` prop with the current `[{team_short, attack, defense}]` array (only teams the user moved off 1.0). Include a "Save to knowledge file" button (`saveKnowledge`) and a caption: "Nudges apply to the xg / blend projection basis." Derive the team list from the returned `teams` keys plus the 20 live teams — simplest: let the user add rows by short name, or seed from `getKnowledge().teams`. Keep it a plain shadcn `Card` + `Input` grid; use the repo's `slider.tsx` only if straightforward.

In `SquadPicker.tsx`: hold `teamNudges` state, render `<TeamStrengthGrid onChange={setTeamNudges} />` (collapsible), and include `team_nudges: teamNudges` in the `buildSquad` params. Show the caption that nudges need the xg/blend basis.

- [ ] **Step 2: Typecheck + build**

Run: `npx tsc -p tsconfig.app.json --noEmit` (no new errors) and `npm run build` (succeeds).

- [ ] **Step 3: Commit**

```bash
git add src/components/TeamStrengthGrid.tsx src/pages/SquadPicker.tsx src/lib/squadPickerApi.ts
git commit -m "feat: team-strength nudge grid on squad picker page"
```

---

## Self-Review

- `team_nudges` wired (xg/blend) → B1 (with a real ratings-shift test). ✓
- `fdr_strength` wired (ppg) → B2 (with a fixture-swing test). ✓
- Value menu + fdr control → F1. ✓
- Team-strength grid → F2. ✓
- `league_id` deferred + reason documented (pre-season picks 404 + heavier fetch). ✓
- Backward compatible (defaults preserve today's behaviour). ✓
