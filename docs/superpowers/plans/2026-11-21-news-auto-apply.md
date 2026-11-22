# News Auto-Apply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scheduled cloud job reads Premier League news and writes guarded minute cuts straight into live projections, with log, expiry and undo.

**Architecture:** New admin endpoint `/admin/refresh-news` runs a background job on the Fly backend: fetch RSS (existing `news_fetch.refresh`), group fresh articles by club, one LLM call per club with that club's live squad list, guard the output in code, merge into a separate `player_knowledge_auto.json` on the volume. `player_knowledge.apply()` field-merges auto < manual < request and drops expired auto entries. A GitHub workflow triggers and polls it.

**Tech Stack:** Python 3, FastAPI, pandas, pytest, Anthropic SDK, GitHub Actions, Fly.io volume.

**Spec:** `docs/superpowers/specs/2026-11-21-news-auto-apply-design.md`

## Global Constraints

- Run tests with `../../FPL/.venv/bin/python -m pytest` from the worktree root (`/Users/ziadnader/05_Projects/Tech/FPL-Assistant/worktrees/news-auto`); worktree has no venv of its own.
- Never switch branches in `FPL/`; all work in this worktree (branch `docs/news-auto-apply`; rename to `feat/news-auto-apply` before PR).
- Every new tunable lives in `src/config.py` with a tag (`[untested]` / `[operational]`); no numbers in logic files.
- AI cut bounds: `minutes_mult` clamped to `[NEWS_AUTO_MIN_MULT=0.7, 1.0]`; `availability` forced `1.0`; `available_from_gw` forced `None`; values ≥ 1.0 dropped.
- Officially flagged players (status != `'a'` or `chance_of_playing_next_round` < 100, NaN counts as 100) never get an auto cut.
- Only articles published after the latest past GW deadline create or refresh an entry.
- Entry alive while `created_gw <= min(gws) <= expires_after_gw`; `created_gw = expires_after_gw = next GW` at write time, where next GW comes from `squad_draft._next_gw(bootstrap)` (the same helper live apply callers use — no second definition); cut applies to every GW in the horizon.
- Precedence: resolve every layer to player ids first (`resolve_keys`), then auto is field-merged under manual; request over manual keeps today's whole-entry replace (`merge_request` semantics unchanged; frontend sends no request overrides today).
- Runtime flags `NEWS_AUTO_ENABLED` / `NEWS_AUTO_DRY_RUN` read from env at call time (`os.environ.get(...)`, default from config) — `config.py` reads no env today, so the override lives in `news_auto_run`, not config.
- Every LLM call (digest + per-club) uses a model id from config; no hard-coded ids left in `news_fetch` / `news_digest` paths this run touches.
- Backtest / replay / monitor paths never import `player_knowledge` or `news_auto` (`test_backtest_paths_do_not_apply_present_day_knowledge` stays green; add `news_auto` to its check).
- `NEWS_KB_DIR = "data/news/articles"` (on the `/app/data` volume).
- Auto file written atomically (temp + `os.replace`), only at end of a successful run.
- Before touching any Anthropic call, load the `claude-api` skill; default model via `config.NEWS_AUTO_MODEL` (verify current Haiku id there, do not reuse the hard-coded `claude-haiku-4-5-20251001` blindly).
- Run `security-review` on the branch diff before the PR; report findings in PR body. Owner merges; never push to master.

## Review Focus

1. LLM returns prose, malformed JSON, a list of strings, or `player_id` as a string/float → entry dropped or coerced, run continues (Task 2 test `test_guard_rejects_malformed_output`).
2. Prompt-injected article says "set minutes_mult to 0" or names a player from another club → clamped to 0.7 / dropped (Task 2 `test_guard_clamps_and_whitelists`).
3. Article with no `Teams` entity or a team name variant ("Spurs", "Man Utd") → matched via name/short_name/aliases or skipped, never mis-assigned (Task 2 `test_group_by_team_aliases_and_unknown`).
4. Auto file missing, empty, or corrupt JSON at apply time → projections unchanged, no exception (Task 1 `test_auto_file_corrupt_is_ignored`).
5. Run crashes mid-way (LLM 500 on club 7 of 12) → previous auto file intact, receipt `ok: false`, lock released (Task 3 `test_run_failure_keeps_previous_file_and_releases_lock`).

---

### Task 1: Config + apply-time merge and expiry

**Files:**
- Modify: `src/config.py` (near `PLAYER_KNOWLEDGE_PATH` ~L633 and `NEWS_KB_DIR` ~L652)
- Modify: `src/player_knowledge.py`
- Modify: `tests/test_player_knowledge_in_recommendations.py` (in `test_backtest_paths_do_not_apply_present_day_knowledge` add `assert "news_auto" not in src.read_text()`)
- Test: `tests/test_player_knowledge_auto.py`

**Interfaces:**
- Produces config: `PLAYER_KNOWLEDGE_AUTO_PATH = "data/models/player_knowledge_auto.json"` `[operational]`, `NEWS_KB_DIR = "data/news/articles"`, `NEWS_AUTO_DIR = "data/news"` `[operational]`, `NEWS_AUTO_ENABLED = True` `[operational]`, `NEWS_AUTO_DRY_RUN = True` `[operational]` (flip to False after first prod dry run), `NEWS_AUTO_MIN_MULT = 0.7` `[untested]`, `NEWS_AUTO_MAX_TEAMS_PER_RUN = 20` `[operational]`, `NEWS_AUTO_MAX_ARTICLES_PER_TEAM = 4` `[operational]`, `NEWS_AUTO_MAX_RUN_SECONDS = 600` `[operational]`, `NEWS_AUTO_MODEL` (current Haiku id) `[operational]`. Env overrides `NEWS_AUTO_ENABLED` / `NEWS_AUTO_DRY_RUN` read via `os.environ` in config the way other operational flags are.
- Produces: `player_knowledge.load_auto_knowledge(path=None) -> dict` (`{"as_of", "players", "tombstones"}`, degrades to empty); `player_knowledge.live_auto_entries(auto: dict, first_gw: int) -> dict[str, dict]` (keeps `created_gw <= first_gw <= expires_after_gw`); `player_knowledge.field_merge(under: dict[int, dict], over: dict[int, dict]) -> dict[int, dict]` (id-keyed; `over` wins per field); `apply(proj, gws, request_pk=None, path=None, stale_days=None, today=None, auto_path=None)` — same return.

- [ ] **Step 1: Write failing tests** in `tests/test_player_knowledge_auto.py` using the `_proj()` helper style from `test_player_knowledge_in_recommendations.py` (id 1, xpts_gw5..7 = 2.0 each):
  - `test_auto_entry_cuts_every_gw_in_horizon`: auto `{"1": {"minutes_mult": 0.8, "expires_after_gw": 5}}`, gws `[5,6,7]` → `xpts_horizon == pytest.approx(4.8)`.
  - `test_expired_auto_entry_is_ignored`: `expires_after_gw: 4`, gws `[5,6,7]` → `xpts_horizon == 6.0`.
  - `test_manual_field_beats_auto_but_keeps_other_fields`: manual `{"1": {"availability": 0.5}}`, auto `{"1": {"minutes_mult": 0.8, "availability": 1.0, "expires_after_gw": 5}}` → `xpts_horizon == pytest.approx(2.4)`.
  - `test_request_beats_manual_and_auto`: request `{"1": {"minutes_mult": 1.0}}` over auto 0.8 → 6.0.
  - `test_auto_file_corrupt_is_ignored`: auto file content `"{not json"` → 6.0, no raise.
  - `test_name_keyed_manual_merges_with_id_keyed_auto`: manual `{"Alpha": {"availability": 0.5}}` (web_name of id 1), auto id `"1"` mult 0.8 → 2.4.
  - `test_future_created_auto_entry_is_ignored`: `created_gw: 6, expires_after_gw: 6`, gws `[5,6,7]` → 6.0.
  - `test_auto_path_defaults_to_config` (monkeypatch `config.PLAYER_KNOWLEDGE_AUTO_PATH`).
  - Keep `test_request_overrides_beat_the_file` passing unchanged.

- [ ] **Step 2: Run** `../../FPL/.venv/bin/python -m pytest tests/test_player_knowledge_auto.py -v` → FAIL (no `auto_path` / functions).

- [ ] **Step 3: Implement** in `src/player_knowledge.py`: `apply` loads manual + auto, filters auto by `live_auto_entries(auto, min(gws))`, `merge_request(manual, request)` as today, `resolve_keys` on that and on the live auto layer, then `field_merge(auto_by_id, manual_by_id)`. Auto-entry `note` passes through to `pk_note`. Add config params listed above. `NEWS_AUTO_DIGEST_MODEL` too; `news_fetch.refresh` callers in this feature pass a generate bound to it.

- [ ] **Step 4: Run** the new file plus `tests/test_player_knowledge.py tests/test_player_knowledge_in_recommendations.py tests/test_data_status.py` → all PASS.

- [ ] **Step 5: Commit** `feat(knowledge): auto knowledge layer with expiry and field-level precedence`.

---

### Task 2: Pure news-to-cuts logic (`src/news_auto.py`)

**Files:**
- Create: `src/news_auto.py`
- Test: `tests/test_news_auto.py`

**Interfaces:**
- Consumes: `news_digest.load_news_articles(kb_dir)` article dicts (`title, url, published, fetched, summary, fpl_takeaways, players, tags, path`) — **extend `news_digest._parse_article` to also return `teams: list[str]`** from the `Entities` section's `- Teams:` line (same pattern as Players).
- Produces:
  - `latest_past_deadline(events: list[dict], now: datetime) -> datetime | None`
  - `next_gw(events, now) -> int`
  - `is_fresh(article: dict, since: datetime | None) -> bool` (uses `published`, falls back to `fetched`; `since is None` → True)
  - `group_by_team(articles: list[dict], teams: list[dict]) -> dict[int, list[dict]]` (bootstrap teams; match normalized `name` / `short_name` / `config.NEWS_TEAM_ALIASES` dict e.g. `{"spurs": "TOT", "man utd": "MUN", "man city": "MCI", "wolves": "WOL", "forest": "NFO"}` `[operational]`; aliases map to `short_name` resolved via bootstrap, never assume ids; unknown names skipped; article on two clubs goes to both)
  - `squad_list(elements: pd.DataFrame, team_id: int) -> list[dict]` (`id, web_name, position, status, chance_of_playing_next_round`)
  - `build_team_prompt(team_name: str, articles: list[dict], squad: list[dict], gw: int) -> str` and module constant `SYSTEM_TEAM` (asks for JSON `{"cuts": [{"player_id": int, "minutes_mult": float, "reason": "<=15 words"}]}`; explicitly: only players in the list; only lost starts / rotation / displaced by a returning teammate; no injuries; empty list if nothing concrete). Exact wording is the builder's.
  - `guard_cuts(raw: str, squad: list[dict], min_mult: float) -> list[dict]` → `[{"player_id": int, "minutes_mult": float, "reason": str}]`
  - `unprocessed(articles: list[dict], processed_urls: set[str]) -> list[dict]` — a club is called only when it has at least one fresh article not yet judged; all its fresh articles go in as context. Processed URLs persist in `data/news/processed.json` (pruned to URLs still in the corpus).
  - `build_entries(cuts_by_team: dict[int, list[dict]], sources_by_team: dict[int, list[str]], team_short: dict[int, str], gw: int, run_id: str) -> dict[str, dict]` → entry shape `{"availability": 1.0, "available_from_gw": None, "minutes_mult": m, "note": "auto (news): <reason>", "source": "news_auto", "sources": [urls], "team": "ARS", "created_gw": gw, "expires_after_gw": gw, "run_id": run_id}`
  - `merge_auto(prev: dict, new_entries: dict, gw: int, now_iso: str) -> tuple[dict, list[dict]]` → (new auto file, log events). Rules: drop prev entries with `expires_after_gw < gw` (log `expire`); new entry for a tombstoned id with `until_gw >= gw` skipped (log `skip_tombstone`); otherwise new replaces prev (log `add` or `refresh`); prev entries not re-confirmed but still alive are kept; drop tombstones with `until_gw < gw`.
  - `revert(auto: dict, player_ids: list[str] | None, run_id: str | None, gw: int) -> tuple[dict, list[dict]]` → removes matching entries, writes tombstone `{"until_gw": entry.expires_after_gw}`, log `revert`.

- [ ] **Step 1: Write failing tests** in `tests/test_news_auto.py` (all pure, no network):
  - `test_latest_past_deadline_and_next_gw` (events GW11 deadline 2026-11-14, GW12 2026-11-28, now 2026-11-21 → deadline 2026-11-14, next_gw 12).
  - `test_is_fresh_uses_published_then_fetched`: `Published: Thu, 19 Feb 2026 23:25:00 +0000` (raw RSS string) parsed via `news_fetch._parse_date`, tz-aware compare.
  - `test_unprocessed_filters_seen_urls`.
  - `test_group_by_team_aliases_and_unknown`: teams `[{id:1,name:"Arsenal",short_name:"ARS"},{id:2,name:"Tottenham Hotspur",short_name:"TOT"}]`; article teams `["Spurs","Arsenal"]` → both; `["Barcelona"]` → none; no teams → none.
  - `test_guard_clamps_and_whitelists`: squad ids {10, 11}; raw `{"cuts":[{"player_id":10,"minutes_mult":0.0},{"player_id":99,"minutes_mult":0.8},{"player_id":11,"minutes_mult":1.1}]}` → `[{"player_id":10,"minutes_mult":0.7,...}]`.
  - `test_guard_excludes_flagged_players`: squad row 10 status `'d'` chance 75 → dropped; status `'a'` chance NaN → kept.
  - `test_guard_rejects_malformed_output`: `"no news"`, `"{bad"`, `{"cuts":"x"}`, `{"cuts":[{"player_id":"10","minutes_mult":"0.8"}]}` → first three `[]`; fourth coerced to id 10, 0.8 (numeric strings OK, non-numeric dropped).
  - `test_merge_auto_add_refresh_expire_tombstone` covering each log kind.
  - `test_revert_by_player_and_by_run`.
  - `test_build_entries_shape` (availability 1.0, available_from_gw None, created/expires = gw).

- [ ] **Step 2: Run** `../../FPL/.venv/bin/python -m pytest tests/test_news_auto.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement** `src/news_auto.py` (pure; imports only `config`, `news_digest._parse_article` helpers, `player_knowledge._norm`, pandas). Add `NEWS_TEAM_ALIASES` to config. Extend `_parse_article` with `teams`; existing `tests/test_news_digest.py` must stay green.

- [ ] **Step 4: Run** `tests/test_news_auto.py tests/test_news_digest.py tests/test_news_fetch.py` → PASS.

- [ ] **Step 5: Commit** `feat(news): per-club news-to-minutes-cut logic with code guardrails`.

---

### Task 3: Run orchestrator (`src/news_auto_run.py`)

**Files:**
- Create: `src/news_auto_run.py`
- Test: `tests/test_news_auto_run.py`

**Interfaces:**
- Consumes: everything Produced by Task 2; `news_fetch.refresh(kb_dir, now=, fetch=, generate=, pl_terms=)`; `news_fetch.pl_terms_from_teams`; `transforms.tables_from_bootstrap(bootstrap)`; `player_knowledge.load_auto_knowledge`.
- Produces:
  - `run(bootstrap: dict, *, run_id: str, lock_held: bool = False, now: datetime | None = None, fetch=None, digest_generate=None, team_generate=None, kb_dir=None, out_dir=None, auto_path=None, dry_run: bool | None = None, max_seconds: float | None = None) -> dict` (the receipt: `{run_id, ok, dry_run, started, finished, next_gw, fetched: n, fresh_articles: n, teams_called: n, cuts: n, events: [...], errors: [...]}`)
  - `acquire_lock(out_dir) -> bool` / `release_lock(out_dir) -> None` — lock file `out_dir/run.lock` created with `os.open(..., O_CREAT|O_EXCL)`, holding started timestamp; stale after `NEWS_AUTO_MAX_RUN_SECONDS * 2` (treated as free).
  - `read_status(out_dir=None, auto_path=None) -> dict` → `{"running": bool, "last_run": receipt | None, "active": {pid: entry}}`
  - `team_generate(prompt: str) -> str` default: Anthropic call with `SYSTEM_TEAM`, `config.NEWS_AUTO_MODEL`, `llm_usage.record_usage(..., feature="news_auto")`.
  - Files: `out_dir/last_run.json` (receipt, atomic), `out_dir/changes.jsonl` (append each log event with `run_id`, `ts`).

- [ ] **Step 1: Write failing tests** (fake `fetch` returning a tiny RSS, fake `digest_generate` returning digest JSON with `teams`, fake `team_generate`; tmp dirs; fixed `now`):
  - `test_run_writes_auto_file_log_and_receipt`: one fresh Arsenal article, team_generate returns cut for squad player 10 → auto file has `"10"` with `minutes_mult` 0.8; `changes.jsonl` has one `add`; receipt `ok: true`.
  - `test_dry_run_writes_log_and_receipt_but_not_auto_file`.
  - `test_stale_article_creates_no_entry` (published before latest past deadline).
  - `test_run_failure_keeps_previous_file_and_releases_lock`: pre-existing auto file; team_generate raises on first call → file bytes unchanged, receipt `ok: false` with error, lock file absent. (One club erroring is fatal for the run: partial runs write nothing — simplest invariant.)
  - `test_second_run_refused_while_locked` → `acquire_lock` False.
  - `test_time_budget_stops_and_writes_nothing` (`max_seconds=0`).
  - `test_digest_total_failure_is_not_ok`: every feed errors or every digest call raises, nothing written → receipt `ok: false` (silent death killed this pipeline before).
  - `test_clubs_with_only_processed_articles_are_not_called` (team_generate call count 0 on second run with same corpus).
  - `test_disabled_flag_short_circuits` (`config.NEWS_AUTO_ENABLED=False` → receipt `ok: true, skipped: "disabled"`, no LLM calls).

- [ ] **Step 2: Run** `../../FPL/.venv/bin/python -m pytest tests/test_news_auto_run.py -v` → FAIL.

- [ ] **Step 3: Implement** `run`: enabled check → `news_fetch.refresh` into `kb_dir` → `load_news_articles` → filter `is_fresh(since=latest_past_deadline)` → `group_by_team` → cap teams/articles → per club `team_generate(build_team_prompt(...))` → `guard_cuts` → `build_entries` → `merge_auto(load_auto_knowledge(auto_path), …)` → atomic write unless dry run → append log → write receipt. Lock acquired by caller (endpoint) so status reads see it; `run` itself releases in `finally` only if it acquired (accept `lock_held: bool = False` param). `run_id` is passed in by the endpoint. Receipt `ok: false` when `news_fetch.refresh` returns errors and wrote nothing. Mark URLs processed only after a successful run.

- [ ] **Step 4: Run** Task 2 + Task 3 tests → PASS.

- [ ] **Step 5: Commit** `feat(news): news auto run with lock, receipt, change log and dry run`.

---

### Task 4: Admin endpoints

**Files:**
- Create: `api/news_router.py`
- Modify: `api/main.py` (include router next to `wildcard_router` ~L87)
- Test: `tests/test_news_router.py`

**Interfaces:**
- Consumes: `news_auto_run.run / acquire_lock / release_lock / read_status`, `news_auto.revert`, `main.get_bootstrap_cached`.
- Produces routes (all `dependencies=[Depends(require_admin)]`):
  - `POST /admin/refresh-news` → `acquire_lock` else `409 {"detail": "news run already in progress"}`; start `threading.Thread(target=..., daemon=True)` that calls `run(bootstrap, lock_held=True)`; `run_id` = UTC `YYYYMMDDTHHMMSSZ` generated here and passed to `run`; return `202 {"run_id": run_id, "started": iso}`.
  - `GET /admin/news-status` → `read_status()`.
  - `POST /admin/news-knowledge/revert` body `{"player_ids": [..]} | {"run_id": ".."}` (exactly one, else 422; 409 while the run lock is held) → revert, atomic write, append log, return `{"reverted": [ids]}`.

- [ ] **Step 1: Write failing tests** with the `refresh_client` fixture pattern from `tests/test_refresh_status.py` (monkeypatch `FPL_ADMIN_KEY`, `get_bootstrap_cached`, config paths to tmp; monkeypatch `news_auto_run.run` to a fake that records the call):
  - `test_refresh_news_requires_admin` (no key → 401).
  - `test_refresh_news_returns_202_and_runs` (join thread via monkeypatched `threading.Thread` that runs inline).
  - `test_refresh_news_409_when_locked`.
  - `test_news_status_shape`.
  - `test_revert_by_player_writes_tombstone`; `test_revert_requires_exactly_one_selector` → 422.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `tests/test_news_router.py tests/test_refresh_status.py` → PASS.

- [ ] **Step 5: Commit** `feat(api): admin endpoints to run, inspect and revert news auto-apply`.

---

### Task 5: Schedule, image, docs

**Files:**
- Create: `.github/workflows/refresh-news.yml`
- Modify: `.dockerignore` (add `kb/auto/news/`)
- Modify: `CLAUDE.md` (new "### News auto-apply (2026-11)" section under Architecture: what runs, files on volume, guardrails, dry-run flag, revert curl, backtest boundary)
- Modify: `src/data_status.py` only if its `NEWS_KB_DIR` freshness check breaks on the new dir (expect none; verify)

**Interfaces:** consumes Task 4 routes; secrets `FPL_API_BASE_URL`, `FPL_ADMIN_KEY` (already exist).

- [ ] **Step 1: Write workflow**: `on.schedule` crons `"0 7 * * *"`, `"0 17 * * *"`, `"0 19 * * 5"`, plus `workflow_dispatch`; steps mirror `refresh-backend.yml` secret check + wake-retry; POST `/admin/refresh-news` (accept 202 or 409); loop `GET /admin/news-status` every 30 s up to 15 min until `running == false`; print `last_run` (including `events`, which is how the owner reads the dry-run changes, since `changes.jsonl` sits on the Fly volume) with `jq`; fail if `last_run.run_id` differs from the 202's `run_id` or `last_run.ok != true`. On 409 exit 0 with a note (a run is already going). Staging leg optional, `continue-on-error`, same `FPL_DEV_*` skip pattern.
- [ ] **Step 2: Verify** `../../FPL/.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/refresh-news.yml'))"` → no error; `actionlint` if installed.
- [ ] **Step 3: Full suite** `../../FPL/.venv/bin/python -m pytest -q` → all PASS (compare count with master baseline).
- [ ] **Step 4: Commit** `chore(news): schedule news auto-apply, drop stale corpus from image, document`.

---

### Task 6: Gate and PR

- [ ] **Step 1:** Run `security-review` skill on the branch diff. Focus: prompt-injection boundary (`guard_cuts`), admin auth on three routes, path handling (no client-supplied paths), thread/lock safety.
- [ ] **Step 2:** Rename branch `git -C <worktree> branch -m feat/news-auto-apply`; push; open PR to `master` with summary, security findings, and rollout: deploy with `NEWS_AUTO_DRY_RUN` on → trigger workflow by hand → owner reads the workflow log's `events` once; **pass criterion: at least one sensible rotation/displacement cut from a predicted-XI article** (if none appear across a GW's runs, the RSS blurbs are too thin and option C is what delivers the Konsa case — report that) → set `fly secrets set NEWS_AUTO_DRY_RUN=0 -a fpl-assistant-api`.
- [ ] **Step 3:** Owner merges. Do not push after merge (check PR state first).
