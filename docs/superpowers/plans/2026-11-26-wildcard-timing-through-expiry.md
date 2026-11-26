# Wildcard timing through expiry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once the wildcard's expiry is inside the model horizon, score every candidate week through expiry and play the best one (now only if it beats every later week by a margin).

**Architecture:** `score_wildcard` gains an `end_gw` that replaces the fixed horizon; `recommend_chips` passes it through; `build_chip_plan` picks the wildcard week with the new rule and adds a `timing` object to the outlook row. Frontend card reads `timing`.

**Tech Stack:** Python/pandas/pytest (FPL backend); React/TS/vitest (fpl-decision-hub).

**Spec:** `docs/superpowers/specs/2026-11-26-wildcard-timing-through-expiry-design.md`

## Global Constraints

- `CHIP_PLAN_WC_HOLD_MARGIN = 3.0` `[untested]`; `CHIP_PLAN_MIN_EV["wildcard"] = 25.0`. Constants live in `src/config.py` only.
- Through-expiry mode iff `expires_gw <= current_gw + horizon - 1`.
- Play now iff `now >= later + margin` and `now > 0`; no later week → play iff `now > 0`.
- `timing = {end_gw, now_gw, now_gain, next_best_gw, next_best_gain, margin}`; `bar` = `next_best_gain + margin` (0 with no later week). Existing outlook/rec fields keep their meaning.
- Other chips, and the wildcard before the expiry is in view, behave exactly as before.
- No entry IDs in committed files.

## Review Focus

- No later week has a positive gain (all filtered as 0) → `next_best_gw` None, `next_best_gain` 0, margin still applies (later = 0): play now iff now ≥ 3. (Pinned in Task 2.)
- Current GW is the expiry week → play iff now > 0, bar 0. (Task 2.)
- `now` week missing from recs (gain 0) and a later week positive → plan the later week, status play with that event_id, no nudge. (Task 2.)
- Second half: expiry 38 enters the horizon at GW31; same rule. (Task 2, parametrised via `chip_windows`.)
- Older frontend without `timing`: `bar` stays a number, `event_id`/`ev_gain` populated. (Task 3 keeps the old path.)

---

### Task 1: `score_wildcard(end_gw=...)` + config

**Files:** Modify `src/chip_advisor.py` (`score_wildcard`, `recommend_chips`), `src/config.py`. Test `tests/test_chip_wildcard_timing.py`.

**Interfaces — Produces:** `score_wildcard(..., end_gw: int | None = None)`: when set, `future_gws = [g for g in range(gw, end_gw + 1) if projections exist]` and `horizon` is ignored. `recommend_chips(..., wc_end_gw: int | None = None)` forwards it.

- [ ] Test `test_end_gw_scores_through_expiry`: 3 GWs of projections where the wildcard side beats the squad by 1 pt each GW; `end_gw=3` from gw 1 → ev 3.0, `window_gws == [1, 3]`; from gw 2 → 2.0; default (horizon 2) from gw 1 → 2.0.
- [ ] Implement; config: `CHIP_PLAN_WC_HOLD_MARGIN = 3.0  # [untested]`, wildcard bar 25.0 with a 2026-11-26 calibration comment (no entry ids).
- [ ] Run `pytest tests/test_chip_wildcard_timing.py tests/test_chip_wildcard_netting.py -q` → pass. Commit.

### Task 2: through-expiry week selection in `build_chip_plan`

**Files:** Modify `src/chip_advisor.py` (`build_chip_plan`, `_chip_guidance`). Test `tests/test_chip_wildcard_timing.py`.

**Interfaces — Consumes:** Task 1. **Produces:** pure helper `pick_wildcard_week(curve: dict[int, float], now_gw: int, margin: float) -> dict` returning `{"event_id", "now_gain", "next_best_gw", "next_best_gain", "bar", "play_now"}`; outlook row `timing` key.

- [ ] Tests for `pick_wildcard_week`:
  - owner shape `{12:17.4,13:10.2,14:8.9,15:10.2,16:9.6,17:7.9,18:5.1,19:2.0}`, now 12 → event 12, play_now True, next_best (13 or 15 → earliest of ties = 13) 10.2, bar 13.2.
  - ordinary shape `{12:0.9,13:0.4,14:2.1,15:6.3,16:6.3,17:5.2,18:2.8,19:0.6}` → event 15, play_now False.
  - within margin `{12:10.0,13:8.0}` → event 13, play_now False.
  - expiry week `{19:0.6}`, now 19 → event 19, play_now True, bar 0, next_best_gw None.
  - no later positive `{12:2.0}` with later weeks absent → play_now False only if 2.0 < 3 → event 12, play_now False (hold, nothing better: status hold).
  - nothing positive `{}` → event None.
- [ ] Integration test via `build_chip_plan` (monkeypatch `score_wildcard`/projections minimal, current_gw 12, horizon 8, no chips played): wildcard outlook has `timing.end_gw == 19`, status play, event 12, nudge chip wildcard. With current_gw 5 (expiry not in view) → no `timing`, bar 25 rule.
- [ ] Implement: in timing mode, call order — `recommend_chips(..., wc_end_gw=expires)`; selection via `pick_wildcard_week`; status `play` when `event_id` is not None and (`play_now` or event later than now with gain > 0); `hold` when the chosen week is now but `play_now` False. Guidance branch for timing (play now / plan later / hold within margin), each naming `end_gw` and the next best week.
- [ ] Run chip tests `pytest tests -q -k chip` → pass. Commit.

### Task 3: frontend card

**Files:** `src/lib/fplAssistantApi.ts` (`ChipOutlookRow.timing?`), `src/lib/planFlow.ts` (wildcard card), `src/lib/planFlow.test.ts`.

- [ ] Tests: with `timing` and nudge wildcard → `gain` = `timing.now_gain`, gainNote `through GW19 · next best GW13 +10.2`; with timing and hold (event 15) → gain = now_gain, gainNote `through GW19 · best week GW15`; without timing → existing "needs N pts to play" note unchanged.
- [ ] Implement, run `npx vitest run src/lib src/components/plan` → pass. Commit.

### Task 4: docs, verify, PRs

- [ ] `docs/chip-planner.md`: one paragraph on the two modes. Full backend suite; security review per phase; PR bodies list the calibration evidence and the not-backtested caveat.
