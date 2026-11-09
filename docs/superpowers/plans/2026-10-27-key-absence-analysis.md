# Key-Player Absence Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A script that, for every PL team and its top-3 key players, reports how teammates' attacking output moves when the key player is absent, with opponent/venue control, a league pool, shrinkage and a placebo, on both seasons on disk.

**Architecture:** Pure pandas logic in a new `src/key_absence.py` (frame-in / frame-out, no I/O, fully unit-tested on synthetic frames). A thin CLI `scripts/analyze_key_absence.py` does loading, the optional GW refresh, network bootstrap fetch, and writes two CSVs plus a markdown report. No production module is modified.

**Tech Stack:** Python 3, pandas, numpy, pytest. Existing helpers: `src.fixture_difficulty` (ratings, `expected_xg_for_fixture`, `build_team_match_xg`), `src.live_history` (`missing_event_ids`, `append_events`), `src.fpl_client` (`get_bootstrap`, `get_fixtures`).

**Spec:** `docs/superpowers/specs/2026-10-27-key-absence-analysis-design.md`

## Global Constraints

- No change to `src/projections.py`, `src/output_model.py`, `src/fixture_difficulty.py`, `src/live_history.py`, or any API route.
- Top-N default 3. Teammate threshold: ≥ 180 minutes in both buckets. Key-selection minutes floor: 270 this season. "Team played fixture" guard: ≥ 11 rows with minutes > 0. Shrinkage k = 4. Bootstrap draws = 2000, interval = 90%. Decision rule: key-pooled 90% interval excludes placebo-pooled mean AND key-pooled effect < 0.95.
- Gating effect uses teammates-only xG (team xG minus key player's own). Whole-team effect reported beside it.
- Goalkeepers (`element_type == 1`) excluded from key selection and placebo.
- Both seasons must run through the same functions; schema differences are normalised in one loader (`kickoff_time_x` → `kickoff_time`).
- Work happens in a git worktree off `master` on branch `feature/key-absence-analysis` (per memory: never switch branches in the shared `FPL/` checkout).

## Review Focus

1. A key player who is present for every fixture (n_absent = 0) must produce a row with `n_absent = 0` and NaN effect, never a crash or a division by zero. → Task 4 test.
2. A fixture where the key player has a row with `minutes == 0` (2025-26 schema) and a fixture where he has no row at all (2026-27 schema) must both count as absent. → Task 2 test.
3. A team with fewer than 3 eligible outfield players after the minutes floor must return the players it has, not raise. → Task 3 test.
4. `--key-players` override with a name that matches no player on the team must fail loudly with the team and name, not silently fall back. → Task 6 test.
5. Teammate rates must be minutes-weighted, not match-averaged: a 10-minute cameo with one xA must not dominate. → Task 5 test.

---

### Task 1: Loader and normalisation

**Files:**
- Create: `src/key_absence.py`
- Test: `tests/test_key_absence.py`

**Interfaces:**
- Produces: `normalize_history(match_df: pd.DataFrame, fixtures: list[dict]) -> pd.DataFrame` — columns `element, element_type, team_id, fixture, event, was_home, kickoff_time, minutes, starts, expected_goals, expected_assists`, types coerced; rows whose `team_id` is not in the fixture's `(team_h, team_a)` dropped; `kickoff_time_x` renamed. `fixtures` is the `/fixtures/` payload (list of dicts with `id, team_h, team_a`).
- Produces: `team_fixture_sets(df: pd.DataFrame) -> pd.DataFrame` — one row per `(team_id, fixture)` the team *played* (≥ 11 rows with `minutes > 0`), columns `team_id, fixture, event, was_home, team_xg_for`.

- [ ] **Step 1: Write failing tests**

```python
def test_normalize_drops_rows_outside_fixture_pair():
    fixtures = [{"id": 1, "team_h": 1, "team_a": 2}]
    df = pd.DataFrame([
        {"element": 10, "element_type": 4, "team_id": 1, "fixture": 1, "event": 1, "was_home": True, "kickoff_time_x": "2026-08-21T19:00:00Z", "minutes": 90, "starts": 1, "expected_goals": 0.5, "expected_assists": 0.1},
        {"element": 11, "element_type": 4, "team_id": 3, "fixture": 1, "event": 1, "was_home": False, "kickoff_time_x": "2026-08-21T19:00:00Z", "minutes": 90, "starts": 1, "expected_goals": 0.5, "expected_assists": 0.1},
    ])
    out = key_absence.normalize_history(df, fixtures)
    assert out["element"].tolist() == [10]
    assert "kickoff_time" in out.columns and "kickoff_time_x" not in out.columns

def test_team_fixture_sets_requires_eleven_players():
    rows = [_row(e, team=1, fixture=1, minutes=90, xg=0.1) for e in range(11)]
    rows += [_row(e, team=2, fixture=1, minutes=90, xg=0.1) for e in range(100, 105)]  # one-sided scrape
    out = key_absence.team_fixture_sets(pd.DataFrame(rows))
    assert out["team_id"].tolist() == [1]
    assert abs(out["team_xg_for"].iloc[0] - 1.1) < 1e-9
```

Write a `_row(element, team, fixture, minutes, xg, xa=0.0, starts=None, event=1, was_home=True, etype=3)` helper at the top of the test module; `starts` defaults to `1 if minutes >= 60 else 0`.

- [ ] **Step 2: Run tests, expect ImportError / AttributeError**

Run: `python -m pytest tests/test_key_absence.py -q`

- [ ] **Step 3: Implement `normalize_history` and `team_fixture_sets` in `src/key_absence.py`**

Module docstring: one paragraph pointing at the spec. `normalize_history` keeps only the eleven listed columns (missing optional ones filled: `starts` from `minutes >= 60`, `expected_assists` 0.0). Use `pd.to_numeric(..., errors="coerce")` throughout.

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/key_absence.py tests/test_key_absence.py
git commit -m "feat(key-absence): history normalisation and team-fixture sets"
```

---

### Task 2: Presence buckets per (team, key player)

**Files:**
- Modify: `src/key_absence.py`
- Test: `tests/test_key_absence.py`

**Interfaces:**
- Consumes: `team_fixture_sets` output (Task 1).
- Produces: `presence_buckets(df: pd.DataFrame, team_fx: pd.DataFrame, team_id: int, player_id: int) -> pd.DataFrame` — `team_fx` rows for `team_id`, filtered to fixtures between the player's first and last appearance (`minutes > 0`) for that team, with added columns `bucket` ∈ `{"present","absent","benched"}` and `key_xg` (player's `expected_goals` in that fixture, 0.0 when absent). present = minutes > 0 and starts ≥ 1; benched = minutes > 0 and starts == 0; absent = no row or minutes == 0.

- [ ] **Step 1: Write failing tests**

```python
def test_absent_inferred_from_missing_row_and_zero_minutes():
    # team 1 plays fixtures 1,2,3; key player 10 plays 1 (start) and 3 (start), row with 0 minutes in 2
    ...
    out = key_absence.presence_buckets(df, team_fx, team_id=1, player_id=10)
    assert dict(zip(out["fixture"], out["bucket"])) == {1: "present", 2: "absent", 3: "present"}

def test_absent_without_any_row_counts_too():
    # same but fixture 2 has no row for player 10 at all
    assert dict(zip(out["fixture"], out["bucket"]))[2] == "absent"

def test_benched_bucket():
    # fixture 2: minutes 20, starts 0
    assert ...[2] == "benched"

def test_moved_player_fixtures_before_first_appearance_excluded():
    # team plays 1,2,3; player first appears in 3 → only fixture 3 returned
    assert out["fixture"].tolist() == [3]
```

- [ ] **Step 2: Run, expect failures**
- [ ] **Step 3: Implement `presence_buckets`**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `feat(key-absence): presence buckets with inferred absence`

---

### Task 3: Key-player and placebo selection

**Files:**
- Modify: `src/key_absence.py`
- Test: `tests/test_key_absence.py`

**Interfaces:**
- Produces: `select_key_players(signals: pd.DataFrame, top: int = 3, min_minutes: float = 270.0, overrides: dict[int, list[int]] | None = None) -> dict[int, list[int]]` — `signals` has one row per player: `player_id, team_id, element_type, minutes, threat, creativity, now_cost, last_ppg, this_ppg` (NaN allowed in `last_ppg`). Rank-sum within team of `threat/minutes*90`, `creativity/minutes*90`, `now_cost`, `last_ppg`, `this_ppg` (equal weights, higher is better, NaN ranks last), GK excluded, players under `min_minutes` use `last_ppg`-only rank for the two rate signals (spec: "below that, last-season rate" — implement as: rates set to NaN, so they rank last on those two). Tie-break by `minutes`. `overrides[team_id]` replaces that team's list verbatim.
- Produces: `select_placebo(df: pd.DataFrame, key: dict[int, list[int]]) -> dict[int, int]` — per team, the outfield player with most minutes not in `key[team_id]`.

- [ ] **Step 1: Write failing tests**

```python
def test_select_excludes_gk_and_returns_top_n(): ...
def test_select_rate_not_total():
    # A: 900 min, threat 300; B: 450 min, threat 150 → identical rate → tie → broken by minutes → A first, but B must still be in top 2
def test_select_short_team_returns_what_it_has():
    # team with 2 eligible outfielders → list of 2, no raise
def test_override_replaces_list(): ...
def test_placebo_excludes_keys_and_gk(): ...
```

- [ ] **Step 2: Run, expect failures**
- [ ] **Step 3: Implement both functions**
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `feat(key-absence): key-player and placebo selection`

---

### Task 4: Team-level effect with fixture expectation

**Files:**
- Modify: `src/key_absence.py`
- Test: `tests/test_key_absence.py`

**Interfaces:**
- Consumes: `presence_buckets` (Task 2); `fixture_difficulty.expected_xg_for_fixture(ratings, team_id, opp_id, is_home)`.
- Produces: `attach_expected(buckets: pd.DataFrame, ratings: dict, fixtures: list[dict]) -> pd.DataFrame` — adds `opp_id`, `expected_for`, `team_ratio = team_xg_for / expected_for`, `teammates_ratio = (team_xg_for - key_xg) / expected_for`.
- Produces: `team_effect(buckets: pd.DataFrame) -> dict` — keys `n_present, n_absent, n_benched, team_ratio_present, team_ratio_absent, teammates_ratio_present, teammates_ratio_absent, team_effect, teammates_effect, xg_for_present, xg_for_absent`. Effects are `absent / present` means; NaN when either n is 0.

- [ ] **Step 1: Write failing tests**

```python
def test_ratio_controls_for_opponent():
    # ratings: team 1 attack 1.0; opp 2 defense 0.6 (tight), opp 3 defense 1.4 (leaky)
    # present fixture vs leaky opp: xg 1.4·league; absent fixture vs tight opp: xg 0.6·league, key_xg 0
    # raw xg_for lower when absent, but teammates_effect ≈ 1.0 (within 1e-6)

def test_n_absent_zero_gives_nan_effect_not_error():
    eff = key_absence.team_effect(buckets_all_present)
    assert eff["n_absent"] == 0 and math.isnan(eff["teammates_effect"])

def test_teammates_effect_ignores_key_players_own_xg():
    # key makes 100% of team xG when present, teammates 1.0 both buckets → teammates_effect == 1.0, team_effect < 1
```

Build `ratings` dicts by hand (`{1: {"attack":1.0,"defense":1.0}, 2: {...}, "_league": 1.4}`), do not call `compute_team_ratings` in tests.

- [ ] **Step 2: Run, expect failures**
- [ ] **Step 3: Implement `attach_expected` and `team_effect`**

`opp_id` from the fixtures list via `fixture` id. Home/away from `was_home`.

- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `feat(key-absence): opponent-controlled team effect`

---

### Task 5: Teammate rates, pooling, shrinkage, bootstrap

**Files:**
- Modify: `src/key_absence.py`
- Test: `tests/test_key_absence.py`

**Interfaces:**
- Produces: `teammate_rates(df: pd.DataFrame, buckets: pd.DataFrame, team_id: int, player_id: int, min_minutes: float = 180.0) -> pd.DataFrame` — one row per teammate with ≥ `min_minutes` in both present and absent fixtures: `teammate_id, element_type, min_present, min_absent, xg90_present, xg90_absent, xa90_present, xa90_absent, xg90_ratio, xa90_ratio`. Minutes-weighted: `sum(xg)/sum(minutes)*90` per bucket.
- Produces: `pool_effects(rows: list[dict], key: str = "teammates_effect", weight_key: str = "n_absent", draws: int = 2000, seed: int = 0) -> dict` — `{"effect": weighted mean, "n": sum of weights, "lo": 5th pct, "hi": 95th pct, "pairs": count}` by resampling rows with replacement. Rows with NaN effect or zero weight are skipped.
- Produces: `shrink(raw: float, n: float, pooled: float, k: float = 4.0) -> float` = `(n*raw + k*pooled)/(n+k)`; NaN raw treated as n = 0.
- Produces: `decision(key_pool: dict, placebo_pool: dict, bar: float = 0.95) -> tuple[bool, str]` — True iff `placebo_pool["effect"]` not in `[key_pool["lo"], key_pool["hi"]]` and `key_pool["effect"] < bar`; string is the one-line reason.

- [ ] **Step 1: Write failing tests**

```python
def test_teammate_rates_minutes_weighted():
    # teammate: present 2×90 min, xa 0.1 each; absent 10 min with xa 1.0 and 170 min with xa 0 → xa90_absent = 1.0/180*90 = 0.5, not mean of per-match rates
def test_teammate_below_threshold_excluded(): ...
def test_pool_weights_by_n_absent_and_skips_nan(): ...
def test_shrink_formula(): assert key_absence.shrink(0.5, 4, 1.0) == 0.75
def test_decision_rule():
    assert key_absence.decision({"effect":0.85,"lo":0.80,"hi":0.90}, {"effect":1.0})[0] is True
    assert key_absence.decision({"effect":0.85,"lo":0.70,"hi":1.05}, {"effect":1.0})[0] is False
    assert key_absence.decision({"effect":0.97,"lo":0.96,"hi":0.98}, {"effect":1.0})[0] is False
```

- [ ] **Step 2: Run, expect failures**
- [ ] **Step 3: Implement the four functions** (`numpy.random.default_rng(seed)` for the bootstrap)
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `feat(key-absence): teammate rates, pooling, shrinkage, decision rule`

---

### Task 6: Orchestration, selection signals, override parsing

**Files:**
- Modify: `src/key_absence.py`
- Test: `tests/test_key_absence.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_signals(df: pd.DataFrame, bootstrap: dict, last_season_df: pd.DataFrame | None, last_bootstrap: dict | None) -> pd.DataFrame` — the `signals` frame of Task 3. `threat, creativity, now_cost, minutes, team_id, element_type` from `bootstrap["elements"]`; `this_ppg` from `df` (`total_points` present? the normalised frame drops it — so compute from `bootstrap["elements"]["total_points"]` / appearances with minutes>0 in `df`); `last_ppg` by joining `bootstrap` `code` → `last_bootstrap` `code` → last season `element`, from `last_season_df` (`total_points` sum / appearances with minutes>0, NaN under 10 appearances). For the 2025-26 run pass `last_season_df=None` → `last_ppg` all NaN, and build `threat/creativity` from the file's own columns summed per player (the file has them) and `now_cost` from the latest `value`; expose this path as `build_signals_from_history(df_raw: pd.DataFrame) -> pd.DataFrame`.
- Produces: `parse_overrides(spec: str | None, bootstrap: dict, teams_short_map: dict[int, str]) -> dict[int, list[int]]` — `"CHE:João Pedro,Palmer;ARS:Saka"` → ids; name match is accent-insensitive on `web_name` within the team; unknown team or name raises `ValueError("CHE: no player named X")`.
- Produces: `run_analysis(df: pd.DataFrame, fixtures: list[dict], ratings: dict, key: dict[int, list[int]], placebo: dict[int, int], teams_short_map: dict[int, str], names: dict[int, str]) -> dict` with keys `team_rows` (list of dicts, one per (team, key player), including `team_short, player_name` and all `team_effect` keys plus `shrunk_teammates_effect`), `teammate_rows` (list of dicts from `teammate_rates` with `team_short, key_player_name, teammate_name`), `placebo_rows`, `key_pool`, `placebo_pool`, `decision` (bool, str).

- [ ] **Step 1: Write failing tests**

```python
def test_parse_overrides_accent_insensitive_and_errors(): 
    # "CHE:Joao Pedro" matches web_name "João Pedro"; "CHE:Nobody" raises ValueError containing "CHE" and "Nobody"
def test_run_analysis_end_to_end_synthetic():
    # 2 teams, 4 fixtures each, one key player absent for 2 → team_rows has 2 entries per team-key, key_pool["pairs"] >= 1, decision tuple
```

- [ ] **Step 2: Run, expect failures**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run, expect PASS; run full suite** `python -m pytest -q`
- [ ] **Step 5: Commit** `feat(key-absence): signals, overrides, run_analysis`

---

### Task 7: CLI, refresh, report

**Files:**
- Create: `scripts/analyze_key_absence.py`
- Test: `tests/test_key_absence.py` (report rendering only)

**Interfaces:**
- Consumes: `run_analysis` (Task 6), `live_history.missing_event_ids/append_events`, `fpl_client.get_bootstrap/get_fixtures`, `fixture_difficulty.resolve_team_ratings/compute_team_ratings/build_team_match_xg/load_match_history`.
- Produces (in `src/key_absence.py`): `render_report(result: dict, season: str, key: dict, names: dict, teams_short_map: dict, caveats: list[str]) -> str` — markdown with sections in spec order: selection list; pooled key vs placebo with decision line; per-team table sorted by `shrunk_teammates_effect` ascending (columns: team, key player, n_present, n_absent, n_benched, teammates_effect raw, shrunk, team_effect); per-team top-5 teammate movers each way; caveats.

CLI behaviour (`python -m scripts.analyze_key_absence --season 2026-27 [--refresh] [--top 3] [--key-players "..."] [--out-dir data/backtest] [--docs-dir docs]`):

1. Load `data/processed/fpl/<season>/player_match_history_<season>.csv` via `pd.read_csv`.
2. `--refresh` (current season only): `bootstrap = fpl_client.get_bootstrap()`, `fixtures = fpl_client.get_fixtures()`, `missing = live_history.missing_event_ids(existing, bootstrap)`, `append_events`, write back to the same path. Print appended GWs.
3. Fixtures: for 2025-26 read `data/raw/fpl/2025-26/fixtures.json`; for the current season fetch live (cache to `data/raw/fpl/<season>/fixtures.json` and `bootstrap_static.json`, creating the dir).
4. Ratings: current season → `resolve_team_ratings(build_team_match_xg(df), teams_short_map=..., halflife_days=1e6)`; 2025-26 → `compute_team_ratings(..., halflife_days=1e6, shrinkage_matches=0)`.
5. Signals → `select_key_players` (+ overrides) → `select_placebo` → `run_analysis` → write `data/backtest/key_absence_<season>.csv`, `data/backtest/key_absence_teammates_<season>.csv`, `docs/key_absence_<season>_<YYYY-MM-DD>.md`. Print the pooled line and decision to stdout.

Caveats list always includes: inferred absence, transfers bounded, n per team, "2025-26 selection uses season totals from the same matches (identical for every player, noted)".

- [ ] **Step 1: Write failing test for `render_report`** — assert the decision line and one per-team row appear in the string for a tiny synthetic `result`.
- [ ] **Step 2: Run, expect failure**
- [ ] **Step 3: Implement `render_report` and the CLI**
- [ ] **Step 4: Run tests; then run the CLI on 2025-26** `PYTHONPATH=. python -m scripts.analyze_key_absence --season 2025-26` — expect three files written and a pooled line printed. Spot-check: 20 teams, 60 key rows (or fewer with short teams), no NaN in `n_absent`.
- [ ] **Step 5: Run on 2026-27 with refresh** `PYTHONPATH=. python -m scripts.analyze_key_absence --season 2026-27 --refresh` — expect "appended [5, 6, 7, 8]" (or whatever is finished) and the report.
- [ ] **Step 6: Commit** `feat(key-absence): CLI, refresh and markdown report` (commit the two generated 2025-26 CSVs and both reports; `data/processed` stays untracked as today).

---

### Task 8: Read the result and write the handoff note

**Files:**
- Modify: `docs/superpowers/specs/2026-10-27-key-absence-analysis-design.md` (append "Result" section)

- [ ] **Step 1:** Append to the spec: pooled key vs placebo for both seasons, decision outcome, the three largest per-team shrunk effects, Chelsea / João Pedro row verbatim, and whether phase 2 is unlocked.
- [ ] **Step 2:** Commit `docs(key-absence): phase-1 result`, push branch, open PR to `master` with the pooled numbers in the body.
