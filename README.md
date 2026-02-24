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

### Train first xPts model (GW history → ridge)

Use the latest scraped `player_gw_history_*.csv` and train up to a GW cap (default `26`):
- `python3 scripts/train_xpts_model.py --train-max-gw 26 --valid-gws 3`

What it writes:
- `data/models/xpts_ridge_<season>_gw<used_gw>.json` (model + metrics)
- `data/models/xpts_ridge_<season>_gw<used_gw>_valid_predictions.csv`
- `data/models/xpts_ridge_<season>_gw<used_gw>_valid_metrics_per_gw.csv`

## Chat (RAG beta)

The app includes a **Chat** tab that can:
- Answer questions using your **loaded squad + projections + optimizer** (tool-based)
- Optionally retrieve snippets from local docs in `kb/` (RAG)

To enable LLM answers, set:
- `OPENAI_API_KEY`
- (optional) `OPENAI_MODEL` (default: `gpt-4o-mini`)

Example:
- `export OPENAI_API_KEY="..." && streamlit run fpl_app_v1.py`

Docs for retrieval:
- Put `.md` / `.txt` files in `kb/`
- Use the sidebar “Clear cache” button if you add new docs and want to rebuild the index

## Main Features

- Rolling averages and player form by position
- Match context: home/away, opponent, team odds
- Set-piece taker flags (penalty, corner, free kick)

## Repo Structure
- `fpl_app_v1.py` – Streamlit UI (Squad / Transfers / Planner / Chat)
- `src/` – core logic (FPL API client, projections, optimizer, season scraping)
- `scripts/` – runnable scripts (refresh/backtest/train)
- `kb/` – optional knowledge base for RAG

## Next Steps

- Train a baseline xPts model on the scraped current-season dataset (minutes + points model)
- Add 3-GW horizon transfer planning (hits, roll/hold logic)
- Add external sources (injuries, xG providers, coach changes) as a second stage
- Deploy as an API for web/iOS clients

---

Project by [Your Name]. Contributions and feedback welcome!
