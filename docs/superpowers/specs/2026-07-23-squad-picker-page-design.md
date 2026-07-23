# Squad Picker (tunable, local-only) — Design Spec

**Date:** 2026-07-23
**Status:** Approved (brainstorming) → ready for implementation plan
**Owner:** Ziad (personal tool — dev-only first, structured to graduate later)

## Goal

A **dev-only** page that builds a full 15-man FPL squad **from scratch** for a chosen GW horizon, driven by **tunable parameters**. You set the knobs (horizon, budget, projection basis, fixture/xG weights, availability, team-strength nudges, squad structure); the backend runs the cold-start / wildcard draft engine and renders the result on the existing pitch visualization plus a squad table, a per-position value menu, and **projected points per GW** (last-season-based). Reusable in-season for wildcard rebuilds.

Motivating problem: at season start (and on a wildcard) there is no from-scratch squad builder with exposed controls. The engine can already draft a 15 (`optimizer.build_chip_squad`), and — critically — the pre-season live bootstrap **retains last-season aggregates** (`points_per_game`, `minutes`, `expected_goals_per_90`, `expected_assists_per_90`, `expected_goals_conceded_per_90`, `saves_per_90`), so a real cold-start projection is possible from the live API alone. This page exposes that pipeline with tuning.

## Scope

**In scope (v1)**
- From-scratch 15-man draft for GW `gw_start` over a horizon (default 5 GWs), budget default £100.0m.
- **Three projection bases**, selectable: `ppg`, `xg`, `blend`.
- Parameter knobs (see Parameters section): build setup, player signals, team-strength nudge grid, squad structure, differential/ownership.
- Result: starting XI + bench + captain/vice + formation + squad cost/bank, rendered on `PitchVisualization` + table + value menu.
- **Projected points**: per-GW (XI + captain doubled) and horizon total, from the same per-GW xPts columns.
- Notable-exclusion notes (flagged-out players who would otherwise be strong).
- Backtest of the `xg` basis on 2025-26 before it is trusted as default.

**Out of scope (YAGNI / follow-ons)**
- **Fatigue / rotation congestion** model — no congestion signal exists; flagged, not built.
- **Keeper spend cap** constraint — low payoff; not built.
- **Defensive-contribution (DC) points** component — roadmap B1, its own backtest-gated sub-project (bootstrap carries `defensive_contribution_per_90`).
- Production surface: no auth/entitlement/mobile polish yet. Backend + component structured so promotion is a small step, but not done now.
- In-place transfer/what-if on an existing team (this page drafts fresh).

## Chosen approach: refactor draft core → `src/squad_draft.py`, new gated router, reuse `output_model` + frontend

The draft logic currently lives only in `scripts/cold_start_squad.py`. Extract the core into a pure, importable, testable function; the script and the API both call it. The `xg` basis reuses the existing `output_model.expected_points` (already built) via two small cold-start adapters. The frontend reuses `PitchVisualization`, `PlayerCard`, `QueryErrorCard`, and the `fplAssistantApi` client.

Rejected alternatives:
- **Extend `build_recommendations` with a from-scratch mode** — couples cold-start into the transfer/beam-search path; messy, entry-id-coupled.
- **Pure-frontend hitting the wildcard endpoint with a dummy entry** — no cold-start projection seed; hacky; can't tune the projection basis.

## Architecture

```
[core]  src/squad_draft.py   (pure, no I/O — dependency-injectable for tests)
   build_squad(bootstrap, fixtures, params) -> dict
     1. transforms.tables_from_bootstrap / fixtures_df
     2. availability filter (drop status i/s/u/n unless include_flagged)
     3. projection basis:
          ppg  : minutes-shrunk last-season ppg -> projections.project_elements_next_gws
          xg   : cold-start adapters -> output_model.expected_points (per GW)
          blend: PROJ_MODEL_BLEND_WEIGHT mix of the two
        + add_wildcard_scores (objective for the draft)
     4. optimizer.build_chip_squad(objective, budget, structure knobs)
     5. optimizer.optimize_lineup -> XI, bench, captain/vice, formation
     6. projected_points per GW (XI + captain double) + horizon total
     returns: squad[], starting_xi[], bench[], captain/vice, formation,
              cost/bank, value_menu[], projected_points{}, notes[]

[core]  src/squad_draft_xg.py  (cold-start adapters for the xg basis)
   rates_from_bootstrap(elements)   -> {player_id, xg90, xa90, minutes_sample, pos}
   minutes_from_bootstrap(elements) -> minutes_df (E[minutes], P(start) from last-season mins/starts)
   (feed output_model.expected_points alongside team ratings + fixtures)

[backend]  api/squad_router.py   (mounted ONLY if SQUAD_PICKER_MODE=1)
   POST /squad/build            body = params -> full draft result JSON
   GET  /squad/knowledge        -> current knowledge_discount.json grid
   POST /squad/knowledge        -> save edited per-team nudges (optional persist)

[frontend] /squad route  (registered ONLY if import.meta.env.DEV && VITE_SQUAD_PICKER===1)
   ParameterPanel (knobs A-E) + TeamStrengthGrid (per-team atk/def sliders)
   -> POST /squad/build -> SquadResult (PitchVisualization + table + value menu
      + projected-points strip + notes)
```

## Parameters (request schema for `POST /squad/build`)

Ready = engine supports today; New = small new code.

**A. Build setup**
- `horizon_gws` — int 1-8, default 5 · Ready
- `budget_m` — float, default 100.0 · Ready
- `objective` — `wildcard` (multi-GW + premium captain) | `free_hit` (single GW) | `plain` · Ready
- `gw_start` — defaults to bootstrap `is_next` · Ready

**B. Player signals**
- `projection_basis` — `ppg` | `xg` | `blend`, default `ppg` (pending backtest) · ppg Ready / xg New (adapters) / blend Ready
- `blend_weight` — 0.0-1.0 (only for `blend`), maps to `PROJ_MODEL_BLEND_WEIGHT` · Ready
- `minutes_prior_k` — float, default 500 (ppg reliability shrink) · Ready
- `fdr_strength` — 0.0-2.0, default 1.0 (scales fixture-difficulty swing) · Ready-ish (expose weight)
- `include_flagged` — bool, default false (exclude status i/s/u/n) · Ready
- `min_chance_of_playing` — int %, default 0 (derate doubtful) · Ready

**C. Team-strength nudge grid** (= coach change + transfers + team performance)
- `team_nudges` — list of `{team_short, attack, defense}` multipliers, default from `knowledge_discount.json`; promoted teams pre-filled with defaults (0.82 atk / 1.20 def). Clamped to `FDR_RATING_MIN..MAX`. · Ready

**D. Squad structure**
- `max_per_team` — int, default 3 · Ready
- `min_fwd_minutes` — float, default 0 (raise for balanced 3-real-forward build) · Ready
- `min_premium_attackers` — int, default from `CHIP_WILDCARD_MIN_PREMIUM_CAPTAINS` · Ready
- `premium_floor` — £m, default from config · Ready
- `formation` — `auto` | fixed (e.g. `3-4-3`) · Ready

**E. Differential (mini-league)**
- `league_id` — optional; when set, rank/tilt candidates by ownership-adjusted EV (SP2 `ownership_ev`) · Ready

## Projected points

From the per-GW `xpts_gw{N}` columns already produced:
```
projected_points: {
  per_gw: [{ gw, xi_points, captain_bonus, total }],   // total = XI sum + captain's xpts again
  horizon_total
}
```
Captain + XI held constant across the horizon (static opening squad). Shown as a strip with per-GW bars + total. Inline caveat: cold-start estimate from last-season form/xG; directional, not a guarantee.

## xg basis — cold-start adapters (detail)

`output_model.expected_points(elements_df, fixtures, ratings, player_rates, minutes_df, gw)` already computes appearance + goals (xg90) + assists (xa90) + clean-sheet + goals-conceded penalty + saves + bonus, DGW-aware and fixture/ratings-adjusted. Two adapters replace its usual match-history inputs with last-season bootstrap aggregates:
- `rates_from_bootstrap`: `expected_goals_per_90` → `xg90`, `expected_assists_per_90` → `xa90`, `minutes` → `minutes_sample`; shrink toward `OUTPUT_POSITION_BASE_*` by minutes confidence (same shape `compute_player_rates` returns).
- `minutes_from_bootstrap`: last-season `minutes`/`starts` → P(start), E[minutes] (mirror `minutes_model.minutes_projection` output columns).
Team `ratings` = carryover seed + `team_nudges` (already used by the `ppg` path's fixture context).

## Backtest gate (discipline per roadmap)

Status (2026-07-23): the projection-basis DEFAULT is `ppg` (`DEFAULT_PARAMS["projection_basis"] = "ppg"`); `xg` and `blend` are opt-in via the knob. The gate's protective purpose — never silently ship an unvalidated basis as the default — is therefore already met.

A live divergence diagnostic (`scripts/backtest_xg_basis.py`) reports how far the `xg` and `ppg` bases disagree on the real current pool (squad overlap, captain agreement, horizon-total, rank correlation). This is NOT an accuracy backtest.

FOLLOW-ON (before `xg` may become the default): a rigorous walk-forward accuracy backtest on 2025-26 comparing `xg` vs `ppg` (MAE, captain hit-rate, top-N precision). This requires reconstructing as-of-each-GW per-90 xG rates + minutes from historical data (the cold-start adapters read the pre-season bootstrap's retained last-season aggregates, which do not exist mid-season) — tracked as its own sub-project. Until it produces a win, `ppg` stays the default.

## Error handling

- `build_squad` returns `{ok, reason, notes[]}`; infeasible cases (budget too low, not enough players in a position, missing data) return `ok=false` with a reason. Frontend renders `QueryErrorCard` / inline warnings.
- Live FPL API flaky off-season: reuse the existing query retry/backoff (Fly cold-start already handled in `queryClient`).
- Notable flagged-out exclusions surfaced in `notes[]`.

## Testing

Backend unit tests on `src/squad_draft.build_squad` (dependency-injected bootstrap/fixtures — no network):
- Legal 15 (2 GKP / 5 DEF / 5 MID / 3 FWD), budget respected, ≤ `max_per_team`, valid formation.
- Availability filter drops flagged players; `include_flagged` keeps them.
- Minutes-shrink kills a synthetic 1-game high-ppg player (no small-sample mirage).
- `team_nudges` shift a team's ratings in the expected direction.
- Determinism: same inputs → same squad.
- `xg` basis: adapters produce well-formed rates/minutes; `output_model.expected_points` runs and yields per-GW xPts.
- `projected_points.horizon_total` == sum of per-GW totals; captain double applied once.

Frontend: light (dev tool) — render smoke test + one param round-trip.

## Follow-ons (post-v1)

1. **Backtest & possibly default-on the `xg` basis.**
2. **Defensive-contribution points** (roadmap B1) — feeds both bases.
3. **Fatigue/congestion** discount (Europe + fixture density).
4. **Graduate to production** — auth/entitlement/mobile/empty-states; the router + component are already structured for it.

## v1 backend — shipped status (2026-07-23)

Backend built + reviewed on `feature/xg-expected-points` (SP5, commits `be59007..ea2aca9`, 72 tests). **The frontend plan must build controls only for the WIRED params below.**

**Wired end-to-end:** `horizon_gws`, `budget_m`, `objective`, `gw_start`, `projection_basis` (ppg/xg/blend), `blend_weight`, `minutes_prior_k`, `include_flagged`, `min_chance_of_playing`, `max_per_team`, `min_fwd_minutes`, `min_premium_attackers`, `premium_floor`, `formation`. `notes[]` now populated with flagged-out notable exclusions.

**NOT wired in v1 (removed from `DEFAULT_PARAMS`; do NOT surface as controls until implemented):**
- `fdr_strength` — FDR-swing scalar; no hook yet.
- `team_nudges` (per-request) — the per-team attack/defense grid affects the **xg/blend** bases only, and only via the persisted `data/models/knowledge_discount.json` edited through `GET/POST /squad-picker/knowledge`. The **ppg** basis honours no nudges. So the frontend team-strength grid should edit the knowledge file (endpoints exist) and the user should pick an xg/blend basis for nudges to take effect.
- `league_id` — no `ownership_ev` differential hookup yet.

**Caveats the UI must show:**
- **ppg basis, GW1:** at cold-start (no current-season history) `projections` uses FPL's own `ep_next` as the GW1 base (`PROJ_EP_NEXT_BLEND_WEIGHT=0.50`); the last-season ppg baseline drives GW2+. The **xg** basis bypasses `projections` entirely, so it is fully last-season-xG driven for all GWs.
- **Projected-points absolute scale is NOT comparable across bases:** the `xg` horizon-total runs ~58% above `ppg` (rank-corr 0.929, so ordering agrees) — the gap is the ppg minutes-shrink + `output_model`'s appearance floor, not extra signal. Present per-basis, never as "xg projects more points."

**Endpoint prefix is `/squad-picker`** (not `/squad`, which the app owns). Gated by `SQUAD_PICKER_MODE=1`.

**Backend follow-ons before the tuning tool is fully trustworthy:** wire the 3 hidden knobs; move NaN-sanitization from the router into `build_squad` core; harden `POST /knowledge` (atomic write + shape check); rigorous historical xg-vs-ppg accuracy backtest (needs as-of-GW rate reconstruction) + xg absolute-scale calibration before `xg` can become the default.
