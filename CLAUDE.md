# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
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

## Environment

Required env vars (set in `fly.toml` secrets or `.env` locally):

```
FPL_ADMIN_KEY=...         # protects /admin/refresh
ANTHROPIC_API_KEY=...     # LLM rationale in src/explainer.py
REQUESTS_CA_BUNDLE=...    # optional, for corporate proxies
```

## FPL rules (2026-27) — check advice against these

The rulebook lives in `src/rules.py` (re-exported by `config.py`); never tune it. Rules that recommendation logic and copy must respect:

- **Chips come in two sets.** Each of Wildcard, Free Hit, Bench Boost and Triple Captain can be played once in GW1–19 and once in GW20–38 (`CHIP_PLAN_PHASE_SPLIT_GW = 19`). A first-set chip not played by the GW19 deadline is lost — it does not carry over. `chip_advisor.chip_windows` gives each chip's `half` and `expires_gw`.
- **Advice must stay inside the chip's own half.** FA Cup blanks (usually GW29–33) and most doubles fall in the second half, so "save it for the blank/double" is only valid for a second-set chip. First-half guidance comes from `CHIP_PLAN_SEASON_PRIORS_FIRST_HALF`; second-half from `CHIP_PLAN_SEASON_PRIORS`.
- **One chip per gameweek.** A Wildcard or Free Hit week uses no free transfers and grants no +1: the banked count carries through unchanged (FPL rule since 2025-26; `ft_tracker`). GW1 is squad creation; everyone enters GW2 with 1 FT.
- **Free transfers bank up to 5** (`FT_MAX`); each extra transfer costs 4 points (`TRANSFER_HIT_POINTS_STEP`).
- **Squad:** 15 players (2 GKP, 5 DEF, 5 MID, 3 FWD), £100m, max 3 per club (`CHIP_MAX_PER_TEAM` / `TRANSFER_MAX_PER_TEAM`).

## Architecture

All tunable constants live in `src/config.py` — never hardcode numbers in logic files. When changing model behaviour, change config first.

### Projection engine (`src/projections.py`)

The xPts model blends a season PPG baseline with a recency-weighted recent average, then applies fixture multipliers per GW:

1. **Blank GWs** (team had no fixture) are **excluded entirely** from the recent average — not treated as 0-point games.
2. **Per-GW multipliers**: FDR difficulty (`DIFFICULTY_MULTIPLIER` in `src/projections.py` — the table there is the truth; `CHIP_PLAN_TC_DIFF_MULT` and `scripts/backtest_season.py` carry drifted copies, see the 2026-10-05 review), home/away, opponent team form, own team form, play probability (injury/doubt)
3. **ep_next is still in the GW1 number**: `PROJ_EP_NEXT_BLEND_WEIGHT = 0.50` (`[untested]`) — next-GW xPts is half FPL's own ep_next, half the blended model; later GWs use the model only. The backtest adapter sets ep_next to 0.0 (`src/backtest_adapter.py`), so backtests have never exercised this blend (found 2026-10-05, fix planned as a backtest-parity phase).
4. **Early-season shrinkage** (2026-09): the blended baseline is pulled toward a price×position prior (`PROJ_SHRINKAGE_GAMES`, `PROJ_PRICE_PRIOR_SLOPE`), weighted by finished GWs — a 4.1m defender with two clean sheets no longer projects like a premium. `PROJ_SHRINKAGE_GAMES` 2.5 (tuned by the live-season replay, see Monitoring below). Pre-season (0 finished GWs) untouched. First-choice penalty takers get `PROJ_PENALTY_TAKER_UPLIFT` (+0.45/GW) after shrinkage.
5. Known open issue: promoted-team small-sample clusters still inflate (shrinkage+`CHIP_PLAN_XPTS_CLAMP` are stopgaps); root fix + per-player home/away splits are backlogged pending an SP3 backtest.

### xG expected-points stack (ON, 0.7 blend)

A parallel, per-player, per-GW expected-points table (`xpts_model_*`) that `projections.project_elements_next_gws` blends into its baseline via `PROJ_MODEL_BLEND_WEIGHT` (**0.7** — fixture/underlying numbers outweigh recent points). The 1-GW MAE sweep is a tie between 0.5 and 0.7 and degrades past 0.8; don't raise it past 0.8, and revisit with a horizon-aware backtest (`scripts/backtest_blend_sweep.py`; reasoning in the `config.py` comment). Three composable modules combined by `src/expected_points.py`:

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

### Availability-adjusted team strength (2026-10-26)

`src/availability.py`, behind `AVAIL_ENABLED` (on). A doubtful or missing player weakens his team by his share of its recent output (attack: xG + xA share over the last `AVAIL_SHARE_WINDOW_MATCHES` team matches; defence: keeper/defender minutes share), scaled by (1 − play probability) and, for a doubt (`d`), by one GW of the horizon. That adjusts the team's attack/defence ratings after the knowledge discount in both rating builders (projection difficulty + xG model), which moves opponents' clean-sheet and attacking outlooks, and applies a teammate multiplier to the team's other MID/FWD final xPts (`avail_teammate_mult`, floor `AVAIL_TEAMMATE_FLOOR`), because a player's own team attack is baked into his per-90 rates. Fail-soft: any error leaves projections unadjusted. All `AVAIL_*` impacts are `[untested]`; it shipped with the previous model in shadow.

### Monitoring + live-season replay (2026-10-26)

- **Replay** (`scripts/backtest_live_season.py`, `src/season_replay.py`): replays this season's finished GWs through the production projection code from the stored pre-deadline snapshots (export `player_gw_snapshots` to `data/replay/*.csv`), patching the three history loaders per GW. `--parity-gw N` compares the replay with the stored `model_xpts` (GW8: 0.026 mean |diff|). Ranks candidates by price-band bias with a 1% MAE gate. Results: `docs/calibration/`.
- **Versions + shadow**: bump `PROJ_MODEL_VERSION` on every projection change and put the previous values of the changed keys in `PROJ_SHADOW_OVERRIDES`. The snapshot job writes `model_version`; `scripts/shadow_snapshot.py` (GitHub runner, never the API) writes `runner_xpts` (current model) and `shadow_xpts` (previous) computed on the same data. Migration `supabase/migrations/20261026_snapshot_model_version.sql` must be applied before deploying.
- **Report** (`scripts/monitor_report.py`, `src/monitoring.py`): per-version MAE / bias / rank correlation / captain hit and the position × price-band table; rollback verdict after 3 GWs (shadow MAE > 1% better, or live band bias worse → roll back).

### Monitoring dashboard data (2026-11)

Not the model-error monitoring above. This scores what the app advised against The Scout, the owner's own team and real points, one report per gameweek and entry, for an owner-only page (spec `docs/superpowers/specs/2026-11-05-monitoring-dashboard-design.md`; dry-run record `docs/monitoring/2026-11-backfill-check.md`). It observes only: nothing here changes advice.

- **Tables** (`supabase/migrations/20261106_monitoring_tables.sql`, RLS on, service role writes, select only for user ids in `monitor_owners`): `expert_picks` (Scout articles, names resolved to player ids), `entry_gw_actuals` (picks, transfers, FPL's own score), `advice_snapshots` (`origin` `replay` = rebuilt later, `live` = saved before the deadline; a live row is never overwritten), `monitor_reports` (the finished report the page reads; disposable: rerunning the backfill rebuilds it from fresh fetches, it does not read the other three back).
- **Scout feed** (`src/scout_feed.py`, `src/scout_names.py`): the Premier League content feed (`config.SCOUT_FEED_BASE_URL`, unofficial) lists articles by tag and returns each as JSON with an HTML body. Scout Selection and the transfer radar have one `<h5>` per player (`Name (Club) £X.Xm`) and parse by rule; the captain is the sentence with "vice-captain" naming two listed players. The season squad and wildcard squads are a graphic, so their fifteen live in `data/monitoring/scout_overrides.json` and count only once `confirmed_by_owner` is true. Names match on club plus name; anything not exactly one player is stored as unmatched and the article flagged `needs_review`, never guessed.
- **Scoring** (`src/monitor_xi.py`, `src/monitor_scoring.py`): `best_xi` is exact (legal formation, 3 per club). Transfers = points of the player bought minus the player sold over 1/3/5 gameweeks, verdict on 3; wildcard squads over 5, fielding the eleven the stored projection would pick each week. Real points come from FPL's `/event/{gw}/live/`, never from a sum of picks (the snapshot table has no GW1 rows). A run that could not fetch all its inputs stores no report for the affected gameweeks and exits non-zero (`writable`).
- **Replay** (`src/monitor_replay.py`, `season_replay.project_as_of`): past advice is rebuilt with today's engine on as-of inputs, from the owner's real squad that week. It calls `transfer_planner.plan_transfers`, `api.wildcard._build_preset` and `recommender.hot_by_position` directly, never `build_recommendations` / `build_wildcard_drafts` or the HTTP routes (they read live data). Knowledge files are off, the wildcard's injury prior comes from an as-of status file built from the snapshots, and today's set-piece orders are blanked (`monitor_replay.project`). Still present-day, and said in every rebuilt report: the fixture list, club and position. Guards: `test_no_future_history_leaks`, `test_wildcard_uses_as_of_inputs_and_never_the_live_loaders`, `test_set_piece_orders_are_switched_off_before_the_engine_sees_them`, plus the source-text check that neither module mentions the player knowledge file.
- **Report** (`src/monitor_gw_report.py`): every key always present; a part that cannot be built is `{"available": false, "reason"}`. Points are null until the gameweek is finished. The headline includes the captain only when the Scout stated one.
- **Run it**: dry run (no database) `PYTHONPATH=. python scripts/monitor_backfill.py --gws 1-10 --snapshots-csv data/replay/snapshots_2026-27.csv --out-dir /tmp/monitor-dryrun`; real run = the "Monitor backfill" workflow, every six hours with `--gws auto` (the next deadline's gameweek and the six before it: the live gameweek fills in once FPL marks it finished, every 1/3/5-gameweek window is re-scored, older gameweeks are left alone; picks are fetched for the live gameweek too, points only for finished ones) or by hand with a range. `--skip-replay` skips the engine.

### Transfer recommender (`src/recommender.py`)

Beam search over sell/buy combinations — feeds the frontend's collapsed "Quick options" list (the horizon planner is the advice). Guardrails: min score-gain threshold, no captain sell unless large gain, position attack bonus, set-piece order bonuses, the shared `TRANSFER_PLAN_POS_GAIN_MULT` bars, and bench-seller discipline (`swap_gain`: bench swaps compete on raw `base_score` — a set-piece taker is worthless on the bench). Weights in `config.py` under `TRANSFER_*`.

### Horizon transfer planner (`src/transfer_planner.py`)

Greedy per-GW walk across the projection horizon, separate from the single-GW beam search above. Accrues one FT per GW (cap 5, 2026-27 banking rule), like-for-like swaps only. Emitted by `build_recommendations` as `transfer_plan_horizon`; rendered by the frontend's `HorizonTransferPlan`. The 2026-09 discipline layer (all config-gated, `TRANSFER_PLAN_*`):

- **The headline plan is the product's ONE piece of advice**: at most `min(MAX_MOVES_PER_GW, banked FTs)` moves per GW (`MOVES_FOLLOW_FT`), never hit-funded (`ALLOW_HITS = False`); hits-allowed callers keep old semantics.
- **Roll-vs-move counterfactual**: every first-GW spend is compared against banking the FT and playing a double next week (the alt walk gets its banked FT back); the verdict names the counterfactual's moves and quotes both nets. Injury urgency bypasses.
- **Structured verdict** (2026-09-16): `verdict_detail` carries action, GW range, per-move `this_gw_gain`/`horizon_gain`, `plan_net`, the rejected `roll_alternative` and (on roll) `next_move`; `reasoning` is one clause. `src/plan_merge.py` then puts the plan's first-GW moves at the front of `transfers.moves` (`in_plan: true`) so `squad_with_transfers_steps[1]` applies the recommendation; beam survivors follow as alternatives.
- **XI-aware**: a bench seller's swap only credits points the buyer adds by displacing the weakest same-position XI member — bench churn is worth 0.
- **Positional bars**: GKP/DEF swaps need `POS_GAIN_MULT` × min_gain (2.0 / 2.25) — shared with the beam search.
- **Head-to-head hedge nudge**: buys directly opposing an owned GKP/DEF↔attacker pair that GW get `TRANSFER_H2H_CONFLICT_PENALTY` (variance preference, deliberately small) and an `h2h_conflicts` warning on the move record.
- **Horizon = slider**: `MIN_HORIZON_GWS` is 1. "1 GW" ranks moves on this week alone and skips roll-vs-move (needs a next week); 3 GW default unchanged. The gain bar scales with the horizon (`scaled_min_gain`: `TRANSFER_PLAN_MIN_GAIN` 2.0 over `TRANSFER_PLAN_MIN_GAIN_REF_GWS` 3 → 0.67 at 1 GW), so a short horizon is not silently stricter.
- **Injury-priority preference (2026-09-18)**: when tied/near-tied swaps land on the same buy, `TRANSFER_PLAN_INJURED_SELL_BONUS` (default 1.0, tie-break only — reported `score_gain` never changes) nudges `_best_swap`'s selection toward selling the availability-risk player first; toggle via `plan_transfers(prioritize_injured=...)` / API `prioritize_injured` (default true), and moves carry `sell_availability` when the seller has risk.

### Chip timing planner (`src/chip_advisor.py`, 2026-09)

Full reference (EV per chip, FH gates, fixture context, distributions, endpoints, snapshots): `docs/chip-planner.md` — read it before touching `src/chip_advisor.py`, `src/chip_distribution.py`, `src/european.py` or `api/chips.py`. Gotcha: the `data/models/european_calendar.json` seed ships with an empty `teams` map — the European signal is off until the qualified sides are filled in on the volume.

### Data refresh & snapshots

`/admin/refresh` (POST, key-protected) fetches fresh bootstrap + fixtures, invalidates TTL caches, writes player + history CSVs to `data/processed/fpl/`. GitHub Actions (`refresh-backend.yml`) runs every 6 hours with wake-retry, validation, and failure alerting.

### Weekly database (`player_gw_snapshots` in Supabase)

Per-player, per-GW history: pre-deadline model/FPL state plus post-GW actuals, upserted into Supabase table `player_gw_snapshots` (PK `(season, gw, player_id)`, RLS on, service-role writes only). Migration lives in `supabase/migrations/` but is applied manually via the Supabase dashboard SQL editor.

- **`GET /admin/model-snapshot`** (admin-key) — `build_model_snapshot()` in `api/main.py` returns `{season, next_gw, deadline_utc, blend_weight, finished_gws, players[]}` with per-player `model_xpts` from the projection engine. `season` comes from `season_label_from_bootstrap` (`src/season_history.py`); `pos` is derived from bootstrap `element_types` — never hardcode the position map.
- **`scripts/snapshot_to_db.py`** — twice-daily job (`.github/workflows/snapshot-db.yml`, cron 09:00/16:00 UTC). Pure row builders (`snapshot_rows`, `actuals_rows`) are separated from the I/O shell so they're testable without network (`tests/test_snapshot_db.py`). Snapshot leg skips writes at/after the deadline; actuals leg fills finished GWs whose `actual_points` is NULL from FPL's `/event/{gw}/live/`. `finished_gws` is read from the snapshot payload (raw bootstrap fetch only as fallback for an older deployed API). Supabase reads carry an explicit `limit` to lift PostgREST's default 1000-row cap.
- Extra env (GitHub secrets): `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.

### Top-10k EO, rank gain, field benchmarks (2026-10)

`src/top10k_eo.py` (`POST /admin/refresh-top10k`), `src/rank_model.py`, `src/field_projection.py` — read the modules for shapes and tunables. Gotchas:

- FPL picks are readable only after the deadline, so the top-10k sample is always the **current** GW and lags the GW being planned by one.
- Missing data is `null`/`None`, never 0 (no sample, no rank yet, unreadable standings) — `eo_top10k` 0.0 means sampled and nobody owns him.
- Field projection scores plain `xpts_gw{N}`, never the chip objective column.

### Free transfers derivation

`src/ft_tracker.resolve_free_transfers` is the one entry point (H2, 2026-10): a season walk over `/entry/{id}/history/` — +1 per GW, banked up to `FT_MAX` (5, `src/rules.py`), Wildcard/Free Hit weeks maintain the count, GW1 never banks. Only when that fetch fails does it fall back to the old single-GW heuristic (`event_transfers == 0` → 2, else 1). `/recommendations`, the chat context and the Chips tab all call it; never re-derive FT inline.

### Deployment

**Fly.io is the production backend.** `fly.toml` + `Dockerfile` (slim Python) define the Fly.io app (`fpl-assistant-api`, region `lhr`); `master` auto-deploys via `.github/workflows/fly-deploy.yml`. The machine auto-suspends when idle (free tier) — the refresh workflow wakes it with retry.

The tracked `data/models/*.json` seeds (ratings, knowledge discount, European calendar) ship in the image at `/app/seed/models` (staged by the Dockerfile, since `/app/data` is a volume mount that shadows the image); `src/seed_models.py`'s `ensure_seed_models()` runs at `api/main.py` import and copies any seed missing from the volume into `data/models` — it never overwrites a file already there, so runtime writes (e.g. `knowledge_discount.json`) win.

Legacy/alternative: an Azure Container App path also exists in the repo (`.github/workflows/deploy-azure-containerapp.yml`, `docs/production_azure.md`, app `fpl-refresh-app`). It is **not** the intended backend — treat it as deprecated.
