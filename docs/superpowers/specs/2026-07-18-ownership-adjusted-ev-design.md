# Ownership-Adjusted EV + Captain-Differential Flag — Design

**Date:** 2026-07-18
**Repo:** `FPL/` (backend)
**Status:** Approved design, pre-implementation
**Sub-project:** 2 of 4 in the pre-season recommendation-robustness cycle (see
`2026-07-17-minutes-rotation-model-design.md` §0 for the full decomposition)

---

## 1. Goal & non-goals

**Goal:** Make the mini-league strategy genuinely *differential-aware*. Replace
the raw-xPts candidate ranking in `league_strategy` with an **ownership-adjusted
expected-value** score, and add a **captain-differential flag**. This is the core
"beat your mates, not the game" positioning.

**Non-goals:**
- Any change to the projection engine or the minutes model (sub-project 1).
- Frontend rendering of the new fields (`League.tsx`) — deferred to the frontend
  cycle; this sub-project only makes the API return them.
- Global "effective ownership" tooling (we stay mini-league-specific).

---

## 2. Current state (verified against code, 2026-07-18)

- `src/league.py:league_ownership(rival_squads)` returns, per player, the
  fraction of the supplied squads (±3 neighbour rivals + me) that own them — the
  true mini-league ownership signal.
- `src/league_strategy.py`:
  - `analyze_league(...)` produces `league_ownership` and `differentials`.
  - `_player_meta(...)` builds per-player meta carrying `selected_by_percent`
    (global ownership, a string like `"23.4"`), `model_xpts_horizon`, `ep_next`,
    `now_cost`, `position_id` (= `element_type`), `fixtures`.
  - `_candidate_targets(analysis, elements_meta, mode)` (`~L103-151`) ranks
    candidates **purely** by `ep()` = `model_xpts_horizon` (fallback `ep_next`).
    Ownership is attached to rows (`league_ownership`) but **never scored**.
    Differential mode applies a hard `league_own >= 0.20` skip filter only.
  - `_llm_narrative(...)` cites `model_xpts_horizon` in the strategy text.
  - `build_strategy(...)` assembles the response.

**Key advantage over sub-project 1:** this feature **works pre-season**. Both
`selected_by_percent` (draft-squad ownership) and projections exist in July, so
the template and EV are computable now — it can ship enabled for launch.

---

## 3. The differential-EV score (`src/ownership_ev.py`, new module)

A small pure module, unit-testable in isolation, keeping `league_strategy.py`
from growing further.

**Position template (global-ownership-weighted baseline):**
```
for each position pos in {GKP, DEF, MID, FWD}:
    w_i   = float(selected_by_percent_i)          # global ownership, players i at pos
    x_i   = xpts_horizon_i                          # model_xpts_horizon, fallback ep_next, fallback 0
    template_xpts[pos] = Σ(w_i · x_i) / Σ(w_i)      if Σ(w_i) > 0
                       = mean(x_i)                   otherwise (degenerate: no ownership data)
```
This is "what the field effectively gets at this position" — the opportunity cost
you net out.

**Differential EV (per player):**
```
league_own    = clip(league_ownership, 0, 1)        # from analyze_league; missing -> 0
differential_ev = (xpts_horizon − template_xpts[pos]) · (1 − league_own)
```
- Above-template players at low league ownership score highest (the differentials
  worth making).
- Below-template players get **negative** EV (correctly deprioritised).
- A player everyone in your league owns (`league_own → 1`) scores ~0 regardless of
  xPts — owning them can't differentiate you.

**Public functions:**
- `compute_position_templates(elements_meta) -> dict[int, float]` keyed by
  `position_id` (1=GKP…4=FWD).
- `differential_ev(xpts_horizon, template_xpts_pos, league_ownership) -> float`.
- `annotate_candidates(candidates, templates, ownership) -> list` — adds
  `differential_ev` and `template_xpts` to each candidate row (pure, returns new
  list).

**Edge cases:** `selected_by_percent` coerced via `float(... or 0)`; a position
with zero total ownership falls back to the simple mean; missing `xpts_horizon`
falls back to `ep_next` then `0.0`; missing `league_ownership` → `0.0` (full
differential weight).

---

## 4. Ranking wiring (`league_strategy._candidate_targets`)

Behind `config.LEAGUE_EV_RANKING` (default **True**):

- Compute `templates = ownership_ev.compute_position_templates(elements_meta)`
  once in `build_strategy` (or lazily in `_candidate_targets`).
- In **all three modes** (chase / defend / differential), after building the
  candidate list, annotate with `differential_ev` and **sort by `differential_ev`
  descending** instead of `ep()`.
- Differential mode keeps its `league_own >= 0.20` skip filter, then ranks the
  survivors by `differential_ev`.
- When `LEAGUE_EV_RANKING = False`, the existing `ep()` sort runs unchanged
  (reversibility / A-B).

Candidate rows keep `model_xpts_horizon` and `league_ownership` for display and
gain `differential_ev` + `template_xpts`.

---

## 5. Captain-differential flag (`league_strategy.detect_captain_differential`)

`detect_captain_differential(analysis, elements_meta, templates, fixture_ticker) -> dict | None`:

1. **Consensus captain** = among players with `now_cost >= LEAGUE_EV_CAPTAIN_PREMIUM_FLOOR`
   (default 85 = £8.5m) and position ∈ {MID, FWD}, the one with the **highest
   league ownership** (the player your league will captain). None qualifying → return `None`.
2. **Hard fixture?** Look up the consensus captain's team's next-GW difficulty band
   in `fixture_ticker`; hard iff band ∈ {`hard`, `very_hard`}. No ticker / not hard
   → return `None`.
3. **Alternative** = among MID/FWD players with `league_ownership < LEAGUE_EV_CAPTAIN_DIFF_MAX_OWNERSHIP`
   (default 0.10) and positive `differential_ev`, the highest-`differential_ev` one.
   None → return `None`.
4. Otherwise emit:
   ```json
   {
     "consensus_captain": {"id","web_name","team_short","league_ownership","fixture","model_xpts_horizon"},
     "alternative":       {"id","web_name","team_short","league_ownership","differential_ev","model_xpts_horizon","fixture"},
     "reason": "<consensus captain> faces <hard fixture>; <alt> is a <own%> differential."
   }
   ```

---

## 6. Narrative integration (`_llm_narrative`)

- Add `differential_ev` (and `league_ownership`) to each candidate line in the
  `USER_TEMPLATE`, and update the rules so every rationale cites the differential
  EV and league ownership (e.g. "+6.2 diff-EV at 14% league ownership").
- When `captain_differential` is present, add a `Captain differential:` line to the
  prompt and instruct the model to surface it in the headline/watchouts.
- `SYSTEM_PROMPT` gains "use ONLY the provided differential_ev / league_ownership
  numbers" to keep the no-hallucinated-numbers guarantee.

---

## 7. Output surface (`build_strategy`)

- `candidates[*]` gain `differential_ev`, `template_xpts`.
- Response gains `captain_differential` (object or `null`).
- No breaking change to existing fields; consumers select by name.

---

## 8. Config additions (`src/config.py`)

```python
# --- mini-league ownership-adjusted EV (src/ownership_ev.py + league_strategy.py) ---
LEAGUE_EV_RANKING = True              # rank candidates by differential EV (False = legacy raw-xPts sort)
LEAGUE_EV_CAPTAIN_PREMIUM_FLOOR = 85  # now_cost (tenths) floor for a "premium" captain (£8.5m)
LEAGUE_EV_CAPTAIN_DIFF_MAX_OWNERSHIP = 0.10   # alt must be under this league ownership to flag
```

---

## 9. Validation (spot-check, ship-fast)

`scripts/spotcheck_league_ev.py`: for a sample entry+league, print the top-10
candidates under the legacy `ep()` sort vs. the new `differential_ev` sort
side-by-side (name, model_xpts, league_own, template, differential_ev), plus the
`captain_differential` result. You eyeball that highly-owned premiums drop and
genuine low-owned differentials rise. Guarded to skip cleanly if no live league
data is reachable.

---

## 10. Testing (TDD)

Unit tests (`tests/test_ownership_ev.py`):
- `compute_position_templates`: global-ownership-weighted average per position;
  zero-ownership fallback to mean; string `selected_by_percent` coercion.
- `differential_ev`: above-template + low ownership > below-template; owner-of-all
  (`league_own=1`) → ~0; missing ownership → full weight; below-template → negative.
- Ranking: a high-xPts/high-league-owned player ranks **below** a lower-xPts
  low-owned differential once EV-sorted.

Unit tests (`tests/test_captain_differential.py`):
- Hard consensus-captain fixture + qualifying alt → flag emitted with both players.
- Easy fixture → `None`. No premium owner → `None`. No <10% alt → `None`.

`tests/test_league_strategy_ranking.py`: `_candidate_targets` sorts by
`differential_ev` when `LEAGUE_EV_RANKING=True`, and reproduces the legacy `ep()`
order when `False` (reversibility), using a fabricated `analysis`/`elements_meta`
(no network).

---

## 11. Rollout

- `LEAGUE_EV_RANKING` ships **True** (works pre-season, is the tool's core value).
  Reversible to legacy behaviour via the flag.
- The spot-check is for confidence, not a gate.

---

## 12. Risks & open questions

- **Coarse league ownership.** With ±3 rivals (~7 squads incl. me), the
  `(1 − league_ownership)` multiplier moves in ~1/7 steps. This is the real
  mini-league signal, accepted; documented so the narrative doesn't over-claim
  precision.
- **Template sensitivity to `selected_by_percent`.** Pre-season draft ownership is
  volatile; the template will shift as the field settles. Acceptable — it always
  reflects current field state, and the flag allows falling back.
- **Consensus-captain heuristic** (highest league-owned premium MID/FWD) is a
  proxy; a manager could captain differently. Documented as a heuristic; the flag
  is advisory, surfaced in narrative, never forced.
```
