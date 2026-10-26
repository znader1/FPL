# Projection Calibration + Monitoring Implementation Plan (plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay this season's finished gameweeks through the production projection code to test three settings against actual points, ship the winners only with the user's sign-off, and monitor every following gameweek against the previous model in shadow.

**Architecture:** A live-season replay builds as-of-GW engine inputs from the stored pre-deadline snapshots plus the per-GW history, patches the same three history loaders the existing sweeps patch, and scores candidate config overrides with a calibration table (MAE, bias, rank correlation by position × price band). Monitoring adds a model version to the twice-daily snapshot and, after a projection change, a shadow projection of the previous model computed on the GitHub runner in its own process (the 512 MB Fly machine stays out of it, and config overrides never touch live requests). A report script compares live and shadow per GW and applies the rollback rule.

**Tech Stack:** Python 3.11, pandas 1.5, FastAPI, pytest; Supabase Postgres (`player_gw_snapshots`, migration applied by hand).

**Spec:** `docs/superpowers/specs/2026-10-26-wildcard-calibration-design.md` (parts 1 and 6).

## Global Constraints

- Every tunable lives in `src/config.py` with a tag (`[untested]`, `[tuned]` + evidence, `[operational]`, `[flag]`); no `getattr(config, …, default)` fallbacks (`tests/test_config_single_source_of_truth.py` enforces it). `src/rules.py` is never changed.
- Price bands: `<6`, `6-8`, `8+` (£m, lower bound inclusive: 6.0 is `6-8`, 8.0 is `8+`).
- Population: all player-GWs where the player's team had a fixture that GW (benched and zero-minute included), with an appearances-only (minutes > 0) breakdown alongside.
- "Not worse": overall 1-GW MAE within 1% of the current model's.
- Rollback: after 3 finished GWs, roll back if shadow 1-GW MAE < 0.99 × live MAE, or if live price-band bias is worse than shadow's (definition in Task 6).
- Last season (Vaastav) evidence is directional only and must be printed with the label `NON-PARITY`.
- No future leak: every input for target GW `t` uses only data from GWs `< t`, except the snapshot row for `t` itself (captured before `t`'s deadline).
- Supabase migrations ship as SQL files and are applied by hand in the dashboard before the code that writes the new columns is deployed.
- Work in the worktree `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/worktrees/wildcard-calibration` (branch `feature/wildcard-calibration`). `.venv/bin/python` in every command means `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL/.venv/bin/python` (the worktree has no venv of its own); run commands from the worktree root.

## Review Focus

- **A player with no snapshot row for the target GW** (new signing mid-season): the replay drops him from that GW and counts the drop; it never fills him with defaults.
- **A blank GW for a team:** its players are excluded from the population for that GW (no fixture), not scored as a 0-vs-0 hit.
- **The shadow step fails** (FPL fetch error, engine exception): the live rows are already written, `shadow_xpts` stays null for that GW, the error is logged, and the job still succeeds.
- **An override key that does not exist in config** (typo in `PROJ_SHADOW_OVERRIDES` or `--grid`): rejected with an error naming the key, never silently ignored.
- **An older API without `model_version`:** `snapshot_rows` writes null for the new columns instead of failing.

---

### Task 1: Config override context manager

**Files:**
- Create: `src/config_overrides.py`
- Test: `tests/test_config_overrides.py`

**Interfaces:**
- Produces: `config_overrides(overrides: dict[str, object])` — a context manager that sets each `src.config` attribute, yields, and restores the originals even on exception. Raises `KeyError("unknown config key: NAME")` before changing anything if any key is not an existing upper-case attribute of `src.config`.

- [ ] **Step 1: Write the failing tests**

```python
from src import config
from src.config_overrides import config_overrides
import pytest

def test_overrides_apply_and_restore():
    before = config.PROJ_MODEL_BLEND_WEIGHT
    with config_overrides({"PROJ_MODEL_BLEND_WEIGHT": 0.123}):
        assert config.PROJ_MODEL_BLEND_WEIGHT == 0.123
    assert config.PROJ_MODEL_BLEND_WEIGHT == before

def test_restores_on_exception():
    before = config.PROJ_SHRINKAGE_GAMES
    with pytest.raises(RuntimeError):
        with config_overrides({"PROJ_SHRINKAGE_GAMES": 0.0}):
            raise RuntimeError("boom")
    assert config.PROJ_SHRINKAGE_GAMES == before

def test_unknown_key_rejected_before_any_change():
    before = config.PROJ_MODEL_BLEND_WEIGHT
    with pytest.raises(KeyError, match="NOT_A_KEY"):
        with config_overrides({"PROJ_MODEL_BLEND_WEIGHT": 0.9, "NOT_A_KEY": 1}):
            pass
    assert config.PROJ_MODEL_BLEND_WEIGHT == before
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_config_overrides.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement `config_overrides`** in `src/config_overrides.py` with `contextlib.contextmanager`; validate all keys first.
- [ ] **Step 4: Run to verify they pass** — same command → 3 passed.
- [ ] **Step 5: Commit** — `git add src/config_overrides.py tests/test_config_overrides.py && git commit -m "feat(calibration): config override context manager"`

---

### Task 2: Fixture strength as a config setting

**Files:**
- Modify: `src/config.py` (next to `PROJ_OPP_FORM_FACTOR`), `src/projections.py:556-583`
- Test: `tests/test_fdr_strength_config.py`

**Interfaces:**
- Produces: `config.PROJ_FDR_STRENGTH = 1.0  # [untested] scales how far the baseline leg's fixture-difficulty multiplier swings from 1.0; 1.0 = today. Does not touch the xG leg (ratings/venue).`. `project_elements_next_gws(..., fdr_strength=None, ...)`: `None` reads `config.PROJ_FDR_STRENGTH` at call time; an explicit number still wins.

- [ ] **Step 1: Write the failing tests** — build one small elements/fixtures frame (reuse the helpers in `tests/test_wildcard_scores.py` or `tests/wildcard_market_fixture.py` where they fit); assert `xpts_gw{N}` with `config_overrides({"PROJ_FDR_STRENGTH": 1.0})` equals the call with explicit `fdr_strength=1.0`, and that with `PROJ_FDR_STRENGTH = 2.0` a D4/D5-fixture player's xPts drops further below the 1.0 run than a D3 player's does.
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_fdr_strength_config.py -q`.
- [ ] **Step 3: Implement** — add the config line; change the default to `None` and resolve it from config at the top of the function.
- [ ] **Step 4: Run the new tests and the full suite** — `.venv/bin/python -m pytest -q` → all pass (1.0 keeps behaviour identical).
- [ ] **Step 5: Commit** — `git commit -am "feat(projections): fixture strength reads PROJ_FDR_STRENGTH"`

---

### Task 3: Live-season replay inputs

**Files:**
- Create: `src/season_replay.py`
- Test: `tests/test_season_replay.py`

**Interfaces:**
- Consumes: bootstrap dict, fixtures list (FPL API shape), `history_df` in the `player_gw_history_*.csv` shape (`player_id, gw, gw_total_points, gw_minutes, gw_starts, gw_fixture_count, gw_team_id_end, gw_team_difficulty_avg`), `snapshots_df` in the `player_gw_snapshots` shape, `match_df` in the `player_match_history_*.csv` shape (has `event`).
- Produces:
  - `build_live_engine_inputs(target_gw: int, horizon: int, bootstrap: dict, fixtures: list, history_df, snapshots_df) -> tuple[elements_df, fixtures_window, teams_short_map, history_capped, dropped_ids: list[int]]`
  - `cap_match_history(match_df, target_gw: int) -> DataFrame` (rows with `event < target_gw`)
  - `actuals_for_gw(snapshots_df, history_df, gw: int) -> DataFrame[player_id, actual, minutes, had_fixture]` — `actual`/`minutes` from the snapshot's `actual_points`/`actual_minutes`, `had_fixture` from `history_df.gw_fixture_count > 0` for that GW.

Element fields: static fields (`id, web_name, team, element_type, penalties_order, direct_freekicks_order, corners_and_indirect_freekicks_order`) from the bootstrap; as-of fields from the snapshot row for `target_gw` (`now_cost = round(price_m*10)`, `status`, `chance_of_playing_next_round = chance`, `ep_next = fpl_ep_next`, `selected_by_percent = ownership_pct`); history-derived fields from GWs `< target_gw` only (`total_points`, `minutes`, `points_per_game` = total points / GWs with minutes > 0, `form` = mean points over the last 4 GWs in which the team had a fixture). Players with no snapshot row for `target_gw` go to `dropped_ids`. The frame carries every column in `config.ELEMENTS_KEEP` the bootstrap path would provide: derive `starts` as the sum of `gw_starts` over GWs `< target_gw`, set `chance_of_playing_this_round` equal to the next-round chance, and take any remaining static column from the bootstrap. A missing column must fail loudly, never default silently (a zero `starts` empties `start_share` and the XI pool downstream).

- [ ] **Step 1: Write the failing tests**
  - `test_no_future_history_leaks`: history with GW 5–9 rows, target 7 → `history_capped.gw.max() == 6`; a player who scored 20 in GW8 has `form` and `total_points` unaffected.
  - `test_as_of_fields_come_from_target_gw_snapshot`: snapshots for GW6 (price 6.0, status `a`) and GW7 (price 6.2, status `d`, chance 50) → target 7 element has `now_cost == 62`, `status == "d"`, `chance_of_playing_next_round == 50`.
  - `test_player_without_snapshot_is_dropped_not_defaulted`: id 999 in bootstrap, no GW7 snapshot → not in elements, `999 in dropped_ids`.
  - `test_cap_match_history_strictly_before_target`.
  - `test_frame_has_every_engine_column`: `set(config.ELEMENTS_KEEP) <= set(elements.columns)`, and `starts` equals the summed `gw_starts` before the target GW.
  - `test_actuals_mark_blank_gw_as_no_fixture`: a player whose team had `gw_fixture_count == 0` in GW7 → `had_fixture` False.
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_season_replay.py -q`.
- [ ] **Step 3: Implement** the three functions in `src/season_replay.py`.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(calibration): live-season replay inputs from snapshots + history"`

---

### Task 4: Calibration table metric

**Files:**
- Modify: `src/backtest_metrics.py` (append)
- Test: `tests/test_backtest_metrics_calibration.py`

**Interfaces:**
- Produces: `price_band(price_m: float) -> str` returning `"<6" | "6-8" | "8+"`; `calibration_table(frames: list[DataFrame]) -> DataFrame` with columns `pos, band, n, mae, bias, spearman, mae_app, bias_app, n_app`. Input frames carry `player_id, position, price_m, xpts, actual, minutes, had_fixture`. Rows with `had_fixture == False` are excluded. One row per (pos, band) plus `("ALL","ALL")`. `bias` = mean(xpts − actual). `*_app` = same over rows with minutes > 0. `spearman` via `pandas` rank correlation, `None` when n < 3.

- [ ] **Step 1: Write the failing tests** — `price_band(5.95) == "<6"`, `price_band(6.0) == "6-8"`, `price_band(8.0) == "8+"`; a two-frame fixture where MID 8+ rows predict 5 and score 3 → that cell's `bias == 2.0`; a no-fixture row is excluded from `n`; a zero-minute row counts in `n` but not in `n_app`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** both functions.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(calibration): calibration table by position x price band"`

---

### Task 5: Replay runner, results, user sign-off

**Files:**
- Create: `scripts/backtest_live_season.py`
- Create: `docs/calibration/2026-10-26-live-replay.md` (results, written after the run)
- Test: `tests/test_backtest_live_season.py`

**Interfaces:**
- Consumes: Task 1 `config_overrides`, Task 3 replay inputs, Task 4 `calibration_table`.
- Produces: `parse_grid(spec: str) -> list[dict[str, float]]` — `"A=1,2;B=3"` → the Cartesian product `[{"A":1,"B":3},{"A":2,"B":3}]`; `replay_frames(gws, horizon, overrides, inputs) -> list[DataFrame]` (frames in Task 4's shape; `horizon=5` frames compare the 5-GW xPts sum with the 5-GW actual sum, and only windows fully inside the finished GWs are scored).

CLI: `PYTHONPATH=. .venv/bin/python -m scripts.backtest_live_season --snapshots-csv PATH --tune-gws 3-6 --holdout-gws 7-8 --grid "PROJ_SHRINKAGE_GAMES=5,2.5,0;PROJ_MODEL_BLEND_WEIGHT=0.5,0.6,0.7;PROJ_FDR_STRENGTH=1,1.5,2" [--horizon 1|5] [--out CSV]`. It reads the bootstrap, the fixtures and the local `data/processed/fpl/**/player_gw_history_*.csv` and `player_match_history_*.csv` (run the refresh first: `api.main.get_bootstrap_cached`, `fpl_refresh_next_gw.refresh_next_gw_snapshot`, `refresh_match_history`). It patches `projections.load_latest_player_gw_history`, `minutes_model.load_minutes_history` and `fixture_difficulty.load_match_history` per GW exactly as `scripts/backtest_blend_sweep.py` does, prints the current config's row first, then ranks candidates by tune-GW price-band bias (`monitoring.band_bias`-style: mean |bias| over (pos, band) cells with n ≥ 20), keeping only candidates whose tune-GW 1-GW MAE is within 1% of the current config's. For the current config and the top 3 candidates it prints the hold-out calibration table and a per-GW line (MAE and band bias for every tune and hold-out GW), so a win that rests on one week is visible. Snapshots CSV: export `select * from player_gw_snapshots where season='2026-27'` (the Supabase SQL editor or the MCP tool) to a gitignored path under `data/`.

- [ ] **Step 1: Write the failing tests** for `parse_grid` (product, float parsing, unknown key rejected via Task 1 when applied) and for the 5-GW window rule (`gws=3..8, horizon=5` scores only windows starting at 3 and 4).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement the runner.**
- [ ] **Step 4: Run the tests, then run the replay** for horizon 1 and 5 on the 2026-27 snapshots. Also run the existing `scripts/backtest_blend_sweep.py` on 2025-26 for the blend weight and print its table under a `NON-PARITY (2025-26, no ep_next/status)` heading.
- [ ] **Step 5: Write `docs/calibration/2026-10-26-live-replay.md`**: the grid, hold-out tables, the per-GW lines, and a plain-language summary per candidate. State that `PROJ_FDR_STRENGTH` only moves the baseline leg (the xG leg's fixture effect runs through team ratings and venue), so at blend 0.7 it can move about 30% of a projection; a flat result on that axis means "this knob is weak", not "fixtures don't matter". Lead with what changes for which kinds of players (for example "premium midfielders −0.6 a week, cheap regular defenders +0.4"), then whether hold-out MAE is within the 1% "not worse" line.
- [ ] **Step 6: Commit** — `git add scripts/backtest_live_season.py tests/test_backtest_live_season.py docs/calibration && git commit -m "feat(calibration): live-season replay runner + first results"`
- [ ] **Step 7: STOP. Show the user the plain-language summary and ask which settings to ship (or none).** Do not start Task 8 without an explicit choice.

---

### Task 6: Model version + shadow projection in the weekly snapshot

**Why on the runner, not on Fly:** the Fly machine has 512 MB (`fly.toml`, shared-cpu-1x) and already runs two uvicorn workers; a child process loading pandas and the whole engine there is an out-of-memory risk, and patching config inside a live worker would leak into concurrent requests. The shadow therefore runs in the GitHub Actions snapshot job, in its own process, on data it refreshes itself, right after the live snapshot is written. Known gap: the runner reads the repo's `data/models` seeds, not the Fly volume's runtime-edited `knowledge_discount.json`, so live and shadow can differ by that nudge; the report states it.

**Files:**
- Modify: `src/config.py`, `api/main.py:1995-2045` (`build_model_snapshot`), `scripts/snapshot_to_db.py:19-36`, `.github/workflows/snapshot-db.yml`
- Create: `scripts/shadow_snapshot.py`, `supabase/migrations/20261026_snapshot_model_version.sql`
- Test: `tests/test_snapshot_db.py` (extend), `tests/test_shadow_snapshot.py`

**Interfaces:**
- Config: `PROJ_MODEL_VERSION = "2026-10-22.blend70"  # [operational] bump on every projection change`; `PROJ_SHADOW_MODEL_VERSION = None  # [operational]`; `PROJ_SHADOW_OVERRIDES = {}  # [operational] previous model's config values, computed in shadow after a projection change`.
- `build_model_snapshot()` adds top-level `model_version`; `snapshot_rows` writes `model_version` (null when the payload lacks it).
- `scripts/shadow_snapshot.py`:
  - `shadow_rows(proj_df, season: str, gw: int, version: str) -> list[dict]` (pure) → `{"season", "gw", "player_id", "shadow_xpts", "shadow_model_version"}` per player, xPts rounded to 3 decimals.
  - `main()`: exits 0 with a log line when `config.PROJ_SHADOW_OVERRIDES` is empty or the deadline has passed (same rule as `snapshot_rows`); otherwise refreshes data locally (bootstrap, fixtures, `fpl_refresh_next_gw.refresh_next_gw_snapshot`, `refresh_match_history`, status snapshot, the same sequence as a local refresh), runs `project_elements_next_gws` for the next GW (horizon 1) inside `config_overrides(config.PROJ_SHADOW_OVERRIDES)`, and upserts `shadow_rows` with `Prefer: resolution=merge-duplicates` so only the shadow columns change. Any exception logs and exits 0: the shadow never fails the job.
- Workflow: after the live snapshot step, `pip install -r requirements.txt` and run `PYTHONPATH=. python scripts/shadow_snapshot.py` with the same Supabase secrets, `continue-on-error: true`.
- Migration: `alter table public.player_gw_snapshots add column model_version text, add column shadow_model_version text, add column shadow_xpts numeric(7,3);`

- [ ] **Step 1: Write the failing tests** — `snapshot_rows` copies `model_version` and writes None for an old payload; `shadow_rows` shapes rows and rounds; `main()` with empty overrides makes no network call (monkeypatch `requests` to raise); `main()` restores `config.PROJ_MODEL_BLEND_WEIGHT` after a run with `{"PROJ_MODEL_BLEND_WEIGHT": 0.5}` (monkeypatch the refresh and projection calls); a projection exception exits 0 and upserts nothing.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** the config lines, the route field, the row field, the script, the workflow step and the migration file.
- [ ] **Step 4: Run the new tests and the full suite.**
- [ ] **Step 5: Commit** — `git commit -m "feat(monitoring): model version in the snapshot + shadow projection on the runner"`

---

### Task 7: Monitoring report + rollback verdict

**Files:**
- Create: `scripts/monitor_report.py`, `src/monitoring.py`
- Test: `tests/test_monitoring.py`

**Interfaces:**
- Consumes: Task 4 `calibration_table`, `captain_hit_rate` in `src/backtest_metrics.py`.
- Produces (`src/monitoring.py`, pure):
  - `frames_from_snapshots(rows_df, column: str) -> list[DataFrame]` — one Task-4 frame per GW from snapshot rows that have actuals, using `column` (`"model_xpts"` or `"shadow_xpts"`) as `xpts`; `had_fixture` from the history (passed in) or, when absent, `actual_minutes > 0 or model_xpts > 0.5`.
  - `band_bias(table) -> float` — mean of |bias| over (pos, band) cells with `n >= 20`, excluding the ALL row.
  - `rollback_verdict(live_frames, shadow_frames, gws_since_ship: int) -> str` returning `"wait"` when `gws_since_ship < 3`, `"rollback"` when shadow overall MAE < 0.99 × live MAE or `band_bias(live) > band_bias(shadow)`, else `"keep"`.
- CLI: `PYTHONPATH=. .venv/bin/python -m scripts.monitor_report [--csv PATH | (env SUPABASE_URL, SUPABASE_SERVICE_KEY)] --season 2026-27 [--since-version VERSION]` prints, per version, per GW and cumulative: MAE, bias, rank correlation, captain hit rate, the calibration table, and the verdict.

- [ ] **Step 1: Write the failing tests** — `rollback_verdict` returns `"wait"` at 2 GWs; `"rollback"` when shadow MAE is 1.5% lower; `"keep"` when shadow MAE is 0.5% lower and band bias is not better; `"rollback"` when MAE ties but live band bias is larger; `band_bias` ignores cells with `n < 20`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** `src/monitoring.py` and the CLI.
- [ ] **Step 4: Run the tests; run the report on the exported 2026-27 snapshots** (no shadow yet, so it prints the live table and `"wait"`).
- [ ] **Step 5: Commit** — `git commit -m "feat(monitoring): per-version report and rollback verdict"`

---

### Task 8: Ship the chosen settings (only after Task 5's sign-off)

**Files:**
- Modify: `src/config.py`, `CLAUDE.md` (projection-engine and xG-blend paragraphs)
- Test: full suite; `tests/test_config_single_source_of_truth.py`

**Interfaces:**
- Consumes: the user's choice from Task 5 Step 7; Task 6 config names.

- [ ] **Step 1: Set the chosen values** with `[tuned]` tags whose comments cite `docs/calibration/2026-10-26-live-replay.md` and the hold-out MAE and band-bias numbers.
- [ ] **Step 2: Bump `PROJ_MODEL_VERSION`** (for example `"2026-10-26.calib1"`), set `PROJ_SHADOW_MODEL_VERSION = "2026-10-22.blend70"` and `PROJ_SHADOW_OVERRIDES` to the previous values of exactly the keys that changed.
- [ ] **Step 3: Update `CLAUDE.md`** wherever it states the old values (blend weight, shrinkage), and add a short "Monitoring" note: replay command, report command, rollback rule.
- [ ] **Step 4: Run the full suite** — `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5: Commit** — `git commit -am "feat(projections): ship calibrated settings; previous model runs in shadow"`
- [ ] **Step 6: Before the PR:** run the security review on the branch diff, remind the user to apply `supabase/migrations/20261026_snapshot_model_version.sql` in the dashboard before merging, and open one backend PR.
