# Monitoring dashboard: app vs The Scout vs reality

Design, 2026-11-05. Brainstormed with the owner (Ziad). Sections marked **(owner)** are his decisions; sections marked **(designer's call)** are mine and open to challenge.

## 1. Intent

The owner wants actual points to be the referee. Before each deadline the app proposes things (a best team, transfers, a captain, wildcard squads) and the official FPL Scout publishes its own picks. After the gameweek, he wants to see, side by side, what the app proposed, what the Scout proposed, what he actually did, and what really happened, for every gameweek of the season, so he can learn where the engine is wrong and when to trust it over the experts.

Today none of that exists as something he can open. The only monitoring is a terminal report of per-player projection error (`scripts/monitor_report.py`, shipped in PR #76).

**Why now:** the engine changed a lot in October (wildcard v2, calibration, netting, availability, XI floor; PRs #75–#78, #81, all merged). The owner has no way to see whether those changes help.

## 2. Who it is for **(owner)**

- The owner only. It is a personal tool first; proof for customers may come later and is not part of this work.
- It lives in the live app (opens from any browser or phone, fills itself after each gameweek), visible only to the owner's login. Other users must not see the page or its data.
- Default entry is his: **107342** ("ZN Analytics"). A second tracked entry, **5645321** ("Nader z"), is selectable.

## 3. Goals, non-goals, anti-goals

**Goals**
1. One page per gameweek showing app vs Scout vs the owner's team vs the best possible, player by player.
2. Transfers, captain and wildcard advice scored against real points over the following gameweeks.
3. A season view with running totals.
4. **Full history from GW1 to GW10 first (owner's top priority)**, then every gameweek automatically.
5. From now on, the app's advice is saved before each deadline, so later scoring uses what was actually shown.

**Non-goals**
- No customer-facing page, no marketing claims, no polish beyond the app's existing look.
- No expert sources other than The Scout on premierleague.com in this version.
- No change to the engine, to recommendations, or to anything the app advises. This work only observes.
- No fix for the premium-midfielder bias or any other finding the dashboard surfaces.

**Anti-goals (would make it a failure even if it works)**
- Any future information leaking into a replayed past gameweek. A replayed GW6 must use only what was knowable before the GW6 deadline.
- Numbers that flatter the app: silent re-picks, hindsight line-ups presented as advice, missing weeks dropped from totals.
- An invented value where data is missing. Missing is shown as missing.
- The page or its data reachable by any user other than the owner.
- Rewriting history: a stored pre-deadline record changed after the deadline.

## 4. What the owner sees **(owner, from mockups)**

Mockups are kept in `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/.superpowers/brainstorm/66359-1793911985/content/` (`pitch-colours.html`, option 2, is the chosen look; `landing-view.html` layout B is the season tab).

**Look:** the same visual language as the app (pitch, jerseys, player cards, gameweek bar, dark and light themes). Reuse the existing components (`PitchVisualization`/`DraftPitch`, `PlayerCard`, `JerseyIcon`, `GameweekNav`) where they fit.

**Gameweek tab (opens first, on the latest gameweek)**
- Gameweek bar with previous/next, state (before deadline / live / finished), and four score chips: App XI, Scout, You, Best possible.
- **Three pitches side by side, each in its own colour**, including the pitch surface itself: **App = pink** (the brand colour), **Scout = orange**, **You = blue**. On a phone they stack.
  - App best XI
  - Scout Selection
  - Your team, with the bench strip underneath
- Each player card shows points scored (captain doubled), then the app's pre-deadline projection in grey. A pink outline marks players that are also in the app's XI. A player who did not play is faded.
- A slim strip under the pitches: best possible XI in hindsight, with its total.
- Three cards underneath: **Transfers**, **Captain**, **Wildcard draft** (section 5).
- Before a deadline, the same page shows the picks with no points yet.

**Season tab**
- One row per gameweek: App XI, Scout Selection, Your team, Best possible, and who came closer. Running totals. Clicking a row opens that gameweek.
- Side cards: transfers record, captain record, wildcard verdicts, projection error (reuse `src/monitoring.py`).

## 5. What is compared, and how it is scored

Points always mean official FPL points for that gameweek. Sections 5.1–5.5 were agreed with the owner in substance; the exact rules below are **designer's calls** unless marked.

### 5.1 Best-XI contest (app vs Scout vs you vs best possible)
- **App best XI:** the eleven with the highest summed pre-deadline projection for that gameweek, taken from the stored `player_gw_snapshots.model_xpts` (no replay). Legal formation (1 GKP, 3–5 DEF, 2–5 MID, 1–3 FWD), at most 3 per club, no budget cap. Captain and vice by the product's own captain rule (`captain_advisor.recommend_captain`, which is not simply the highest projection), so the page tests the rule the app really uses.
- **What `model_xpts` is, exactly:** the engine's number with the team-level knowledge discount, **without** the owner's hand-entered player notes (`build_model_snapshot` uses `get_projections_cached`, which skips `player_knowledge.apply`). The advice he sees on screen does include those notes. See 5.7. Solve it exactly; a greedy pick is not acceptable (the last slot in GW9 was decided by 0.002 projected points and swung 8 real points).
- **Scout Selection:** the eleven as published, captain and vice as named.
- **Your team:** the real picks and the real score from FPL (`entry_history.points`, autosubs and captain included). Transfer hits shown separately.
- **Best possible:** the legal eleven with the most real points, no captain. A hindsight ceiling, never called advice.
- **Scoring for App and Scout:** sum of real points, captain counted twice; if the captain played 0 minutes the vice is doubled. No bench, so a player who did not play scores 0.
- **A week where the Scout states no captain** (GW9): the headline comparison is **without captain on both sides**. The with-captain figure is shown as a secondary line only when the article points at one player, stored as `captain_inferred`, never as stated.
- Each side's total price is shown; the Scout states no budget rule (GW10's eleven cost £82.4m).

Verified sample, GW9 (hand-computed during the brainstorm, use as a test fixture). Headline, no captain (the Scout named none): **App XI 70** (Raya 5; Gabriel 6, Silva 8, Van Hecke 15; Tavernier 3, Neto 3, Rudoni 9, Rogers 9, Mbeumo 1; Haaland 2, Evanilson 9), **Scout 69** (Suzuki 1; Mukiele 0, Silva 8, Van Hecke 15; Palmer 8, Rogers 9, Kudus 7, Tavernier 3, Manzambi 7; Haaland 2, N.Jackson 9). Secondary, Haaland captain on both (inferred for the Scout): 72 and 71; these are the figures the owner saw in the mockups. Owner 64, bench 22. Best possible 115. The hand-built app XI used a greedy 3-per-club rule; the exact solver may differ, in which case the solver wins and the fixture is updated.

### 5.2 Captain
Four lines, one gameweek each, raw (undoubled) points of the pick: the app's pick for the owner's squad (`captain_advisor.recommend_captain` over his starting eleven with the stored projections), the Scout's captain, the owner's captain, and the best in hindsight (in his squad, and overall).

### 5.3 Transfers, contest 1: the owner's squad **(owner: three lines)**
For each gameweek, three lines:
1. **What the app advised** for his squad: the headline plan's first-gameweek moves from `transfer_planner.plan_transfers` (which may be "roll, no move").
2. **What he did:** his real transfers from FPL.
3. **Doing nothing:** zero.

Every move is scored the same way: points of the player bought minus points of the player sold, summed over the following gameweeks, starting with the gameweek the move was made for. Raw points, whether or not the player would have started (known simplification, stated on the card). A hit costs 4.

The app's advice each week starts from his **real** squad that week, not from the app's own earlier advice. It is a one-step-ahead test.

Chip weeks: a wildcard or Free Hit week has no transfer line (GW7 was his Free Hit, with eight "transfers"); it is labelled as a chip week.

### 5.4 Transfers, contest 2: who to buy, in general **(owner: separate contest)**
The Scout's transfer radar does not know his squad, so it cannot enter contest 1. It is compared with the app's own target list:
- **Scout list:** the players tipped in that gameweek's transfer radar.
- **App list (designer's call):** `recommender.prepare_market` then `recommender.hot_by_position` with no owned players, keeping the top 2 each of DEF, MID, FWD (the function's default is 5 per position).
- **Metric:** average real points per listed player over the window, shown next to each player's own total and price. Points per £m is shown alongside, because the app's list will lean premium and the Scout's will lean cheap.
- Each Scout tip also shows what the app projected for that player at the time.

### 5.5 Wildcard **(owner accepted the proposal; he has no firm view yet)**
For each gameweek, the app's wildcard draft (the Balanced preset is the headline; the other two presets are recorded and shown smaller) against the squad he kept:
- "The squad he kept" = his real fifteen for that gameweek, after the transfers he made. In a Free Hit week it is his permanent squad (the picks from the gameweek before), and the card is labelled as a chip week.
- Both squads are frozen for the window (no further transfers on either side).
- Each gameweek in the window, each squad fields the eleven and captain that the app's stored pre-deadline projections for that gameweek would pick (legal formation). Same rule for both, no hindsight.
- Score = real points of those elevens over **five** gameweeks. A third line shows what he actually scored over the same weeks.
- When The Scout publishes a wildcard squad, it is scored the same way as a third squad.

### 5.6 Windows **(owner agreed)**
Transfers and buy lists show gain after 1, 3 and 5 gameweeks; **3 is the verdict**. Wildcard uses 5. A window that is not finished shows its partial total and "n of w gameweeks played"; it gives no verdict.

### 5.7 Engine alone, with a badge for the owner's manual player list **(owner, 2026-11-05)**
The stored projections are engine-only (5.1). So the App XI and the grey number on each card can include a player the owner's own notes had ruled out that week, which the on-screen advice would not have recommended.
- GW2–GW10 can only be engine-only: the notes as they stood each week were never saved.
- **Decided:** the scored number is engine-only all season (comparable week to week, and it tests the engine rather than his own manual list). From GW11, also save the list-adjusted number, and put a badge on any player card where the manual list had ruled the player out or discounted him (for example "your list said: out until GW13"), so he can see at once when an App XI pick was the raw engine and not what the app told him on screen. This needs one extra stored value per player per gameweek.

## 6. What exists today (checked 2026-11-05)

| Thing | State |
|---|---|
| `player_gw_snapshots` (Supabase `tetvymwgpaordnmsnneo`) | Pre-deadline `model_xpts`, price, status, ownership for every player, GW2–GW10; real points and minutes for GW2–GW9. Twice-daily job `snapshot-db.yml` (09:00 and 16:00 UTC). `model_version`, `shadow_xpts`, `runner_xpts` columns exist since tonight. **No GW1 rows.** |
| `chip_plan_snapshots` | Chip advice per tracked entry and gameweek. Its `actual_points` is wrong (sums all fifteen picks, no captain, bench included: stored 73/37/84 for GW7/8/9, real 76/32/64). Do not use that column. Fixing it is a separate hotfix, out of scope. |
| Live-season replay | `src/season_replay.py` + `scripts/backtest_live_season.py` rebuild engine inputs as of a past gameweek from the stored snapshot row and capped history. The as-of inputs come from `src/season_replay.py`; the per-gameweek loader patching lives in `scripts/backtest_live_season.project_gw` and should move into `src/` to be reused here. Parity was 0.026 mean difference at GW8 when measured against the model of that day; that figure is stale now that the price pull changed (see the parity note in `docs/calibration/2026-10-26-live-replay.md`). Needs a snapshot row, so it cannot do GW1. |
| Per-player error report | `src/monitoring.py`, `scripts/monitor_report.py`. |
| Old replay page | `/replay` route (frontend `Replay.tsx`, backend `api/replay_router.py`, `src/replay_builder.py`): last season only, static files, laptop only (`import.meta.env.DEV`). Pure helpers are reusable (`replay_builder.optimal_captain`, `replay_snapshot.derive_transfers`); the page itself is superseded, not extended. |
| Transfer, wildcard, captain advice | **Not stored anywhere.** `build_recommendations` and `build_wildcard_drafts` compute on request. |
| Scout articles | **Available as structured data** from the Premier League's public content feed, no login: `https://api.premierleague.com/content/premierleague/text/en/?tagNames=<tag>&pageSize=30&page=N` lists articles (id, title, date, tags); `.../text/en/<id>` returns one article with its `body` HTML, where each player is an `<h5>` heading in the form `Name (Club) £X.Xm`. Tags, checked 2026-11-05: `franchise:fpl-scout-picks` returns Scout Selection for GW2–GW10, the GW1 season-start squad, and four Scout wildcard squads (GW2, GW3, GW4, GW6); `franchise:transfer-radar` returns the radar for GW1 and GW3–GW10 (GW2's radar is tagged under scout-picks); `content-creator:The-Scout` covers all of them. Page size is capped at 30. GW9 names no captain (text implies Haaland); GW10 names captain and vice. Not yet checked from a GitHub runner. |
| GW10 Scout picks | Already extracted by hand: `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/monitoring/2026-27/gw10/scout_selection.json` and `transfer_radar.json`. They become the first rows; delete the folder once loaded. |
| Owner's history | Public FPL API: `/entry/{id}/history/`, `/entry/{id}/event/{gw}/picks/`, `/entry/{id}/transfers/`. Chips so far: Bench Boost GW1, Free Hit GW7. |
| Auth | Backend verifies Supabase JWTs (`src/auth.py`, `require_user`, admin routes by static key). The backend holds **no** Supabase service key. The frontend already reads one table directly under row-level security (`gw_plans`). |

## 7. How it gets made **(designer's calls)**

### 7.1 Shape
Compute off the API, read straight from the database.

1. **Jobs on the GitHub runner** (same pattern as `shadow_snapshot.py`: install requirements, refresh FPL data on the runner, write with the service key) collect inputs and build one finished report per gameweek and entry.
2. **Reports are stored in Supabase** and the page reads them directly with the owner's own session, protected by row-level security.
3. **No new user-facing routes on the production API** and no service key on Fly. The replay is heavy and has no business on the request path. The one exception is forward capture (7.4b), which needs admin-key read routes in the style of the existing `/admin/chip-plan`.

All scoring is pure Python in `src/` (no network, no FastAPI), unit-tested, called by thin scripts.

### 7.2 Tables (new migration, applied in the Supabase dashboard before the code that writes them merges)
- `expert_picks`: key `(season, gw, source, series)`. `source` = `scout`; `series` = `selection`, `transfer_radar`, `wildcard`. Columns: url, title, published_at, fetched_at, captain and vice player ids, `captain_stated` boolean, `players` jsonb (raw name, raw club, price, resolved `fpl_player_id`, reason, stated horizon), `needs_review` boolean.
- `advice_snapshots`: key `(season, gw, entry_id, kind, origin)`. `kind` = `transfer_plan`, `wildcard_drafts`, `buy_targets` (entry_id 0, squad-independent). `origin` = `live` (saved before the deadline from production) or `replay` (rebuilt later). Columns: model_version, payload jsonb, captured_at. A `live` row is never overwritten after its deadline.
- `entry_gw_actuals`: key `(season, gw, entry_id)`. Picks, transfers, chip, points, points on bench, transfer cost, bank, value.
- `monitor_reports`: key `(season, gw, entry_id)`. The finished report the page renders (section 5 outputs), plus `built_at` and the code version. Rebuilt whenever inputs or scoring rules change; inputs are the source of truth, reports are disposable.
- A season summary is either a second kind of row in `monitor_reports` or computed in the page from the per-gameweek rows; builder's choice.

Row-level security on all four: service role writes; **select only for the owner's user id(s)**, held in a small `monitor_owners` table. No policy for anyone else, so other signed-in users get nothing.

### 7.3 Access
- Database is the real gate (above).
- Frontend: route `/app/monitor` under `ProtectedRoute`. The nav link appears only when a cheap owner check succeeds (for example a select on `monitor_owners` returning his own row). A non-owner who types the URL sees the normal not-found page. No owner id in the client bundle.

### 7.4 Pipelines
**a. Scout extraction.** A script lists the Scout's articles from the public content feed by tag (section 6), picks the ones for each gameweek by title, fetches each by id and parses its `body` deterministically (`<h5>` headings `Name (Club) £X.Xm`; captain and vice from the sentence that names them). No LLM in the first version. Anything that does not parse cleanly is stored with `needs_review = true` and shown on the page as "needs review", never guessed.
- **Name matching:** Scout names are full names with club; FPL uses short names with diacritics ("Djordje Petrovic" vs `Petrović`; a bare "Palmer" also matches an Ipswich goalkeeper). Match on club + name, normalised; ambiguous or missing matches go to `needs_review`. A committed override file maps the stubborn ones.
- **Finding the articles:** automatic, from the tag listings, for the backfill and for every future week. The gameweek comes from the title ("...for Gameweek 10", "Gameweek 10 transfer radar", "GW6 squad for Wildcarders"); an article whose gameweek or series cannot be read from its title is stored as `needs_review`. A small committed override file can pin or correct an article id for a gameweek. The feed is unofficial and could change; if a listing call fails the job says so loudly and the page shows the Scout column as missing for that week. The first build step confirms the feed answers from a GitHub runner.
- **Scout wildcard squads exist this season** (GW2, GW3, GW4, GW6) and feed section 5.5 directly.
- **Formats vary (checked 2026-11-05):** the weekly Scout Selection and the transfer radar use one `<h5>` heading per player and parse by rule. The GW1 season squad and the wildcard squads (GW2, GW3, GW4, GW6) are written as prose under thematic headings, so no rule can read their fifteen. Those five are entered by hand in a committed override file, proposed during the build and **confirmed by the owner** before they count; until confirmed they show as "needs review" and are not scored. Some weeks name no captain. Store what is published. Never invent an eleven or a captain. A week with no stated captain is compared without captain on both sides, and says so.
- Only picks and facts are stored, with a link back; article text is not copied.

**b. Forward capture (before each deadline).** Extend the existing twice-daily job to save, per tracked entry, the headline transfer plan, the three wildcard drafts and the buy-target list, as `origin = live` rows. What is saved must equal what production would show the owner, and that rules out computing on the runner: the player notes, the status history and the runtime knowledge nudges exist only on the Fly volume (stated in the `scripts/shadow_snapshot.py` docstring). So capture goes through **new admin-key read routes** on the production API, same pattern as `/admin/chip-plan`, called by the job. Capture uses the server defaults (3-gameweek horizon, injured-first on, no pins); the owner's browser-only slider settings cannot be read by a job, and the page says "at default settings".

**c. After each gameweek.** Pull the owner's picks, transfers and score from FPL; player points are already filled by the existing actuals leg. Rebuild that gameweek's report and every earlier report whose window it completes.

**d. Backfill, GW1–GW10 (the priority).** One manually triggered run over a gameweek range:
- Scout rows from the index file.
- Owner actuals from FPL.
- App best XI from stored projections (GW2 onward).
- Transfer plans, wildcard drafts and buy targets by **replay**, stored as `origin = replay`.

### 7.5 Replay rules
- Replay goes through `season_replay.build_live_engine_inputs` → projections → `transfer_planner.plan_transfers` / `api/wildcard.preset_squad_ids` / `prepare_market` + `hot_by_position`, called directly. **Not through the HTTP routes or `build_recommendations`**, which read live data.
- Wildcard drafts in replay: `api/wildcard.preset_squad_ids(proj_all, bootstrap, play_event_id, horizon, budget_m, preset_name)` already takes projections as an argument and returns the fifteen a preset drafts; use it (or the `_scoring_frame` / `_build_preset` pair under it), not `build_wildcard_drafts`, which loads live context. Budget = his squad value at *t−1* from `/entry/{id}/history/` (`value` there is selling prices plus bank). **Check before trusting it:** `_scoring_frame` adds trend and injury-prior signals (`projections.attach_wildcard_signals`) and a European-fixture haircut; any of those that read present-day files must be fed as-of data or switched off in replay, and the report must say which.
- Squad before gameweek *t* = his real picks from *t−1*, with the permanent squad restored after a Free Hit week. That rule exists today only inline in `load_fpl_context` (`api/main.py`, "Free hit picks are temporary"); replay needs it as a small pure helper. Bank and squad value from his history at *t−1*. Free transfers from `ft_tracker`.
- The knowledge files (team and player) are **off** in replay: they hold present-day information. The existing test `test_backtest_paths_do_not_apply_present_day_knowledge` (`tests/test_player_knowledge_in_recommendations.py`, parametrised by module path) pins this for other paths; add the new replay modules to it.
- Replay runs **today's engine** on past data. The page labels replayed advice as "rebuilt with today's engine", distinct from "saved before the deadline". This is deliberate: it tests the engine he uses now. From GW11 on, rows are `live`.
- **Injury prior in replay:** the wildcard scorer reads an injury prior from `status_history.csv`, which exists only on the Fly volume and has no as-of cut (`injury_prior.player_injury_prior`). On the runner it would be silently empty; copied over it would leak present-day status. Rebuild it as-of from the `status` column of the stored snapshots, and label the report accordingly.
- **Parity check with every backfill.** PR #76 printed parity but set no pass mark, so this design sets one, in `config.py`, tagged `[untested]`: mean absolute difference ≤ 0.10 points and correlation ≥ 0.99 between replayed projections and the stored `model_xpts`. It applies **only** where the stored row carries the same `model_version` as the code doing the replay (with the team knowledge file in place for that comparison, since stored rows include it). Where no same-version row exists, which is every gameweek before the 2026-10-26 version, the report says "no same-version baseline" and is neither passed nor failed. A failed check marks the report; it does not stop it.

### 7.6 Edge cases to handle explicitly
- **GW1:** no pre-deadline snapshot exists, so there is no app column; the page says "no app data". No transfers exist in GW1. Scout squad, owner's team (Bench Boost week) and real points still show.
- Blank and double gameweeks: a player with no fixture scores 0 that week; a double counts both matches (already how FPL points work).
- Player sold, transferred abroad or removed from the game mid-window: scores what FPL records, 0 if absent.
- GW10 is before its deadline at the time of writing: page shows picks only.
- The second entry (5645321) joined in August; its early weeks may be empty.

## 8. Constraints
- Shared checkout: never switch branches in `FPL/` or the frontend directory; work in worktrees under `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/worktrees/` and `FPL-Assistant-Front/worktrees/`. Pull requests; the owner merges.
- Migrations are applied by hand in the Supabase dashboard **before** merging code that writes new columns or tables (PostgREST rejects unknown columns).
- Every tunable goes in `src/config.py`, tagged; no numbers in logic files.
- Security review on every phase diff before its pull request, findings in the PR body. The service key stays in GitHub secrets; never logged.
- Tests first for the scoring module; GW9 fixture above.
- Frontend deploys to the personal Vercel team (`ziad-naders-projects`) only.
- FPL game terms: this is private, personal use of public data; nothing is published.

## 9. Order of work
1. **Data layer and backfill:** tables, extraction, owner actuals, scoring module, replay, GW1–GW10 reports in the database. Checkable with a query before any page exists.
2. **Page:** gameweek tab, then season tab.
3. **Forward capture** wired into the twice-daily job, in time for GW11's deadline.

GW10's deadline is Friday 6 November, 18:30 GMT. Forward capture will not exist by then; GW10's advice will be `replay`. Its Scout picks are already saved.

## 10. Left to the builder
- Exact solver for the best eleven; table and column names; report JSON shape; how the season summary is stored.
- How much of the existing pitch components can be reused as they are versus thin copies for three-across sizing.

## 11. Out of scope, noted for later
- Hotfix for `chip_plan_snapshots.actual_points` (use `entry_history.points`).
- More expert sources; a public evidence page.
- Starting-eleven-aware transfer scoring.
- Retiring the old `/replay` page once this one covers its ground.
