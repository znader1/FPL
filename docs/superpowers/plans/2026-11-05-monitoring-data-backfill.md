# Monitoring Dashboard, Plan 1: Data Layer and GW1–GW10 Backfill

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store, for every gameweek from GW1 to GW10 and both tracked entries, one finished report comparing the app, The Scout, the owner's team and real points, checkable by a database query before any page exists.

**Architecture:** Pure scoring and parsing modules in `src/` (no network), one I/O script that reads the FPL API, the Premier League content feed and Supabase, and writes four tables. Replay of past advice calls the engine directly on as-of inputs. Nothing is added to the production API and nothing the app advises changes.

**Tech Stack:** Python 3.10 (pandas 1.5, requests), Supabase Postgres via PostgREST, GitHub Actions. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-05-monitoring-dashboard-design.md` (read it first; this plan argues from it).

**This is plan 1 of 3.** Plan 2 (the page, frontend repo) and plan 3 (saving advice before each deadline) are written after this one lands, because both depend on the report shape fixed in Task 7.

## Global Constraints

- Work only in the worktree `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/worktrees/monitoring-dashboard` (branch `feature/monitoring-dashboard`). Never switch branches in `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL`. Use `git -C <absolute path>`.
- Run tests with `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/FPL/.venv/bin/python -m pytest <path> -q` from the worktree root.
- No future information in a replayed gameweek: only data knowable before that gameweek's deadline. Knowledge files (team and player) are off in replay.
- Missing data is stored and reported as missing. Never a default, never a guess, never an invented eleven or captain.
- No change to any existing module's behaviour except the one move in Task 6 (a function relocated, same behaviour). `build_recommendations`, `build_wildcard_drafts` and the HTTP routes are not called and not edited.
- Every tunable is a tagged constant in `src/config.py` (`# [operational]`, `# [untested]`); no numbers in logic files. FPL rules come from `src/rules.py` (`CHIP_MAX_PER_TEAM`) and `optimizer.VALID_FORMATIONS`.
- The Supabase service key is read from the environment only and never logged or printed.
- `.gitignore` ignores `*.csv`: commit CSV fixtures with `git add -f`.
- Migrations are applied by the owner in the Supabase dashboard before the code that writes the tables runs.
- Tests first. Commit after each task. Security review of the whole diff before the pull request; findings go in the PR body. The owner merges.
- Module names: the repo already has `src/monitoring.py` and `scripts/monitor_report.py` (model-error monitoring from PR #76). Do not touch or shadow them; this plan's modules are `scout_names`, `scout_feed`, `monitor_xi`, `monitor_scoring`, `monitor_replay`, `monitor_gw_report`, `scripts/monitor_backfill.py`.

## Review Focus

Conditions the spec implies that are most likely to bite, each pinned by a test in the task that owns the code:

1. **A Scout pick that cannot be matched to an FPL player** (new signing, spelling, two players with one surname at a club). Expected: the article is stored with `needs_review`, the unmatched name is listed, totals exclude nothing silently. Tests in Task 2 and Task 7.
2. **A window that is not finished** (a GW9 move judged over 3 gameweeks when 1 has been played). Expected: partial total, `played` < window, `complete: false`, no verdict. Test in Task 5.
3. **The feed returns two articles for one gameweek and series, or none.** Expected: the latest published wins deterministically; none means the Scout column is missing for that week, the run continues. Test in Task 3.
4. **Chip weeks** (Bench Boost GW1, Free Hit GW7). Expected: no transfer line in a Free Hit or Wildcard week; the squad going into GW8 is the GW6 squad, not the Free Hit fifteen. Tests in Task 5 and Task 6.
5. **Replay fails or is incomplete for one gameweek** (engine error, or a squad player absent from that gameweek's snapshot). Expected: that card says unavailable with the reason, dropped players are named, every other gameweek and card still builds. Tests in Task 6 and Task 7.

---

## File Structure

| File | Responsibility |
|---|---|
| `supabase/migrations/20261106_monitoring_tables.sql` | Five tables, row-level security, owner-only select |
| `src/config.py` (modify) | `MONITOR_*` and `SCOUT_FEED_*` constants |
| `src/scout_names.py` | Match a Scout "Name (Club)" to an FPL player id |
| `src/scout_feed.py` | Classify feed articles by title; parse players and captain from an article body |
| `src/monitor_xi.py` | Exact best eleven, line-up from fifteen, eleven scoring |
| `src/monitor_scoring.py` | Transfer gains over windows, buy-list averages, squad window score |
| `src/season_replay.py` (modify) | Receives `project_as_of`, moved from `scripts/backtest_live_season.py` |
| `src/monitor_replay.py` | As-of advice: squad before a gameweek, transfer plan, wildcard squads, buy targets, parity |
| `src/monitor_gw_report.py` | Assemble one gameweek report (the contract for the page) |
| `scripts/monitor_backfill.py` | I/O shell: fetch, upsert, local dry run |
| `.github/workflows/monitor-backfill.yml` | Manually triggered run |
| `data/monitoring/scout_overrides.json` | Hand-entered picks for articles a rule cannot parse; id pins |
| `tests/test_scout_names.py`, `test_scout_feed.py`, `test_monitor_xi.py`, `test_monitor_scoring.py`, `test_monitor_replay.py`, `test_monitor_gw_report.py`, `test_monitor_backfill.py`, `test_monitor_migration.py` | One test module per source file |
| `tests/fixtures/monitor/` | Real article bodies, a GW9 snapshot extract, the owner's GW6–GW9 picks |

---

### Task 1: Tables and configuration

**Files:**
- Create: `supabase/migrations/20261106_monitoring_tables.sql`
- Modify: `src/config.py` (append a "Monitoring dashboard" block after the `PROJ_SHADOW_OVERRIDES` block)
- Test: `tests/test_monitor_migration.py`

**Interfaces:**
- Produces (tables, all in schema `public`, RLS enabled, no anon policy):
  - `monitor_owners(user_id uuid primary key)`
  - `expert_picks(season text, gw int, source text, series text, article_id bigint, url text, title text, published_at timestamptz, fetched_at timestamptz, captain_player_id int, vice_player_id int, captain_stated boolean, captain_inferred_player_id int, players jsonb, unmatched jsonb, needs_review boolean, primary key (season, gw, source, series))`
  - `advice_snapshots(season text, gw int, entry_id bigint, kind text, origin text, model_version text, payload jsonb, captured_at timestamptz, primary key (season, gw, entry_id, kind, origin))`
  - `entry_gw_actuals(season text, gw int, entry_id bigint, picks jsonb, transfers jsonb, chip text, points int, points_on_bench int, transfer_cost int, bank_m numeric, value_m numeric, captured_at timestamptz, primary key (season, gw, entry_id))`
  - `monitor_reports(season text, gw int, entry_id bigint, report jsonb, built_at timestamptz, code_version text, primary key (season, gw, entry_id))`
  - Select policy on the last four: `using (auth.uid() in (select user_id from public.monitor_owners))`. `monitor_owners` select policy: `using (user_id = auth.uid())`.
- Produces (config):

```python
MONITOR_WINDOWS_GWS = (1, 3, 5)  # [operational]
MONITOR_TRANSFER_VERDICT_WINDOW_GWS = 3  # [operational]
MONITOR_WILDCARD_WINDOW_GWS = 5  # [operational]
MONITOR_ADVICE_HORIZON_GWS = 3  # [operational] the API's default horizon_gws; capture and replay use it
MONITOR_BUY_LIST_PER_POSITION = 2  # [untested]
MONITOR_BUY_LIST_POSITIONS = ("DEF", "MID", "FWD")  # [operational]
MONITOR_WILDCARD_HEADLINE_PRESET = "balanced"  # [operational] must be in CHIP_WILDCARD_PRESET_ORDER
MONITOR_PARITY_MAX_MEAN_ABS_DIFF = 0.10  # [untested]
MONITOR_PARITY_MIN_CORR = 0.99  # [untested]
MONITOR_ENTRY_IDS = (107342, 5645321)  # [operational] tracked entries, 2026-27 ids
SCOUT_FEED_BASE_URL = "https://api.premierleague.com/content/premierleague/text/en"  # [operational] unofficial public feed
SCOUT_FEED_TAGS = ("franchise:fpl-scout-picks", "franchise:transfer-radar", "content-creator:The-Scout")  # [operational]
SCOUT_FEED_PAGE_SIZE = 30  # [operational] the feed caps a page at 30
SCOUT_FEED_MAX_PAGES = 4  # [operational]
SCOUT_OVERRIDES_PATH = "data/monitoring/scout_overrides.json"  # [operational]
```

- [ ] **Step 1: Write the failing test** in `tests/test_monitor_migration.py`

```python
import pathlib, re
SQL = pathlib.Path("supabase/migrations/20261106_monitoring_tables.sql")
TABLES = ["monitor_owners", "expert_picks", "advice_snapshots", "entry_gw_actuals", "monitor_reports"]

def test_every_table_has_rls_and_an_owner_only_select_policy():
    sql = SQL.read_text().lower()
    for t in TABLES:
        assert f"create table if not exists public.{t}" in sql
        assert f"alter table public.{t} enable row level security" in sql
        assert re.search(rf"create policy [^;]+ on public\.{t}\s+for select[^;]+auth\.uid\(\)", sql)
    assert "for insert" not in sql and "for update" not in sql and "for delete" not in sql
    assert " anon" not in sql

def test_config_headline_preset_is_a_real_preset():
    from src import config
    assert config.MONITOR_WILDCARD_HEADLINE_PRESET in config.CHIP_WILDCARD_PRESET_ORDER
    assert config.MONITOR_TRANSFER_VERDICT_WINDOW_GWS in config.MONITOR_WINDOWS_GWS
```

- [ ] **Step 2: Run it, expect FAIL** (file not found): `pytest tests/test_monitor_migration.py -q`
- [ ] **Step 3: Write the migration and the config block.** Header comment in the SQL, same wording style as `20261026_snapshot_model_version.sql`: apply in the dashboard SQL editor (project `tetvymwgpaordnmsnneo`) before the backfill runs; then insert the owner's `auth.users` id into `monitor_owners` by hand (the comment gives the statement with a placeholder, not a real id).
- [ ] **Step 4: Run** `pytest tests/test_monitor_migration.py tests/test_config_single_source_of_truth.py -q`, expect PASS.
- [ ] **Step 5: Commit** `feat(monitor): tables with owner-only read, config block`

---

### Task 2: Match Scout names to FPL players

**Files:**
- Create: `src/scout_names.py`
- Test: `tests/test_scout_names.py`

**Interfaces:**
- Produces:
  - `normalise(text: str) -> str`: lower-case, accents stripped (`Petrović` → `petrovic`), HTML entities decoded, punctuation and repeated spaces removed.
  - `club_short(club_raw: str, teams: list[dict]) -> str | None`: `teams` are bootstrap teams (`name`, `short_name`). Resolves official names plus the Scout's variants. Required aliases, as a module constant `CLUB_ALIASES`: `AFC Bournemouth`/`Bournemouth` → `BOU`; `Spurs`/`Tottenham Hotspur` → `TOT`; `Man City`/`Manchester City` → `MCI`; `Man Utd`/`Manchester United` → `MUN`; `Brighton`/`Brighton & Hove Albion` → `BHA`; `Nott'm Forest`/`Nottingham Forest` → `NFO`; `Wolves` → `WOL`; `West Ham` → `WHU`; `Newcastle` → `NEW`. Unknown club → `None`.
  - `match_player(name_raw: str, club_raw: str, players: list[dict], teams: list[dict], overrides: dict | None = None) -> dict` returning `{"player_id": int | None, "status": "matched" | "ambiguous" | "not_found" | "unknown_club" | "override"}`. `players` rows carry `id`, `first_name`, `second_name`, `web_name`, `team_short`. `overrides` maps `"<normalised name>|<SHORT>"` → player id.

- [ ] **Step 1: Write the failing tests.** Player rows are small hand-built lists; the cases are real ones from this season.

```python
PLAYERS = [
    {"id": 1, "first_name": "Đorđe", "second_name": "Petrović", "web_name": "Petrović", "team_short": "BOU"},
    {"id": 154, "first_name": "Cole", "second_name": "Palmer", "web_name": "Palmer", "team_short": "CHE"},
    {"id": 700, "first_name": "Alex", "second_name": "Palmer", "web_name": "Palmer", "team_short": "IPS"},
    {"id": 112, "first_name": "Jan Paul", "second_name": "van Hecke", "web_name": "Van Hecke", "team_short": "TOT"},
    {"id": 300, "first_name": "Nicolas", "second_name": "Jackson", "web_name": "N.Jackson", "team_short": "AVL"},
    {"id": 5, "first_name": "Gabriel", "second_name": "dos Santos Magalhães", "web_name": "Gabriel", "team_short": "ARS"},
    {"id": 6, "first_name": "Gabriel", "second_name": "Martinelli Silva", "web_name": "Martinelli", "team_short": "ARS"},
    {"id": 7, "first_name": "Gabriel", "second_name": "Fernando de Jesus", "web_name": "G.Jesus", "team_short": "ARS"},
    {"id": 8, "first_name": "Rayan", "second_name": "Vitor Simplício Rocha", "web_name": "Rayan", "team_short": "BOU"},
]
```

  Assertions: `("Djordje Petrovic", "AFC Bournemouth")` → 1 matched (the `Dj`/`Đ` spelling must resolve; if the general rule cannot, it resolves through `overrides` and the test passes the override, asserting status `override`); `("Cole Palmer", "Chelsea")` → 154; `("Jan Paul van Hecke", "Spurs")` → 112; `("Nicolas Jackson", "Aston Villa")` → 300; `("Gabriel", "Arsenal")` → 5 (an exact `web_name` match wins over first-name matches); `("Rayan", "AFC Bournemouth")` → 8; `("Luka Vuskovic", "Brighton &amp; Hove Albion")` with a BHA player `Vušković` → matched; `("Palmer", "Arsenal")` → `not_found`; `("John Smith", "Atlantis FC")` → `unknown_club`; two BOU players both named `Smith` and query `("Smith", "Bournemouth")` → `ambiguous`, `player_id` None.

- [ ] **Step 2: Run, expect FAIL** (module missing).
- [ ] **Step 3: Implement.** Rule order inside the resolved club: override; exact normalised `web_name`; exact normalised `first_name + second_name`; every token of the Scout name present in the full-name tokens. Exactly one candidate at the first rule that yields any → matched; more than one → ambiguous.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(monitor): match Scout names to FPL players by club and name`

---

### Task 3: Read the Scout feed

**Files:**
- Create: `src/scout_feed.py`, `data/monitoring/scout_overrides.json` (content `{"articles": {}, "names": {}}`)
- Create fixtures: `tests/fixtures/monitor/article_4756626.json` (GW10 selection), `article_4750445.json` (GW9 selection), `article_4756485.json` (GW10 radar), `article_4726681.json` (GW6 wildcard squad), `article_4681112.json` (GW1 season squad)
- Test: `tests/test_scout_feed.py`

**Interfaces:**
- Produces:
  - `classify_article(title: str) -> tuple[str, int] | None`: `(series, gw)` with series in `selection`, `transfer_radar`, `wildcard`, `season_squad`; `None` for anything else.
  - `pick_articles(listing: list[dict], season_start: str) -> dict[tuple[int, str], dict]`: listing rows are feed items (`id`, `title`, `date`); ignores items dated before `season_start`; for a duplicate key keeps the latest `date`.
  - `parse_players(body_html: str) -> list[dict]`: one row per `<h5>` heading of the form `Name (Club) £X.Xm` → `{"name_raw", "club_raw", "price_m", "reason"}` (`reason` = the text between this heading and the next, tags stripped, at most 300 characters).
  - `parse_captain(body_html: str, players: list[dict]) -> dict`: `{"captain": name_raw | None, "vice": name_raw | None, "stated": bool, "inferred": name_raw | None}`.
  - `parse_article(article: dict, overrides: dict) -> dict`: `{"series", "gw", "article_id", "url", "title", "published_at", "players", "captain", "vice", "captain_stated", "captain_inferred", "needs_review", "review_reason"}`. `url` = `https://www.premierleague.com/en/news/<id>`.

- [ ] **Step 1: Save the five fixtures.** For each id, fetch `https://api.premierleague.com/content/premierleague/text/en/<id>` (browser-like `User-Agent`), keep only `id`, `title`, `date`, `body`, write as JSON. These are real pages; the tests below assert on their real content.

- [ ] **Step 2: Write the failing tests.**

```python
def test_classify_real_titles():
    c = scout_feed.classify_article
    assert c("Scout Selection: Best Fantasy team for Gameweek 10") == ("selection", 10)
    assert c("The Scout’s FPL Gameweek 10 transfer radar") == ("transfer_radar", 10)
    assert c("The Scout's GW6 squad for Wildcarders and new starters") == ("wildcard", 6)
    assert c("The Scout's FPL Gameweek 4 Wildcard squad") == ("wildcard", 4)
    assert c("FPL GW3 Wildcard squad: How to own Haaland, Fernandes, Joao Pedro AND Palmer") == ("wildcard", 3)
    assert c("The Scout’s FPL GW2 squad for Wildcarders and new starters") == ("wildcard", 2)
    assert c("Scout Selection: The best Fantasy squad for 2026/27") == ("season_squad", 1)
    assert c("The Scout's FPL Gameweek 9 Differentials") is None
    assert c("Sage on Palace claiming a late point") is None

def test_gw10_selection_parses_eleven_with_stated_captain():
    a = scout_feed.parse_article(load("article_4756626.json"), {})
    assert [p["name_raw"] for p in a["players"]] == [
        "Djordje Petrovic", "Gabriel", "James Tarkowski", "Maxim De Cuyper", "Morgan Rogers",
        "Martin Odegaard", "Marcus Tavernier", "Pascal Gross", "Erling Haaland", "Alexander Isak", "Thierno Barry"]
    assert a["players"][0] == {**a["players"][0], "club_raw": "AFC Bournemouth", "price_m": 4.5}
    assert (a["captain"], a["vice"], a["captain_stated"]) == ("Erling Haaland", "Alexander Isak", True)
    assert a["needs_review"] is False

def test_gw9_selection_has_no_stated_captain_but_one_inferred():
    a = scout_feed.parse_article(load("article_4750445.json"), {})
    assert len(a["players"]) == 11
    assert (a["captain"], a["captain_stated"], a["captain_inferred"]) == (None, False, "Erling Haaland")

def test_gw10_radar_parses_four_tips_with_entity_decoded_club():
    a = scout_feed.parse_article(load("article_4756485.json"), {})
    assert [(p["name_raw"], p["club_raw"], p["price_m"]) for p in a["players"]] == [
        ("Rayan", "AFC Bournemouth", 6.3), ("Cody Gakpo", "Liverpool", 7.1),
        ("Iliman Ndiaye", "Manchester City", 5.8), ("Luka Vuskovic", "Brighton & Hove Albion", 5.2)]

def test_prose_squads_are_flagged_not_guessed():
    for f in ("article_4726681.json", "article_4681112.json"):
        a = scout_feed.parse_article(load(f), {})
        assert a["players"] == [] and a["needs_review"] is True

def test_override_supplies_the_picks_for_a_prose_squad():
    ov = {"articles": {"4726681": {"players": [{"name": "Bukayo Saka", "club": "Arsenal"}] * 15, "confirmed_by_owner": True}}}
    a = scout_feed.parse_article(load("article_4726681.json"), ov)
    assert len(a["players"]) == 15 and a["needs_review"] is False
    ov["articles"]["4726681"]["confirmed_by_owner"] = False
    assert scout_feed.parse_article(load("article_4726681.json"), ov)["needs_review"] is True

def test_pick_articles_takes_latest_duplicate_and_skips_old_seasons():
    listing = [{"id": 1, "title": "Scout Selection: Best Fantasy team for Gameweek 5", "date": "2026-09-17T10:00:00Z"},
               {"id": 2, "title": "Scout Selection: Best Fantasy team for Gameweek 5", "date": "2026-09-18T09:00:00Z"},
               {"id": 3, "title": "Scout Selection: Best Fantasy team for Gameweek 27", "date": "2026-02-20T10:00:00Z"}]
    out = scout_feed.pick_articles(listing, season_start="2026-08-01")
    assert out == {(5, "selection"): listing[1]}
```

- [ ] **Step 3: Run, expect FAIL.**
- [ ] **Step 4: Implement.** Captain rules, in this order: (a) a sentence containing "named captain" whose text names two listed players → captain, vice, `stated` True (real sentence: "...Erling Haaland (£15.8m) and ... Alexander Isak (£9.2m) are named captain and vice-captain respectively."); (b) otherwise `stated` False, and `inferred` = the one listed player whose own section mentions `captaincy` or `armband`, only when exactly one section does. The bare word "captain" must not count (GW10's Odegaard section says "the Arsenal captain"). A `selection` article with a player count other than 11, or a `transfer_radar` with none, sets `needs_review` with a `review_reason`.
- [ ] **Step 5: Run, expect PASS.**
- [ ] **Step 6: Commit** `feat(monitor): classify and parse Scout articles from the content feed`

---

### Task 4: Best eleven, line-up from a squad, eleven scoring

**Files:**
- Create: `src/monitor_xi.py`, `tests/fixtures/monitor/gw9_snapshots.csv`, `tests/fixtures/monitor/gw9_expected.json`
- Test: `tests/test_monitor_xi.py`

**Interfaces:**
- Consumes: `optimizer.VALID_FORMATIONS`, `config.CHIP_MAX_PER_TEAM`, `captain_advisor.recommend_captain(starting_xi_df, top_n)` (frame columns `player_id, name, pos, team, price_m, xpts`).
- Produces (a "pool" is a `DataFrame` with `player_id, pos, team_short, value` plus pass-through columns):
  - `best_xi(pool: pd.DataFrame, max_per_club: int | None) -> list[int]`: the legal eleven maximising summed `value`; `max_per_club=None` means no cap. Exact, not greedy. Ties broken by lower `player_id` so the result is deterministic.
  - `pick_lineup(squad: pd.DataFrame) -> dict`: for a fifteen (or fewer), `{"xi": [ids], "bench": [ids], "captain_id", "vice_id"}`; eleven by `best_xi(squad, None)`, captain and vice by `app_captain`.
  - `app_captain(xi: pd.DataFrame) -> tuple[int | None, int | None]`: first and second of `recommend_captain(top_n=2)`; `xi` needs `name, price_m, xpts`.
  - `score_xi(xi_ids, captain_id, vice_id, points: dict[int, int], minutes: dict[int, int]) -> dict`: `{"no_captain": int, "with_captain": int | None, "captain_used": int | None}`. The captain is doubled; if he played 0 minutes the vice is doubled; `with_captain` is `None` when `captain_id` is `None`. A player missing from `points` contributes 0 and is listed under `"missing": [ids]`.

- [ ] **Step 1: Export the GW9 fixture.** Run this against Supabase project `tetvymwgpaordnmsnneo` (Supabase MCP `execute_sql`, or the dashboard) and save the rows as `tests/fixtures/monitor/gw9_snapshots.csv`:

```sql
select player_id, web_name, pos, team_short, price_m, model_xpts, actual_points, actual_minutes
from public.player_gw_snapshots where season = '2026-27' and gw = 9 order by player_id;
```

  Write `gw9_expected.json` by hand from the spec: Scout ids for (Suzuki AVL, Mukiele SUN, Silva BOU, Van Hecke TOT, Palmer CHE, Rogers CHE, Kudus TOT, Tavernier BOU, Manzambi AVL, Haaland MCI, N.Jackson AVL) looked up in the CSV by `web_name` + `team_short`; owner picks in order `[496, 8, 112, 534, 94, 40, 427, 480, 154, 411, 249, 109, 552, 115, 423]`, captain 411, vice 154.

- [ ] **Step 2: Write the failing tests.**

```python
def test_best_xi_is_exact_against_brute_force_on_a_small_pool():
    # 2 GKP, 5 DEF, 5 MID, 4 FWD across 3 clubs with a 3-per-club cap; values chosen so the
    # greedy "top by value then fix the cap" answer is not optimal.
    pool = small_pool()
    assert sum_value(pool, monitor_xi.best_xi(pool, 3)) == brute_force_best(pool, 3)

def test_best_xi_is_legal_on_real_gw9():
    pool = gw9().rename(columns={"model_xpts": "value"})
    xi = pool[pool.player_id.isin(monitor_xi.best_xi(pool, 3))]
    counts = xi.pos.value_counts().to_dict()
    assert len(xi) == 11 and counts["GKP"] == 1 and 3 <= counts["DEF"] <= 5 and 2 <= counts["MID"] <= 5 and 1 <= counts["FWD"] <= 3
    assert xi.team_short.value_counts().max() <= 3
    assert xi.value.sum() >= 60.0 - 0.05   # the hand-built eleven in the spec summed 60.0

def test_best_possible_gw9_is_115():
    pool = gw9().rename(columns={"actual_points": "value"})
    ids = monitor_xi.best_xi(pool, 3)
    assert int(pool[pool.player_id.isin(ids)].value.sum()) == 115

def test_scout_gw9_scores_69_without_captain_and_71_with_haaland():
    e = expected(); pts, mins = points_minutes(gw9())
    assert monitor_xi.score_xi(e["scout_ids"], None, None, pts, mins)["no_captain"] == 69
    assert monitor_xi.score_xi(e["scout_ids"], 411, None, pts, mins)["with_captain"] == 71

def test_owner_gw9_eleven_scores_64():
    e = expected(); pts, mins = points_minutes(gw9())
    assert monitor_xi.score_xi(e["owner_picks"][:11], 411, 154, pts, mins)["with_captain"] == 64

def test_vice_is_doubled_when_captain_did_not_play():
    assert monitor_xi.score_xi([1, 2], 1, 2, {1: 0, 2: 5}, {1: 0, 2: 90}) == {
        "no_captain": 5, "with_captain": 10, "captain_used": 2, "missing": []}

def test_a_player_without_points_is_reported_not_silently_zero():
    assert monitor_xi.score_xi([1, 9], None, None, {1: 4}, {1: 90})["missing"] == [9]
```

- [ ] **Step 3: Run, expect FAIL.**
- [ ] **Step 4: Implement.** `best_xi` approach: for each formation in `VALID_FORMATIONS`, a depth-first search over positions that takes players in descending value and prunes on the club cap and on an optimistic bound (the sum of the best remaining values ignoring the cap). No new dependency. If the exact GW9 eleven differs from the hand-built one in the spec, the solver's answer stands; record it in `gw9_expected.json` as `app_xi_ids` for Task 7. The other expectations (69, 71, 64, 115) come from real points: if the real data contradicts one, stop and report it; do not edit the expectation to fit.
- [ ] **Step 5: Run, expect PASS.**
- [ ] **Step 6: Commit** (`git add -f` the CSV) `feat(monitor): exact best eleven, line-up and scoring with the GW9 fixture`

---

### Task 5: Transfer gains, buy lists, squad windows

**Files:**
- Create: `src/monitor_scoring.py`
- Test: `tests/test_monitor_scoring.py`

**Interfaces:**
- Consumes: `monitor_xi.pick_lineup`, `monitor_xi.score_xi`, `config.MONITOR_WINDOWS_GWS`.
- Produces. `points_by_gw` is `dict[int, dict[int, int]]` (gameweek → player id → points); `last_finished_gw: int`.
  - `window_points(player_id, gw, window, points_by_gw, last_finished_gw) -> dict`: `{"points": int, "played": int, "complete": bool}` over gameweeks `gw .. gw+window-1`, counting only finished ones. A player absent from a finished gameweek's map counts 0.
  - `moves_windows(moves: list[dict], gw, hits: int, points_by_gw, last_finished_gw, windows=config.MONITOR_WINDOWS_GWS) -> dict[str, dict]`: `moves` rows `{"sell_id", "buy_id"}`; per window `{"gain": int, "played": int, "complete": bool}` where `gain` = Σ(buy − sell) − 4 × `hits`. No moves → gain 0.
  - `transfers_verdict(app_windows: dict | None, you_windows: dict) -> str | None`: on `config.MONITOR_TRANSFER_VERDICT_WINDOW_GWS`; `"app"`, `"you"`, `"level"`, or `None` when that window is incomplete or the app line is unavailable.
  - `list_windows(player_ids, prices_m: dict[int, float], gw, points_by_gw, last_finished_gw) -> dict`: `{"players": [{"id", "price_m", "windows": {...}}], "avg": {"1": float, ...}, "avg_per_m": {...}}`; averages are per listed player; an empty list gives `None` averages.
  - `squad_windows(squad_ids, gw, window, snapshots_by_gw: dict[int, pd.DataFrame], last_finished_gw) -> dict`: `{"points": int, "played": int, "complete": bool, "by_gw": {gw: {"xi": [...], "captain_id", "points"}}}`. Each finished gameweek: line-up by `pick_lineup` on that gameweek's stored `model_xpts`, scored with that gameweek's real points and minutes. A squad player with no snapshot row that gameweek is left out of the line-up and listed under `"absent"`. A gameweek with no snapshot rows at all (GW1) cannot have a line-up picked: it is skipped, not counted in `played`, and listed under `"no_projection_gws"`.
  - `is_transfer_chip_week(chip: str | None) -> bool`: True for `freehit` and `wildcard` (FPL's chip names), False otherwise including `bboost` and `3xc`.

- [ ] **Step 1: Write the failing tests**, with the owner's real moves:

```python
PTS = {8: {12: 0, 154: -1, 418: 0, 112: 7}, 9: {12: 0, 154: 8, 418: 0, 112: 15}}

def test_gw9_maguire_to_van_hecke_is_plus_15_after_one_gameweek():
    w = monitor_scoring.moves_windows([{"sell_id": 418, "buy_id": 112}], 9, 0, PTS, last_finished_gw=9)
    assert w["1"] == {"gain": 15, "played": 1, "complete": True}
    assert w["3"] == {"gain": 15, "played": 1, "complete": False}

def test_gw8_saka_to_palmer_is_minus_1_then_plus_7():
    w = monitor_scoring.moves_windows([{"sell_id": 12, "buy_id": 154}], 8, 0, PTS, last_finished_gw=9)
    assert w["1"]["gain"] == -1 and w["3"] == {"gain": 7, "played": 2, "complete": False}

def test_a_hit_costs_four_and_no_move_is_zero():
    assert monitor_scoring.moves_windows([{"sell_id": 418, "buy_id": 112}], 9, 1, PTS, 9)["1"]["gain"] == 11
    assert monitor_scoring.moves_windows([], 9, 0, PTS, 9)["1"]["gain"] == 0

def test_no_verdict_until_the_three_gameweek_window_is_complete():
    inc = {"3": {"gain": 15, "played": 1, "complete": False}}
    assert monitor_scoring.transfers_verdict(inc, inc) is None
    done = lambda g: {"3": {"gain": g, "played": 3, "complete": True}}
    assert monitor_scoring.transfers_verdict(done(9), done(4)) == "app"
    assert monitor_scoring.transfers_verdict(done(4), done(4)) == "level"
    assert monitor_scoring.transfers_verdict(None, done(4)) is None

def test_chip_weeks():
    assert monitor_scoring.is_transfer_chip_week("freehit") and monitor_scoring.is_transfer_chip_week("wildcard")
    assert not monitor_scoring.is_transfer_chip_week("bboost") and not monitor_scoring.is_transfer_chip_week(None)

def test_list_average_and_points_per_million():
    out = monitor_scoring.list_windows([112, 154], {112: 4.9, 154: 9.8}, 9, PTS, 9)
    assert out["avg"]["1"] == 11.5 and round(out["avg_per_m"]["1"], 3) == round((15 / 4.9 + 8 / 9.8) / 2, 3)

def test_squad_window_uses_that_weeks_stored_projection_and_reports_absentees():
    # two gameweeks of tiny snapshots; a squad player missing from the second one
    ...assert out["played"] == 2 and out["by_gw"][2]["absent"] == [missing_id]
```

- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement.** **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(monitor): transfer gains, buy-list averages and squad windows`

---

### Task 6: Replay past advice

**Files:**
- Modify: `src/season_replay.py` (add `project_as_of`), `scripts/backtest_live_season.py` (`project_gw` becomes a one-line call to it), `tests/test_player_knowledge_in_recommendations.py` (add `"src/monitor_replay.py"` and `"src/season_replay.py"` to the `module_path` list of `test_backtest_paths_do_not_apply_present_day_knowledge`)
- Create: `src/monitor_replay.py`
- Test: `tests/test_monitor_replay.py`

**Interfaces:**
- Consumes: `season_replay.build_live_engine_inputs`, `transfer_planner.plan_transfers` and `scaled_min_gain`, `api.wildcard.european_haircut` and `_build_preset`, `projections.attach_wildcard_signals(df, gw_start, match_df=, status_path=)`, `recommender.prepare_market` and `hot_by_position`, `ft_tracker.derive_free_transfers(events, chips, next_event_id)`, `injury_prior.COLUMNS`.
- Produces:
  - `season_replay.project_as_of(target_gw, horizon, inputs, overrides=None) -> pd.DataFrame`: the body of today's `scripts.backtest_live_season.project_gw`, unchanged in behaviour (`inputs` keys `bootstrap, fixtures, history_df, match_df, snapshots_df`; `proj.attrs["dropped_ids"]`).
  - `monitor_replay.permanent_squad_before(gw, picks_by_gw: dict[int, list[int]], chips: list[dict]) -> list[int] | None`: the fifteen he held going into `gw` = picks of `gw-1`, or of `gw-2` when `gw-1` was a Free Hit week; `None` for `gw <= 1` or when the needed picks are missing.
  - `entry_state_before(gw, picks_by_gw, history: dict) -> dict | None`: `{"squad_ids", "bank_m", "value_m", "free_transfers"}`; bank and value from the `history["current"]` row of `gw-1` (tenths → millions); free transfers from `derive_free_transfers(history["current"], history["chips"], gw)`.
  - `write_status_history_as_of(snapshots_df, season, gw, path) -> int`: writes a status CSV in `injury_prior.COLUMNS` format built only from snapshot rows with gameweek `< gw` (snapshot `status`, `chance`); returns rows written.
  - `replay_transfer_plan(gw, state, inputs) -> dict`: `{"available": True, "moves": [{"sell_id", "buy_id"}], "action": "move" | "roll", "plan": <plan_transfers result>, "dropped_squad_ids": [...]}` or `{"available": False, "reason": str}`.
  - `replay_wildcard_squads(gw, budget_m, inputs, status_path) -> dict`: `{"available": True, "presets": {"aggressive": [15 ids], "balanced": [...], "gems": [...]}, "notes": [str]}` or unavailable with reason; a preset whose build fails maps to `None`.
  - `replay_buy_targets(gw, inputs) -> dict`: `{"available": True, "player_ids": [...]}`, top `MONITOR_BUY_LIST_PER_POSITION` of each of `MONITOR_BUY_LIST_POSITIONS`.
  - `parity(proj, snapshots_df, gw, code_version) -> dict`: `{"status": "pass" | "fail" | "no_same_version_baseline", "mae", "corr", "n"}`.

**Rules the implementer cannot infer:**
- Transfer plan call mirrors production (`api/main.py`, the `transfer_planner.plan_transfers(` call): `gws = [gw, gw+1, gw+2]` (`MONITOR_ADVICE_HORIZON_GWS`), `itb_m=state["bank_m"]`, `start_ft=state["free_transfers"]`, `ft_cap=5`, `allow_hits=config.TRANSFER_PLAN_ALLOW_HITS`, `max_moves_per_gw=config.TRANSFER_PLAN_MAX_MOVES_PER_GW`, `min_gain=transfer_planner.scaled_min_gain(3)`, `prioritize_injured=True`, and `opponents_by_gw` built from the as-of fixtures the same way production builds it (team short name ↔ team short name per gameweek). The advised moves are those of the plan row whose `gw` equals the target gameweek.
- Wildcard: project with `horizon = config.CHIP_WILDCARD_DEFAULT_HORIZON_GWS`; `scoring = attach_wildcard_signals(european_haircut(proj, gws, bootstrap), gw_start=gw, match_df=<match history capped below gw>, status_path=<as-of status CSV>)`; then `_build_preset(scoring, gw, horizon, budget_m, name)` for each name in `CHIP_WILDCARD_PRESET_ORDER`. `budget_m = state["value_m"]`. Do not call `preset_squad_ids` or `_scoring_frame`: they read live files. Notes always include "injury prior rebuilt from stored snapshot statuses" and "European haircut uses the calendar file as shipped".
- Buy targets: `prepare_market(proj, score_col="xpts_horizon", horizon_gws=3)` then `hot_by_position(el, owned_ids=[], n=MONITOR_BUY_LIST_PER_POSITION)`.
- Parity compares only when the snapshot rows for `gw` carry `model_version == code_version`; otherwise `no_same_version_baseline` with `mae`/`corr` `None`. Pass = `mae <= MONITOR_PARITY_MAX_MEAN_ABS_DIFF and corr >= MONITOR_PARITY_MIN_CORR`.
- Every `replay_*` catches engine exceptions and returns unavailable with the exception text; it never raises to the caller.
- Squad players absent from the as-of projection frame (`proj.attrs["dropped_ids"]`) go in `dropped_squad_ids`; the plan still runs on the rest.

- [ ] **Step 1: Write the failing tests.**

```python
def test_squad_before_gw8_is_the_gw6_squad_because_gw7_was_a_free_hit():
    picks = {6: list(range(1, 16)), 7: list(range(101, 116))}
    chips = [{"name": "bboost", "event": 1}, {"name": "freehit", "event": 7}]
    assert monitor_replay.permanent_squad_before(8, picks, chips) == list(range(1, 16))
    assert monitor_replay.permanent_squad_before(7, picks, chips) == list(range(1, 16))
    assert monitor_replay.permanent_squad_before(1, picks, chips) is None
    assert monitor_replay.permanent_squad_before(6, picks, chips) is None   # GW5 picks missing

def test_entry_state_reads_bank_value_and_free_transfers_from_history():
    history = {"current": [{"event": 1, "bank": 5, "value": 1000, "event_transfers": 0},
                           {"event": 2, "bank": 12, "value": 1004, "event_transfers": 0}], "chips": []}
    s = monitor_replay.entry_state_before(3, {2: list(range(1, 16))}, history)
    assert (s["bank_m"], s["value_m"], s["free_transfers"]) == (1.2, 100.4, 2)

def test_as_of_status_history_has_no_row_from_the_target_gameweek_or_later(tmp_path):
    snaps = pd.DataFrame({"gw": [5, 6, 7], "player_id": [1, 1, 1], "status": ["a", "i", "a"], "chance": [None, 0, None]})
    n = monitor_replay.write_status_history_as_of(snaps, "2026-27", 7, tmp_path / "s.csv")
    out = pd.read_csv(tmp_path / "s.csv")
    assert n == 2 and out.event.max() == 6 and list(out.columns) == list(injury_prior.COLUMNS)

def test_transfer_plan_is_called_with_production_arguments(monkeypatch):
    # patch season_replay.project_as_of to return a small frame and transfer_planner.plan_transfers to record kwargs
    ...assert seen["gws"] == [9, 10, 11] and seen["allow_hits"] is config.TRANSFER_PLAN_ALLOW_HITS
    assert seen["start_ft"] == 2 and seen["itb_m"] == 1.2 and seen["prioritize_injured"] is True

def test_engine_error_becomes_unavailable_with_a_reason(monkeypatch):
    monkeypatch.setattr(season_replay, "project_as_of", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    out = monitor_replay.replay_transfer_plan(9, STATE, INPUTS)
    assert out == {"available": False, "reason": "ValueError: boom"}

def test_a_squad_player_missing_from_the_snapshot_is_named(monkeypatch):
    ...assert out["dropped_squad_ids"] == [423]

def test_parity_needs_a_same_version_row():
    snaps = pd.DataFrame({"gw": [9], "player_id": [1], "model_xpts": [4.0], "model_version": ["old"]})
    proj = pd.DataFrame({"id": [1], "xpts_gw9": [4.0]})
    assert monitor_replay.parity(proj, snaps, 9, "new")["status"] == "no_same_version_baseline"

def test_replay_modules_do_not_read_the_knowledge_files():
    for path in ("src/monitor_replay.py", "src/season_replay.py"):
        assert "player_knowledge" not in pathlib.Path(path).read_text()
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Move `project_gw` into `season_replay.project_as_of`**, keep `scripts.backtest_live_season.project_gw` as a call to it. Run `pytest tests/test_backtest_live_season.py tests/test_season_replay.py -q`: expect PASS, unchanged.
- [ ] **Step 4: Implement `src/monitor_replay.py`.**
- [ ] **Step 5: Run** `pytest tests/test_monitor_replay.py tests/test_player_knowledge_in_recommendations.py tests/test_backtest_live_season.py -q`, expect PASS.
- [ ] **Step 6: Commit** `feat(monitor): replay transfer plan, wildcard squads and buy targets as of a past gameweek`

---

### Task 7: The gameweek report (contract for the page)

**Files:**
- Create: `src/monitor_gw_report.py`
- Test: `tests/test_monitor_gw_report.py`

**Interfaces:**
- Consumes: everything produced by Tasks 2–6.
- Produces: `build_gw_report(gw: int, entry_id: int, data: dict) -> dict`. `data` keys, all plain Python or DataFrames, no network:
  `season`, `last_finished_gw`, `next_gw`, `snapshots_by_gw` (gameweek → DataFrame of that gameweek's snapshot rows), `points_by_gw`, `expert` (dict keyed `(gw, series)` → matched `expert_picks` row), `actuals_by_gw` (gameweek → `entry_gw_actuals` row for this entry), `advice` (dict keyed `(gw, kind)` → `advice_snapshots` row, `live` preferred over `replay`), `parity` (gameweek → parity dict), `code_version`.

**Report shape** (every key always present; a part that cannot be built is `{"available": false, "reason": "..."}`):

```json
{
  "season": "2026-27", "gw": 9, "entry_id": 107342,
  "state": "finished",
  "players": {"411": {"name": "Haaland", "club": "MCI", "pos": "FWD", "price_m": 15.8, "xpts": 7.07, "points": 2, "minutes": 90}},
  "app_xi":   {"available": true, "ids": [], "captain_id": 411, "vice_id": 0, "projected": 60.0, "price_m": 0.0,
               "points_no_captain": 70, "points_with_captain": 72, "model_version": null},
  "scout_xi": {"available": true, "url": "", "published_at": "", "ids": [], "unmatched": [], "captain_id": null, "vice_id": null,
               "captain_stated": false, "captain_inferred_id": 411, "price_m": 0.0,
               "points_no_captain": 69, "points_with_captain": 71, "needs_review": false},
  "you":      {"available": true, "ids": [], "xi_ids": [], "bench_ids": [], "captain_id": 411, "vice_id": 154, "chip": null,
               "points": 64, "points_on_bench": 22, "transfer_cost": 0},
  "best_xi":  {"available": true, "ids": [], "points": 115},
  "headline": {"basis": "no_captain", "app": 70, "scout": 69, "you": 64, "best": 115},
  "captain":  {"app_for_you": {"id": 0, "points": 0}, "scout": {"id": 411, "points": 2, "stated": false},
               "you": {"id": 411, "points": 2}, "best_in_squad": {"id": 112, "points": 15}, "best_overall": {"id": 112, "points": 15}},
  "transfers": {"chip_week": false, "verdict_window": 3, "verdict": null,
                "app": {"available": true, "origin": "replay", "action": "move", "moves": [], "windows": {}},
                "you": {"moves": [{"sell_id": 418, "buy_id": 112}], "hits": 0, "windows": {}}},
  "buy_lists": {"app": {"available": true, "origin": "replay", "players": [], "avg": {}, "avg_per_m": {}},
                "scout": {"available": true, "url": "", "players": [], "unmatched": [], "avg": {}, "avg_per_m": {}}},
  "wildcard":  {"window": 5, "kept": {"ids": [], "points": 0, "played": 1, "complete": false},
                "app": {"available": true, "origin": "replay", "headline_preset": "balanced", "presets": {}},
                "scout": {"available": false, "reason": "no Scout wildcard squad this gameweek"},
                "actual": {"points": 64, "played": 1}},
  "replay": {"parity": {"status": "no_same_version_baseline", "mae": null, "corr": null, "n": 0},
             "dropped_squad_ids": [], "notes": []}
}
```

**Rules:**
- `state`: `before_deadline` when `gw >= next_gw`, `finished` when `gw <= last_finished_gw`, else `live`. Before the deadline every points field is `null` and the picks are still present.
- `headline.basis` is `with_captain` only when the Scout article states a captain; then `app`/`scout` are the with-captain totals. `you` is always his real score; `best` never has a captain.
- `players` holds every player id referenced anywhere in the report, once.
- `app_xi` for a gameweek with no snapshot rows: `{"available": false, "reason": "no pre-deadline snapshot"}`.
- `scout_xi` with unmatched names: still available, `needs_review: true`, totals computed on the matched players, `unmatched` lists the raw names.
- GW1 has no Scout eleven: `scout_xi` is `{"available": false, "reason": "season squad, not an eleven"}`. The GW1 season squad and the wildcard squads feed `wildcard.scout` (ids, points over the window, `needs_review`), and only when their override is owner-confirmed; otherwise `wildcard.scout` is unavailable with reason "squad article needs review".
- `transfers.chip_week` true → `app` and `you` carry `{"available": false, "reason": "chip week"}` and `verdict` is `null`.
- `wildcard.kept.ids`: his real fifteen for the gameweek; in a Free Hit week, `permanent_squad_before(gw)`.
- `captain.app_for_you`: `monitor_xi.app_captain` over his starting eleven with that gameweek's stored projection.

- [ ] **Step 1: Write the failing tests.** `build(gw, **changes)` is a test helper: it assembles `data` from the Task 4 GW9 fixture for gameweek 9 and from small hand-built frames for the other gameweeks (GW6 and GW7 picks with a `freehit` chip in GW7; no snapshot rows for GW1).

```python
def test_gw9_headline_is_70_69_64_115_without_captain():
    r = build(9)
    assert r["headline"] == {"basis": "no_captain", "app": r["app_xi"]["points_no_captain"], "scout": 69, "you": 64, "best": 115}
    assert r["scout_xi"]["points_with_captain"] == 71 and r["you"]["points_on_bench"] == 22
    assert r["transfers"]["you"]["windows"]["1"]["gain"] == 15

def test_gw1_has_no_app_column_but_still_has_the_owner():
    r = build(1)
    assert r["app_xi"] == {"available": False, "reason": "no pre-deadline snapshot"}
    assert r["you"]["available"] is True and r["transfers"]["app"]["available"] is False

def test_before_the_deadline_picks_show_and_points_are_null():
    r = build(10, last_finished_gw=9, next_gw=10)
    assert r["state"] == "before_deadline" and r["scout_xi"]["ids"] and r["scout_xi"]["points_no_captain"] is None

def test_free_hit_week_has_no_transfer_line_and_keeps_the_permanent_squad():
    r = build(7)
    assert r["transfers"]["chip_week"] is True and r["transfers"]["verdict"] is None
    assert r["wildcard"]["kept"]["ids"] == GW6_PICKS

def test_an_unmatched_scout_name_is_listed_and_flagged():
    r = build(9, scout_unmatched=[{"name_raw": "New Signing", "club_raw": "Chelsea"}])
    assert r["scout_xi"]["needs_review"] is True and r["scout_xi"]["unmatched"][0]["name_raw"] == "New Signing"

def test_unavailable_replay_does_not_break_the_report():
    r = build(9, advice={})
    assert r["transfers"]["app"]["available"] is False and r["headline"]["scout"] == 69

def test_every_player_referenced_is_in_players():
    r = build(9); ids = collect_ids(r)
    assert ids <= {int(k) for k in r["players"]}

def test_report_is_json_serialisable():
    json.dumps(build(9))
```

- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement.** **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(monitor): gameweek report assembly`

---

### Task 8: I/O shell and workflow

**Files:**
- Create: `scripts/monitor_backfill.py`, `.github/workflows/monitor-backfill.yml`
- Test: `tests/test_monitor_backfill.py`

**Interfaces:**
- Produces (pure row builders, tested; network functions thin and untested, same split as `scripts/snapshot_to_db.py`):
  - `expert_rows(parsed_articles, players_by_gw, teams, overrides, season, now_iso) -> list[dict]` (runs `scout_names.match_player`, fills `captain_player_id`, `vice_player_id`, `captain_inferred_player_id`, `unmatched`, `needs_review`).
  - `actuals_row(entry_id, season, gw, picks_payload, transfers, history, now_iso) -> dict` (`points` = `entry_history.points`; `transfers` filtered to `event == gw`; `chip` = `active_chip`).
  - `advice_rows(entry_id, season, gw, plan, wildcard, buy_targets, code_version, now_iso) -> list[dict]` (always `origin = "replay"`; `buy_targets` rows use `entry_id = 0`).
  - `report_row(report, now_iso, code_version) -> dict`.
  - `parse_gws("1-10") -> [1..10]`; `parse_gws("3,5") -> [3, 5]`.
  - CLI: `python scripts/monitor_backfill.py --gws 1-10 --entries 107342,5645321 [--out-dir DIR] [--snapshots-csv FILE] [--skip-replay]`.
- Behaviour:
  - With `--out-dir`, nothing is written to Supabase: rows and reports are written as JSON files under `DIR` (dry run). With `--snapshots-csv`, snapshots come from that file instead of Supabase (so a dry run needs no service key).
  - Without `--out-dir`: upsert to the four tables through PostgREST with the service key (`on_conflict` = each table's primary key), reading snapshots with an explicit `limit` and paging.
  - First action: list the feed; if the listing fails or returns no article for the season, print one clear line saying the Scout feed is unreachable from this machine, continue without Scout rows, and exit non-zero at the end.
  - Local engine data: call `scripts.shadow_snapshot.refresh_local_data()` before any replay.
  - `advice_snapshots` rows with `origin = "live"` are never written or deleted by this script.
  - One failing gameweek or entry is logged and skipped; the run continues and exits non-zero at the end if anything failed.
  - Never prints the service key or any header containing it.
- Workflow: `workflow_dispatch` with inputs `gws` (default `1-10`) and `entries` (default `107342,5645321`); Python 3.11; `pip install -r requirements.txt`; env `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` from secrets; `PYTHONPATH=. python scripts/monitor_backfill.py --gws "$GWS" --entries "$ENTRIES"` with the inputs passed through `env:`, never interpolated into the shell line; `timeout-minutes: 45`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_actuals_row_uses_the_real_score_not_a_sum_of_picks():
    picks = {"active_chip": None, "entry_history": {"points": 64, "points_on_bench": 22, "event_transfers_cost": 0, "bank": 3, "value": 1012},
             "picks": [{"element": 411, "position": 10, "multiplier": 2, "is_captain": True, "is_vice_captain": False}]}
    row = mb.actuals_row(107342, "2026-27", 9, picks, [{"event": 9, "element_in": 112, "element_out": 418},
                                                         {"event": 8, "element_in": 154, "element_out": 12}], {}, "t")
    assert (row["points"], row["points_on_bench"], row["bank_m"], row["value_m"]) == (64, 22, 0.3, 101.2)
    assert row["transfers"] == [{"sell_id": 418, "buy_id": 112}]

def test_advice_rows_are_always_replay_and_buy_targets_have_entry_zero():
    rows = mb.advice_rows(107342, "2026-27", 9, PLAN, WC, BUY, "v", "t")
    assert {r["origin"] for r in rows} == {"replay"}
    assert [r["entry_id"] for r in rows if r["kind"] == "buy_targets"] == [0]

def test_expert_row_flags_an_unmatched_name():
    rows = mb.expert_rows([PARSED_GW9_WITH_STRANGER], PLAYERS_BY_GW, TEAMS, {}, "2026-27", "t")
    assert rows[0]["needs_review"] is True and rows[0]["unmatched"] == [{"name_raw": "New Signing", "club_raw": "Chelsea"}]

def test_parse_gws():
    assert mb.parse_gws("1-10") == list(range(1, 11)) and mb.parse_gws("3,5") == [3, 5]

def test_workflow_passes_inputs_through_env_not_the_shell_line():
    wf = pathlib.Path(".github/workflows/monitor-backfill.yml").read_text()
    run_lines = [l for l in wf.splitlines() if "monitor_backfill.py" in l]
    assert run_lines and all("${{" not in l for l in run_lines)

def test_script_never_prints_the_service_key():
    src = pathlib.Path("scripts/monitor_backfill.py").read_text()
    assert "print(sb_key" not in src and "SUPABASE_SERVICE_KEY\"])" not in src.replace("os.environ[\"SUPABASE_SERVICE_KEY\"]", "")
```

- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement.** **Step 4: Run** `pytest tests/test_monitor_backfill.py -q` and `python -m compileall -q api src scripts`, expect PASS.
- [ ] **Step 5: Commit** `feat(monitor): backfill script and manual workflow`

---

### Task 9: Dry run on real data, squads that need the owner, docs, pull request

**Files:**
- Modify: `data/monitoring/scout_overrides.json`, `CLAUDE.md` (new section "Monitoring dashboard data (2026-11)"), `docs/superpowers/specs/2026-11-05-monitoring-dashboard-design.md` only if a fact in it proved wrong
- Create: `docs/monitoring/2026-11-backfill-check.md` (what the dry run produced)

- [ ] **Step 1: Export snapshots for the dry run.** `select * from public.player_gw_snapshots where season = '2026-27' order by gw, player_id` → `data/replay/snapshots_2026-27.csv` (untracked; the existing replay uses the same export).
- [ ] **Step 2: Dry run.** `PYTHONPATH=. python scripts/monitor_backfill.py --gws 1-10 --entries 107342,5645321 --snapshots-csv data/replay/snapshots_2026-27.csv --out-dir /tmp/monitor-dryrun`. Expected: exit 0 or a listed set of failures; one report file per gameweek and entry.
- [ ] **Step 3: Check the output against known facts** and record each in `docs/monitoring/2026-11-backfill-check.md`:
  - GW9, entry 107342: headline scout 69, you 64, best 115; `transfers.you.windows["1"].gain == 15`.
  - Owner's real scores GW1–GW9: 56, 84, 49, 90, 42, 75, 76, 32, 64.
  - GW1: `app_xi.available == false`. GW7: `transfers.chip_week == true`.
  - Scout Selection rows for GW2–GW10 each have 11 players; list every `needs_review` row and every unmatched name.
  - Transfer radar rows for GW1–GW10 exist; list any gameweek missing.
  - Parity status per gameweek.
  - For every replayed gameweek: the advised move, and whether any squad player was dropped.
- [ ] **Step 4: Fix what the check exposes** (name overrides in `scout_overrides.json` under `"names"`, title patterns, parsing), re-run until the check is clean or each remaining gap is explained in the check file.
- [ ] **Step 5: Propose the five prose squads.** For articles 4681112 (GW1), 4698173 (GW2), 4705463 (GW3), 4712921 (GW4), 4726681 (GW6): read the article text, write the fifteen names with clubs into `scout_overrides.json` under `"articles"` with `"confirmed_by_owner": false`, and list them in the check file. **Stop and ask the owner to confirm each list**; set `true` only for the ones he confirms. Unconfirmed squads stay `needs_review` and are not scored.
- [ ] **Step 6: Full test suite.** `pytest tests/ -q`: expect all passing, no test removed.
- [ ] **Step 7: CLAUDE.md section**: the four tables, the feed and its tags, the replay rules (knowledge off, as-of status history, no HTTP routes), how to run the dry run and the workflow, and that `src/monitoring.py` is a different thing.
- [ ] **Step 8: Security review** of the branch diff (service key handling, workflow input handling, row-level security policies, no new routes). Findings and rulings go in the PR body.
- [ ] **Step 9: Commit, push, open the pull request.** PR body: what it does, the check file's headline results, "Before merging: apply `supabase/migrations/20261106_monitoring_tables.sql`, then insert your user id into `monitor_owners`", "After merging: run the Monitor backfill workflow once", the security findings.
- [ ] **Step 10 (after the owner merges and runs the workflow): verify in the database.**

```sql
select gw, entry_id, report->'headline' as headline, report->>'state' as state
from public.monitor_reports where season = '2026-27' order by entry_id, gw;
```

  Expected: 20 rows (10 gameweeks × 2 entries); entry 107342 GW9 headline `{"basis":"no_captain","app":<n>,"scout":69,"you":64,"best":115}`. Then delete `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/monitoring/` (the hand-saved GW10 files; the feed supplies the same articles).

---

## Out of this plan

- The page (plan 2) and saving advice before each deadline, including the list-adjusted number and badge from GW11 (plan 3).
- The `chip_plan_snapshots.actual_points` hotfix.
- Reading prose squad articles automatically.
