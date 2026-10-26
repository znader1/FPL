# Availability-Adjusted Team Strength Implementation Plan (plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a key player is doubtful or out, his team's attack (or defence) weakens by his share of the team's output. His teammates' outlook drops, the fixture gets easier for opponents, and everything reverts when he is back.

**Architecture:** A pure module, `src/availability.py`, turns FPL status/chance plus each player's share of recent team output into a per-team "missing share" for attack and defence. That share adjusts the team ratings after the knowledge discount, in both places ratings are built (the projection difficulty source and the xG model), which moves opponents' clean-sheet and attack outlooks. It also gives a teammate multiplier on the final per-GW xPts of the team's other MID/FWD players, because the xG model deliberately keeps a player's own team attack out of his per-90 rates (`src/output_model.py:20-21`), so a ratings change alone would never reach Palmer when João Pedro is out.

**Tech Stack:** Python 3.11, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-wildcard-calibration-design.md` (part 2). Depends on plan 1 (`config_overrides`, model version, shadow) being merged first.

## Global Constraints

- Config only in `src/config.py`, tagged; no `getattr` fallbacks.
- `AVAIL_ENABLED = False` turns the whole feature off and reproduces today's projections exactly (pinned by a test).
- The manual `knowledge_discount.json` nudge stays and composes: availability is applied after it.
- Ratings stay within `FDR_RATING_MIN..FDR_RATING_MAX` after adjustment.
- No future leak: shares use only matches with `event < gw_start`; availability comes from the elements frame passed in (the replay feeds as-of status).
- Ships without a backtest (no history can test it), with the previous model in shadow and plan 1's rollback rule.

## Review Focus

- **A player who left the club or has 0 minutes in the window:** he has no share, so his status moves nothing.
- **A whole team with no match history yet** (start of season, promoted club): no shares, so ratings and multipliers stay at 1.0.
- **Status `a` with a null chance** (the normal case): play probability 1.0, no effect.
- **The out player himself:** his own teammate multiplier ignores his own share; he is already discounted by his play probability elsewhere.
- **Several players out at once:** missing shares add up, and the teammate multiplier floors at `AVAIL_TEAMMATE_FLOOR` instead of going near zero.

---

### Task 1: Availability core (pure)

**Files:**
- Create: `src/availability.py`
- Modify: `src/config.py` (new block "Availability-adjusted team strength")
- Test: `tests/test_availability.py`

**Interfaces:**
- Config (all `[untested]` except the flag): `AVAIL_ENABLED = True  # [flag]`, `AVAIL_SHARE_WINDOW_MATCHES = 6`, `AVAIL_ATTACK_IMPACT = 0.6` (share of a missing player's output the team loses; replacements cover the rest), `AVAIL_DEF_IMPACT = 0.3`, `AVAIL_TEAMMATE_IMPACT = 0.5`, `AVAIL_TEAMMATE_FLOOR = 0.85`, `AVAIL_DOUBT_DEFAULT_CHANCE = 0.5`.
- Produces:
  - `play_probability(elements: DataFrame) -> Series` indexed by element id: status `a` → `chance/100` or 1.0 when chance is null; `d` → `chance/100`, or `AVAIL_DOUBT_DEFAULT_CHANCE` when null; `i`, `s`, `u`, `n` → 0.0.
  - `team_shares(match_df: DataFrame, gw_start: int) -> DataFrame[element, team_id, attack_share, defence_share]` over each team's last `AVAIL_SHARE_WINDOW_MATCHES` matches with `event < gw_start`. `attack_share` = player's (`expected_goals` + `expected_assists`) / team total. `defence_share` = for `element_type` 1–2 only, the player's minutes / the team's GKP+DEF minutes; 0 for MID/FWD.
  - `team_missing(shares, elements, horizon_gws: int) -> dict[int, dict]` → `{team_id: {"attack": float, "defence": float}}` = Σ share × (1 − p) × out_fraction, where out_fraction = `1 / horizon_gws` for status `d` (a doubt covers one GW) and 1.0 otherwise.
  - `apply_to_ratings(ratings: dict, missing: dict) -> dict` — returns a copy with `attack *= 1 − AVAIL_ATTACK_IMPACT × missing.attack` and `defense *= 1 + AVAIL_DEF_IMPACT × missing.defence`, clamped to `FDR_RATING_MIN..FDR_RATING_MAX`. Teams absent from `missing` are unchanged.
  - `teammate_multiplier(shares, elements, missing, horizon_gws: int) -> Series` indexed by element id: MID/FWD get `max(AVAIL_TEAMMATE_FLOOR, 1 − AVAIL_TEAMMATE_IMPACT × (team missing attack − own contribution to it))`; everyone else 1.0.

- [ ] **Step 1: Write the failing tests**
  - `test_play_probability_by_status`: `a`/null → 1.0, `a`/75 → 0.75, `d`/null → 0.5, `i` → 0.0, `s` → 0.0.
  - `test_shares_use_only_matches_before_gw_start`: a GW9 hat-trick does not change GW9 shares.
  - `test_striker_out_cuts_attack_and_teammates`: team with striker share 0.30 (`s`) and a midfielder share 0.25 → team attack missing 0.30; attack rating × (1 − 0.6 × 0.30) = × 0.82; midfielder multiplier = 1 − 0.5 × 0.30 = 0.85.
  - `test_doubt_covers_one_gw_of_the_horizon`: same striker `d`/50 with horizon 5 → missing = 0.30 × 0.5 × 0.2 = 0.03.
  - `test_floor_holds_with_several_out`: three attackers with shares 0.3/0.3/0.2 all out → multiplier for the fourth = 0.85.
  - `test_no_history_team_unchanged`: team absent from shares → rating and multipliers unchanged.
  - `test_out_player_ignores_own_share`.
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_availability.py -q`.
- [ ] **Step 3: Implement** the config block and the five functions.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(availability): play probability, team shares, missing share, rating and teammate adjustments"`

---

### Task 2: Wire availability into projections

**Files:**
- Modify: `src/projections.py:98-113` (`resolve_projection_difficulty_ratings`), `src/projections.py` around the blend at 844-857, `src/expected_points.py:36-49` (`build_ratings`) and `build_expected_points` (`:51`)
- Test: `tests/test_availability_projection.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `resolve_projection_difficulty_ratings(teams_short_map, missing=None)` and `expected_points.build_ratings(..., missing=None)` apply `availability.apply_to_ratings(ratings, missing)` right after `apply_knowledge_discount` when `missing` is not None. `build_expected_points(..., missing=None)` passes it through.
  - In `project_elements_next_gws`, when `config.AVAIL_ENABLED`: compute `shares` from `fixture_difficulty.load_match_history()` (the loader the backtests already patch, so replays stay leak-safe), then `missing`, and pass `missing` to both rating builders. After the model blend, multiply every `xpts_gw{g}` by `teammate_multiplier`, recompute `xpts_horizon` the same way the function already does, and add an output column `avail_teammate_mult` (1.0 when disabled). Any exception in the availability path logs a warning and falls back to unadjusted projections.

- [ ] **Step 1: Write the failing tests** with a small synthetic market and match history (reuse `tests/wildcard_market_fixture.py` patterns; monkeypatch `fixture_difficulty.load_match_history`):
  - `test_disabled_never_touches_projections`: under `config_overrides({"AVAIL_ENABLED": False})`, monkeypatch every `availability` function to raise; projections still return, `avail_teammate_mult` is all 1.0, and `xpts_gw*` equal a second disabled run.
  - `test_striker_out_lowers_teammates_and_raises_opponent_defenders`: striker status `s` → his MID teammate's `xpts_gw{N}` falls, and a defender of the GW opponent gains.
  - `test_failure_falls_back`: monkeypatch `availability.team_shares` to raise → projections still return, `avail_teammate_mult` all 1.0.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement the wiring.**
- [ ] **Step 4: Run the new tests and the full suite** — `.venv/bin/python -m pytest -q`.
- [ ] **Step 5: Spot-check on live data:** in the analysis replay (plan 1's runner, or a local refresh), print Chelsea's MID/FWD `avail_teammate_mult` and xPts before/after with João Pedro `d`/75, and Chelsea's GW opponent's defenders. Paste the numbers into the commit message.
- [ ] **Step 6: Commit** — `git commit -m "feat(availability): team ratings and teammates follow who is available"`

---

### Task 3: Ship with the previous model in shadow

**Files:**
- Modify: `src/config.py`, `CLAUDE.md` (projection-engine section: one paragraph on availability and its config)

- [ ] **Step 1: Bump `PROJ_MODEL_VERSION`** (for example `"…+avail1"`). Set `PROJ_SHADOW_OVERRIDES` to the model running before this ship: add `"AVAIL_ENABLED": False` to whatever plan 1 already put there, so the shadow stays the pre-change model, and say in the commit that the two changes are then judged together.
- [ ] **Step 2: Run the full suite.**
- [ ] **Step 3: Commit** — `git commit -am "feat(projections): ship availability-adjusted strength; previous model in shadow"`
- [ ] **Step 4: Security review on the branch diff, then one backend PR.**
