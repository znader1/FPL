# Minutes / Rotation-Risk Model Activation — Design

**Date:** 2026-07-17
**Repo:** `FPL/` (backend)
**Status:** Approved design, pre-implementation
**Sub-project:** 1 of 4 in the pre-season recommendation-robustness cycle

---

## 0. Context — the pre-season decomposition

One month before the 2026-27 kickoff (~Aug 15), the goal is **more robust,
sellable recommendations**. Recommendations were chosen as the primary focus;
frontend polish follows in a later cycle. The work is decomposed into four
independent sub-projects, each with its own spec → plan → build cycle, in
**ship-fast order** (features live now, backtest as a *guide* not a hard gate):

| # | Sub-project | Core change | Size |
|---|---|---|---|
| **1** | **Minutes / rotation model** (this spec) | Surgical rotation-risk discount on baseline `xpts_gw{N}`, independent of the xG blend | M |
| 2 | Ownership-adjusted EV | Differential EV scoring + captain-differential flag in `league_strategy` | M |
| 3 | Lighter backtest harness | Captain hit-rate + projection MAE vs baseline, used as a guide | M |
| 4 | Injury / news RAG | Separate heavier cycle, likely bleeds into season | L |

**Decisions locked for this sub-project:**
- **Staged, not bundled.** Do the surgical minutes discount now; turning on the
  full xG blend (`PROJ_MODEL_BLEND_WEIGHT > 0`) stays a *separate later decision*
  once sub-project 3 can validate it. The two must remain independent.
- **Relative multiplier**, not absolute (see §3).
- Ship-fast: validate by spot-check, flip on when it looks right.

---

## 1. Goal & non-goals

**Goal:** Replace the crude, injury-only availability discount in the baseline
projection with a proper **rotation-risk** signal, so that a *fit-but-rotated*
player (FPL status `a`, `chance_of_playing = 100%`, but who starts ~55% of the
time) is correctly discounted — the single biggest source of projection error
named in the roadmap.

**Non-goals (explicitly out of scope here):**
- Turning on the full xG expected-points blend (fixture-xG + output-model).
- Ownership-adjusted EV (sub-project 2).
- Backtest validation as a hard gate (sub-project 3; here we only spot-check).
- Any frontend change beyond an *optional* stretch badge (§8).

---

## 2. Current state (verified against code, 2026-07-17)

- `src/minutes_model.py` is **fully built and correct** but **orphaned**: its
  `minutes_projection()` (returning `prob_start`, `prob_appear`, `prob_60`,
  `exp_minutes`) is only consumed by `output_model.py` *inside* the xG stack.
  There is no path that applies "just minutes" to the baseline.
- The only route into projections is `expected_points.blend_into_projections`
  via `config.PROJ_MODEL_BLEND_WEIGHT` (default `0.0`), which turns on the
  **entire** xG stack at once — not usable as a minutes-only lever.
- Baseline availability handling in `src/projections.py`:
  - `~L447-451`: `play_prob = chance_of_playing_next_round / 100` (else 1.0).
  - `~L495` (GW1, `i==0`): `xpts = xpts * play_prob`.
  - `~L499-503` (GW2-3, `i<=2`): faded injury discount via
    `PROJ_INJURY_FUTURE_GW_FADE = 0.5`.
  - This is **injury-only**. A fit-but-rotated player gets `play_prob = 1.0`
    and therefore **zero** discount. That is the gap.
- `minutes_projection()` currently returns only the combined `prob_start`
  (already `= history_rotation × availability`); it does **not** expose the two
  components separately. A small additive change is needed (§4).

---

## 3. Core mechanic — relative rotation-risk multiplier

The baseline already partially encodes minutes (it blends FPL's own
`ep_next` and recent-GW average minutes). A naïve `prob_start × xPts` would
**double-count** and deflate *every* player — even nailed starters have
`prob_start ≈ 0.9` — making our xPts read systematically low vs FPL. So the
multiplier is **relative to a nailed-starter reference**, capped at 1.0, so only
below-nailed players are discounted:

```
rotation_mult = clamp(prob_start_effective / NAILED_REF, 0, 1)
cameo_bonus   = CAMEO_VALUE * clamp(prob_appear − prob_start_effective, 0, 1)
minutes_mult  = clamp(rotation_mult + cameo_bonus, 0, 1)
```

Defaults: `NAILED_REF = 0.85`, `CAMEO_VALUE = 0.30`.

Worked examples (immediate GW, healthy):
- Nailed starter `prob_start 0.95` → `rotation_mult = 1.0` (capped) → **1.0**
- Rotation risk `prob_start 0.55`, `prob_appear 0.80` → `0.647 + 0.30·0.25 = 0.72`
- Injured `prob_start 0.10`, `prob_appear 0.20` → `0.118 + 0.30·0.10 = 0.15`

**Why relative wins:** surgical (targets exactly the rotation-risk gap), no
global deflation, keeps our xPts comparable to FPL's numbers, and avoids
re-basing the whole projection.

---

## 4. Wiring into `projections.py`

Behind a single flag `config.PROJ_APPLY_MINUTES_MODEL` (default `False`):

1. Compute `mins = minutes_model.minutes_projection(elements, history, gw)`
   once per GW in the existing GW loop.
2. **Separate injury from rotation for future GWs.** Extend
   `minutes_projection()` to also return two columns:
   - `rotation_prob_start` — the history-based `blended_start` *before*
     availability is applied.
   - `availability` — the `_availability_series` value.
   (Backward compatible: existing callers ignore the extra columns.)
3. Per GW `i`:
   - GW1 (`i == 0`): `avail_eff = availability` (full).
   - Future GWs (`i >= 1`): fade only the injury component —
     `avail_eff = 1 − (1 − availability) · PROJ_INJURY_FUTURE_GW_FADE`.
     Rotation persists (a squad player is rotated every week); injuries resolve.
   - `prob_start_effective = rotation_prob_start · avail_eff`.
   - Build `minutes_mult` per §3 and multiply `xpts_gw{gw}` by it **instead of**
     the current `play_prob` / injury-fade path.
4. When `PROJ_APPLY_MINUTES_MODEL` is `False`, the current `play_prob` path runs
   unchanged — **fully reversible**, guarantees byte-for-byte current behavior.

The two paths are mutually exclusive to avoid double-discounting injuries
(the minutes multiplier already subsumes availability).

---

## 5. Data flow

```
elements (live bootstrap: status, chance_of_playing_next_round)
player_gw_history CSV (gw_minutes, gw_starts)
        │
        ▼
minutes_model.minutes_projection(gw)
  → prob_start, prob_appear, rotation_prob_start, availability
        │
        ▼
projections.py GW loop  (flag on)
  → minutes_mult per GW  → xpts_gw{gw} *= minutes_mult
        │
        ▼
xpts_horizon, recommender, captain_advisor, league_strategy, /explain
```

---

## 6. Error handling / fallback

- Missing history CSV → `minutes_projection` returns empty → `minutes_mult`
  defaults to `1.0` (no discount = current behavior).
- The whole minutes block is wrapped in `try/except` (mirroring the existing
  blend hook at `projections.py:521-530`); any error falls back to the legacy
  `play_prob` path. Projections must never break.

---

## 7. Validation — ship-fast, guide not gate

`scripts/spotcheck_minutes.py`:
- Runs projections with `PROJ_APPLY_MINUTES_MODEL` off vs on for the current GW.
- Prints the **biggest movers** (largest `xpts_horizon` deltas) with
  `web_name, team, prob_start, minutes_mult, before, after`.
- Asserts a handful of **known cases**:
  - a nailed premium (e.g. Haaland/Salah tier) moves < ~3%;
  - a known squad-rotation player is discounted meaningfully;
  - a flagged/injured player is discounted at least as much as today.
- You eyeball the movers list, then flip `PROJ_APPLY_MINUTES_MODEL = True`.
- Later, sub-project 3 can measure this against 2025-26 ground truth.

---

## 8. Output surface & optional frontend hook

- Add `prob_start` and `minutes_mult` to the projection output whitelist
  (`projections.py` `keep_base`), so the recommender / `/explain` can cite
  "rotation risk" and the frontend can display it.
- **Stretch (defer to the frontend polish cycle):** map `prob_start` to a
  "Nailed / Rotation risk / Doubt" badge on `PlayerCard.tsx`; have the explainer
  mention it. Small, but a strong trust/sellability signal. Not required to ship
  sub-project 1.

---

## 9. Testing (TDD)

Unit tests (pytest), written before implementation:
- `minutes_mult` formula: nailed → 1.0, rotation risk → expected band,
  injured → low; monotonic in `prob_start`.
- Future-GW fade: injury component fades, rotation component does not.
- Flag off → projection output identical to a captured baseline snapshot
  (regression guard on reversibility).
- Missing-history fallback → multiplier 1.0, no exception.

---

## 10. Config additions (`src/config.py`)

```python
PROJ_APPLY_MINUTES_MODEL = False   # master flag; flip True after spot-check
MINUTES_NAILED_START_REF = 0.85    # prob_start at/above which a player is "nailed"
MINUTES_CAMEO_POINT_VALUE = 0.30   # value of a likely cameo relative to a start
# reuses existing PROJ_INJURY_FUTURE_GW_FADE = 0.5 for future-GW injury fade
```

---

## 11. Risks & open questions

- **Coefficient tuning is judgment, not proof** (ship-fast). `NAILED_REF` and
  `CAMEO_VALUE` defaults are reasonable but get refined by the spot-check and,
  later, sub-project 3. Documented as tunable.
- **Pre-season history is thin.** Early-season `prob_start` leans on the prior
  (`MINUTES_START_PRIOR = 0.55`, `MINUTES_PRIOR_WEIGHT = 2.0`); with the relative
  cap this mostly self-corrects, but the first few GWs will be noisier — worth a
  note in launch comms ("rotation signal sharpens as minutes accrue").
- **Interaction with the deferred xG blend.** Because the xG stack's
  `output_model` *also* applies the minutes model, if the full blend is later
  turned on we must ensure the surgical multiplier isn't stacked on top of the
  blended column. Handled by staging (§0) — revisit when sub-project 3 lands.
```
