# Pre-Launch Audit — 2026-09-12

Three parallel audits: UX/UI, architecture + security, commercial/pricing. Every finding
below was verified against code with a `path:line` citation. Baseline at time of audit:
`./.venv/bin/python -m pytest -q` → **408 passed** (272s); `npm run typecheck` → clean.

> **Keep this file local.** It contains a working exploit against the live production host.

---

## 0. Ship order (the actual worklist)

### Gate 1 — before anyone pays

| # | Item | Effort | Ref |
|---|---|---|---|
| 1 | `sub`-based authorization — client-supplied `entry_id` must stop being trusted | M | [C4](#c4-no-authorization-jwt-sub-never-read) |
| 2 | Rate-limit key → `Fly-Client-IP`; add per-user limits on the 5 LLM routes; Anthropic console spend cap | S | [C2](#c2-rate-limit-key-is-client-controlled), [H5](#h5-unmetered-llm-spend) |
| 3 | Request body cap (2MB) + `--limit-concurrency 24` + `min_machines_running = 1` | S | [C3](#c3-no-request-body-size-cap) |
| 4 | Delete `or FPL_API_KEY` admin fallback | S | [C5](#c5-admin-key-collapses-into-the-user-key) |
| 5 | Enable GitHub push protection + secret scanning; delete Azure workflow; make CI a required check | S | [C6](#c6-ci-does-not-gate-deploys), [H8](#h8-github-secret-scanning-disabled) |
| 6 | Fix the dead `/app` screen; move `dark` to `<html>` | S | [U1](#u1-a-single-failed-eventsnext-wedges-app-forever), [U2](#u2-every-radix-portal-renders-light-theme) |
| 7 | Delete unimplemented landing claims ("projected rank gain", "fine-tuned") | S | [U8](#u8-landing-overpromises-and-claims-data-that-does-not-exist) |
| 8 | Precompute chip plans on the existing cron; `/chips/plan` becomes cache-only | M | [H1](#h1-global-lock-serializes-chip-plan-builds) |

### Gate 2 — before charging (evidence, not code)

- Score the `chip_plan_snapshots` rows already collected (entries 107342 / 5645321, twice-daily cron) for GW1–GW7 against realized points. Costs £0.
- Run the season backtest of the September tunables (`scripts/backtest_season.py` exists).
- Fix the projections clamp bug so chip thresholds can be set honestly rather than set to suppress output.

### Gate 3 — post-launch

Pitch palette, `<main>` landmarks + skip links, Playwright 375px smoke test, `useProfile` → react-query, terminology consolidation (`xPts` / `xP` / "Projected points").

---

## 1. Security & architecture

### Endpoint / auth table

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/` | none | `api/main.py:1584` |
| GET | `/health` | none | `api/main.py:1589` |
| GET | `/events/next` | none | `api/main.py:1594` — cache miss triggers upstream fetch |
| GET | `/fixtures/difficulty` | JWT *or* static `FPL_API_KEY` | `api/main.py:1602` |
| POST | `/admin/refresh` | static `FPL_ADMIN_KEY` | `api/main.py:1614` |
| GET | `/admin/model-snapshot` | static admin key | `api/main.py:1793` |
| GET | `/admin/chip-plan` | static admin key | `api/main.py:1805` |
| GET | `/squad` | JWT | **IDOR** `api/main.py:1840` |
| GET | `/entry/identity` | JWT | **IDOR** `api/main.py:1852` |
| POST | `/squad` | JWT | IDOR `api/main.py:1869` |
| POST | `/squad/manual` | JWT | **cross-tenant WRITE** `api/main.py:1882` |
| DELETE | `/squad/manual` | JWT | **cross-tenant DELETE** `api/main.py:1922` |
| POST | `/squad/optimize` | JWT | IDOR + `apply=true` write + unbounded CPU `api/main.py:1938` |
| GET | `/recommendations` | JWT | IDOR `api/main.py:1956` |
| POST | `/recommendations` | JWT | IDOR `api/main.py:1979` |
| GET | `/league/list` | JWT | IDOR `api/main.py:1992` |
| POST | `/league/strategy` | JWT | IDOR `api/main.py:2006` |
| POST | `/explain` | JWT | **LLM, client-authored prompt body** `api/main.py:2066` |
| GET/POST | `/evaluation/xpts` | JWT | `api/main.py:2090`, `:2102` |
| POST | `/chat` | JWT (router-level `api/main.py:79`) | **LLM**, IDOR `api/chat.py:327` |
| POST | `/chat/captain`, `/chat/transfer`, `/chat/chip` | JWT | LLM, IDOR `api/chat.py:231`, `:253`, `:291` |
| GET | `/chips/plan` | JWT (`api/main.py:86`) | IDOR, ~60s CPU `api/chips.py:49` |
| POST | `/squad-picker/build`, `/players`, `/lineup`, `/transfer-plan`, `/gk-pairs` | JWT | live in prod (`SQUAD_PICKER_MODE=1`) `api/squad_router.py:31`+ |
| POST | `/squad-picker/digest-news` | JWT | **unbounded LLM loop** `api/squad_router.py:105` |
| POST | `/squad-picker/team-news` | JWT | `api/squad_router.py:137` |
| GET | `/squad-picker/knowledge`, `/player-knowledge` | JWT | `api/squad_router.py:154`, `:163` |
| POST | `/squad-picker/knowledge`, `/player-knowledge` | static admin key | **writes model inputs** `api/squad_router.py:172`, `:182` |
| GET | `/replay/*` | JWT | `REPLAY_MODE` off in prod; `season` regex-validated `api/replay_router.py:39` |

### CRITICAL

#### C4. No authorization — JWT `sub` never read

**Severity: launch blocker.** Effort: **M**

The chain, end to end:

1. `verify_supabase_jwt` correctly validates signature, `aud`, `exp`, `sub` against Supabase
   JWKS and **returns the decoded claims** — `src/auth.py:66-84`.
2. `check_api_key` discards them. It only tests `verify_supabase_jwt(token) is not None` and
   returns `None` for "OK" — `src/auth.py:108-113`.
3. `require_user` likewise returns only pass/fail — `src/auth.py:129-131`.
4. So no caller can know *who* is authenticated. Verified:
   `grep -rn '"sub"\|\.get("sub")\|claims\|user_id' api/ src/auth.py` returns only the
   `options={"require": ["exp","sub"]}` literal at `src/auth.py:81`. No route consults
   `profiles.entry_id`.
5. `entry_id` therefore comes purely from the request and is used directly —
   `api/main.py:1897` (`safe_int(payload.get("entry_id"))`), `src/manual_squad.py:38`
   (`_path_for` → `data/manual_squads/entry_<id>.json`).

Auth is a turnstile, not a lock: every route asks "is *anyone* logged in", never "is this
*your* entry". Reads are mostly public FPL data, so severity concentrates in the writes:

- `DELETE /squad/manual` — `api/main.py:1922` → `clear_manual_squad(entry_id)` →
  `src/manual_squad.py:66-72` calls `p.unlink()` with **no ownership test**.
- `POST /squad/manual` — `api/main.py:1882` → `save_manual_squad` →
  `src/manual_squad.py:41-52` overwrites any entry's file.
- `POST /squad/optimize` with `apply=true` — `api/main.py:1938`, `api/main.py:824`.

**One-request exploit.** Sign up for a free account, then:

```bash
curl -X DELETE 'https://fpl-assistant-api.fly.dev/squad/manual?entry_id=<victim>' \
  -H 'Authorization: Bearer <my own valid token>'
# → {"entry_id": <victim>, "removed": true}
```

A paying customer's imported XV is destroyed. Entry IDs are public and enumerable, so this
scripts trivially across the whole user base.

**Fix.** Have `check_api_key` / `require_user` *return* the claims instead of `None`; add a
FastAPI dependency that resolves `entry_id` server-side from `profiles` keyed on `sub`; make
the client-supplied `entry_id` either ignored or accepted only when it matches. One
correctly-scoped read already exists to model it on: the frontend filters `profiles` by
`userId` at `src/hooks/useProfile.ts:49-52`.

#### C2. Rate-limit key is client-controlled

Effort: **S**

`api/main.py:135-138` — `_client_ip` returns
`request.headers["x-forwarded-for"].split(",")[0].strip()`. Fly's proxy **appends** the real
client address to any inbound `X-Forwarded-For` rather than replacing it, so position `[0]` is
whatever the attacker sent. The trustworthy value is `Fly-Client-IP`. That function is the
`key_func` for the only limiter in the app (`api/main.py:144`).

*Exploit:* rotate `X-Forwarded-For: 1.2.3.<n>` per request and the `90/minute` + `1500/hour`
defaults (`api/main.py:143`) never trigger on any route, LLM endpoints included. Storage is
also in-process (no `storage_uri`), so counters reset on every Fly auto-suspend.

*Fix:* key on `Fly-Client-IP`; add a second limit keyed on the JWT `sub`.

#### C3. No request body size cap

Effort: **S**

`grep` for `limit_concurrency|limit_max_requests|max_request|body_size|Content-Length` across
`Dockerfile` and `api/*.py` returns nothing. The launch line is bare
`uvicorn --workers ${WEB_CONCURRENCY:-2}` (`Dockerfile:15`) and the VM is `memory = '512mb'`
(`fly.toml:40`). Starlette buffers the entire body before `Body(...)` deserialization.

*Exploit:* one ~400MB POST to `/explain` (`api/main.py:2066`) OOM-kills the single process;
`min_machines_running = 0` (`fly.toml:29`) means it restarts cold and can be killed on a loop.

*Fix:* body-size middleware at 2MB plus `--limit-concurrency 24`.

#### C5. Admin key collapses into the user key

Effort: **S**

`src/auth.py:118` — `required = (FPL_ADMIN_KEY or FPL_API_KEY)`. `FPL_API_KEY` is *also*
accepted on every user route (`src/auth.py:111`, reached from `check_api_key` on all 13
inline-auth routes) and is the key the docs instruct you to set
(`docs/production_azure.md:22,58`).

*Blast radius:* if `FPL_ADMIN_KEY` is unset, any holder of the shared user key gets
`POST /admin/refresh`, `GET /admin/model-snapshot`, and `POST /squad-picker/knowledge` — the
last writes `knowledge_discount.json`, whose multipliers feed straight into the projection
engine (`api/squad_router.py:182-187`). Silent privilege escalation with no code change.

Done right: with neither var set it fails closed with 503 (`src/auth.py:119-120`).

*Fix:* delete the `or FPL_API_KEY` fallback; confirm `FPL_ADMIN_KEY` is a distinct Fly secret.

#### C6. CI does not gate deploys

Effort: **S**

`.github/workflows/fly-deploy.yml:5-8` fires on push to `master` with no `needs:` on the test
job; `api-ci.yml:3-8` runs in parallel. **A red suite deploys.**

Separately `.github/workflows/deploy-azure-containerapp.yml:3-6` still deploys on push to
`main` to a *second live app* with its own secret copies, and lines 126-129 splice
`${{ secrets.FPL_ADMIN_KEY }}` / `FPL_API_KEY` into a shell variable passed as a command
argument — process-table exposure that defeats log masking under `set -x`.

*Recommendation:* **delete the Azure workflow outright** and revoke its Azure + `FPL_API_KEY`
secrets. `CLAUDE.md` already calls that path deprecated; it is a second unmonitored production
surface with weaker secret handling and no upside. Then fold the test job into
`fly-deploy.yml` as a `needs:` dependency and add it as a required status check.

### C1 — leaked key: RESOLVED, no action beyond a usage check

Full object-DB scan (846 backend blobs, 556 frontend, 25-pattern pickaxe — not sampling):

- The leaked OpenAI legacy key is **already revoked** — `GET /v1/models` returns **HTTP 401**.
- Added `1eb82b8` (2025-06-04), removed `1a853a1` (2026-02-06). ~8 months live, permanent in
  history, reachable from `origin/master`, `origin/HEAD`, `origin/develop`,
  `origin/feature/xpts-components`, both `knowledge-watch/*`.
- **Both live keys were never committed** — zero pickaxe hits for `sk-proj-` and
  `sk-ant-api03` across all history. No `service_role` JWT in either repo.
- Confirmed absent: `AKIA`/`ASIA`, `ghp_`/`github_pat_`, `xoxb-`, `AIza`,
  `-----BEGIN PRIVATE KEY-----`, `FlyV1`/`fm2_`, `sk_live`.
- The frontend's committed `eyJ…` decodes to `role=anon` for the **retired** project
  `ouicfgyizlfgwqpzotat` — public by design.

**Skip the history rewrite.** The key-bearing commit is the tip of `refs/pull/17/head` and an
ancestor of **27 server-side pull refs**, which survive `git filter-repo` + force-push — the
blob stays fetchable via `git fetch origin refs/pull/17/head`. A rewrite is cosmetic, and it
invalidates 14 backend + 15 frontend branches plus every open PR. Fork count is 0 on both.

Residual actions: check platform.openai.com Usage for anomalous spend in the exposure window;
add a `gitleaks protect --staged` pre-commit guard; consider making both repos private
(`znader1/FPL` is public and carries a personal FPL entry ID).

### HIGH

#### H1. Global lock serializes chip-plan builds
Effort: **M** — `api/chips.py:61-67` holds one process-wide `threading.Lock` across the entire
build, and the cache key includes `entry_id` (`api/chips.py:57`) so distinct users never share
a result. The code's own comment documents a live GW3 deadline-day incident and a "minutes of
CPU" cost (`api/chips.py:19-21`). *Fix:* precompute on the existing 6-hourly cron —
`/admin/chip-plan` (`api/main.py:1805`) exists for exactly this — and make `/chips/plan`
cache-only, returning 202 on a miss.

#### H2. Unbounded CPU from one query param
Effort: **S** — `api/main.py:818`: `horizon_gws = max(1, int(safe_int(...) or 3))`, no upper
bound; `src/projections.py:491-492` then builds `range(horizon_gws)` columns. `max_rounds` is
uncapped the same way (`api/main.py:820`), `max_swaps` defaults to unlimited
(`api/main.py:822`). `POST /squad/optimize {"horizon_gws":100000}` pins the vCPU indefinitely.
Clamp to 1–8, matching the correct handling on `/recommendations`.

#### H3. Cache stampede with no stale fallback
Effort: **S** — `get_bootstrap_cached` (`api/main.py:190`), `get_fixtures_cached` (`:198`) and
`get_projections_cached` (`:235`) have no single-flight lock, and `_cache_get` returns `None`
past TTL rather than stale data (`:177-181`). With `PROJECTIONS_TTL = 1800`
(`src/config.py:15`), every 30 minutes N concurrent requests each rebuild the full model. When
FPL DataDome-blocks, all three raise and every request 502s. `get_event_live_cached` already
implements the correct stale-on-error fallback (`api/main.py:225-228`) — copy it.

#### H4. Upstream retry loop amplifies latency 5×
Effort: **S** — `api/main.py:541-550` tries up to five candidate event ids, each a 20s-timeout
`requests.get` (`src/fpl_client.py:227`), with no retry budget and no circuit breaker.
`tenacity` is in `requirements.txt:11` but unused in `fpl_client.py`. One blocked upstream
burns 100s of a threadpool slot per request.

#### H5. Unmetered LLM spend
Effort: **S** — `grep 'limiter.limit'` across `api/` returns **nothing**: no per-route limit
anywhere. The only control is the bypassable per-IP default (C2). No per-user quota, no spend
ceiling in code.

Caps that *do* exist: `message` bounded to 500 chars (`api/chat.py:34`); output capped
(`max_tokens=1024` `agents/orchestrator.py:164`, `500` `src/explainer.py:7`); turn loops
bounded (6 in `agents/orchestrator.py:161`, 5 in `agents/transfer_agent.py:138`); model never
client-selectable (`api/main.py:2084`, `:2054`).

*Worst-case bill, honestly bounded:* the architecture keeps prompts small — heavy DataFrames
stay in Python and only `top_n=5` tool results reach the model
(`agents/transfer_agent.py:84-89`, `agents/orchestrator.py:137-149`) — so ≈$0.10–0.25 per
`/chat`. The real ceiling is single-vCPU throughput, ~10–60 req/min sustained →
**≈$150–900/hour** from one authenticated attacker.

*Fix:* `@limiter.limit("10/hour")` keyed on JWT `sub` for the four `/chat*` routes and
`/explain`, plus a hard Anthropic console spend cap.

#### H6. `/explain` feeds a client-authored prompt to the LLM
Effort: **S** — `api/main.py:2086` passes the raw request body to `explainer.explain`, which
lifts attacker-controlled `name`/`team`/`position` strings out of unbounded
`starting_xi`/`bench` lists into the prompt (`src/explainer.py:34-48`). No entry-count or
string-length cap. Also `api/chat.py:36` accepts `chips_remaining: Optional[list[str]]` —
arbitrary unvalidated strings reaching the agent prompt (`api/chat.py:312`, `:376`).
*Fix:* derive `recommendations` server-side from `entry_id`; whitelist `chips_remaining`
against the four chip names.

#### H7. Unbounded in-memory caches
Effort: **S** — `_plan_cache` (`api/chips.py:24`), `explainer._cache` (`src/explainer.py:10`),
`_projections_cache` (`api/main.py:233`), `_event_live_cache` (`api/main.py:175`) are plain
dicts with no eviction, each keyed partly on user input. Steady growth to OOM on 512MB.
`cachetools.TTLCache(maxsize=…)` is already a transitive dependency.

#### H8. GitHub secret scanning disabled
Effort: **S** — both public repos (`znader1/FPL`, `znader1/fpl-decision-hub`) have all five
security features off. GitHub has therefore never scanned them and never auto-notified
OpenAI — which is *why* an 8-month live-key exposure went unflagged. Push protection would
have blocked `1eb82b8` at the source. Two `gh api -X PATCH` calls; highest value-per-effort
item in the review.

### MEDIUM

- **M1. Supabase RLS — verified correct.** `profiles` has RLS plus owner-scoped policies on all
  three verbs, and the monetizable `plan` column is locked against client writes
  (`supabase/migrations/20260822090000_lock_plan_column.sql:17-32`). Backend tables
  `player_gw_snapshots` and `chip_plan_snapshots` have RLS enabled with **no policies**
  (`supabase/migrations/20260825_player_gw_snapshots.sql:27`,
  `supabase/migrations/20260902_chip_plan_snapshots.sql:22`) → the anon key reads nothing. The
  browser touches exactly one table, filtered by `userId` (`src/hooks/useProfile.ts:49-52`).
  **The anon key is not enough to read anyone else's rows.** No secret in the shipped bundle.
- **M2. Indirect prompt injection into the projection model.** `src/news_digest.py:247-254`
  interpolates scraped RSS `title`/`summary`/`fpl_takeaways` into a prompt whose parsed JSON
  becomes `availability` / `minutes_mult` multipliers (`:264-269`). A crafted headline on a
  third-party feed could mark a player unavailable. **Latent, not live:**
  `NEWS_KB_DIR = "kb/auto/news"` (`src/config.py:369`) and `kb` is excluded from the image
  (`.dockerignore:15`), so the corpus is empty in prod and `article_count` is 0. It arms the
  instant that corpus is mounted on the data volume.
- **M3. `propose_player_knowledge` makes one LLM call per matched player**, no loop cap, no
  caching (`src/news_digest.py:257-270`) — latency and cost bomb behind
  `/squad-picker/digest-news`, same `kb/` mitigation.
- **M4. Error-shape inconsistency; no stack-trace leakage.** `src/auth.py:113,120,124` return
  `{"error": …}` while everything else returns `{"detail": …}` — the same 401 has two shapes
  depending on route. Unhandled non-`HTTPException` errors bypass `_scrub_server_errors`
  (`api/main.py:150`) and fall to Starlette's plain-text 500, a third shape. **No stack traces
  reach clients** — verified: the handler rewrites every ≥500 detail to a fixed string
  (`api/main.py:159-164`), covering the routes that interpolate exceptions into `detail`
  (`api/chat.py:247`, `api/squad_router.py:37`), and `debug=False` suppresses tracebacks.
- **M5. Input validation — mixed, mostly good.** Verified safe: `horizon_gws` clamped 1–8
  (`api/main.py:1045`), `latest_n_matches` clamped (`:1093-1095`), `free_transfers`/`hit_cap`
  clamped by `src/recommender.py:238-242`, `itb_m` coerced via `safe_float` at all four use
  sites (`api/main.py:1192,1417,1467`), `chips_plan` bounded by `Query(..., ge=1)` /
  `ge=2, le=12` (`api/chips.py:51-52`), replay `season` regex-validated
  (`api/replay_router.py:39`). Gaps: H2 above, and `current_gw` in `api/chat.py:35` unbounded.
  Pandas empty-frame paths at `api/main.py:344,348,1506` all guarded.
- **M6. No 401 recovery in the UI.** `src/lib/authFetch.ts:46` throws `UnauthorizedError`,
  consumed only to suppress retries (`src/App.tsx:38`). No `signOut()` or redirect; an expired
  token renders a permanently un-retryable error card.
- **M7. Prod CSP `connect-src` includes the dev backend**
  `https://fpl-assistant-api-dev.fly.dev` (`vercel.json:9`).
- **M8. Dependencies unpinned, no lockfile.** `fastapi`, `uvicorn`, `anthropic`, `slowapi` all
  `>=` (`requirements.txt:12-18`) — deploys are not reproducible. `pandas==1.5.1` /
  `numpy==1.23.4` pinned but ~3 years stale.
- **M9. `FPL_COOKIE`/`FPL_BEARER` is one operator's FPL session shared across all users**
  (`api/main.py:559-568`). It authenticates only that operator's entry, so for every paying
  customer the pre-deadline path silently degrades to the manual-import fallback.

### Verified safe (code read, not assumed)

CORS `"*"` boot-guard raises at import (`api/main.py:114-117`); docs/OpenAPI disabled unless
`FPL_ENABLE_DOCS=1` (`:53-59`); `build_xpts_evaluation` hardcodes the CSV path and explicitly
refuses client-supplied paths, closing the `read_csv` file-read oracle (`:1553-1560`); admin
keys compared with `hmac.compare_digest`, never read from query or body
(`src/auth.py:99,121-123`).

### Deadline-load verdict

**First failure: threadpool exhaustion via `/chips/plan` at roughly 20–40 concurrent users —
not 100.**

One `shared-cpu-1x`, 512MB, `WEB_CONCURRENCY=1` (`fly.toml:18,38-40`). Every route is a sync
`def`, so requests run in Starlette's 40-slot anyio threadpool against a single shared vCPU
under the GIL. A chip-plan build costs ~60s of that vCPU while holding the process-wide lock
(`api/chips.py:25,61`), and distinct `entry_id`s never share a cache key — builds queue
strictly. Forty users opening the Chips tab inside a minute consume all 40 slots; the 100th
waits ~100 minutes. With the pool full `/health` cannot be served, the 10s Fly health check
fails (`fly.toml:33`), the machine restarts, every in-process cache dies, and the stampede
(H3) replays into the same wall. `min_machines_running = 0` (`fly.toml:29`) means the first
deadline-hour user additionally pays a cold boot plus a cold model build.

**Cheapest mitigation, in order:**
1. `min_machines_running = 1` — one line, removes cold start.
2. Precompute chip plans for all linked entry ids on the existing `refresh-backend.yml` cron;
   make `/chips/plan` cache-only with 202 on miss. Deletes the ~60s synchronous path, no new
   infra.
3. Single-flight locks + stale-on-error on the three cache getters, copying
   `get_event_live_cached`.
4. `--limit-concurrency 24` plus the C3 body cap.

Scaling the box helps only *after* those: per-process caches mean two workers halve the hit
rate, which is precisely why `WEB_CONCURRENCY=1` was chosen (`fly.toml:13-17`).

### Ops gaps

- **No error tracking** — no Sentry or equivalent in `api/`, `src/`, or `requirements.txt`.
- **No logging configuration** — no `logging.basicConfig` anywhere; the root logger defaults to
  WARNING, so `logger.info` at `api/main.py:1543` never emits. No JSON logs, no request ids, no
  way to correlate a user complaint with a log line.
- **Health check is a liveness stub** — `api/main.py:1589-1592` returns `{"ok": True}` without
  touching upstream, cache, or the data volume. Stays green while every real route 502s.
- **No Supabase backups** — nothing in `docs/` covers backup, restore, or retention; migrations
  are applied by hand via the dashboard SQL editor, so schema state is untracked.
- **No rollback runbook** — no documented `fly releases` / `fly deploy --image` path, no
  post-deploy smoke test.
- **Two live deploy targets** until the Azure workflow is deleted (C6).
- **No secrets inventory** — `.env.example` still advertises `OPENAI_API_KEY`, `FPL_PASSWORD`,
  `FPL_COOKIE` (`.env.example:4,8,20`); the only secrets doc is the deprecated
  `docs/production_azure.md`. Nothing states what must be a Fly secret.
- **No pre-commit secret guard** (`gitleaks protect --staged` / `detect-secrets`).
- **`SQUAD_PICKER_MODE=1` is set in production**, exposing a router whose own docstring reads
  "Dev-only squad picker" (`api/squad_router.py:1`).

---

## 2. UX / UI

### Ship blockers

#### U1. A single failed `/events/next` wedges `/app` forever
Effort: **S** — `Index.tsx:179` sets `retry: false`; `:284` returns early on `isError`, so
`selectedGW` stays `null`, `gwResolved` is false, and `:651-655` renders bare "Loading…" with
no error, no retry, no escape. A first-time user has no `fpl_selected_gw` in localStorage
(`:52-61`), so **they are the only ones exposed**. Fly scale-to-zero means one cold-start 502
kills the app. This is also where an expired session lands — worse than the BACKLOG's
"401-retry skeletons": a dead screen, not a slow one. *Fix:* give `nextEventQuery` the default
2-retry policy and render `QueryErrorCard` when `nextEventQuery.isError && !gwResolved`.

#### U2. Every Radix portal renders light theme
Effort: **S** — `dark` is applied per-page on a div (`Index.tsx:648`, `League.tsx:93`,
`SquadPicker.tsx:194`), but portals mount to `document.body`, outside it. Only
`OptimizeSquadDialog.tsx:167` remembered to re-add `dark`. Light-on-dark breakage in:
`MobileParameterDrawer.tsx:28` (the whole mobile drawer), `GameweekNav.tsx:80` (GW picker),
`ParameterForm.tsx:100,124` (horizon + chip selects), `PlayerCard.tsx:208` (score breakdown on
all 15 players), `ParameterSidebar.tsx:72-134`, `Navbar.tsx:99`. *Fix:* put `dark` on `<html>`
in `index.html`, delete the per-page copies.

#### U3. Typing your team ID silently disables the stranger-squad guard
Effort: **M** — `ParameterForm.tsx:77` calls `onEntryIdChange(Number(e.target.value))` on every
keystroke → `Index.tsx:605` → `setEntryAndReset(value)` with **no identity argument** →
`useProfile.ts:88-90` writes `managerName`/`joinedTime` as `null` → `checkEntryIdentity`
returns `"unknown"` (`entryIdentity.ts:47-49`) → **the rollover banner can never fire for that
user.** Only the overlay path (`Index.tsx:632-643`) fetches identity. Typing "588004" also
fires 6 Supabase upserts and 6 squad fetches. *Fix:* commit on blur/Enter; route both paths
through `handleEntryIdSubmit`.

#### U4. Mobile first-run has no visible primary CTA
Effort: **S** — the Recommend button is `hidden lg:inline-flex` on desktop
(`Index.tsx:761`) and `lg:hidden` inside the drawer (`ParameterForm.tsx:185`) — on a phone it
exists *only* behind the sliders FAB (`MobileParameterDrawer.tsx:22`). A new mobile user links
their team, sees a pitch and "Run a recommendation to see projected points…"
(`RecommendationsPanel.tsx:136`), and no button. *Fix:* render the CTA inline in the panel's
empty state.

#### U5. The verdict banner — the product's one piece of advice — is unreadable
Effort: **S** — `RecommendationsPanel.tsx:337` uses `text-emerald-700` on
`bg-emerald-600/[0.08]` over an 8%-lightness background ≈ **2.8:1**; `:394`
`text-emerald-600` ≈ 4.0:1 and `text-red-600` ≈ 3.1:1 at `text-xs`. Same class of bug on the
pitch: `PlayerCard.tsx:69-75` (`text-rose-700`/`amber-700`/`sky-700`) has **no** `dark:`
variant, unlike `getDifficultyClass` at `:44-59` which does. `index.css:94-96` already
documents this exact rule. *Fix:* 300/400-weight shades throughout.

#### U6. The main mobile interaction opens a popup wider than the screen
Effort: **S** — `PlayerCard.tsx:208` — `HoverCardContent className="w-96"` = 384px on a 375px
viewport, and it is deliberately tap-enabled (`:125-136`).

#### U7. The rollover warning is passive, and three pages don't check at all
Effort: **M** — `Index.tsx:712-718` shows the amber banner but still renders the stranger's
squad beneath it and offers no "change ID" action. `League.tsx:51`, `Fixtures.tsx` and
`SquadPicker.tsx` each read their own `entryId` with zero identity check (grep: 0 hits for
`checkEntryIdentity`), and `League.tsx:172` badges `Entry #{entryId}`. *Fix:* block data render
behind the banner, add a re-link button, lift the check into a shared hook.

#### U8. Landing overpromises and claims data that does not exist
Effort: **S** — `Landing.tsx:112` "Win your FPL league"; `Landing.tsx:48` promises "projected
rank gain" — **no rank-gain field exists anywhere in `src/` or `api/`** (grep: only this
string). `Landing.tsx:119-120` claims a "fine-tuned" FPL AI — it is stock `claude-haiku-4-5`
with prompts (`src/explainer.py:6`). The sole uncertainty disclaimer is `Terms.tsx:12`, while
`RecommendationsPanel.tsx:151-156` renders a 4xl "Projected xPts" hero with no framing.
`Landing.tsx:86` still says "Ready for the new season" — the season is live.

#### U9. No deadline, no freshness
Effort: **S/M** — `/events/next` already returns `deadline_time_utc` and `hours_to_deadline`
(`fplAssistantApi.ts:240-242`) and the UI renders neither. Last-refresh exists only as a hover
`title`, only when a GW is live (`GameweekNav.tsx:51-54,110-114`) — unreachable on touch. For
a deadline-driven product this is the cheapest trust win available.

### High-impact polish

- **The "ONE advice" is two clicks deep and invisible on load.** Default tab is `summary`
  (`RecommendationsPanel.tsx:621`); the verdict banner reaches the DOM only via `planSlot` in
  the Transfers tab (`:321`). Before pressing Recommend there is *no* advice at all. ~12
  interactive groups / 30+ controls on `/app`. Make Transfers default once a recommendation
  exists; hoist the verdict above the pitch. **M**
- `GameweekNav.tsx:127-138` — "Proj. xPts"/"GW Pts"/"Rank" labels are `hidden xl:inline`, so
  below 1280px the bar is two unlabelled numbers. `:117-120` — live vs planning is **pure hue**
  on mobile. **S**
- Tap targets under 44px: `GameweekNav.tsx:63,77,97` (28px), `PitchVisualization.tsx:288,299`,
  `TransferPlanner.tsx:230,242,342`, `TransferPlanPanel.tsx:68`. **S**
- The FAB permanently covers panel content — `MobileParameterDrawer.tsx:22` is
  `fixed bottom-5 right-5` and `RecommendationsPanel.tsx:680` has no bottom padding, hiding
  "Apply transfer" (`TransferPlanner.tsx:342`). **S**
- `Index.tsx:648` `h-screen` + `:650` inner `overflow-y-auto` — use `dvh`; on iOS the bottom
  sits under the toolbar. **S**
- Overflow at 375px, no `flex-wrap`/`overflow-x`: `RecommendationsPanel.tsx:384-398,416-430`;
  `TransferPlanner.tsx:296-316`; `ChipRoadmapPanel.tsx:20-31,43-61`; `TeamStrengthGrid.tsx:196`;
  `PlayerListPanel.tsx:95-96` (7-col table, no `overflow-x-auto`). **S each**
- Nameless form controls: `SquadPicker.tsx:617-635` — the `Field` helper renders `<Label>` as a
  *sibling* with no `htmlFor` and no child `id`, making ~14 controls anonymous;
  `ParameterForm.tsx:89-131` selects and `:152,167` switches likewise; `ParameterSidebar.tsx:150`
  collapse button has no accessible name; `GameweekNav.tsx:77` sets `focus:ring-0` with no
  replacement. **M**
- Hover-only help unreachable on touch: `SquadPicker.tsx:625` (12px `Info` trigger is the only
  doc for every advanced field), `ParameterSidebar.tsx:78-105` (`div` triggers, no `tabIndex`),
  `PlayerCard.tsx:170,188,195` (FDR / "Live points" / "Projected points" only in `title`). **M**
- Jargon shipped raw: `PitchVisualization.tsx:307` **"ZN Pick"** (developer initials);
  `TransferPlanner.tsx:217` "ITB after moves"; `TeamStrengthGrid.tsx:255` "as_of:";
  `SquadPicker.tsx:281-283` `<option>free_hit</option>`; `:425` "Basis ppg";
  `PlayerCard.tsx:79-83` prints backend column names. `xPts` appears in 13 files and is defined
  only inside a hover card (`PlayerCard.tsx:228`). **S/M**
- `GET /fixtures` doesn't exist — `api/main.py:1602` has only `/fixtures/difficulty`, while
  `.env`/`.env.example` set `VITE_FPL_FIXTURES_URL=/fixtures?event_id={event_id}`. Fixture chips
  silently vanish. **S**
- `npm test` is red: `vitest.config.ts` has no `include`/`exclude`, so it collects
  `.claude/worktrees/chip-planner-frontend/**` → 9 failures from a stale worktree.
  `npm run typecheck` passes clean. **S**
- `Auth.tsx:185` `signUp` omits `emailRedirectTo` while `:78` `resetPasswordForEmail` sets it —
  confirmation links depend entirely on the Supabase Site URL. **S**
- `Index.tsx:396` writes `differential` to localStorage but it is absent from the effect's deps
  (`:401-402`), so toggling it alone never persists. **S**

### What is already good — do not touch

The GW-substitution handling is genuinely well-reasoned: never mutating GW state from a
response, the explicit banner (`Index.tsx:331-371`), the off-season card gated on `isSuccess`
not `isFetched` (`:431`), and the next-event latch guard that prevents a transient outage from
pinning users to GW38 (`:279-284`). `UnauthorizedError` + retry-disabling
(`authFetch.ts:46`, `App.tsx:38`) is the right shape — it just needs a sign-in CTA instead of a
dead Retry. `parseEntryIdInput` accepting a pasted URL (`entryId.ts:13`), the onboarding overlay
copy and its "Draft my squad" escape hatch (`PitchVisualization.tsx:374-421`),
`joined_time`-not-team-name rollover logic (`entryIdentity.ts:25-36`), the `Terms.tsx:12`
disclaimer, `League.tsx` mobile layout, the `vercel.json` CSP, `aria-hidden` on pitch markings,
`PlayerCard.tsx:130-142` keyboard handling.

---

## 3. Commercial

### The core problem

Fantasy Football Hub **Starter is £29.88/yr promo** (£59.76 list) and already ships chip + team
planning, AI transfers, a price predictor and live rank
([/member-upgrade](https://www.fantasyfootballhub.co.uk/member-upgrade)) — **plus a "win your
mini-league or your money back" guarantee** ([/join](https://www.fantasyfootballhub.co.uk/join)),
which is this product's stated positioning (`docs/launch_comms_plan.md`) with a refund attached.

So the wedge is **not** "chip planning exists". It is EV-per-candidate-GW with expiry-aware
windows plus a quoted roll-vs-move counterfactual (`src/chip_advisor.py`,
`src/transfer_planner.py`). Real, but thin — and invisible on a landing page. It only shows up
in use.

### Where it genuinely wins

- **The roll-vs-move counterfactual.** Every first-GW spend is compared against banking the FT
  and playing a double next week, both nets quoted, never hit-funded
  (`src/transfer_planner.py`). Under the 2026-27 five-FT banking rule this is the most valuable
  unmodelled decision in FPL, and no competitor surfaces the counterfactual explicitly.
  **This, not chip timing, is the lead feature.**
- **Chip timing as EV, not a planner UI.** `src/chip_advisor.py` does per-chip EV per candidate
  GW with expiry-aware windows, an urgency ramp, a structural zone beyond the horizon, and a
  Poisson `haul_prob` for TC — deeper than Hub Starter's planner, *once the clamp bug is fixed*.
- **League-ownership-adjusted differential EV.** `src/ownership_ev.py` uses *league* ownership
  for the `(1 − ownership)` multiplier and *global* for the template baseline
  (`src/config.py:493`). More correct than "differentials = low global ownership", which is what
  most tools ship.
- **The published knowledge file** (`data/models/knowledge_discount.json`) as a transparency
  loop. Nobody publishes their hand adjustments. Cheap, and the only moat competitors won't copy.

### Bear case

1. **Thin wedge vs a guaranteed incumbent** — above. Also **FPL Copilot**
   ([fplcopilot.com](https://fplcopilot.com/)) markets an "AI-Powered FPL Optimizer" with
   expected points *and* chip strategy — closest feature match found; price unverified.
2. **The chip optimizer is currently tuned to say "hold."** `src/config.py:246-269` documents it:
   `CHIP_PLAN_MIN_EV["wildcard"] = 120.0` was set *"well above the observed (still-noisy)
   ceiling so WC reads 'hold'"* because a *"clearly-wrong cheap cluster (3 Hull City defenders,
   all pinned at the clamp) reads as equally valuable as Haaland/Saka."* The TC/BB floors
   (15.0/10.0, `:237-241`) came from **one live spot-check on one entry on 2026-09-02**; the FH
   floor is *"flagged for a follow-up backtest rather than guessed at here."* Charging for a
   chip-timing product whose thresholds suppress its own output to mask an upstream projections
   bug is the single weakest point in the commercial case.
3. **Model credibility is n=1.** The public track record is one Substack post claiming a personal
   top-75K finish (`docs/substack_top75k_part1.md:3`). The minutes model failed its own backtest
   and is off (`src/config.py:488`); the September tunables are unbacktested; realized-advice
   scoring does not exist. Compare: FPL Review publishes a per-GW projection file the community
   has stress-tested for years at €3.90/mo; Hub claims measurable outperformance; Scout sells a
   decade of named-manager editorial. All three anchor on something checkable.
4. **Two landing claims are not implemented** — see U8. Free, these are puff. Paid, they are
   consumer-protection exposure and the first thing a hostile Reddit thread finds.
5. **Churn shape destroys monthly LTV** *(modelled — no public data found on mid-season FPL
   attrition)*: August peak → ~−5%/mo Sep–Dec → a 35–45% cliff Jan–Feb as dead ranks disengage →
   25–35% of the August cohort surviving to May → ~zero Jun–Jul. A £4.99/mo sub with a ~3.5-month
   average paid life yields **£17.50 LTV**. That is the entire argument for a season pass.
6. **The LLM tap is open** — see H5. No per-user quota, no prompt caching anywhere
   (`cache_control` absent from `src/`, `agents/`, `api/`), so every orchestrator question
   re-pays full input on Sonnet 4.6 (`agents/orchestrator.py:33`). FPLai caps at 100
   analyses/month; ChatFPL meters messages explicitly.
7. **Single-founder deadline fragility** — see the load verdict. Plus: every FPL
   entry/league/live path raises a hard error on DataDome 403 with no fallback
   (`src/fpl_client.py:138,173,196,228,240,256,269`). A DataDome rule change at 23:00 Friday is
   a total outage for paying customers while you sleep.
8. **Legal: low-moderate, and payment does change it.** Premier League Terms of Use, IP section:
   *"The Website and App must not be used in any other way, including for commercial purposes"*;
   *"No rights are granted to use any of [the trade marks, logos and brand names] without the
   prior written permission of the owner"*
   ([premierleague.com](https://www.premierleague.com/en/terms-and-conditions)). Charging moves
   you from tolerated hobby scraping to plainly commercial re-utilisation. Enforcement has been
   effectively nil against Scout/Hub/Fix/FPL Review for a decade, so the realistic worst case is
   a takedown or API block, not litigation. The riskiest asset is not the data — it is the brand:
   "FPLedge" with an "FPL" logo badge (`Landing.tsx:313-315`). Trademark is far easier to act on.
   Disclaimers exist (`Landing.tsx:317`, `Terms.tsx:20`) and help.

### Competitor prices (2026-27)

Every row below has a fetched source. Rows marked *unverified* were not confirmable.

| Product | Tier | Price | Billing | Source |
|---|---|---|---|---|
| **Fantasy Football Scout** | Assistant Scout | Free | — | [/pricing](https://www.fantasyfootballscout.co.uk/pricing) |
| | Chief Scout | £10/mo (£5 first mo, code FFS5) | monthly | same |
| | Chief Scout annual | **£50/yr** (was £120) | annual | same |
| | Mega Bundle (+ ad-free LiveFPL, Mini League Mate, Premier Fantasy Tools) | **£100/yr** (was £206) | annual | same |
| **Fantasy Football Hub** | Starter | £59.76/yr list → **£29.88/yr** promo | annual | [/member-upgrade](https://www.fantasyfootballhub.co.uk/member-upgrade) |
| | Pro | £95.76/yr list → **£47.88/yr** promo | annual | same |
| | Ultra | £359.76/yr list → **£179.88/yr** promo | annual | same |
| | monthly-only points | *unverified* (Stripe IDs exist, amounts unpublished) | — | — |
| **FPL Review** | Premium | **€3.90/mo + VAT** | monthly only | [Patreon](https://www.patreon.com/fplreview/membership) |
| | Dev Supporter | €6.50/mo + VAT | monthly only | same |
| **LiveFPL** | Core site | Free (ad-supported) | — | [Scout /pricing](https://www.fantasyfootballscout.co.uk/pricing) |
| | Premium (iOS) | **£2.99/mo · £24.99/yr** | both | [App Store](https://apps.apple.com/gb/app/livefpl/id6753036580) |
| | Premium (web) | *unverified* (login-gated) | — | — |
| **FPL Form** | — | **Free, donation only** ("currently $60/month" hosting) | — | [/support-fpl-form](https://fplform.com/support-fpl-form) |
| **Planete FPL** | — | *unverified — domain does not resolve* (`ENOTFOUND`) | — | — |
| **Tokvam Transfer Algorithm** | 3 tiers | €3 / €7.50 / €72 per mo + VAT | monthly (−15% annual) | [Patreon](https://www.patreon.com/TransferAlgorithm/membership) |
| **Fantasy Football Fix** | Premium / Premium Plus | **£3.48 / £3.98 per mo billed yearly**; £1 intro to 10 Oct 2026; £295 lifetime | both | [/premium](https://www.fantasyfootballfix.com/premium/) |
| **FPLai** | Pro / Season Pass | £6.99/mo (100 analyses) · **£34.99 to 31 May 2027** | monthly / one-off | [fplai.app](https://fplai.app/) |
| **ChatFPL.ai** | Free / Premium / Elite | Free (20 msgs) · £7.99 (100) · £14.99 (500) per mo | monthly | [chatfpl.ai](https://www.chatfpl.ai/) |
| **FPL Pulse** | Free / Pulse Pro | £0 forever · **£2.99/mo or £24.99/yr** | both | [fplpulse.com](https://www.fplpulse.com/) |
| **FPL Copilot** | Pro | *unverified* — Stripe weekly/monthly/yearly, no published price | — | [fplcopilot.com](https://fplcopilot.com/) |
| **Premier Fantasy Tools** | Supporter | **£17.49/yr** (from £24.99) · **£3.39/mo billed** (£2.39 effective) | both | [/register](https://www.premierfantasytools.com/membership-account/register/) |
| **fpl.team** | Wonderkid / Veteran | £2.49 / £4.99 mo; £2.08 / £4.16 annual | both | [/subscribe](https://fpl.team/subscribe/) |

**Positioning map:** free/donation floor (FPL Form, LiveFPL core, FPL Pulse free, r/FPL sheets)
→ £2–4/mo utility (Pulse Pro, fpl.team, Premier Fantasy Tools, FPL Review, Tokvam, Fix) → £7–10/mo
tools+content (FPLai, ChatFPL, Scout monthly) → **£29.88–£100/yr season bundles (Hub
Starter/Pro, Scout, FPLai) — the band being entered** → £180–360/yr concierge (Hub Ultra).

### Recommended pricing

**Free (acquisition).** The xG fixture ticker and team attack/defence ratings, the full xPts
table, a one-GW lineup + captain pick, the published knowledge file and changelog, and a public
accuracy page. Give away everything that generates a screenshot.

**FPLedge Season Pass — £29, one payment, valid to 31 May 2027. Launch at £19 for the first
300**, honoured at 2027-28 renewal. Treat £19 as the real launch price, not a discount: at £29
you ask a stranger to match Hub Starter with no track record, no experts and no guarantee.
**Match the money-back promise** — a refund is cheap when breakeven is 16 users, and it
neutralises Hub's strongest conversion lever.

No monthly option in year one: modelled monthly LTV is ~£17.50 and arrives *after* the January
cliff, whereas £29 collected in August removes churn management from a one-person operation.

**Behind the paywall:** the roll-vs-move counterfactual (lead with this), chip-timing EV curves
with expiry windows, mini-league differential EV + captain-differential, and AI chat **metered
at 100 questions/month**.

**Willingness to pay.** Mini-league rivals (bragging rights in 8–20 person WhatsApp leagues —
the emotional driver, and why league-specific output is inherently shareable), cash-league
players (a £20 entry makes £29 trivially rational), and top-10k chasers (smallest, most
demanding, already paying FPL Review / Tokvam). The ceiling for a hobby decision tool with no
guarantee is **~£35/season, ~£10/mo**; Scout at £50/yr and Hub Ultra at £180/yr clear it only on
brand and human experts.

**The one-sentence "why pay when free exists":** *"Free tools show you the numbers; FPLedge tells
you the single move to make this week, what banking your transfer instead is worth, and which
gameweek to burn each chip — and publishes every call it got wrong."*

### Revenue model

**Assumptions:** 9-month season; £29 pass; Stripe UK 1.5% + 20p domestic / ~2.5% + 20p mixed
international → **net ~£28**; Vercel Hobby is non-commercial so Pro is required once charging;
Supabase Free pauses after 7 days idle so Pro is required; usage ≈ 6 chat questions + 2 explains
per active GW over ~25 active GWs; LLM capped at 100 questions/month.

**Fixed stack, monthly:** Fly.io `shared-cpu-1x`/512MB ≈ $3.32 + volume ≈ **$4** · Supabase Pro
**$25** · Vercel Pro **$20** · domain ~$1.50 → **≈ $50/mo ≈ £39/mo ≈ £350/season.**
Step-function risk: `/chips/plan` costs minutes of CPU on one shared vCPU
(`src/config.py:233`, `fly.toml:18`), so ~200 concurrent pre-deadline users forces a bigger
machine (+£40–60/mo).

**LLM variable cost:** Haiku 4.5 $1/$5 per MTok, Sonnet 4.6 $3/$15. One orchestrator question ≈
Sonnet 8k in + 600 out ($0.033) + two Haiku specialists ($0.020) ≈ **$0.053**; one `/explain`
(Haiku, 500-token cap, `src/explainer.py:6-7`) ≈ **$0.012**. Per active GW ≈ $0.34 → **£8–10/season
uncapped**, £25–30 for a power user, **£4–5 with the 100-question cap**. Prompt caching would cut
input spend materially and is not implemented.

**Contribution per season pass: £28 − £5 capped LLM − ~£1 marginal infra ≈ £22.**

| Milestone | Paying users | Note |
|---|---|---|
| Cover fixed stack (£350/season) | **16** | reachable from your own leagues — not evidence |
| Stack + bigger deadline machine (£850) | **39** | real infra breakeven at scale |
| £5,000/season | **228** | ~11k–23k free signups at 1–2% conversion |
| £20,000/season side income | **910** | ~45k–90k free signups |
| £50,000/season salary | **2,275** | 1.4–2.8% of the ~8.2M registered 2026-27 managers |

**Honest read:** breakeven is trivial (16); a salary is implausible in year one (2,275).
Realistic year-one band is **100–400 paying users ≈ £2,200–£8,800 contribution.** Price is not
the constraint — at £19 or £39 the answer is the same order of magnitude. **Distribution is.**

### The kill question and the 4-week test

**Will strangers — not your mini-league — pay for roll-vs-move and chip timing when Hub Starter
is £29.88 with a refund guarantee?**

**The test (GW4–GW7, ~£0).** Turn on Stripe. Flip `BETA_ALL_ACCESS` to `false`
(`src/lib/entitlements.ts:15`) and paywall exactly three things: the roll-vs-move
counterfactual, the chip-timing planner, the mini-league differential panel. Price £29 season /
£19 founder, with a money-back promise. Drive it **only where nobody knows you** — one
r/FantasyPL data post per deadline week, plus the Substack. Count **paid conversions from cold
traffic**:

- **≥25 paying strangers** → double down.
- **10–24** → real but thin against a guaranteed £29.88 incumbent; stay content-led, quit nothing.
- **<10** → stop selling; keep it as a personal tool and writing asset.

**Run in parallel, free.** Score the `chip_plan_snapshots` rows already collected for GW1–GW7.
Was "roll" right? Did the recommended chip GW beat the alternatives? If seven GWs of your own
recorded advice cannot beat a naive baseline, no price is defensible.

**Minimum evidence before taking money.** Run the season backtest of the September tunables;
expose `/evaluation/xpts` (`api/main.py:2090`) as a public dated accuracy page with MAE +
captain hit-rate versus a named baseline; and delete "projected rank gain" and "fine-tuned"
from the landing page today, paid or not.

---

## Provenance

Three independent agents, read-only, every claim code-cited. Two self-corrected mid-run: the
security agent downgraded the leaked-key finding from Critical to Low after a full object-DB
scan proved the key revoked and the live keys never committed; the pricing agent retracted three
price rows (and one fabricated competitor) that had been filled from search snippets rather than
fetched sources. The table above is the post-verification set — treat any row marked
*unverified* as exactly that.
