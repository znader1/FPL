# Transfer Planner v2: FT Banking Verdict, Injury Priority, GW-Boundary Correctness, xG-Powered Projections

**Date:** 2026-08-24 (v2 revision 2026-08-25)
**Status:** Approved design, pending implementation plan
**Branch:** backend `feature/xg-expected-points`, frontend branch off `fix/auth-token-on-api-calls`

## v2 revision note

v1 designed a new two-branch module before discovering `src/transfer_planner.py` already ships a greedy multi-GW roll/bank horizon walk (commit `e013f98`), emitted as `transfer_plan_horizon` and rendered by the frontend's `HorizonTransferPlan`. v2 extends that module instead of duplicating it, and adds workstream B: making the projections that feed it xG-based, gated on backtest evidence.

## Problem

The shipped horizon planner rolls/spends on a raw threshold but: ignores injuries entirely, exposes no single verdict the UI can lead with, receives a free-transfer count derived by a binary 1/2 heuristic (rule allows banking to 5), and consumes form data that can include a half-played gameweek. Separately, projections still run on the ppg/form baseline — the xG expected-points stack (including the new defensive-contribution term) sits inert at `PROJ_MODEL_BLEND_WEIGHT = 0.0`.

## Goals

**Workstream A — planner correctness:**
1. Red-flagged likely-XI players force a spend verdict; rolling is never recommended while one sits in the XI.
2. Top-level `verdict` + human `reasoning` on the plan (`roll` / `spend` / `spend_forced_injury`).
3. FT derivation accurate to the 5-cap banking rule (authenticated value clamped [1,5]; season-walk fallback).
4. Recommendations target the next deadline; form inputs use only finished gameweeks.
5. Planner A/B backtest (planner-driven transfers vs always-spend) on 2025-26 before any default-behaviour claim.

**Workstream B — xG-powered predictions:**
6. Run the DC-term A/B and the blend-weight sweep on 2025-26 Vaastav data; raise `PROJ_MODEL_BLEND_WEIGHT` to the winning weight only if it beats the baseline. Planner and all recommendations then run on xG-blended, latest-data projections with zero code coupling.

Non-goals: rewriting the greedy walk into beam/DP (backtest decides if that's ever needed), price prediction, new response blocks (extend `transfer_plan_horizon` in place).

## Architecture

No new modules. Touched units:

```
api/main.py            FT season-walk fallback; clamp; pass injury columns onward
src/transfer_planner.py  injury gate + verdict/reasoning fields (extends plan_transfers)
src/projections.py     finished-GW-only form inputs (audit + targeted fix)
src/config.py          PROJ_MODEL_BLEND_WEIGHT raise (workstream B, evidence-gated)
scripts/backtest_season.py  --planner A/B mode
frontend RecommendationsPanel/HorizonTransferPlan  verdict banner (additive)
```

## Workstream A design

### Injury gate (`src/transfer_planner.py`)

`_build_info` gains `status` and `chance_of_playing_next_round` per player. Red flag = `status` in (`i`, `s`, `u`) or `chance == 0`. In the first horizon GW, red-flagged squad members in the likely XI (top-11 of squad by first-GW xPts, formation-legal not required for this check) are forced sells: the walk must propose their best like-for-like replacement even when gain < `min_gain` (threshold bypassed for forced sells only). While a forced sell exists, `action` for that GW is `transfer` and the top-level verdict is `spend_forced_injury`. Red-flagged bench players and yellow doubts (25/50/75) change nothing.

### Verdict + reasoning

`plan_transfers` return gains:
- `verdict`: from the first horizon GW — `spend_forced_injury` (injury gate fired) else `transfer`→`spend` / `roll`→`roll`.
- `reasoning`: template string, e.g. roll: `"Best available move gains +1.3 xPts (< 2.0 threshold). Roll the FT (2→3) — next GW the plan makes 2 moves for +4.1."`; spend: names the move(s) and gain; forced: names the flagged player.
- `first_gw_ft_before` / `first_gw_ft_after` for the banner.
All additive; existing per-GW `plan` list unchanged.

### FT derivation (`api/main.py`)

- Authenticated `my_team._free_transfers`: clamp to [1, 5] (today unclamped int).
- Fallback: replace the binary heuristic with a season walk over `entry/{id}/history` current-season events (add the fetch if not already in this path): start `ft = 1` at GW1; per finished GW `ft = min(5, ft − event_transfers + 1)` with floor 0 before the +1; Wildcard/Free-Hit GWs consume no banked FTs (chip GWs from `chips` list in the same history payload). Unfinished (in-play) GW: its `event_transfers` still subtracts — spent is spent — but the +1 accrual for the next GW only counts once that GW's deadline has passed.

### GW-boundary rules (`src/projections.py`, `api/main.py`)

- Transfer target: audit `/recommendations` for `is_current` leakage while a GW is in play; target is always the `is_next` deadline.
- Form inputs (recent-average window, `latest_n_matches`): only rounds whose event has `finished == true`; in-progress GW rows dropped via the same exclusion mechanism as blank GWs.

### Backtest gate (`scripts/backtest_season.py`)

New `--planner` mode: transfers each GW are chosen by `plan_transfers`'s first-GW action (including rolling) instead of the always-spend path. A/B vs the existing always-spend baseline over 2025-26 GW2–29. Report total points, transfer count, hits taken.

## Workstream B design (xG activation)

Pure evidence runs — the code already exists:
1. **DC A/B:** `OUTPUT_APPLY_DC` on vs off through the season backtest; keep on only if MAE/total-points don't regress.
2. **Blend sweep:** the existing blend-weight sweep (commit `c40e10b`) over `PROJ_MODEL_BLEND_WEIGHT` ∈ {0.0 … 1.0}; pick the argmax on 2025-26.
3. **Decision:** raise `PROJ_MODEL_BLEND_WEIGHT` default to the winner only if it beats weight 0.0; record numbers in the plan. In-season: knowledge-discount file + live 2026-27 data keep ratings current (existing refresh path); cold-start convergence monitoring stays per roadmap.

## API contract

`transfer_plan_horizon` extended (additive):

```json
{
  "verdict": "roll | spend | spend_forced_injury",
  "reasoning": "Best available move gains +1.3 xPts (< 2.0). Roll the FT (2→3) — next GW the plan makes 2 moves for +4.1.",
  "first_gw_ft_before": 2,
  "first_gw_ft_after": 3,
  "...": "all existing fields unchanged (gws, plan[], total_net_gain, ...)"
}
```

## Frontend

`HorizonTransferPlan` gains a verdict banner (three variants + hidden when fields absent); `FplTransferPlanHorizon` type extended in `src/lib/fplAssistantApi.ts`. Existing table rendering untouched.

## Error handling

- Planner exceptions: existing behaviour kept — block omitted, response never breaks.
- History fetch failure → FT falls back to authenticated value, else existing heuristic, else 1.
- Missing status columns in projections → injury gate no-ops (no force, no crash).

## Testing

- **Unit:** FT season walk (banking to 5, WC/FH weeks, in-play GW spend-but-no-accrual); injury gate (red starter forces, red bench doesn't, yellow doesn't, missing columns no-op); verdict/reasoning for all three verdicts; clamp of authenticated FT.
- **Backtest:** `--planner` A/B; DC A/B; blend sweep. Numbers recorded in the plan doc before any default flips.
- **Frontend:** vitest for the banner variants + absent-field fallback.
- **Staging:** full flow on the existing staging pair before prod flip.
