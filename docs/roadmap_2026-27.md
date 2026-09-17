# FPLedge 2026-27 Pre-Season Roadmap

**Written:** 2026-07-22 · **GW1:** ~mid-August 2026 (~3-4 weeks out)
**Goal:** ship the 26-27 rule-driven edges before GW1, each validated on the backtest harness.

---

## What's already built (don't rebuild)

| Feature | State | Flag |
|---------|-------|------|
| Minutes/rotation model (SP1) | Built, **dormant** — backtest proved the multiplicative discount never beats baseline MAE | `PROJ_APPLY_MINUTES_MODEL=False` |
| Ownership-adjusted EV + captain-differential (SP2) | **Shipped, ON** | `LEAGUE_EV_RANKING=True` |
| Walk-forward backtest harness (SP3) | Built — `scripts/backtest_season.py`, `backtest_metrics.py` | — |
| Personal GW-replay tool (SP4) | Built — local test bed (`REPLAY_MODE=1`) | — |
| xG fixture-difficulty + carryover seed + knowledge file | Built, blend **off** | `PROJ_MODEL_BLEND_WEIGHT=0.0` |

## The validation loop (use for EVERY change)

1. `python scripts/backtest_season.py --season 2025-26 --start 2 --end 38 --use-engine --weekly-chips --smart-transfers` → per-GW points, MAE, captain hit-rate, rank.
2. `/replay` tool for per-GW model-vs-actual eyeballing.
3. **Rule:** no projection/recommender change ships without a backtest win vs the current baseline (2025-26: engine ≈ 2022 pts, MAE ≈ 2.13, captain hit ≈ 22-30%).

---

## Phase A — Pre-season prep (Week 1, NOT data-gated)

- [ ] **A1. Update `data/models/knowledge_discount.json` for 26-27** — promoted teams (weak default handles unknowns), big transfers, pre-season injuries. Current file dated June 10. *Test:* fixture-difficulty ratings sanity-check for moved players.
- [ ] **A2. Verify refresh pipeline flips to the 26-27 API** — when FPL opens the new season, run `/admin/refresh`; confirm bootstrap/fixtures + `player_match_history` rebuild. *Test:* `available_gws` / processed CSVs populate for 2026-27.
- [ ] **A3. (optional) Extend team-ratings seed to full 38** via Vaastav (marginal; GW33 seed is fine).

## Phase B — Build + test NOW on 2025-26 (Weeks 1-3) — the real edges

### B1. Defensive-contribution expected-points component ★ top edge
26-27 keeps DC points + tweaks BPS (1 per **3** CBI). Most tools underweight this.
- Add a DC xPts component: CBI + tackles per 90 → P(hit the DC points threshold) → expected DC points. **CBI is in Vaastav 2025-26 data** (`expected_*` + tackles/CBI columns), so fully backtestable now.
- Wire into `src/output_model.py` / `expected_points.py` behind a new flag (e.g. `OUTPUT_APPLY_DEF_CONTRIB`), blend like the xG stack.
- *Test:* backtest 2025-26 with flag off vs on — MAE, captain hit-rate, top-N precision, especially for DEF/DM. **Done when:** ≥ baseline on defenders without hurting overall.

### B2. FT-banking transfer planner ★ top edge
26-27 rule: roll up to **5 free transfers**, and they **survive Wildcard/Free Hit**.
- Fix FT derivation (`entry_history.event_transfers` logic) for the 5-cap + chip-survival rule.
- Extend `src/recommender.py` beam search to value **banking** FTs (holding for a multi-move swing is now cheaper).
- *Test:* backtest with the new FT model — does banking improve season total vs always-spend? **Done when:** total ≥ baseline and no illegal-move regressions.

### B3. (revisit) minutes model — non-multiplicative form only
Prior finding: multiplicative discount hurts. Only worth it if reframed.
- Try minutes as a **selection/flagging** signal (exclude likely-benched from captain/transfer targets) or additive, not a blanket multiplier.
- *Test:* backtest vs baseline. **Done when:** it finally beats baseline, else leave dormant.

## Phase C — Data-gated (in-season, GW1-6+)

- [ ] **C1. BPS/bonus recalibration** — refit the bonus piece of `output_model.py` (`OUTPUT_BONUS_PER_XGI` + DC overlap) for 1-per-3 CBI once 26-27 BPS accrues (~GW6).
- [ ] **C2. Price-predictor ingestion** — check if FPL's new official price predictor is API-exposed; if so, feed rise/fall likelihood into transfer *timing*.
- [ ] **C3. Cold-start monitoring** — watch xG carryover seed vs live convergence GW1-6; raise `PROJ_MODEL_BLEND_WEIGHT` only if the blend beats baseline on live data.

---

## Schedule (to GW1)

| Week | Focus |
|------|-------|
| **1** | A1 knowledge file + A2 refresh check; start **B1** (DC component) |
| **2** | Finish B1 backtest; build **B2** (FT-banking planner) |
| **3** | B2 backtest + polish; full dry-run through the `/replay` tool on 2025-26 |
| **4 (GW1)** | Live refresh + cold-start monitoring; begin Phase C |

## Process note
Each Phase-B item is its own **brainstorm → writing-plans → subagent-driven-development** cycle (same as SP1-4). Backtest-gate before enabling any flag.
