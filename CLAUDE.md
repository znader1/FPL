# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install deps
pip install -r requirements.txt

# Run dev server (port 8001 to avoid clash with other services)
uvicorn api.main:app --reload --port 8001

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

No test suite currently. Smoke-test projection logic inline with `python3 -c "..."` scripts.

## Environment

Required env vars (set in `fly.toml` secrets or `.env` locally):

```
FPL_ADMIN_KEY=...         # protects /admin/refresh
REQUESTS_CA_BUNDLE=...    # optional, for corporate proxies
```

## Architecture

**Stack:** FastAPI, uvicorn, pandas, requests, `cachetools.TTLCache`.

All tunable constants live in `src/config.py` — never hardcode numbers in logic files. When changing model behaviour, change config first.

### Request flow

```
api/main.py  (FastAPI routes, auth, orchestration)
  → src/fpl_client.py        (FPL API fetch + TTL caching)
  → src/projections.py       (xPts engine — see below)
  → src/optimizer.py         (starting XI / bench / captain selection)
  → src/recommender.py       (transfer planning, multi-move beam search)
  → src/league_strategy.py   (mini-league chase/defend/differential logic)
  → src/explainer.py         (LLM rationale via Anthropic API)
```

### Projection engine (`src/projections.py`)

The xPts model blends a season PPG baseline with a recency-weighted recent average, then applies fixture multipliers per GW:

1. **Base score** = `PPG_WEIGHT × ppg + FORM_WEIGHT × form` (season-long signal)
2. **Recent average** = recency-weighted mean over last N GWs (last-2 GWs get 2× weight). Blank GWs (team had no fixture) are **excluded entirely** — they are not treated as 0-point games.
3. **Blended base** = `RECENT_BLEND_WEIGHT × recent_avg + (1 - RECENT_BLEND_WEIGHT) × base_score`
4. **Per-GW multipliers**: FDR difficulty (`{1:1.25, 2:1.12, 3:1.0, 4:0.88, 5:0.75}`), home/away, opponent team form, own team form, play probability (injury/doubt)
5. **DGW**: second fixture counts at `DGW_EXTRA_FIXTURE_DISCOUNT` (0.65) of a normal fixture
6. **Late season** (GW > `LATE_SEASON_GW_THRESHOLD`): window shrinks to 3 GWs so recent form dominates
7. **ep_next removed**: FPL's own ep_next is opaque and slow-reacting; own blended model used for all GWs (`EP_NEXT_BLEND_WEIGHT = 0.0`)

### Transfer recommender (`src/recommender.py`)

Beam search over sell/buy combinations. Key guardrails: min score gain threshold, no sell of captain unless large gain, position attack bonus, set-piece order bonuses. All weights in `config.py` under `TRANSFER_*`.

### Chip optimizer (`src/optimizer.py` + chip logic in `api/main.py`)

- `free_hit`: optimize for next GW only, ignore sell prices
- `wildcard`: blend of next-fixture xPts, multi-GW horizon, DGW upside, premium captaincy coverage. Weights in `config.py` under `CHIP_WILDCARD_*`.

### Data refresh & snapshots

`/admin/refresh` (POST, key-protected) fetches fresh bootstrap + fixtures from FPL API, invalidates TTL caches, and writes player + history CSVs to `data/processed/fpl/`. GitHub Actions workflow (`.github/workflows/refresh-backend.yml`) runs every 6 hours with wake-retry, validation, and failure alerting.

### Free transfers derivation

Free transfers for the target GW are derived from `entry_history.event_transfers` of the **current squad GW** (already fetched in `/squad`). If `event_transfers == 0` for that GW → 2 FT available next GW; otherwise 1. No extra API call needed.

### Branches

| Branch | Purpose |
|--------|---------|
| `master` | Production (auto-deploys to Fly.io) |
| `feature/smarter-projections` | Improved xPts model (blank GW exclusion, recency weighting, ep_next removal, stronger FDR) — deploy to `fpl-assistant-api-dev` for A/B testing |

### Deployment

`fly.toml` defines the Fly.io app. `Dockerfile` uses a slim Python image. The machine auto-suspends when idle (Fly free tier) — the GitHub Actions refresh workflow includes a wake-with-retry step to handle cold starts.
