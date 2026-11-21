# News auto-apply — design

Date: 2026-11-21 · Status: draft for owner approval

## Intent

The news → player-knowledge rail has been dead since February 2026: the local
launchd job (`scripts/com.fpl.refresh-news.plist`) was never loaded, the corpus
(`kb/auto/news`, 85 articles) was last written 20 Feb 2026, and even when it ran,
`POST /squad/digest-news` only returned proposals that needed a manual admin
POST. Net effect: no news ever reached projections this season.

Motivating case (GW11): Konsa was proposed as a transfer while news said Saliba
was back and might take his place. The engine should have discounted Konsa's
minutes on its own.

Owner decision: news changes projections **without owner review**, inside hard
guardrails (option A). A Friday research agent (option C) is wanted later and
must plug into the same rail.

## Goals

1. Scheduled, cloud-run news ingestion; no dependency on the owner's Mac.
2. AI-read news writes minute cuts straight into live projections.
3. Covers displacement: "teammate returns" cuts the rival in the same
   position, not only players the article names.
4. Every change logged with its source; any change can be undone.
5. Changes expire on their own; a stale cut never lingers.

## Non-goals

- Re-applying official FPL injury flags. `projections.py:656-854` already
  multiplies GW1 by `chance_of_playing_next_round` and fades future GWs. Writing
  `digest_bootstrap_news` output into knowledge would double-count (0.75 × 0.75
  on GW1, full-horizon cut for a one-week doubt). That flag rail stays as it is
  today: automatic, inside projections.
- AI-driven availability (injury out / return dates). Official flags own that.
- Upgrades. AI news can never raise a player's projection.
- Option C (research agent). Only the ingest seam is reserved (see Future).
- Venue form / fixture-swing candidates (separate projects).

## Anti-goals (failure even if it "works")

- A rumour or prompt-injected RSS text zeroes or boosts a player.
- The wrong player is cut (name collision).
- Auto-writes clobber the owner's manual knowledge entries.
- Present-day knowledge leaks into backtest / replay / tuning
  (`test_backtest_paths_do_not_apply_present_day_knowledge` must stay green).
- A news failure breaks the main 6-hourly `/admin/refresh`.

## Constraints (verified)

- Fly volume `fpl_data` mounts at `/app/data`; `min_machines_running = 1`.
  `kb/` is outside the volume, so the corpus is wiped each deploy (and the Feb
  articles ship in the image).
- `seed_models.ensure_seed_models` never overwrites volume files that exist.
- `POST /squad/player-knowledge` replaces the whole file.
- `player_knowledge.apply()` is the single live entry point (`api/main.py`
  ×3, `api/wildcard.py`, `api/chat.py`); backtests never call it.
- `propose_player_knowledge` passes LLM numbers through unclamped;
  `index_by_player` falls back to single surname tokens.
- GitHub Actions already hit admin endpoints with `FPL_ADMIN_KEY`
  (`.github/workflows/refresh-backend.yml`).

## Approaches considered

1. **Backend `/admin/refresh-news` + scheduled GitHub workflow — CHOSEN.**
   Same pattern as `/admin/refresh`; LLM key stays on Fly; writes land on the
   volume; C later feeds the same merge code.
2. GitHub runner does fetch + digest, POSTs results. Rejected: LLM key in two
   places, logic split across runner and backend.
3. Fold into existing `/admin/refresh`. Rejected: couples failures, LLM cost
   4×/day.

## Design

### Storage (on the volume)

- Corpus: `NEWS_KB_DIR` → `data/news/articles/` (survives deploys; URL dedupe
  works). Old `kb/auto/news` dropped from the image.
- Auto knowledge: new file `data/models/player_knowledge_auto.json`, written
  only by the news job, atomically (temp file + `os.replace`).
- Manual file `player_knowledge.json` untouched by the job.
- Change log: append-only `data/news/changes.jsonl` — one line per
  add / expire / revert, with run id, player id, team, mult, note, source URLs.
- Run receipt: `data/news/last_run.json` (counts, errors, duration).

### Ingestion run (`POST /admin/refresh-news`, `require_admin`)

Runs in a background thread; returns `202 {run_id}` immediately. A second call
while one is running returns `409`. `GET /admin/news-status` returns the last
receipt plus active auto entries.

1. `news_fetch.refresh()` into the new corpus dir (existing code; prune by age).
2. **Group new + recent articles by Premier League team**, not by player.
   Team tagging from article tags/title matched to bootstrap team names.
3. **One LLM call per team with news**, giving: the articles (capped, e.g. 4),
   and that team's squad list **from live bootstrap** — id, web_name,
   position, status, chance_of_playing. Never from model memory. The model
   returns `[{player_id, minutes_mult, reason}]` and may name any player on the
   list, which covers displacement (article about Saliba returning, cut for
   Konsa).
4. **Guardrails in code** (the trust boundary — RSS text is untrusted):
   - `player_id` must be in the list sent for that team; else dropped.
   - `minutes_mult` numeric, clamped to `[NEWS_AUTO_MIN_MULT=0.7, 1.0]`;
     values ≥ 1.0 dropped (no-op).
   - `availability` forced 1.0, `available_from_gw` None.
   - Caps: `NEWS_AUTO_MAX_TEAMS_PER_RUN`, `NEWS_AUTO_MAX_ARTICLES_PER_TEAM`.
   - **Officially flagged players are excluded** (status != 'a' or
     chance_of_playing < 100): their injury is already priced by the flag rail,
     and a cut on top would double-count. Enforced in code, not the prompt.
     *(Builder-check call.)*
   - **Only fresh articles create or refresh an entry**: an article counts for
     the GW whose deadline window it was published in (after the previous GW
     deadline). Older articles may be sent as context but cannot keep a cut
     alive, so one article never re-confirms itself for two weeks.
     *(Builder-check call.)*
5. Merge into the auto file: each entry stamped `created_gw` (= next GW) and
   `expires_after_gw` (= next GW). Re-confirmed by a later run → refreshed.
   Entries whose player is reverted (tombstone) are skipped until expiry.
6. Log + receipt.

### Apply-time (`player_knowledge.apply`)

- Load manual + auto; **field-level merge, precedence request > manual > auto**
  (a manual entry that sets only `availability` keeps the auto `minutes_mult`).
  *(Builder-check call.)*
- Drop auto entries where `expires_after_gw < next GW` (filter inside
  `apply`, so the backtest pin keeps covering it).
- Effect unchanged: `xpts_gw{g} *= minutes_mult` across the **whole horizon**
  while the entry is alive (owner decision 2026-11-21: displacement lasts, so a
  cut lowers every projected GW; expiry at the next deadline unless fresh news
  renews it keeps a rumour from lingering).
- `pk_note` carries the reason + "auto (news)" so existing UI notes show it.

### Undo

`POST /admin/news-knowledge/revert {player_id | run_id}` (`require_admin`):
removes the entries, writes a tombstone until their expiry, logs it.

### Schedule

New workflow `.github/workflows/refresh-news.yml`: daily 07:00 and 17:00 UTC,
plus Friday 19:00 UTC (late pressers before Saturday deadline), plus
`workflow_dispatch`. Calls the endpoint, then **polls `news-status` every ~30 s
until the run finishes** (fail the job after a timeout). The polling is
load-bearing: `fly.toml` has `auto_stop_machines = 'stop'`, so an idle machine
would be stopped mid-run and kill the background thread. Run duration capped
by `NEWS_AUTO_MAX_RUN_SECONDS`; a run interrupted mid-way writes nothing
(auto file is only replaced at the end). Separate from `refresh-backend.yml`.

Assumption: prod is one Fly machine with one volume (`min_machines_running = 1`;
not verified from here, owner can run `fly machines list -a fpl-assistant-api`).
Run lock and state live in files on the volume, not in process memory. The
polling stays regardless: cheap, and it surfaces the result in the job log.
If prod ever scales past one machine, the auto file and lock move to Supabase.

### Config (all new params tagged, in `config.py`)

`NEWS_AUTO_ENABLED` (kill switch, default on in prod after first dry run),
`NEWS_AUTO_DRY_RUN` (write log + receipt but not the auto file),
`NEWS_AUTO_MIN_MULT=0.7`, caps above, path constants.

### Rollout

1. Deploy with `NEWS_AUTO_DRY_RUN=1`; trigger manually; owner reads the log
   for one run (sanity, not ongoing review).
2. Flip dry run off. Watch GW12 cuts in the log.

## Future (not built now)

- **Option C** research agent posts findings to a separate ingest endpoint
  with its own low-privilege key (September plan: the agent never holds the
  admin key). Same guardrails and merge function.
- More feeds (3 RSS sources today).

## Left to the builder

- Exact team-tagging heuristic for articles; how to handle articles touching
  two teams (send to both).
- Prompt wording and JSON schema for the per-team call; model id — load the
  `claude-api` skill before touching `_anthropic_generate` (hard-coded id may be
  stale).
- Whether the old per-player `propose_player_knowledge` / `digest-news` path is
  kept for the UI or retired.
- Test layout; must include: clamp + id-whitelist tests, expiry filter,
  manual-over-auto precedence, revert tombstone, backtest pin unchanged.
- Security review on the diff before the PR (prompt-injection boundary, new
  admin endpoints).
