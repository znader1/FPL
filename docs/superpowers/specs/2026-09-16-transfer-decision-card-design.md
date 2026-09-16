# Transfer Decision Card — design

**Date:** 2026-09-16 · **Status:** approved in chat, awaiting spec review
**Repos:** backend `FPL` (this repo), frontend `FPL-Assistant-Front/fpl-decision-hub`
**Sub-project 1 of 4** (see "Programme" at the end).

## Problem

The Transfers tab's verdict is one backend prose string
(`src/transfer_planner.py:381-394`, counterfactual clause appended at `:356-359`)
rendered verbatim (`RecommendationsPanel.tsx:361`). Three defects:

1. **Horizon is invisible.** `+2.79 xPts` in the verdict and `+2.8` on the GW5 row
   are both the sum over the plan horizon (min 3 GWs, `TRANSFER_PLAN_MIN_HORIZON_GWS`),
   while `net +6.48` is the whole 3-GW plan. Nothing on the card says which number
   covers which weeks. The per-GW slice (`this_gw_gain`, shipped 2026-09-12) exists in
   the payload but is not rendered on the card.
2. **Prose, not a decision.** "Move now: X -> Y (+2.79 xPts >= 2.0 threshold) — beats
   rolling for next week's no move (net +6.48 vs +0.0)." mixes the action, the bar,
   and the counterfactual into one sentence with four numbers.
3. **Apply acts on the wrong engine.** "Apply next transfer" steps through the
   single-GW beam list (`transfers.moves`, `Index.tsx:442-455`,
   `squad_with_transfers_steps`), not the plan's move. The card says "make the move";
   the button may apply a different one. The "not in plan — plan says hold" badge is a
   symptom of this.

## Decisions taken (from brainstorm)

- Headline shows **both** numbers, this-GW first: `+0.9 this GW · +2.8 over GW5–7`.
- **One answer.** The multi-GW plan is the recommendation. Beam options become a
  collapsed "Alternatives — this GW only" list. The top-level Apply applies the plan.
- No change to thresholds, horizons, engines, or chip logic. Engine quality is
  sub-project 2 and is backtest-gated (season points is the gate, MAE reported).

## Backend

### `src/transfer_planner.py` — structured verdict

`plan_transfers` gains a `verdict_detail` dict beside the existing `verdict` and
`reasoning`. Derived from data already computed; the decision logic is untouched.

```python
"verdict_detail": {
    "action": "spend" | "roll" | "spend_forced_injury",
    "horizon": {"start_gw": 5, "end_gw": 7, "n": 3},
    "ft_before": 1,
    "ft_after": 0,                    # == first_gw_ft_before / first_gw_ft_after
    "threshold": 2.0,                 # min_gain actually used
    "moves": [                        # first-GW moves; [] on roll
        {"sell": {...}, "buy": {...}, "position": "MID",
         "this_gw_gain": 0.9, "horizon_gain": 2.8,
         "forced_injury": False, "h2h_conflicts": []}
    ],
    "this_gw_gain": 0.9,              # sum over moves
    "horizon_gain": 2.8,              # sum over moves (== plan[0].gw_gain)
    "hit_cost": 0.0,                  # plan[0].hit_cost
    "plan_net": 6.5,                  # total_net_gain of the returned plan
    "roll_alternative": {             # None when no counterfactual was run
        "net": 0.0,                   # roll_alternative_net_gain
        "gw": 6,                      # first GW the roll path moves in
        "moves": [{"sell": {...}, "buy": {...}, "horizon_gain": 3.7}]   # [] = "no move"
    },
    "next_move": {                    # roll only: first later transfer in the plan
        "gw": 6, "moves": [...], "horizon_gain": 3.7
    } | None
}
```

Rules:
- When the counterfactual flips the verdict to `roll` (`:348-355`), `verdict_detail`
  is built for the **returned** (alt) plan, with `roll_alternative` describing the
  rejected spend path: `{"net": <spend plan total>, "gw": <first gw>, "moves": [...]}`.
  Field name stays `roll_alternative` for a stable schema; `action` disambiguates.
- `reasoning` is kept for `/chat`, `agents/transfer_agent.py:90` and `/explain`, but
  shortened to one clause per case (no counterfactual clause appended). Examples:
  - spend: `Move now: Szoboszlai -> Tavernier (+0.9 this GW, +2.8 over GW5-7).`
  - roll: `Roll: bank the FT (1->2); best next move is Rogers -> Saka in GW6 (+3.7).`
  - forced: `Flagged player (Rogers) in your likely XI — replace now.`
- `_note` per-GW strings unchanged (rendered in the staircase rows).

### `api/main.py` — plan moves become the applyable moves

After both `transfer_preview` (beam) and `transfer_plan_horizon` exist and before the
`squad_with_transfers_steps` loop (`:1500`):

1. If `verdict_detail.action` is `spend` or `spend_forced_injury`, build
   `plan_moves` from `verdict_detail.moves` in beam move shape
   (`recommender.move_from_seller_buyer` keys: `position`, `sell`, `buy`, `score_gain`,
   plus `buy_hot_score`/`buy_set_piece_score` when derivable, else omitted).
2. `transfers.moves = plan_moves + [m for m in beam_moves if (sell.id, buy.id) not in plan_pairs]`.
3. Every move gets `in_plan: true|false`. `transfers.transfer_plan.transfer_count_built`
   updated to the new length. `moves_by_position` rebuilt from the merged list.
4. Steps are then built from the merged list unchanged, so `apply_transfer_count=1`
   applies the recommendation. When two plan moves exist, steps 1 and 2 are the plan.
5. On `roll`, `transfers.moves` is the beam list as today, all `in_plan: false`.
6. Wrapped in the same never-fail `try/except` as the plan itself; on any failure the
   beam list is returned untouched.

`annotate_moves_next_fixture` runs **after** the merge so plan moves get fixture labels.

No change to `suggest_transfers`, `plan_transfers` search, or config.

## Frontend

### Types — `src/lib/fplAssistantApi.ts`

- `FplTransferMove.in_plan?: boolean`.
- `FplTransferPlanMove.this_gw_gain?: number` (already emitted, not typed).
- `FplTransferPlanHorizon.verdict_detail?: FplTransferVerdictDetail` mirroring the
  schema above.

### `DecisionCard` replaces `VerdictBanner` (`RecommendationsPanel.tsx:330-369`)

Renders from `verdict_detail`; falls back to today's `reasoning` banner when
`verdict_detail` is absent (old backend, or planner failure). `data-testid` stays
`plan-verdict-banner` so existing tests keep their anchor.

Spend / forced layout:

```
MAKE THE MOVE                                     FT 1→0
Szoboszlai (LIV £7.0) → Tavernier (BOU £6.1)
+0.9 this GW   ·   +2.8 over GW5–7
Plan GW5–7 nets +6.5 · rolling instead nets +0.0        [Apply]
```

- Forced-injury uses the destructive tone and a "flagged" chip on the seller.
- Hits (when `allow_hits`): third number `−4 hit` and the this-GW figure is net.
- `[Apply]` = existing `onApplyTransferAtIndex(k-1)` for k plan moves (the plan moves
  are indices 0..k-1 after the backend merge). Button label "Applied" and disabled
  once `appliedTransferCount >= k`. Hidden when `onApplyTransferAtIndex` is absent.

Roll layout:

```
ROLL                                              FT 1→2
Bank the free transfer. No move clears +2.0 over GW5–7.
Next planned move: Rogers → Saka in GW6 (+3.7 over GW6–7)
```

When `roll_alternative` exists (spend was rejected): second line reads
`Moving now (X → Y) would net +A over GW5–7; rolling nets +B.`

Numbers are formatted once via a shared `fmtGain(n)` (`+0.9`, `−1.2`, one decimal).

### `HorizonTransferPlan` (`RecommendationsPanel.tsx:372-480`)

- Header: `Plan GW5–7` + small outline chip `free transfers only` or `N hits`.
- "Net over 3 GWs" → `Net +6.5 over GW5–7`.
- Move rows: `+0.9 this GW · +2.8` using `this_gw_gain` when present.
- Rest unchanged (first row visible, tail collapsed).

### `TransferPlanner.tsx` — demote quick options

- Section becomes a collapsed `<details>` titled
  `Alternatives — this GW only, ranked by this-GW gain (N)`. Closed by default.
- Inside: the Moves / Gain / Hit cap / ITB / Applied badge row, "Reset applied", and
  the per-move cards with their own Apply buttons. Moves with `in_plan` show an
  `in plan` chip instead of "not in plan — plan says hold"; the latter badge is
  removed (the plan is now the first entries of the same list).
- The top-level "Apply next transfer" button moves into the DecisionCard (above).
  When the verdict is `roll`, no top-level Apply is shown; alternatives keep theirs.
- "Hot Targets" unchanged.

### `Index.tsx`

No logic change: `applyTransferAtIndex` / `appliedTransferCount` already index
`transfers.moves`, which now starts with the plan moves.

## Error handling

- Backend: merge step is inside the existing never-fail block; failure logs a warning
  and leaves the beam list. `verdict_detail` absent → frontend fallback banner.
- Frontend: `DecisionCard` guards every optional field; missing `roll_alternative`
  and `next_move` simply omit their line.

## Testing

Backend (`tests/test_transfer_planner.py` + new `tests/test_verdict_detail.py`):
- spend: `verdict_detail.moves[0].this_gw_gain` equals the GW-slice difference,
  `horizon_gain == plan[0].gw_gain`, `horizon.n == len(gws)`.
- roll with counterfactual flip: `action == "roll"`, `roll_alternative.net` equals the
  rejected spend plan's total, `next_move.gw` equals the alt plan's first transfer GW.
- forced injury: `action == "spend_forced_injury"`, `moves[0].forced_injury is True`.
- hits allowed: `hit_cost` equals `plan[0].hit_cost`.
- `reasoning` never contains "beats rolling" or "threshold".

Backend (`tests/test_recommendations_plan_merge.py`, route-level via existing
`build_recommendations` fixtures): plan moves lead `transfers.moves`, no duplicate
pairs, `in_plan` flags set, `squad_with_transfers_steps[1]` applies the plan move,
roll verdict leaves the beam order intact.

Frontend (vitest):
- `RecommendationsPanel.test.tsx`: DecisionCard spend / roll / forced / fallback
  (no `verdict_detail`) — asserts both numbers and the GW range text, Apply wiring
  calls `onApplyTransferAtIndex(k-1)`.
- `TransferPlanner.test.tsx`: alternatives collapsed by default, `in plan` chip,
  "not in plan" badge gone, top-level Apply absent on roll.

Manual: `/replay` or a prod-shaped `/recommendations` call, screenshot at 375px and
desktop, confirm the card reads in under five seconds.

## Branches / rollout

- Backend: `feature/decision-card` off `feature/xpts-components`.
- Frontend: `feature/decision-card` off `feature/stack-odds`.
- Backend ships first (additive payload; old frontend ignores it). Frontend second.

## Out of scope (later sub-projects)

2. **Engine quality** — FT-banking 5-cap + chip survival (roadmap B2), `min_gain`
   calibration, hit valuation, beam/plan consistency at the search level.
   Gate: `scripts/backtest_season.py --smart-transfers` season points ≥ baseline;
   MAE + captain hit reported for diagnosis.
3. **Chips** — score `chip_plan_snapshots` GW1–7, WC min-EV retune, clamp follow-ups.
4. **Ship** — Google sign-in, FPL data/ToS position, remaining audit gate-1 items,
   evidence gate.

Each gets its own brainstorm → spec → plan cycle.
