# Transfer tab: planner runner-ups + density cut — design

**Date:** 2026-09-16 · **Status:** approved in chat (follow-up to the decision-card spec)
**Repos:** backend `FPL` branch `feature/decision-card`, frontend `fpl-decision-hub` branch `feature/decision-card`
**Parent:** `2026-09-16-transfer-decision-card-design.md`

## Problems (from staging test, entry 107342)

1. The user asked "why not Brobbey → Barry?" The planner scores that swap +2.3 this GW / +5.2 over
   GW5–7, second-best single move, but the page never shows runner-ups. The "Alternatives" list
   comes from the beam engine, scored over the display horizon, and returned only the chosen move.
2. The tab is dense: header badges, card, staircase, alternatives, hot targets, all visible.
3. `GW5–7` wraps across lines in the staircase header at phone width.
4. Staging never got the 6-hourly refresh; its history was two GWs stale and it lacked the odds key.
   (Odds key and GitHub secrets already set by hand; the workflow edit below makes it stick.)

## Backend

### `src/transfer_planner.py` — `verdict_detail.runner_ups`

At the first horizon GW (`gi == 0`, not the `_skip_first_gw` counterfactual), after `hz`, `xi`,
`team_counts` are built and BEFORE any forced sell or greedy move mutates `squad`, compute one
candidate per seller:

```python
def _ranked_swaps(squad, info, unowned, hz, bank, team_counts, xi, opps_gw, h2h_pen, min_gain, pos_mult, n):
    cands = []
    for s in squad:
        best = _best_swap({s}, info, unowned, hz, bank, team_counts, xi=xi,
                          squad_all=squad, opps_gw=opps_gw, h2h_pen=h2h_pen)
        if best is None:
            continue
        bar = float(min_gain) * float(pos_mult.get(best["pos"], 1.0))
        best["clears_bar"] = bool(best["gain"] > bar)
        cands.append(best)
    cands.sort(key=lambda m: m["gain"], reverse=True)
    return cands[:n]
```

`n = getattr(config, "TRANSFER_PLAN_RUNNER_UPS", 5)` (new constant in `src/config.py`, documented in
`docs/config_reference.md`). After `plan[0]` exists, drop any candidate whose `(sell, buy)` pair is
in `plan[0].moves`, convert each with `_move_record(m, info, gw=g)` → `_detail_move`, add
`clears_bar`, and store as `verdict_detail["runner_ups"]` (list, may be empty). On the
counterfactual flip the returned `alt` plan copies `runner_ups` from the rejected `result`.

`_verdict_detail(result, min_gain, rejected=None, runner_ups=None)` gains the parameter; the key is
always present.

Semantics: runner-ups are "the best swap for each other player in your squad, ranked", scored by the
same XI-aware horizon gain as the chosen move. `clears_bar` says whether it would have passed the
positional bar on its own. On a roll verdict the list is the best swaps that all failed the bar.

Tests (`tests/test_verdict_detail.py`): spend market with two sellers and two upgrades →
`runner_ups[0]` is the other seller's swap, the chosen pair is absent, `clears_bar` true; roll market →
`runner_ups` non-empty with `clears_bar` false and `horizon_gain` below `threshold`; `len ≤ n`;
counterfactual flip → `runner_ups` present on the returned plan; `_skip_first_gw` recursion does
not raise.

### `.github/workflows/refresh-backend.yml` — staging refresh

Add a step after "Refresh API caches and snapshot", `continue-on-error: true`, env
`FPL_DEV_API_BASE_URL: ${{ secrets.FPL_DEV_API_BASE_URL }}`, `FPL_DEV_ADMIN_KEY: ${{ secrets.FPL_DEV_ADMIN_KEY }}`:

```bash
if [ -z "$FPL_DEV_API_BASE_URL" ] || [ -z "$FPL_DEV_ADMIN_KEY" ]; then
  echo "Staging refresh skipped: FPL_DEV_* secrets not set"; exit 0
fi
curl -fsS -m 300 -X POST "${FPL_DEV_API_BASE_URL%/}/admin/refresh" \
  -H "Content-Type: application/json" -H "X-API-Key: ${FPL_DEV_ADMIN_KEY}" \
  -d '{"run_snapshot": true}' | tee staging-refresh-response.json
```

Both secrets already exist on `znader1/FPL`. The dev app auto-suspends; `-m 300` plus
`continue-on-error` means a cold start never fails the prod job.

## Frontend

### Types — `src/lib/fplAssistantApi.ts`

```ts
export interface FplTransferRunnerUp extends FplTransferVerdictMove { clears_bar: boolean; }
// on FplTransferVerdictDetail:
runner_ups?: FplTransferRunnerUp[];
```

### `DecisionCard.tsx`

- Every GW range string is wrapped in `<span className="whitespace-nowrap">`.
- New block under the nets/Apply row, rendered when `runner_ups.length > 0`:
  - Heading (10px uppercase muted): spend → `Also considered`; roll → `Best available — all below the bar`.
  - Rows, one line each: `{i+2}. Sell → Buy` left; right `+x this GW · +y` (`fmtGain`), plus a muted
    `below bar` tag when `!clears_bar`. Row index starts at 2 on spend (the card's move is 1), at 1 on roll.
  - First 3 rows visible; remaining rows inside `<details>` `show N more`.
- `data-testid="runner-ups"` on the block.

### `RecommendationsPanel.tsx` — `HorizonTransferPlan`

The whole staircase collapses behind one `<details>` (closed by default). Summary text:
`Plan GW5–7 · 3 moves · net +7.5` (moves = total transfer moves; append ` · N hits` when hits > 0),
range wrapped `whitespace-nowrap`. Inside: the existing rows, all GWs, no nested "show the rest"
details any more; the hits bill sentence and the `free transfers only` chip stay inside at the top.
`data-testid="plan-net"` element stays (now inside the details) so the earlier test holds.

### `TransferPlanner.tsx` — shell only

Keep: `Card`, the "Transfer Planner" title, the loading state, `planSlot`. Remove: GW/FT header
badges (the card shows FT, the tab header shows the GW), the alternatives `<details>`, the Hot
Targets block, and every helper only they used (`readPlayerName`, `readTeamShort`, `formatPlayerMeta`,
`toDebugValue`, `debugTransfers`, `hotRows`, `alternatives`, `horizonLabel`, `formatPoints`,
`formatMoney`, `readFiniteNumber`, `isLikelyTeamCode`, `POSITION_ORDER`, `JerseyIcon`, `Badge`
imports as they become unused). Props reduce to `{ transfers?, planSlot?, isLoading? }`; when
`!isLoading && !planSlot && (transfers?.moves ?? []).length === 0` show "No transfer suggestions
returned." The beam list is no longer displayed anywhere; it still feeds Apply indexing server-side.

### `HotTargets.tsx` (new) + Watchlist tab

Extract the Hot Targets rendering (jersey, name, team · price · next fixture, xPts + horizon) into
`src/components/HotTargets.tsx` with props `{ hotByPosition?: FplTransfersRecommendation["hot_by_position"] }`;
`WatchlistTab` renders `<HotTargets hotByPosition={recommendation.transfers?.hot_by_position} />`
under its existing sections with the heading `Hot targets`. Nothing else on Watchlist changes.

### Tests

- `DecisionCard.test.tsx`: runner-ups render 3 rows + `show 2 more` for 5 entries; numbering starts
  at 2 on spend / 1 on roll; `below bar` tag; block absent when list empty; range span has
  `whitespace-nowrap`.
- `RecommendationsPanel.test.tsx`: staircase summary text `Plan GW5–7 · 1 move · net +6.5`; details
  closed by default; rows still render inside (existing `plan-net`/row assertions kept).
- `TransferPlanner.test.tsx`: renders plan slot; no `<details>`, no "Hot", no jersey when `planSlot`
  given; empty-state text when no plan and no moves.
- `HotTargets.test.tsx`: renders positions and players; nothing when empty.
- Frontend `CLAUDE.md` "Transfer Planner panel" section updated: card + runner-ups, collapsed
  staircase, no beam display, hot targets on Watchlist.

## Out of scope

Engine changes (which move wins), thresholds, the beam engine itself, a non-cumulative apply for
runner-ups (they are informational; Apply stays on the card).
