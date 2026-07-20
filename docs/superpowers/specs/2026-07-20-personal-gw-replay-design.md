# Personal GW Replay (view-only, local-only) — Design Spec

**Date:** 2026-07-20
**Status:** Approved (brainstorming) → ready for implementation plan
**Owner:** Ziad (personal tool — not shipped)

## Goal

A **personal, local-only** frontend mode to replay any past gameweek of a completed FPL season and compare, per GW, **what the model would have done vs. what actually happened vs. what you actually did**. Read-only analysis. Never deployed; zero production surface.

Motivating problem: the live frontend serves only current-season state from the live FPL API — it cannot reconstruct a past GW's data conditions (setting `event_id` mixes historical picks with current-era projections). Historical GW replay currently exists only in the Python backtest (walk-forward over Vaastav data), which is not wired to the UI. This feature bridges that gap for personal use.

## Scope

**In scope**
- Season **2025-26** first (data on hand); season is a parameter so future seasons reuse the pipeline.
- View-only comparison. No interactive decision-making, no what-if sandbox.
- Four per-GW panels:
  1. **Per-player model xPts vs actual** — your squad that GW, each player's as-of-GW model xPts (no future leak) next to actual points.
  2. **Captain: model vs yours vs optimal** — model's captain pick, your actual captain, and the optimal (highest-scoring) pick; points left on table.
  3. **Suggested transfer that GW** — the recommender's sell/buy + expected gain as-of that GW, against what you actually did.
  4. **SP2 league diff-EV ranking** — ownership-adjusted differential-EV candidates for that GW (**global-ownership fallback**, see Caveats).

**Out of scope (YAGNI)**
- Interactive what-if / re-simulation from a chosen GW.
- Full app parity (every endpoint in historical mode).
- True mini-league ownership history.
- Shipping any of this to production.

## Chosen approach: Precompute → static JSON + gated endpoint + reuse frontend

Historical data is immutable, so precomputing per-GW model output to files is strictly correct and fast. The live FPL API (flaky off-season) is touched exactly once, to snapshot your entry. The existing frontend components are reused read-only.

Rejected alternatives:
- **On-the-fly historical endpoint** — recomputes each GW per request via `backtest_adapter`; re-runs the engine (minutes per season) for freshness we don't need on frozen data.
- **Standalone notebook / static HTML** — loses the requirement to view it in the frontend reusing League/Squad UI.

## Architecture

```
[one-off]  scripts/snapshot_entry.py --entry <id> --season 2025-26
   fetches /entry/{id}/event/{gw}/picks (GW1-38) + /entry/{id}/history
   -> data/replay/2025-26/entry_<id>.json
      (per GW: picks, captain, vice, transfers, chip, points, bank)

[one-off]  scripts/build_replay.py --season 2025-26 --start 2 --end 38
   walk-forward via backtest_adapter (no future leak); per GW:
     model per-player xPts, model captain, suggested transfer,
     SP2 candidates (global-ownership fallback), actuals
   -> data/replay/2025-26/gwNN.json

[backend]  api/replay_router.py   (mounted ONLY if REPLAY_MODE=1)
   GET /replay/seasons
   GET /replay/{season}/gw/{gw}?entry_id=   -> merged model + your-team + actuals
   GET /replay/{season}/summary?entry_id=   -> season totals: model vs you vs optimal

[frontend] /replay route  (registered ONLY if VITE_REPLAY_MODE=1)
   GW slider 1-38 -> 4 comparison panels
```

## Components (isolated units)

| Unit | Purpose | Depends on |
|------|---------|-----------|
| `scripts/snapshot_entry.py` | Capture your real season (per-GW picks/captain/transfers/chips/points) → JSON | `src/fpl_client.py` entry endpoints |
| `src/replay_builder.py` (pure) | Given season + GW range, produce per-GW model + actual records; the model-vs-reality compute. Writes `gwNN.json`. | `backtest_adapter`, `projections`, `ownership_ev`, `captain_advisor`, `transfer_advisor` |
| `scripts/build_replay.py` | Thin CLI wrapper over `replay_builder` | ↑ |
| `api/replay_router.py` | FastAPI `APIRouter`; reads JSON files, merges entry snapshot + GW model file; conditionally mounted | file IO only |
| `src/pages/Replay.tsx` + `src/lib/replayApi.ts` (frontend) | GW slider + 4 panels; reuse squad pitch read-only | replay endpoints |

Design intent: `replay_builder.py` is a **pure, offline-testable** unit — no network, no FastAPI. The scripts and router are thin shells around it and the snapshot file.

## Data flow

- **Build time:** one snapshot (live API) + one walk-forward (Vaastav, local) → static JSON under `data/replay/<season>/`.
- **View time:** frontend → gated backend router → static JSON. **No live API.** Immutable data → files are a correct cache.

## Data contracts (shapes)

`entry_<id>.json`
```json
{
  "entry_id": 1234567,
  "season": "2025-26",
  "gws": {
    "1": {"picks": [{"element": 351, "is_captain": true, "is_vice": false, "multiplier": 2}],
          "captain": 351, "vice": 233, "transfers": [], "chip": null,
          "points": 53, "bank": 0.0}
  }
}
```

`gwNN.json`
```json
{
  "season": "2025-26", "gw": 7, "setup_gw": false,
  "players": [{"element": 351, "model_xpts": 6.4, "actual_points": 12, "position_id": 3}],
  "model_captain": 351,
  "optimal_captain": 427,
  "suggested_transfer": {"sell": 233, "buy": 99, "expected_gain": 1.2},
  "sp2_candidates": [{"element": 99, "differential_ev": 2.1, "template_xpts": 4.0,
                      "global_ownership": 0.08, "ownership_basis": "global"}]
}
```

Merged `/replay/{season}/gw/{gw}` response = `gwNN.json` + the entry's matching GW slice (your captain, your transfer, your points) so the frontend gets one payload.

## Isolation / gating (personal-only)

- **Backend:** `api/main.py`:
  ```python
  if os.environ.get("REPLAY_MODE") == "1":
      from api.replay_router import router as replay_router
      app.include_router(replay_router)
  ```
  Env unset in production → router absent.
- **Frontend:** `/replay` route registered only when `import.meta.env.VITE_REPLAY_MODE === "1"` (in `.env`, absent from `.env.production`); Vite dead-code-drops it from prod builds.
- **Data:** add `data/replay/` to `.gitignore` — personal entry never committed or pushed.
- **No modification** to shipped League/Squad/Index pages or their endpoints; Replay reuses components read-only.

## Error handling

- `snapshot_entry`: API already rolled to 2026-27 / wiped 2025-26 (404 or empty picks) → **fail loud** ("capture window closed"). Partial coverage → save what exists, log missing GWs. **Time-sensitive: run first, ASAP.**
- `build_replay`: inherits backtest no-future-leak (GW N uses only `< N`). GW1 = squad-build, unscored → `"setup_gw": true`; UI shows a note, not a fabricated projection.
- `replay_router`: missing file → 404 naming season/GW. **Never** falls back to the live API (that would reintroduce the incoherent current-era-numbers bug this feature exists to avoid).
- Frontend: `REPLAY_MODE` off but `/replay` reached → 404/redirect.

## Testing

- **Unit `replay_builder`** on a 3-player / 2-GW fixture: assert model xPts values; optimal captain = max actual scorer; no-future-leak (GW N ignores rows with GW ≥ N).
- **Unit** merge (entry snapshot + GW model) → response shape.
- **Unit `snapshot_entry`** against mocked FPL responses: JSON shape + gap handling.
- **Frontend** `Replay.tsx` renders 4 panels from a fixture payload; gating test — route absent when `VITE_REPLAY_MODE` unset.

## Caveats

- **SP2 ownership basis:** no historical mini-league ownership exists. Diff-EV uses global `selected_by_percent` as-of that GW (present in Vaastav), labeled `"ownership_basis": "global"` and surfaced as "global differential" in the UI — not to be read as true league diff-EV.
- **Data completeness:** local processed data covers 2025-26 through GW33; Vaastav mirror through GW38. Backtest/replay uses Vaastav → full 38 GWs available.
- **GW1 unscored** in the walk-forward (setup GW); your real GW1 (53 pts) still shows on the your-team side from the entry snapshot.

## Implementation order (for the plan)

1. `scripts/snapshot_entry.py` — **first, urgent** (capture before the API rolls over).
2. `src/replay_builder.py` + tests.
3. `scripts/build_replay.py` (CLI) → generate `data/replay/2025-26/`.
4. `api/replay_router.py` + gated mount + `.gitignore`.
5. Frontend `replayApi.ts` + `Replay.tsx` + gated route + panels.
6. Wire-up test end-to-end locally with `REPLAY_MODE=1` / `VITE_REPLAY_MODE=1`.
