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
- `curl "http://127.0.0.1:8001/recommendations?entry_id=1234567&event_id=30&horizon_gws=3&latest_n_matches=3&include_transfers=true&free_transfers=1"`
- `curl "http://127.0.0.1:8001/recommendations?entry_id=1234567&event_id=33&chip_strategy=wildcard&chip_horizon_gws=5"`
- `curl "http://127.0.0.1:8001/recommendations?entry_id=1234567&event_id=33&chip_strategy=free_hit&horizon_gws=1"`
- `curl "http://127.0.0.1:8001/events/next"`

Notes:
- `event_id` = the GW you want to optimize for (can be future).
- `squad_event_id` (optional) = which GW to load your saved squad from. If omitted, the API uses `is_current` (or `is_next`).
- If `squad_event_id` is in the future and not available yet, the API falls back to a valid GW and returns a message in `notes[]`.
- Each player in `starting_xi` / `bench` includes `fixtures_horizon[]` and `next_fixtures` to show upcoming opponents across the horizon.
- `recommendations` includes `position_panels` with top candidates per position (`all` and `not_owned`) for your frontend insights panel.
- `recommendations` transfer engine now builds multiple moves using `free_transfers + horizon_gws` (plus optional hit allowance).
- Transfer ordering now prioritizes injured/at-risk starters and underperforming premium slots before low-impact bench/GKP churn.
- `recommendations` now returns `strategy_recommendation` with a structured action (`roll` / `make_transfers` / `use_chip`), confidence, reasons, captain suggestion, transfer summary, chip suggestion, and bench moves.
- `recommendations` accepts `chip_strategy` (`none`, `wildcard`, `free_hit`) and optional `chip_horizon_gws`.
- When chip mode is active, response includes `chip_strategy` details (`objective_score_col`, budget, remaining budget) and `squad_source=chip_draft`.
- `wildcard` draft optimization uses horizon objective (`xpts_horizon`), while `free_hit` uses next-GW objective (`xpts_gw{event_id}`).
- `recommendations` now returns `squad_with_transfers` so frontend can render the pitch **after** applying suggested moves.
- `recommendations` now returns `squad_with_transfers_steps` (0..N applied moves) so frontend can switch applied transfers instantly without re-calling API.
- `recommendations` also returns `transfer_impact`, `transfer_application`, and `timings_ms` for debugging/runtime tracking.
- Main tuning knobs are centralized in `src/config.py` (projection form window, captain position coefficients, transfer weighting, set-piece weighting).
- Full parameter-by-parameter config guide: `docs/config_reference.md`.

Transfer tuning map (`src/config.py`):
- **Core transfer score** (used in `src/recommender.py -> build_transfer_scores`):
  - `TRANSFER_BASE_PPG_WEIGHT`, `TRANSFER_BASE_FORM_WEIGHT`: base quality score.
  - `TRANSFER_CONSISTENCY_*`: season stability + minutes reliability.
  - `TRANSFER_HOT_*`: short-term momentum/hotness.
  - `TRANSFER_SET_PIECE_WEIGHTS`: penalties/FK/corners bonus.
  - `TRANSFER_SET_PIECE_PRIMARY_BONUS`: extra certainty for primary takers.
  - `TRANSFER_ATTACK_BONUS`: position upside bonus.
- **Sell-side prioritization** (used in `src/recommender.py -> suggest_transfers`):
  - `TRANSFER_SELL_STARTER_BOOST`: protect nailed starters from being sold.
  - `TRANSFER_SELL_BENCH_PENALTY`, `TRANSFER_SELL_GKP_PENALTY`: de-prioritize low-impact churn.
  - `TRANSFER_SELL_PREMIUM_*`: prioritize replacing weak premium slots.
  - `TRANSFER_SELL_INJURY_BOOST`: aggressively sell injury/absence risk.
- **Buy-side prioritization** (used in `src/recommender.py -> suggest_transfers`):
  - `TRANSFER_BUY_PREMIUM_*`: favor high-upside MID/FWD upgrades.
  - `TRANSFER_BUY_OWNERSHIP_BONUS`: add signal from strong market consensus.
  - `TRANSFER_BUY_AVAILABILITY_WEIGHT`: penalize doubtful buys.
- **Move control** (used in `src/recommender.py -> suggest_transfers`):
  - `TRANSFER_MIN_SCORE_GAIN`: minimum gain required to execute a move.
  - `TRANSFER_MIN_SCORE_GAIN_BENCH`, `TRANSFER_MIN_SCORE_GAIN_GKP`: guardrails for low-impact churn.
  - `TRANSFER_GUARDRAIL_INJURY_OVERRIDE`: bypass guardrails for clear injury risk.
  - `TRANSFER_HIT_POINTS_STEP`, `TRANSFER_MAX_MOVES`, `TRANSFER_DEFAULT_HOT_TOPN`.
  - `TRANSFER_BEAM_*`: 2-step beam-lookahead search controls.
- **Strategy output thresholds** (used in `api/main.py -> _build_strategy_recommendation`):
  - `STRATEGY_MIN_GAIN_PER_TRANSFER_GW1`, `STRATEGY_MIN_GAIN_PER_TRANSFER_MULTI`: roll vs transfer.
  - `STRATEGY_CHIP_BENCH_BOOST_MIN_XPTS`, `STRATEGY_CHIP_TRIPLE_CAPTAIN_MIN_XPTS`: chip triggers.
  - `STRATEGY_MAX_BENCH_MOVES`: max bench actions in strategy block.
- **Captain ceiling tuning** (used in `src/optimizer.py -> optimize_lineup`):
  - `CAPTAIN_POSITION_MULTIPLIER`, `CAPTAIN_PREMIUM_*`, `CAPTAIN_FORM_CEILING_WEIGHT`, `CAPTAIN_SET_PIECE_PENALTY_WEIGHT`.
- **Chip draft tuning** (used in `src/optimizer.py -> build_chip_squad`):
  - `CHIP_WILDCARD_DEFAULT_HORIZON_GWS`: default planning horizon for wildcard.
  - `CHIP_MAX_PER_TEAM`: per-team cap in wildcard/free-hit draft.
  - `CHIP_SQUAD_SHAPE`: required 15-man shape.
  - `CHIP_UPGRADE_MAX_ITERS`: greedy upgrade iterations during draft optimization.

Browser frontend note (CORS):
- Local dev CORS is enabled for common localhost ports by default (8080/5173/3000).
- For production, set `FPL_API_CORS_ORIGINS` to your real frontend domain(s).

If you deploy publicly, set `FPL_API_KEY` and pass it from your frontend as:
- Header `X-API-Key: <FPL_API_KEY>` (or `Authorization: Bearer <FPL_API_KEY>`)

Admin refresh endpoint:
- `POST /admin/refresh` (requires `FPL_ADMIN_KEY` or `FPL_API_KEY`)
- Use this for scheduled cache warmup + snapshot refresh.

### Production (always-on backend)

- Docker image is provided via `Dockerfile`.
- Deploy backend on Azure App Service (Web App for Containers) or Azure Container Apps.
- Use GitHub Actions:
  - `.github/workflows/api-ci.yml` for CI checks.
  - `.github/workflows/deploy-azure-containerapp.yml` for build + deploy to Azure Container Apps.
  - `.github/workflows/refresh-backend.yml` to trigger `/admin/refresh` every 6 hours.
- For Azure setup and CI/CD steps, see `docs/production_azure.md`.

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
