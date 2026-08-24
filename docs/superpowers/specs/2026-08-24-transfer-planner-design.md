# Transfer Planner: FT Banking, Injury Priority, GW-Boundary Correctness

**Date:** 2026-08-24
**Status:** Approved design, pending implementation plan
**Branch:** backend `feature/xg-expected-points`, frontend branch off `fix/auth-token-on-api-calls`

## Problem

The transfer recommender decides one gameweek at a time and always proposes spending the free transfer, even when the best available move gains little. The 2026-27 rule change allows banking up to 5 free transfers, which the current FT derivation (binary 1/2 heuristic) cannot represent. Two further correctness gaps: recommendations can consume data from a gameweek still being played, and injured players are only softly prioritised for removal.

## Goals

1. Recommend **rolling** the FT when banking projects more total points than spending now.
2. Track free transfers accurately up to the cap of 5.
3. Force a transfer (never recommend rolling) when a red-flagged player sits in the likely XI.
4. Target the next deadline and use only fully finished gameweeks for form inputs.
5. Gate the planner behind a backtest win before it defaults on.

Non-goals: multi-GW beam search over move sequences (approach A, rejected), DP over FT states (approach C, rejected as overkill), price-change prediction, any change to the xG shadow-model blend (orthogonal; planner consumes whatever projections produce).

## Architecture

New pure module `src/transfer_planner.py`, dependency-injectable like the backtest modules. `suggest_transfers` in `src/recommender.py` is **not modified** — the planner calls it per branch.

```
api/main.py /recommendations
  → src/transfer_planner.py  plan_transfers()     [NEW]
      → src/recommender.py   suggest_transfers()  [unchanged, called per branch]
      → projections xpts_gw{N} columns            [already exist]
  → response gains an additive "transfer_plan" block
```

### Config (`src/config.py`)

| Name | Default | Meaning |
|---|---|---|
| `PLANNER_ENABLED` | `False` | Master flag; stays off until the backtest gate passes |
| `PLANNER_LOOKAHEAD_GWS` | `1` | How far ahead the bank branch looks |
| `PLANNER_ROLL_MARGIN` | `0.4` | Bank branch must beat spend by this many xPts to recommend rolling (hysteresis against projection noise) |
| `FT_MAX` | `5` | 2026-27 banking cap |

## Planner algorithm (`plan_transfers`)

Inputs: squad frame, elements, in-the-bank money, free transfers, projections with `xpts_gw{N}` columns, next event id.

1. **Injury gate.** Squad players with red-flag status (`i` long-term, `s`, `u`, or `chance_of_playing_next_round == 0`) who are in the likely XI (current optimizer starters) force verdict `spend_forced_injury`. Branch comparison is skipped; `suggest_transfers` runs normally — the existing `injury_sell_boost` ordering and `TRANSFER_GUARDRAIL_INJURY_OVERRIDE` min-gain bypass already surface the replacement. Red-flagged bench players do not force; yellow doubts (25/50/75) keep their existing soft boost.
2. **Branch SPEND.** `suggest_transfers(..., free_transfers=ft, score_col="xpts_horizon")` → `gain_spend`.
3. **Branch BANK.** Squad unchanged for the next GW (0 gain now); re-run `suggest_transfers` with `free_transfers=min(ft+1, FT_MAX)` scored on the horizon shifted one GW (`xpts_gw{next+1}` onward) → `gain_bank`. The extra FT lets the beam find two-move combinations invisible to a single-FT search.
4. **Verdict.** `roll` if `gain_bank − gain_spend > PLANNER_ROLL_MARGIN` and `ft < FT_MAX`; otherwise `spend`. At `ft == FT_MAX`, never roll (the FT would be forfeited). Both branch gains and the margin are returned.

Stated simplification: the bank branch assumes next-GW prices ≈ current prices and no new injuries. Projection noise dominates one week of price drift; accepted.

## FT derivation (`api/main.py`)

- Authenticated path: `my_team._free_transfers` is the real value — trust it, clamp to [1, `FT_MAX`].
- Fallback: replace the binary heuristic with a season walk over the `entry/{id}/history` events (reuse the response if the endpoint is already fetched in this path; otherwise add the one call), simulating the rule from GW1: `ft = min(FT_MAX, ft − used + 1)` per finished GW; Wildcard/Free-Hit gameweeks do not consume banked FTs.

## GW-boundary rules

- Transfer target is always the `is_next` deadline; audit the `/recommendations` path for `is_current` leakage while a GW is in play.
- Recent-form windows and the FT season walk consume only rounds whose event has `finished == true` (same exclusion mechanism as blank GWs). In-progress GW rows are dropped from performance inputs.
- `event_transfers` of the in-play GW still counts for FT math — transfers already spent are spent; only performance data of unfinished rounds is excluded.

## API contract

Additive `transfer_plan` block in the `/recommendations` response; all existing fields unchanged. Absent when `PLANNER_ENABLED` is off.

```json
{
  "verdict": "roll | spend | spend_forced_injury",
  "free_transfers": 2,
  "ft_after_roll": 3,
  "gain_spend": 0.9,
  "gain_bank": 3.1,
  "margin": 2.2,
  "spend_moves": ["...existing move payload shape..."],
  "bank_preview_moves": ["...the two-move combo found next GW..."],
  "reasoning": "Bank the FT (2→3): double move next GW projects +3.1 xPts vs +0.9 spending now."
}
```

## Frontend

Branch off `fix/auth-token-on-api-calls` (keeps auth + staging wiring). Changes are additive: verdict banner on the transfers view, bank-preview move cards reusing the existing move-card rendering, and the `transfer_plan` type added to `src/lib/fplAssistantApi.ts`. With no `transfer_plan` in the response, the UI renders exactly as today.

## Error handling

- Planner failures degrade gracefully: any exception inside `plan_transfers` logs and omits the `transfer_plan` block — the legacy recommendation payload is never blocked.
- Missing `xpts_gw{next+1}` columns (end of season, short projection horizon) → bank branch unavailable → verdict `spend` with reasoning noting the horizon limit.
- History fetch failure → FT falls back to the authenticated value or 1.

## Testing

- **Unit:** planner pure functions — roll verdict, margin hysteresis, `ft == FT_MAX` never rolls, injury force (red starter vs red bench vs yellow), FT season walk including Wildcard/Free-Hit weeks, graceful degradation paths.
- **Backtest gate:** extend `scripts/backtest_season.py` with a `--planner` mode; A/B the banking planner vs always-spend over 2025-26 GW2–29 on Vaastav data. `PLANNER_ENABLED` defaults on only if banking wins or ties total points.
- **Frontend:** vitest component test for the banner (all three verdicts + absent block).
- **Staging:** full flow on the existing staging pair (Fly dev app + Vercel preview) before any prod flip.
