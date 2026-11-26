# Wildcard timing through expiry — design (approved 2026-11-26)

## Why

The chip planner scored every wildcard week over a fixed 5-GW window and
played it only when that gain beat a flat bar (40, ramping to 0 over the last
5 GWs before expiry). Two faults, both measured on GW12 data with the fixed
xG context (PR #91):

- Weeks were never compared with each other. A wildcard keeps paying after
  week 5: the owner's GW12 gain was +12.8 over 5 GWs and +17.4 through GW19.
- Windows near expiry are truncated (GW12–19: 5,5,5,5,4,3,2,1 weeks), so late
  weeks look small, and the ramp then plays the chip on one of them (~+5 at
  GW18) instead of the best week (+17.4 at GW12).

Scored to a common end (GW19), the owner's best week is GW12; an ordinary
squad's best week is GW15–16, so the rule does not simply favour "now".

## Decided

1. **Two modes.** When the chip's `expires_gw` is inside the model horizon
   (`expires_gw <= current_gw + horizon - 1`), the wildcard is timed through
   expiry. Before that (early in each half), the old rule stays: best 5-GW
   gain vs the bar, as an emergency trigger for a broken squad.
2. **Through-expiry scoring.** Each candidate week g is scored over g..expiry
   (same both-sides scoring as today: best XI per GW, plan squads net of hits,
   preset draft for the wildcard side).
3. **Rule.** Let `now` = gain if played this week, `later` = best gain of any
   later week up to expiry. Play now iff `now >= later + margin` (and
   `now > 0`); otherwise the plan is the best later week. With no later week
   (the expiry week itself) the margin does not apply: play if `now > 0`.
   `margin = CHIP_PLAN_WC_HOLD_MARGIN = 3.0` pts `[untested]`: projection
   noise plus the value of keeping the chip for an injury crisis.
4. **Bar.** `CHIP_PLAN_MIN_EV["wildcard"]` 40 → 25 (above every ordinary squad
   sampled on fixed numbers, max +23; catches ~10/16 synthetic broken squads).
   The expiry ramp no longer affects the wildcard (its last 5 GWs are always
   in through-expiry mode). Other chips unchanged.
5. **Payload.** The wildcard outlook row gains a `timing` object (only in
   through-expiry mode): `{end_gw, now_gw, now_gain, next_best_gw,
   next_best_gain, margin}`. `bar` in that mode is the gain this week must
   reach (`next_best_gain + margin`, or 0 with no later week). Existing fields
   keep their meaning, so an older frontend still renders.
6. **Card copy (frontend).** Replace "needs N pts to play" with the timing
   comparison when `timing` is present, e.g. "through GW19 · next best GW13
   +10.2" (play now) or "through GW19 · best week GW15" (hold). Guidance text
   comes from the backend.

## Out of scope

Triple Captain bar (15 → ~10.5) and the TC/BB expiry ramp: separate config
change awaiting sign-off. Second wildcard draft horizon: the preset draft is
still built for 5 GWs and scored over the longer window (a lower bound for the
wildcard side).

## Evidence / gating

`scripts/backtest_season.py` calls `recommend_chips` with its own floors and
no drafts or transfer plan, so it does not exercise this path. Evidence is the
GW12 calibration rerun (scratch scripts, not committed) plus
`chip_plan_snapshots` over the following GWs. Unit tests pin: owner-shaped
curve plays now, ordinary-shaped curve waits, within-margin holds, expiry-week
edge, early-season mode unchanged.
