# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install deps
pip install -r requirements.txt

# Run dev server (port 8001 to avoid clash with other services)
uvicorn api.main:app --reload --port 8001

# Run the test suite (pytest is dev-only; runtime deps unchanged)
python -m pytest -q                 # full suite
python -m pytest tests/test_ownership_ev.py -q   # a single module

# Deploy to Fly.io (master → production)
fly deploy

# Deploy feature branch to separate Fly app (safe, no master impact)
fly apps create fpl-assistant-api-dev   # one-time
fly deploy --app fpl-assistant-api-dev

# Trigger manual data refresh (replace URL + key)
curl -X POST "$FPL_API_BASE_URL/admin/refresh" \
  -H "X-API-Key: $FPL_ADMIN_KEY" \
  -d '{"run_snapshot": true}'
```

CI (`.github/workflows/api-ci.yml`) compiles `api src scripts` and runs `pytest tests/ -q` on every push.

## Environment

Required env vars (set in `fly.toml` secrets or `.env` locally):

```
FPL_ADMIN_KEY=...         # protects /admin/refresh
ANTHROPIC_API_KEY=...     # LLM rationale in src/explainer.py
REQUESTS_CA_BUNDLE=...    # optional, for corporate proxies
```

## Architecture

**Stack:** FastAPI, uvicorn, pandas, requests, `cachetools.TTLCache`, Anthropic SDK.

All tunable constants live in `src/config.py` — never hardcode numbers in logic files. When changing model behaviour, change config first. Read tunables via `getattr(config, "NAME", default)`.

### Request flow

```
api/main.py  (FastAPI routes, auth, orchestration)
  → src/fpl_client.py        (FPL API fetch + TTL caching)
  → src/projections.py       (xPts engine — see below)
  → src/optimizer.py         (starting XI / bench / captain selection)
  → src/recommender.py       (transfer planning, multi-move beam search)
  → src/transfer_planner.py  (multi-GW roll/bank horizon walk → `transfer_plan_horizon`)
  → src/league_strategy.py   (mini-league chase/defend/differential logic)
  → src/explainer.py         (LLM rationale via Anthropic API)
```

### Projection engine (`src/projections.py`)

The xPts model blends a season PPG baseline with a recency-weighted recent average, then applies fixture multipliers per GW:

1. **Base score** = `PPG_WEIGHT × ppg + FORM_WEIGHT × form` (season-long signal)
2. **Recent average** = recency-weighted mean over last N GWs (last-2 GWs get 2× weight). Blank GWs (team had no fixture) are **excluded entirely** — not treated as 0-point games.
3. **Blended base** = `RECENT_BLEND_WEIGHT × recent_avg + (1 - RECENT_BLEND_WEIGHT) × base_score`
4. **Per-GW multipliers**: FDR difficulty (`{1:1.25, 2:1.12, 3:1.0, 4:0.88, 5:0.75}`), home/away, opponent team form, own team form, play probability (injury/doubt)
5. **DGW**: second fixture counts at `DGW_EXTRA_FIXTURE_DISCOUNT` (0.65) of a normal fixture
6. **Late season** (GW > `LATE_SEASON_GW_THRESHOLD`): window shrinks to 3 GWs so recent form dominates
7. **ep_next removed**: FPL's own ep_next is opaque and slow-reacting; own blended model used for all GWs (`EP_NEXT_BLEND_WEIGHT = 0.0`)

### xG expected-points stack (shadow model — currently OFF)

A parallel, per-player, per-GW expected-points table (`xpts_model_*`) that `projections.project_elements_next_gws` blends into its baseline via `PROJ_MODEL_BLEND_WEIGHT` (**default 0.0** — baseline unchanged until raised). Three composable modules combined by `src/expected_points.py`:

- **`src/fixture_difficulty.py`** — turns per-match xG into per-team **attack/defense** ratings (multipliers vs league avg) with exponential time decay (`FDR_XG_HALFLIFE_DAYS`) and shrinkage (`FDR_XG_SHRINKAGE_MATCHES`). A user-maintained `data/models/knowledge_discount.json` nudges teams for info xG can't see yet (signings, injuries, manager change).
- **`src/minutes_model.py`** — P(start), P(≥60), E[minutes] per player from decayed start/minutes history with a position prior (`MINUTES_*` tunables).
- **`src/output_model.py`** — player per-90 xG/xA → expected returns.

All loaders return empty frames when data is missing → model degrades gracefully. Everything is dependency-injectable for the backtest.

### Minutes / rotation multiplier (SP1 — OFF by default)

`PROJ_APPLY_MINUTES_MODEL` (**default `False`**). A surgical rotation-risk multiplier on projections. **Kept off by decision:** the A/B backtest proved it never beats the baseline MAE — ppg/form already encode minutes. Do not enable without a new backtest win.

### Mini-league ownership-adjusted EV + captain-differential (SP2 — ON)

`src/ownership_ev.py` (pure) + `src/league_strategy.py`. Ranks mini-league candidates by differential EV `(xpts_horizon − template_xpts[pos]) × (1 − clip(league_ownership,0,1))` and flags a captain-differential (premium consensus captain vs a low-owned alt). Surfaces in the response and the LLM narrative (narrative cites only provided `differential_ev`/`league_ownership` — no hallucinated numbers).

- `LEAGUE_EV_RANKING = True` — **default ON**. `False` restores the exact legacy raw-xPts candidate order.
- `LEAGUE_EV_CAPTAIN_PREMIUM_FLOOR = 85` — now_cost tenths (£8.5m) floor for "premium".
- `LEAGUE_EV_CAPTAIN_DIFF_MAX_OWNERSHIP = 0.10` — alt must be under this league ownership to flag.
- Template uses GLOBAL `selected_by_percent`; the `(1 − ownership)` multiplier uses LEAGUE ownership.
- Spot-check (live data): `PYTHONPATH=. python -m scripts.spotcheck_league_ev <entry_id> <league_id> [event_id]`

### Backtest harness (SP3)

`scripts/backtest_*.py` + `src/backtest_adapter.py` / `backtest_data.py` / `backtest_metrics.py`. Pure metrics (MAE, captain hit-rate/regret, top-N precision) and an A/B runner that patches both history loaders with **no future leak** and uses real per-GW starts when present. Used to prove/reject model changes before they ship.

### Transfer recommender (`src/recommender.py`)

Beam search over sell/buy combinations. Guardrails: min score-gain threshold, no captain sell unless large gain, position attack bonus, set-piece order bonuses. Weights in `config.py` under `TRANSFER_*`.

### Horizon transfer planner (`src/transfer_planner.py`)

Greedy per-GW walk across the projection horizon, separate from the single-GW beam search above. Accrues one FT per GW (cap 5, 2026-27 banking rule), makes like-for-like swaps only when gain exceeds `min_gain` (else rolls), optionally takes -4 hits when gain exceeds `hit_penalty`. Emitted by `build_recommendations` as `transfer_plan_horizon` (additive, never breaks the response); rendered by the frontend's `HorizonTransferPlan` component.

### Chip optimizer (`src/optimizer.py` + chip logic in `api/main.py`)

- `free_hit`: optimize for next GW only, ignore sell prices
- `wildcard`: blend of next-fixture xPts, multi-GW horizon, DGW upside, premium captaincy coverage. Weights under `CHIP_WILDCARD_*`.

### Data refresh & snapshots

`/admin/refresh` (POST, key-protected) fetches fresh bootstrap + fixtures, invalidates TTL caches, writes player + history CSVs to `data/processed/fpl/`. GitHub Actions (`refresh-backend.yml`) runs every 6 hours with wake-retry, validation, and failure alerting.

### Weekly database (`player_gw_snapshots` in Supabase)

Per-player, per-GW history: pre-deadline model/FPL state plus post-GW actuals, upserted into Supabase table `player_gw_snapshots` (PK `(season, gw, player_id)`, RLS on, service-role writes only). Migration lives in `supabase/migrations/` but is applied manually via the Supabase dashboard SQL editor.

- **`GET /admin/model-snapshot`** (admin-key) — `build_model_snapshot()` in `api/main.py` returns `{season, next_gw, deadline_utc, blend_weight, finished_gws, players[]}` with per-player `model_xpts` from the projection engine. `season` comes from `season_label_from_bootstrap` (`src/season_history.py`); `pos` is derived from bootstrap `element_types` — never hardcode the position map.
- **`scripts/snapshot_to_db.py`** — twice-daily job (`.github/workflows/snapshot-db.yml`, cron 09:00/16:00 UTC). Pure row builders (`snapshot_rows`, `actuals_rows`) are separated from the I/O shell so they're testable without network (`tests/test_snapshot_db.py`). Snapshot leg skips writes at/after the deadline; actuals leg fills finished GWs whose `actual_points` is NULL from FPL's `/event/{gw}/live/`. `finished_gws` is read from the snapshot payload (raw bootstrap fetch only as fallback for an older deployed API). Supabase reads carry an explicit `limit` to lift PostgREST's default 1000-row cap.
- Extra env (GitHub secrets): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.

### Free transfers derivation

Free transfers for the target GW are derived from `entry_history.event_transfers` of the **current squad GW** (already fetched in `/squad`). `event_transfers == 0` → 2 FT next GW; otherwise 1. No extra API call.

### Branches

| Branch | Purpose |
|--------|---------|
| `master` | Production (auto-deploys to Fly.io) |
| `feature/weekly-db` | Current: weekly `player_gw_snapshots` Supabase table + snapshot job |
| `feature/xg-expected-points` | xG shadow model + SP1 minutes / SP2 ownership-EV / SP3 backtest |
| `feature/smarter-projections` | Improved xPts model (blank-GW exclusion, recency weighting, ep_next removal) |
| `feature/backtest` | Backtest experiments |

### Deployment

**Fly.io is the production backend.** `fly.toml` + `Dockerfile` (slim Python) define the Fly.io app (`fpl-assistant-api`, region `lhr`); `master` auto-deploys via `.github/workflows/fly-deploy.yml`. The machine auto-suspends when idle (free tier) — the refresh workflow wakes it with retry.

Legacy/alternative: an Azure Container App path also exists in the repo (`.github/workflows/deploy-azure-containerapp.yml`, `docs/production_azure.md`, app `fpl-refresh-app`). It is **not** the intended backend — treat it as deprecated. Note: the frontend's `.env.production` (`VITE_FPL_API_BASE_URL`) still points at the Azure URL, so pointing production at Fly.io requires updating that value to the Fly.io URL.
