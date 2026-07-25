# Squad Picker — Full Player List + Manual Swaps

**Date:** 2026-07-25
**Status:** Design approved (pending spec review)
**Scope:** Dev-only Squad Picker (`SQUAD_PICKER_MODE=1` backend + `VITE_SQUAD_PICKER=1` frontend). Never enabled in production.

## Goal

Extend the existing auto-build Squad Picker so the user can:

1. See the **full player pool** (~557 players) beside the built squad — searchable, filterable by position and price, sortable by projected xPts / last-season total points (TP) / value / price — like the official FPL selection screen.
2. **Manually add / remove / swap** players into the 15-man squad. On every change the backend re-optimizes the starting XI, captain, vice, and formation from the new 15 and returns fresh projected points, cost, and bank. Squad legality (position quotas, ≤3 per team, budget) is validated live.

Auto-build still seeds the initial 15; the user then edits from there.

## Non-goals (explicit)

- No full-manual XI control — XI/captain/formation are always auto-optimized from the 15 (user manages only the 15).
- No persistence — client-side squad state only; a page reload re-seeds from a fresh build.
- **No projection-model changes** — the pre-season `ppg_weight → 1.0` fix and set-piece/TP factors are a separate follow-up, out of scope here.
- No production exposure — same DEV+flag gating as today.

## Architecture (Approach A: two backend endpoints + client-held squad state)

Chosen over a single mega-endpoint (would re-project all 557 players on every swap — slow) and over all-client-side optimization (would duplicate the optimizer's formation/captain logic in TypeScript — divergence risk).

### Backend

All new code lives in `api/squad_router.py` (routes) and `src/squad_draft.py` (logic). The projection pipeline is shared so `/build`, `/players`, and `/lineup` can never diverge.

**1. Refactor — extract `project_pool` from `build_squad_from_frames`**

`src/squad_draft.py:build_squad_from_frames` currently inlines: availability filter → minutes-shrink → `min_fwd_minutes` drop → basis routing (`project_elements_next_gws` or `squad_draft_xg.xg_projection`) → `add_wildcard_scores` → `xpts_horizon` sum.

Extract everything up to and including the `xpts_horizon` computation into:

```python
def project_pool(elements, fixtures, teams_short, params) -> pd.DataFrame
```

Returns the projected DataFrame (columns: `id`, `web_name`, `pos`, `team`, `team_short`, `price_m`, `points_per_game`, `total_points`, `selected_by_percent`, `xpts_gw{N}…`, `xpts_horizon`, `wildcard_score`). `build_squad_from_frames` calls `project_pool` then continues into the optimizer as before. **No behavior change to `/build`** — verified by the existing squad tests still passing.

**2. `POST /squad-picker/players` — full projected pool**

- Body: projection params only — `projection_basis`, `horizon_gws`, `gw_start`, `blend_weight`, `minutes_prior_k`, `fdr_strength`, `include_flagged`, `min_chance_of_playing`, `team_nudges`. (No `budget_m` / `formation` / `objective` — those are squad-level.)
- Runs `project_pool` (live wrapper like `build_squad`: fetch bootstrap+fixtures, transforms, default `gw_start` from next event).
- Returns:
  ```json
  {
    "gw_start": 1, "horizon_gws": 5, "projection_basis": "ppg",
    "players": [
      {"player_id": 12, "web_name": "Raya", "pos": "GKP", "team_short": "ARS",
       "team_id": 1, "price_m": 6.0, "points_per_game": 4.1, "total_points": 162,
       "selected_by_percent": 24.3, "xpts_horizon": 14.2, "xpts_per_gw": [3.1, 2.8]}
    ]
  }
  ```
- `team_id` = the raw `team` column (needed for the ≤3-per-team client check). `total_points` = last-season TP (confirmed present in `ELEMENTS_KEEP`). Response passes through `_sanitize` (NaN-safe), same as `/build`.

**3. `POST /squad-picker/lineup` — validate 15 + optimize XI**

- Body: `{"player_ids": [15 ints], "params": {…same projection params + budget_m + formation}}`.
- Steps:
  1. Live fetch + transforms + `project_pool` (same params). Filter the pool to `player_ids`.
  2. **Validate legality** → collect `violations[]`:
     - count == 15 (report missing/unknown ids)
     - position quota exactly GKP 2 / DEF 5 / MID 5 / FWD 3
     - ≤ `max_per_team` (default 3) per `team_id`
     - `sum(price_m) ≤ budget_m`
  3. If violations non-empty → return `{"ok": false, "valid": false, "violations": [...]}` (HTTP 200; it's a user-editing state, not a server error).
  4. Else build a `squad_df` (player_id + pos + price + team) from the 15 and run `optimizer.optimize_lineup(squad_df, pool, score_col=f"xpts_gw{gw_start}", formations=_parse_formation(formation))`.
  5. Return the **same shape as `/build`** (`squad`, `starting_xi`, `bench`, `captain_player_id`, `vice_player_id`, `formation`, `squad_cost_m`, `remaining_budget_m`, `projected_points`) plus `"valid": true`.
- Reuses existing `_projected_points`, `_parse_formation`, and the display-column merge from `build_squad_from_frames` — factor the shared "assemble result from lineup" tail into a helper if it reduces duplication.

Projecting only the 15 is cheap; per-team multipliers (opponent/own-team form, FDR) are team-scoped and identical whether the frame holds 15 rows or 557, so subset projection matches full-pool values exactly.

### Frontend

`pages/SquadPicker.tsx` + `lib/squadPickerApi.ts` (+ existing `TeamStrengthGrid`, `ui/*`).

**API client (`squadPickerApi.ts`)** — add:
- `getPlayers(params: ProjectionParams): Promise<PlayerPool>`
- `optimizeLineup(playerIds: number[], params): Promise<SquadBuildResult & { valid: boolean; violations?: string[] }>`
- Types: `PoolPlayer` (with `team_id`, `total_points`, `xpts_per_gw`), `PlayerPool`.

**Page state:**
- `squadIds: number[]` — the manual 15. Seeded from the build result's squad on a successful "Build squad".
- `useQuery` for `/players` keyed on the projection params (cached; refetched when params change).
- `useMutation` for `/lineup`, debounced ~250ms after `squadIds` changes; its data replaces the displayed XI/table/projected-points.

**Player-list panel** (new, laid out beside the squad table — left column on desktop, collapsible on mobile):
- Search-by-name input; position filter (All/GKP/DEF/MID/FWD); max-price filter; sort selector (xPts horizon / last-season TP / value = `xpts_horizon / price_m` / price).
- Row: name, team_short, pos, £price, TP, 5GW xPts, and a `+` button.
- `+` disabled (greyed, tooltip reason) when adding is illegal: position quota full, that `team_id` already at `max_per_team`, or would exceed `budget_m`. Rows already in `squadIds` render highlighted with a `×` (remove) instead of `+`.

**Squad panel** (extends today's result view):
- 15/15 counter + bank (£`budget_m − cost`), both from the latest `/lineup` result.
- Existing squad table + projected-points card, driven by the `/lineup` result instead of the initial `/build`.
- Each squad row gets a `×` remove control.
- `violations[]` (if any) shown inline as a destructive banner; the XI/projected view holds its last valid state until legal again.

**Params card + TeamStrengthGrid**: unchanged. Changing a param invalidates the `/players` cache and (on next build) re-seeds.

## Data flow

```
Build squad ─▶ /squad-picker/build ─▶ seed squadIds (15)
             └▶ /squad-picker/players ─▶ pool (cached)
Add/remove ─▶ mutate squadIds ─▶ (debounced) /squad-picker/lineup
             ─▶ { valid, violations, XI, captain, formation, cost, bank, projected_points }
             ─▶ update squad panel  (or show violations, keep last valid)
```

## Error handling

- Live FPL fetch failure → 502 with detail (same as `/build`).
- `/lineup` with an illegal 15 → HTTP 200, `valid: false`, `violations[]` (not an error path).
- `/lineup` where `optimize_lineup` returns `None` (no legal formation) → `valid: true` but include a `notes` entry and null XI, so the UI can message it.
- Frontend: `/players` fetch error → disable the list panel with the existing "backend needs `SQUAD_PICKER_MODE=1`" hint; auto-build still works.

## Testing

**Backend (`tests/`):**
- `test_squad_router.py` (extend): `/players` returns rows with `total_points`, `team_id`, `xpts_horizon`, `xpts_per_gw`; count matches available pool for the params.
- `/lineup`: a legal 15 → `valid: true`, XI of 11, captain set, cost/bank correct; an illegal 15 (bad quota / 4-from-one-team / over budget) → `valid: false` with the matching violation; unknown id reported.
- `test_squad_draft.py` (extend): `project_pool` output columns + parity — `build_squad_from_frames` result unchanged after the refactor (existing assertions must still pass).

**Frontend (`lib/squadPickerApi.test.ts`, extend):** `getPlayers` and `optimizeLineup` shape the request/response correctly (mock fetch), including the violations branch.

## Files touched

- `FPL/src/squad_draft.py` — extract `project_pool`; add lineup-assembly helper.
- `FPL/api/squad_router.py` — `POST /players`, `POST /lineup`.
- `FPL/tests/test_squad_router.py`, `FPL/tests/test_squad_draft.py` — new cases.
- `fpl-decision-hub/src/lib/squadPickerApi.ts` — two client fns + types.
- `fpl-decision-hub/src/lib/squadPickerApi.test.ts` — new cases.
- `fpl-decision-hub/src/pages/SquadPicker.tsx` — list panel + manual-swap state.
- (maybe) a small `PlayerListPanel.tsx` component to keep `SquadPicker.tsx` focused.

## Repo / isolation notes

- Backend changes land in the FPL worktree branch `worktree-squad-picker-manual-swap` → committed + draft PR on the FPL repo.
- Frontend is a separate repo (`FPL-Assistant-Front`); its edits are made in place in the user's checkout.
- The running dev backend (`uvicorn` on :8001) is the user's original checkout — to test the new endpoints end-to-end the backend must run from this branch (or the branch merged in).
