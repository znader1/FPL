# Fantasy Premier League (FPL) Player Performance Prediction

This project aims to predict next-gameweek player points in the Fantasy Premier League (FPL) using historical match data (2016–2024), player stats, and match context such as odds and fixture difficulty.

## Recommended “Production-Ready” Direction

Build a **single Python core** (data → features → projections → optimizer), then expose it via:
- **Streamlit** (fast MVP UI for you)
- **HTTP API** (later) for a simple website + iOS app

This repo currently focuses on the Streamlit MVP while keeping the logic in `src/` so it can be reused by a future API server.

## Project Goals

- Predict FPL player points for upcoming gameweeks
- Analyze key features: form streaks, minutes, goals, assists, clean sheets, team performance, and betting odds
- Build a modeling pipeline for sports analytics and ML explainability

## Data Sources

- FPL historical data (2016–2024): https://github.com/vaastav/Fantasy-Premier-League
- Archived match odds from Football-Data.co.uk: https://www.football-data.co.uk/englandm.php
- Official FPL API for current squads

## Quickstart

From the `FPL/` directory:

- Install deps: `python3 -m pip install -r requirements.txt`
- Run the app: `streamlit run fpl_app_v1.py`

### FastAPI (for Lovable / web / iOS clients)

Run locally:
- `uvicorn api.main:app --reload --port 8001`

Useful URLs:
- `http://127.0.0.1:8001/docs` (Swagger UI)
- `http://127.0.0.1:8001/health`

Example calls:
- `curl "http://127.0.0.1:8001/squad?entry_id=1234567"`
- `curl "http://127.0.0.1:8001/recommendations?entry_id=1234567&event_id=30&horizon_gws=3"`

Notes:
- `event_id` = the GW you want to optimize for (can be future).
- `squad_event_id` (optional) = which GW to load your saved squad from. If omitted, the API uses `is_next` (or `is_current`).
- Each player in `starting_xi` / `bench` includes `fixtures_horizon[]` and `next_fixtures` to show upcoming opponents across the horizon.

Browser frontend note (CORS):
- Local dev CORS is enabled for common localhost ports by default (8080/5173/3000).
- For production, set `FPL_API_CORS_ORIGINS` to your real frontend domain(s).

If you deploy publicly, set `FPL_API_KEY` and pass it from your frontend as:
- Header `X-API-Key: <FPL_API_KEY>` (or `Authorization: Bearer <FPL_API_KEY>`)

### Scrape 2025–26 match history (FPL-only)

This builds a **player × fixture** dataset for the current season using `/api/element-summary/{id}/`:

- `python3 -m src.season_history --resume`

Outputs:
- Raw JSON snapshots: `data/raw/fpl/<season>/`
- Aggregated tables:
  - `data/processed/fpl/<season>/player_match_history_<season>.csv` (player × fixture)
  - `data/processed/fpl/<season>/player_gw_history_<season>.csv` (player × gameweek, handles doubles)

### Quick baseline backtest (sanity check)

After scraping, run:
- `python scripts/backtest_baseline.py`

## Main Features

- Rolling averages and player form by position
- Match context: home/away, opponent, team odds
- Set-piece taker flags (penalty, corner, free kick)

## Repo Structure


## Next Steps

- Train a baseline xPts model on the scraped current-season dataset (minutes + points model)
- Add 3-GW horizon transfer planning (hits, roll/hold logic)
- Add external sources (injuries, xG providers, coach changes) as a second stage
- Deploy as an API for web/iOS clients

---

Project by [Your Name]. Contributions and feedback welcome!
