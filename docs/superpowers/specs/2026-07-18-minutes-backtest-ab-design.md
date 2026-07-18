# Minutes A/B Backtest Harness — Design

**Date:** 2026-07-18
**Repo:** `FPL/` (backend)
**Status:** Approved design, pre-implementation
**Sub-project:** 3 of 4 (see `2026-07-17-minutes-rotation-model-design.md` §0)

## 1. Goal & non-goals

**Goal:** A *lighter* walk-forward backtest that validates the minutes/rotation
model (sub-project 1) as a **guide** (not a hard gate): does turning
`PROJ_APPLY_MINUTES_MODEL` on improve projection accuracy on 2025-26 ground
truth? Produces the go/no-go signal for enabling the flag in-season **and** the
sales-credibility number.

**Non-goals:**
- Backtesting the ownership-adjusted EV (sub-project 2). **Not possible** — FPL
  bootstrap state (global + league ownership) is not historical, so there is no
  ownership snapshot to replay. Documented, not attempted.
- The full season simulator (squad/transfer/chip decisions) — confounds the
  minutes signal. This harness measures *projection accuracy* directly.
- Changing any production projection behavior.

## 2. Current state (verified 2026-07-18)

- `scripts/backtest_season.py` is a full season simulator; `project_gw_engine`
  monkeypatches `projections.load_latest_player_gw_history` to inject the capped
  history — but **only that loader**. The minutes model reads a *separate* loader
  (`minutes_model.load_minutes_history`), which the existing harness never
  patches → a minutes A/B there would read live/empty disk data (future leak or
  no history).
- `src/backtest_adapter.py:63` fakes `gw_starts = (minutes >= 60)`. The real
  per-GW Vaastav files (`data/vaastav/2025-26/gws/gwN.csv`) **do** have a real
  `starts` column — usable to close this gap.
- Vaastav 2025-26 has GWs **1–29** cached. Walk-forward range = GW3 → max
  available (currently 29), computed dynamically via `backtest_data.available_gws()`.
- Ground truth: `backtest_data.player_actuals_at(gw)` → per-player `total_points`,
  `minutes`, `starts` for that GW.

## 3. Design

### A. Adapter fix — real starts (`src/backtest_adapter.build_history_df`)
Use the real `starts` column when present in the loaded history, else the
`minutes >= 60` proxy:
```python
if "starts" in history_long.columns:
    df["gw_starts"] = pd.to_numeric(history_long["starts"], errors="coerce").fillna(0).astype(int)
else:
    df["gw_starts"] = (df["gw_minutes"] >= 60).astype(int)  # fallback proxy
```
Strictly better for both this harness and the existing season sim.

### B. Metrics module — `src/backtest_metrics.py` (pure, testable)
All take a merged frame with `xpts` (projected, this GW) + `actual` (actual
points) + `position` + `minutes` (actual):
- `projection_mae(df, top_n=40)` → MAE over the union of {top-`top_n` by `xpts`}
  and {`minutes` > 0}, i.e. the decision-relevant + actually-played universe.
- `mae_by_position(df, top_n=40)` → `{pos: mae}`.
- `captain_hit_rate(per_gw_frames, top_k=5)` → fraction of GWs where the
  top-`xpts` player is within the actual top-`top_k` by `actual`.
- `captain_regret(per_gw_frames)` → mean over GWs of
  `(max actual) − (actual of the top-xpts player)`.
- `top_n_precision(df, n=10)` → `|top-n by xpts ∩ top-n by actual| / n`.

### C. Harness — `scripts/backtest_minutes_ab.py`
```
for target_gw in [3 .. max_available]:
    elements, fixtures, teams_short, history_df = build_engine_inputs(target_gw)
    for flag in (False, True):
        # PATCH BOTH loaders to the capped history (no future leak):
        projections.load_latest_player_gw_history <- lambda: history_df
        minutes_model.load_minutes_history        <- lambda: history_df   # cols: player_id,gw,gw_minutes,gw_starts
        config.PROJ_APPLY_MINUTES_MODEL = flag
        proj = projections.project_elements_next_gws(elements, fixtures, teams_short, target_gw, horizon=3)
        # restore loaders + flag in a finally
    actuals = player_actuals_at(target_gw)   # element -> total_points, minutes
    merge proj[xpts_gw{target_gw}] with actuals -> per-GW frame (off, on)
aggregate + print off-vs-on table + verdict
```
Restore both loaders and the flag in a `finally` every iteration. The committed
`PROJ_APPLY_MINUTES_MODEL` default (False) is never persisted-changed.

### D. Output
A table: metric | minutes OFF | minutes ON | delta, for MAE (overall + per
position), captain hit-rate, captain regret, top-10 precision — plus a one-line
verdict. Also print n_gws and the GW range used.

## 4. Testing (TDD)
`tests/test_backtest_metrics.py` — deterministic synthetic frames:
- MAE: known projected vs actual → known MAE; top-N universe restriction works.
- captain_hit_rate: constructed GWs where the top-projected is / isn't in actual
  top-k → known fraction.
- captain_regret: known best-vs-picked gap.
- top_n_precision: known overlap.
- adapter: `build_history_df` uses real `starts` when present (small synthetic
  Vaastav-shaped frame via monkeypatched `player_actuals_through`), proxy when absent.

## 5. Ship-fast / interpretation
This is a **guide**. Expected read: if minutes-ON reduces MAE and lifts captain
hit-rate across GW3-29, that's the evidence to enable `PROJ_APPLY_MINUTES_MODEL`
a few GWs into next season (after the cross-season history-bleed fix from SP1).
If it's neutral/worse, keep it off and revisit the coefficients. Either way the
number is honest and publishable ("we tested it, here's what we found").

## 6. Risks
- Backtest elements lack real `selected_by_percent`/`status`/`ep_next` (adapter
  placeholders), so the backtest exercises the *history-driven* minutes signal,
  not live availability. That's the right thing to isolate here (rotation, not
  injury) — documented.
- Only 29 GWs cached; the signal is directional, not a large-sample proof.
  Report `n_gws` so the reader calibrates confidence.
