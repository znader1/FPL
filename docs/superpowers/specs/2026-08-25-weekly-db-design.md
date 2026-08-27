# Weekly FPL Database: Pre-Deadline Snapshots + Actuals

**Date:** 2026-08-25
**Status:** Approved design, pending implementation plan
**Branch:** `feature/weekly-db` (backend repo; `master` auto-deploys to prod, so all work stays off it until verified)

## Problem

The model's predictions, FPL's own `ep_next`, deadline-time prices and ownership are unreconstructable after the fact — Vaastav publishes rich post-hoc per-GW stats but cannot say what anyone *believed at the deadline*. Without point-in-time capture there is no honest accuracy tracking (us vs FPL vs reality), no crowd-relative gems evaluation, and the backtest's "ownership/prices are not historical" limitation persists. Every gameweek without capture is data lost forever.

## Goals

1. From GW2 (deadline 2026-08-28 17:30 UTC) onward, capture a pre-deadline snapshot per player per GW: price, ownership, status/chance, FPL `ep_next`, our `model_xpts` with blend-weight provenance.
2. Fill each row's `actual_points` / `actual_minutes` once the GW finishes.
3. Computation happens in the prod backend (which holds the volume data and live config); credentials for the database never enter the prod app.

Non-goals (later sub-projects): gems v2 trend signals, the accuracy-vs-FPL comparison view, any frontend read path, duplicating Vaastav's deep stats (xG/BPS/ICT history stays Vaastav's job).

## Architecture

```
GitHub Actions (twice daily, 09:00 + 16:00 UTC; deadlines ~17:30+ so the
16:00 run is the final pre-deadline state)
  → scripts/snapshot_to_db.py
      → GET  {prod}/admin/model-snapshot   (admin key; NEW endpoint)
      → GET  FPL public API                (actuals for finished GWs)
      → Supabase REST upsert               (service key, GH secret only)
```

- **`GET /admin/model-snapshot`** (backend, admin-key-protected like `/admin/refresh`): returns `{season, next_gw, deadline_utc, blend_weight, players: [{player_id, web_name, pos, team_short, price_m, ownership_pct, status, chance, fpl_ep_next, model_xpts}]}` computed by the same projection path `/recommendations` uses (including `finished_gw_max` and the live blend weight). One source of truth; exact prod provenance.
- **`scripts/snapshot_to_db.py`**: pure-logic core (row building, gating) + thin I/O shell. Behaviour per run:
  1. Call `/admin/model-snapshot`. If the next GW's deadline has not passed → upsert all players' snapshot rows for that GW (idempotent; later runs refresh the row, so the last pre-deadline run wins).
  2. Query Supabase for rows with `actual_points IS NULL` in GWs whose FPL `finished` flag is true → fetch per-player GW points/minutes from the public FPL API → update those rows once.
- **Workflow** `.github/workflows/snapshot-db.yml`: cron `0 9,16 * * *` + `workflow_dispatch`; secrets `FPL_ADMIN_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FPL_API_BASE_URL`.

## Schema

One migration (applied via Supabase MCP), table `public.player_gw_snapshots`:

```sql
create table public.player_gw_snapshots (
  season text not null,
  gw smallint not null,
  player_id integer not null,
  web_name text,
  pos text,
  team_short text,
  price_m numeric(5,1),
  ownership_pct numeric(5,2),
  status text,
  chance smallint,
  fpl_ep_next numeric(6,2),
  model_xpts numeric(7,3),
  model_blend_weight numeric(4,2),
  captured_at timestamptz not null default now(),
  actual_points smallint,
  actual_minutes smallint,
  actuals_captured_at timestamptz,
  primary key (season, gw, player_id)
);
alter table public.player_gw_snapshots enable row level security;
-- no policies: service-role writes only; a read policy ships with gems v2
```

`season` derived from the bootstrap (e.g. "2026-27"), never hardcoded. ~700 rows per GW.

## Error handling

- Model-snapshot endpoint failure → job writes nothing and exits non-zero (GH Actions alert). No silent rows with null `model_xpts`.
- Actuals written only when the event's `finished` flag is true; partial-GW data never lands.
- Upserts keyed on the primary key — re-runs and overlapping schedules are harmless.
- Deadline passed and actuals not yet available → the run is a clean no-op for that GW.

## Testing

- Pure functions (snapshot payload → rows, deadline gating, actuals gating, season derivation) unit-tested in `tests/test_snapshot_db.py`.
- `/admin/model-snapshot`: auth test (401 without key) + payload-shape test with dependency overrides, following `tests/test_squad_router.py` conventions.
- End-to-end: one manual `workflow_dispatch`/local run against the real table before the schedule merges to master; verify row counts and a spot-checked player.
- Staging first: endpoint exercised on `fpl-assistant-api-dev` before prod merge.
