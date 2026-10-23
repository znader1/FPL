# Chip Planner — Design Spec

**Date:** 2026-09-01
**Status:** Approved design, pending implementation plans
**Repos involved:**
- Backend: `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL` (FastAPI, Fly.io)
- Frontend: `/Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub` (this repo)

## Problem

The app today optimizes a squad *given* a chip the user manually selects (`none | wildcard | free_hit`). Nothing answers the planning questions: **which chip, which gameweek, and how does chip timing interact with transfer planning** ("use 2 free transfers now, wildcard in GW8, bench boost on the GW12 double"). Triple captain and bench boost are not modeled at all.

## Decision summary

- **Approach A (chosen):** deterministic EV engine over the existing per-GW xPts projections, with pattern priors as config tunables, validated by the existing backtest harness. LLM used as narrator only — never computes numbers.
- **Approach B (rejected as engine):** LLM agent as planner. Non-deterministic, slow, costly, unbacktestable, number-hallucination risk. Retained only as the narration/chat layer on top of A.
- **Approach C (deferred, kept as future option):** ML / fine-tuning on historical chip decisions. Rejected for now (heavy data work, chip rules change yearly so old labels mislead, marginal gain over EV math). **To keep it viable, we start capturing a labeled dataset now** — see "DB capture" below. Revisit once ≥ 1 season of (recommendation, decision, outcome) triples exists.

## Product shape

Two surfaces in the frontend, one engine in the backend:

1. **Season chip roadmap panel** — always-visible plan: recommended GW per remaining chip with EV gain, provisional markers beyond the model horizon, expiry flags (GW19 / GW38), DGW/BGW markers.
2. **Next-GW nudge card** — appears only when a recommended chip's GW is the next deadline and its EV clears a threshold: "Play Bench Boost this GW (+7.1 xPts)".

## Chip rules assumption

Current season grants two of each chip (WC, FH, BB, TC), first-half set expiring at GW19, second-half set from GW20. **The engine never hardcodes these rules**: chip availability, halves, and expiry are read from the FPL entry/bootstrap API at request time, with config fallbacks. Rules change every season; the engine only assumes "a chip has an availability window and is single-use within it."

---

## Backend design

### 1. Engine — `src/chip_advisor.py` (evolve existing module)

The backend already has a Layer-1 deterministic chip engine (`src/chip_advisor.py`: `ChipRecommendation`, `recommend_chips()`, per-chip scorers for all four chips) wrapped by the chat chip agent. The engine work **extends this module** rather than creating a parallel one. Gaps to close: expiry/half awareness, config-tunable priors (its numbers are currently hardcoded, violating the repo's config rule), a transfer-plan-aware wildcard baseline, budget-aware free-hit comparison, real DGW detection (the chat context builder hardcodes `fixture_count: 1`), the structural zone, the nudge, and a REST route (today it is reachable only through the LLM chat agent).

**Inputs:**
- Per-player per-GW projections over the horizon (existing `projections.project_elements_next_gws`)
- Current squad (picks, bench order, captain), bank/ITB, free transfers
- Chips remaining with availability windows (from FPL API)
- Fixtures per GW (for DGW/BGW detection: team fixture count per GW)
- `transfer_plan_horizon` output (existing greedy horizon walk) as the no-chip baseline

**EV per chip × candidate GW in horizon:**
- **Triple Captain:** `TC_EV(gw)` = best squad player's projected xPts in `gw` (the extra ×1 over normal captaincy). DGW upside arrives automatically because projections already sum double fixtures.
- **Bench Boost:** `BB_EV(gw)` = sum of the 4 projected bench players' xPts in `gw`.
- **Free Hit:** `FH_EV(gw)` = (free-hit-optimized squad xPts in `gw`, existing optimizer) − (own squad's xPts in `gw`). Peaks on blank GWs when the user's squad craters.
- **Wildcard:** `WC_EV(gw)` = (wildcard-optimized squad, existing optimizer, summed xPts from `gw` to horizon end) − (baseline squad xPts over the same window following `transfer_plan_horizon`, including hit costs the baseline would take). This makes "transfers now vs wildcard later" a native comparison.

**Priors — config tunables under `CHIP_PLAN_*` in `src/config.py`** (values are starting points, tuned by backtest):
- `CHIP_PLAN_HORIZON_GWS = 8` — model-zone length
- `CHIP_PLAN_MIN_EV = {"triple_captain": 3.0, "bench_boost": 5.0, "free_hit": 8.0, "wildcard": 6.0}` — below threshold, "hold" is recommended
- `CHIP_PLAN_DGW_BONUS` — additive nudge for BB/TC on detected DGWs
- `CHIP_PLAN_EXPIRY_RAMP_GWS = 5` — within N GWs of a chip's expiry, its EV threshold decays linearly toward 0 ("use it or lose it")
- `CHIP_PLAN_FH_BLANK_ONLY_BIAS` — FH penalized on non-blank GWs
- `CHIP_PLAN_NUDGE_MIN_EV` — floor for the nudge surface

**Two horizon zones:**
- **Model zone** (next `CHIP_PLAN_HORIZON_GWS` GWs): full EV math as above.
- **Structural zone** (beyond, to GW38): no projection-based EV; only structural signals — announced DGWs/BGWs from fixtures, expiry deadlines. Recommendations here carry `provisional: true` and no `ev_gain`, phrased as windows ("BB candidate: DGW29 when confirmed").

**Output shape (engine-internal, mirrors API):** ranked list of recommendations `{chip, event_id, ev_gain, provisional, reasons[], ev_curve[]}` where `ev_curve` is the chip's EV at each model-zone GW (feeds the UI chart), plus a `nudge` (or null) and `transfer_context`.

### 2. API — `GET /chips/plan` (new route in `api/main.py`)

`GET /chips/plan?entry_id=<int>&horizon=<int optional>`

```json
{
  "entry_id": 123,
  "current_gw": 4,
  "chips_remaining": [
    {"name": "bench_boost", "half": 1, "expires_gw": 19, "available": true}
  ],
  "horizon_model_gws": 8,
  "recommendations": [
    {
      "chip": "bench_boost",
      "event_id": 12,
      "ev_gain": 6.4,
      "provisional": false,
      "reasons": ["DGW12: 4 bench players have double fixtures"],
      "ev_curve": [{"gw": 5, "ev": 1.2}, {"gw": 6, "ev": 0.8}]
    }
  ],
  "nudge": {"chip": "bench_boost", "event_id": 5, "ev_gain": 7.1},
  "transfer_context": {"planned_transfers_net_gain": 3.0, "wc_alternative_gw": 8}
}
```

- `nudge` non-null only when a recommended chip's GW equals the next deadline GW and `ev_gain ≥ CHIP_PLAN_NUDGE_MIN_EV`.
- Additive: no changes to existing endpoint responses.
- `/recommendations` additionally accepts `chip_strategy` values `bench_boost` and `triple_captain`. Neither changes squad optimization (BB starts all 15 conceptually; TC only affects captain payout) — they mark the chip in the response so the frontend renders the applied state consistently.

### 3. DB capture — `chip_plan_snapshots` (Supabase)

Mirrors the `player_gw_snapshots` pattern. PK `(season, gw, entry_id)`, RLS on, service-role writes only, migration in `supabase/migrations/` applied via dashboard SQL editor.

**Pre-deadline leg (columns):** `chips_remaining jsonb`, `recommendations jsonb`, `ev_curves jsonb`, `transfer_context jsonb`, `model_meta jsonb` (horizon, prior values, projection blend weight — so future training knows the producing model), `created_at`.

**Post-GW actuals leg:** `chip_played text null` (from FPL entry history), `actual_points int null`, `realized_chip_ev jsonb null` — realized value of each chip *had it been played that GW*, computable from actuals (e.g. actual bench points that GW = realized BB EV; actual best-captain haul = realized TC EV). This labels every GW, played or skipped.

**Job:** extend `scripts/snapshot_to_db.py` (existing twice-daily GitHub Actions workflow). New pure row builders `chip_plan_rows()` / `chip_actuals_rows()` separated from I/O, testable offline like `tests/test_snapshot_db.py`. Snapshot leg skips at/after deadline; actuals leg fills finished GWs with NULL `chip_played`.

This table is the Approach C dataset: (recommendation, decision, outcome) triples accrue from day one.

### 4. Agent / narrative layer

- `/chat/chip` specialist: inject the chip plan JSON into its context so "when should I wildcard?" is answered from the engine's plan. Existing discipline holds: narrative cites only provided numbers.
- `/explain` unchanged; its chip rationale now has real recommendations to explain.

---

## Frontend design (this repo)

### 5. API layer — `src/lib/fplAssistantApi.ts`

- Types: `ChipName = "wildcard" | "free_hit" | "bench_boost" | "triple_captain"` — the backend's canonical chip names (already used by `src/chip_advisor.py` and `_derive_chips_remaining`). The backend normalizes FPL API identifiers (`freehit`, `bboost`, `3xc`) to these before they reach any payload, so the frontend never maps chip names. Plus `ChipPlanRecommendation`, `ChipPlanResponse`, `ChipNudge` matching the contract above.
- `fetchChipPlan(entryId, horizon?, signal?)` — same authFetch/URL-resolution pattern as `fetchUserLeagues`.
- `FplChipStrategy` widens to `"none" | "wildcard" | "free_hit" | "bench_boost" | "triple_captain"` — identical vocabulary to `ChipName`, so a chip recommendation maps to a chip strategy with no translation.

### 6. Components

- **`ChipRoadmapPanel.tsx`** — new "Chips" tab inside `RecommendationsPanel` (existing tab pattern). Season strip from current GW to 38: chip markers at recommended GWs with EV gain, `provisional` rendered as outlined/dashed with "provisional" badge, expiry flags at each chip's `expires_gw`, DGW/BGW markers. Clicking a chip expands reasons + an EV-curve mini chart (model zone only).
- **`ChipNudgeCard.tsx`** — rendered above the pitch in `Index.tsx` when `nudge` is non-null. Copy: "Play {chip} this GW (+{ev} xPts)". CTA sets the existing `chipStrategy` state (now including `bench_boost` / `triple_captain`) so the existing recommendation flow reruns with the chip applied — no new apply path.
- **Query wiring** — TanStack Query for `/chips/plan` in `Index.tsx`, disabled until `gwResolved` (existing flash-prevention rule), keyed by `entryId` + `selectedGW`.

### 7. Vite proxy

Add `/chips` to the dev-server proxy list in `vite.config.ts` (alongside `/squad`, `/recommendations`, `/fixtures`).

---

## Testing

**Backend (pytest, pure functions):**
- Synthetic projections with a planted DGW → BB and TC EV peak on that GW.
- Planted blank GW → FH EV peaks there; FH suppressed on normal GWs.
- Expiry ramp: as candidate GWs approach `expires_gw`, effective threshold decreases monotonically.
- WC EV vs transfer-plan baseline: scenario where two free transfers beat a wildcard, and the reverse.
- Chip availability parsing from FPL API payloads (played/available/windows).
- Snapshot row builders: offline tests for `chip_plan_rows()` / `chip_actuals_rows()`.

**Backtest (SP3 harness):**
- Replay the previous season: does the engine flag the major DGWs/BGWs for BB/FH? Tune `CHIP_PLAN_*` starting values from this before shipping.

**Frontend (vitest):**
- `ChipRoadmapPanel` renders recommendations, provisional badge, expiry flags from a fixture `ChipPlanResponse`.
- `ChipNudgeCard` renders only when nudge present; CTA updates chip strategy.

## Rollout / decomposition

Two implementation plans, one per repo, backend first:

1. **Backend plan** (executed in the `FPL/` repo): engine → route → chat injection → DB migration + snapshot job → backtest tuning.
2. **Frontend plan** (this repo): API types/fetcher → proxy → roadmap panel → nudge card → query wiring.

The frontend plan depends only on the API contract above; it can be built against a fixture JSON before the backend ships.

## Future work (explicitly deferred)

- **Approach C** — ML on `chip_plan_snapshots` once ≥ 1 season of data exists. Candidate shapes: calibration layer on EV thresholds, or a policy model ranking chip windows. Blocked on data volume, not design.
- Cross-entry data collection (top-10k managers' chip usage) if own-entry data proves too thin.
