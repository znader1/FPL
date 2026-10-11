# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
npm install        # install dependencies
npm run dev        # dev server on :8080
npm run build      # production build (also type-checks)
npm run typecheck  # tsc only, no bundle
npm run lint       # ESLint
npm test           # vitest run (whole suite)
npx vitest run src/components/DecisionCard.test.tsx   # single file
npx vitest run -t "runner-ups"                        # tests matching a name
```

Tests are Vitest + Testing Library, colocated as `*.test.ts(x)` (plus `src/lib/__tests__/`). Default environment is node — component tests opt into the DOM with a `// @vitest-environment jsdom` pragma on line 1. `vitest.config.ts` restricts `include` to `src/**` because stale `.claude/worktrees/*` checkouts were once collected; keep that.

Other in-repo context: `BACKLOG.md` (prioritised bugs/features), `docs/superpowers/{specs,plans}/` (design docs per feature), `.claude/skills/frontend-design`.

## Environment

Copy `.env.example` to `.env`. Required vars:

```bash
VITE_SUPABASE_URL=...
VITE_SUPABASE_PUBLISHABLE_KEY=...
VITE_FPL_API_BASE_URL=http://localhost:8000   # points to FastAPI backend
```

The Vite dev server proxies `/squad`, `/recommendations`, `/fixtures`, `/chips` to `VITE_FPL_API_BASE_URL` (falling back to `https://fpl-assistant-api.fly.dev/`; see `vite.config.ts`), so relative URL templates work in dev without CORS issues. The `/squad` proxy bypasses `Accept: text/html` navigations so the dev SPA page at `/squad` still loads. In production, `VITE_FPL_API_BASE_URL` must be set to the Fly.io backend URL.

Endpoint URLs are resolved in `fplAssistantApi.ts` via `getEnvString()` (dynamic `import.meta.env[key]` lookup — grepping `import.meta.env.VITE_FPL_` finds nothing). Each `VITE_FPL_*_URL` template is optional and defaults to the backend route; `VITE_FPL_RECOMMENDATION_URL` and the older `VITE_FPL_TEAM_RECOMMENDATION_URL` are both accepted.

Dev-only flags (never set in production): `VITE_REPLAY_MODE=1` (+ `VITE_REPLAY_ENTRY_ID`) enables `/replay`; `VITE_SQUAD_PICKER=1` enables the old `/squad` bookmark. Both routes are also gated on `import.meta.env.DEV`, so they drop out of production bundles regardless of `.env`.

## Architecture

**Stack:** React + TypeScript + Vite, Tailwind CSS, shadcn/ui, TanStack Query, Supabase auth, React Router.

**Backend:** Separate repo (`FPL/`) running FastAPI on Fly.io. This frontend is purely a consumer — no data processing happens here.

### Request flow

```
Index.tsx (state + TanStack Query)
  → src/lib/fplAssistantApi.ts  (typed fetch wrappers + URL resolution)
  → FastAPI backend (/squad, /recommendations, /explain, /league/*)
```

`fplAssistantApi.ts` is the single API layer. All types (`FplSquad`, `FplTeamRecommendation`, `LeagueStrategyResponse`, etc.) live there. URL templates are read from env vars and interpolated at call time — never hardcode backend URLs in components.

### Auth

Supabase handles auth. `AuthContext` (`src/contexts/AuthContext.tsx`) exposes `session`, `user`, `loading`, `signOut` via `useAuth()`. `ProtectedRoute` (`src/components/ProtectedRoute.tsx`) redirects unauthenticated users to `/auth`, carrying `state.from` so deep links survive sign-in. All `/app/*` routes are wrapped with it in `App.tsx`.

The backend verifies the Supabase JWT, so API calls go through `authFetch` (`src/lib/authFetch.ts`), never bare `fetch`: it attaches `Authorization: Bearer <access_token>` and throws `UnauthorizedError` on 401. The `QueryClient` in `App.tsx` retries twice with backoff (Fly cold starts) but never retries `isUnauthorized(error)`.

`useProfile` (`src/hooks/useProfile.ts`) loads the user's `profiles` row (linked FPL entry id + identity snapshot + `plan` tier). `plan` is read-only on the client (locked by migration `supabase/migrations/*_lock_plan_column.sql`). Feature gating goes through `useEntitlement` / `computeEntitlements` (`src/lib/entitlements.ts`) — components read boolean flags, never plan strings. `BETA_ALL_ACCESS = true` currently grants everything.

### Pages

- `/` — Landing; `/privacy`, `/terms`
- `/auth` — Login/signup (Supabase); `/auth/confirm` email confirmation; `/login`, `/signup` are legacy aliases
- `/app` — Main squad + recommendations (`Index.tsx`)
- `/app/plan/:step` — the GW flow's steps (`transfers | captain | bench | chip | confirm`), rendered by `Index.tsx` so state survives step changes; `/app/captain` redirects to `/app/plan/captain`. See GW plan section
- `/app/league` — Mini-league strategy (mobile-friendly)
- `/app/fixtures` — Fixture Planner (handoff 1c): 6-GW heatmap of the squad, chip windows, weakest links; the old all-teams ticker sits behind an "All teams" `<details>`
- `/app/squad-picker` — Squad picker (lazy-loaded)
- `/replay` — dev-only GW replay (see Environment)

### Key components

- `src/pages/Index.tsx` — owns all state (entryId, GW, chip strategy, applied transfers). Orchestrates TanStack Query for squad, fixtures, next event, and recommendations. User settings persist to `localStorage` under `fpl_*` keys (`fpl_entry_id`, `fpl_selected_gw`, `fpl_chip_strategy`, `fpl_horizon_gws`, …) read/written here; `League.tsx` shares `fpl_entry_id`.
- `src/lib/fplAssistantApi.ts` — all API types and fetch functions. Add new endpoints here.
- `src/components/RecommendationsPanel.tsx` — tabbed panel (summary / transfers / watchlist) + `ExplanationPanel` (Phase 1 LLM rationale, lazy-loads on expand).
- `src/components/ExplanationPanel.tsx` — calls `POST /explain` on first open, caches in component state.
- `src/pages/League.tsx` — calls `GET /league/list` then `POST /league/strategy` with chase/defend/differential mode.
- `src/components/CommandRail.tsx` — desktop left rail: `WeekChecklist` (step navigation), `ProjectedCard`, `ParameterForm` behind a collapsed toggle.
- `src/components/plan/*` — the flow's step views (`TransfersStep`, `CaptainStep`, `BenchStep`, `ChipStep`, `ReviewStep`), `PlanFooter`, `StepChips`, `StepHeader`, `RadioCard`.

### GW selection and flash prevention

`selectedGW` and `squadGW` are typed `number | null`. `getInitialGw()` returns `null` on first load — **do not default to `SAMPLE_SQUAD.event_id`**, that causes a flash of old squad data. All squad/fixtures queries are disabled while `selectedGW === null`. A `useEffect` sets the live GW (`nextEventId - 1`) once `nextEventQuery` resolves — this is the "open on live scores" behaviour. The entire pitch is gated behind `gwResolved = selectedGW !== null`; `resolveGwGateState()` (`src/lib/gwGate.ts`) decides ready/loading/error before that, so a failed `/events/next` shows a retry card instead of wedging on "Loading…".

GW state is **never** mutated from a response. `/squad` can return a different `event_id` than requested (backend substitutes the nearest available picks); render that squad with the informational banner, don't adopt its `event_id` into `squadGW`/`selectedGW`.

### Tab names

The recommendation tab on `PitchVisualization.tsx` is labelled **"ZN Pick"** (not "AI Pick").

### Chips tab (2026-09)

`RecommendationsPanel` has a fourth "Chips" tab: `ChipRoadmapPanel.tsx` renders `GET /chips/plan` (season chip recommendations with EV curves, provisional structural windows, expiry/hold/used states); `ChipNudgeCard.tsx` mounts above the pitch when the plan returns a next-GW nudge and applies via the existing `chipStrategy` state. Since 2026-09-17 the panel opens with a **Fixture context** strip built from `plan.calendar` (one cell per model-zone GW: deadline, `break`/`DGW`/`BGW`/`cup`/`N in UCL` tags with hover detail; notable later weeks behind a `<details>`), TC/BB rows show the chip's extra-points `distribution` (`NN% beats bar` pill, P(return)/P(haul)/P(blank), modal + 80% band), EV-curve bars are shaded by `p_beats_bar`, `Risk:` reasons render amber, and provisional rows with `likelihood < 1` badge `~70% likely` (expected cup-clash blank) instead of `provisional`. `plan.signals.european_calendar === false` shows a "European calendar not configured" hint — the backend's `data/models/european_calendar.json` team map is empty until filled in. Since 2026-09-17 each outlook/recommendation row also carries an optional `guidance` string (plain-language "why hold"/"why play" with a season prior); when present it renders first, above everything else, and the outlook row's engine `reasons` move behind a `<details>` labelled `model detail` — an older backend without `guidance` still gets today's layout. All these fields are optional so an older backend still renders. Chip vocabulary is canonical everywhere (`wildcard | free_hit | bench_boost | triple_captain`) — the backend normalizes FPL's names; the frontend NEVER maps chip names. `FplChipStrategy` includes `bench_boost`/`triple_captain`; only wildcard/free_hit are squad-rebuilding (guards in `Index.tsx` keep that semantics — don't widen them).

### Command Center (2026-10 design handoff, 1a)

`/app` follows the design handoff (`docs/superpowers/specs/2026-10-10-fpledge-redesign-handoff.md`) (1a + shared deadline countdown + 1b Captain Lab + 1c Fixture Planner). Layout on lg+: `CommandRail` (240px, 280px at xl) | pitch column | `RecommendationsPanel` (340px). The rail stacks `WeekChecklist` ("THIS WEEK · n of 4 decisions made", rows derived by `deriveWeekDecisions()` in `src/lib/weekDecisions.ts` — never stored), `ProjectedCard` (plan total + delta vs the no-change squad; percentile ring and benchmark bars only when the backend sends `projected_percentile` / `projected_top10k_avg` / `projected_overall_avg`, which it doesn't yet) and the `ParameterForm` behind a collapsed "Parameters" toggle. `ParameterSidebar` was deleted; phones still use `MobileParameterDrawer` plus a compact checklist strip above the pitch. The navbar (`layout/Navbar.tsx`) shows all app tabs with the active one lit, a `DeadlineCountdown` pill (ticks 1s from `/events/next` `deadline_time_utc`, shares the `["next-event"]` query key, hidden once passed) and an `extras` slot Index fills with FT (and Bank when `entry_history.bank` exists). Pitch starters carry an xPts aura (`PlayerCard` `aura` prop, 30 + xPts × 11 px) and newly applied signings an `IN +x` pill (`src/lib/incomingPlayers.ts`); the bench eyebrow is "Bench". `--fdr-1…5` tokens live in `index.css` (`text-fdr-4` = rose for negatives). `fmtGain`/`gwRange` live in `src/lib/format.ts` (re-exported from `DecisionCard`).

### GW plan + connected flow (v2 handoff, 2026-10-11)

Spec: `docs/superpowers/specs/2026-10-11-fpledge-v2-flow-handoff.md`. **One client-side plan per entry + deadline GW** (`GwPlan` in `src/lib/gwPlan.ts`: `xi`, `bench` [GK, sub1–3], `transfer: "make" | "roll" | null`, `cap`/`vice`, `chip: "none" | ChipName | null` — canonical chip names, never bb/fh/tc — `reviewed`, `locked`). `useGwPlanStore` (`src/contexts/GwPlanContext.tsx`) owns it in Index, provides it via `GwPlanValueProvider`/`useGwPlan()`, persists to `fpl_gw_plan:{entryId}:{gw}`, seeds once from the **latest** squad (the live GW's or later — browsing back to GW20 never reseeds) and reseeds only when the squad's 15 change. Any material patch clears `locked`; `resetPlan()` is the only way back to the seeded squad. **Steps never refetch the squad.** Derived (never stored): `appliedTransferCount = plan.transfer === "make" ? makeMoves(rec).length : 0` (the old `fpl_apply_transfer_count` state is gone; DecisionCard's Apply/Undo write `plan.transfer`); the squad pitch on the deadline GW is `planToTeam()` (`src/lib/planTeam.ts`) of `resolvePlan()` (sell→buy substitution of the verdict's moves, or `roll_alternative.moves` on a roll verdict; a buy with no step-squad record is synthesised from the move with `seller xPts + this_gw_gain`); edits store pre-transfer ids via `toPlanId()`. Projected = `projectPlan()` client-side (XI + captain, TC/BB/FH adjustments; FH gain from the chip plan) with delta vs the seeded squad. `deriveWeekDecisions()` reads the plan: transfers done when `plan.transfer` set, captain done when reviewed and the captain starts (`warn` when benched), bench done when reviewed, chip done when `plan.chip` set — a fresh load is 0 of 4 on purpose. Steps route as `/app/plan/:step` inside Index (`PLAN_STEPS`: squad → transfers → captain → bench → chip → confirm); rail rows / mobile `StepChips` navigate; `PlanFooter` on every step (`footerFor()` in `src/lib/planFlow.ts`: Start/Continue on squad, Next disabled with a hint until Transfers/Chip have a choice, Save GW plan locks, Saved ✓ after). Entering a step with no recommendation for the deadline GW auto-runs ZN Pick once. Transfers step = `transferOptions()` radio cards; Chip step = `chipOptions()` (this week's gain vs best week, used chips disabled); Review = `reviewSummary()` + `reviewWarnings()` + `buildTodo()`; Bench step = `BenchStep` rows + the pitch in swap mode (`PitchVisualization` `starterState`/`onStarterClick`/`incoming` props; rules in `swapCheck`: GK-for-GK, ≥3 DEF/2 MID/1 FWD; `autoSubPreview()` tip). Navbar `planStatus` pill: No changes yet / n unsaved changes (`--warning` amber) / Plan saved; short form below md. `RecommendationsPanel` renders only on the squad step. Not done: the 72% pitch zoom on phones (the pitch's `vh` clamp made it unsafe to apply blind) and the "still to design" states in §6.

### Captain step (`/app/plan/captain`; was the Captain Lab page, handoff 1b)

`CaptainStep` + `CaptainCard` (separate **Make captain / Make vice** buttons, no whole-card click; captaining the vice swaps roles; a benched candidate is dimmed and disabled with a note) derive everything in `src/lib/captainLab.ts` (`buildCaptainLab(rec, goal, plan.cap, { pool, benchedIds, viceId })`): candidates = the three highest-xPts of the plan's 15 (benched ones never the ZN Pick); **Protect rank** → highest `eo_top10k`, **Chase rank** → highest `rank_gain_if_haul`; when only `ownership_pct` (FPL overall selected_by_percent, which the backend now sends — branch `feature/captain-lab-fields` in `FPL-Assistant/FPL`) is present, protect = most owned and chase = highest `p90 × (1 − ownership)` and the tile is labelled "Ownership" instead of "Top 10k EO" (`ownershipBasis`); with neither, both goals fall back to the `is_captain_suggested` player and the page says so under the headline. Range bar (0–20 axis) uses `xpts_p10/p90` when sent, else `score_breakdown.distribution.p80_low/high` (the backend's 80% band *is* p10–p90). Captain and vice are the plan's; the goal persists as `fpl_captain_goal`. Nav tabs are Squad · Captain · Planner · Mini-league · Draft squad (Draft squad hidden from the strip below lg); `activeTabFor()` lights Squad on every plan step except the captain's.

### Fixture Planner (`/app/fixtures`, handoff 1c, 2026-10)

`Fixtures.tsx` renders `FixturePlannerGrid` (a real `<table>`: 15 rows, six GW columns, xPts total) and `PlannerRail` (chip windows, weakest links, FDR legend) at `1fr | 320px`. Pure derivations live in `src/lib/fixturePlanner.ts`: `buildPlannerRows` joins `/squad` players to the `/fixtures/difficulty` ticker by `team_short` (instant: opponent, H/A, band→`fdr` 1–5, DGW count, blank) and overlays per-GW xPts from the recommendation's `fixtures_horizon` once that call lands; `columnTags` reads the chip plan `calendar` (`has_dgw`/`is_blank_heavy`) and falls back to the squad's own cells; `chipWindowsInRange` filters `/chips/plan` recommendations to the displayed GWs and prefixes a squad count line (no EV recomputed); `weakestLinks` = verdict moves + runner-ups with `horizon_gain > 0`, best first. The page fires its own `/recommendations` via `useQuery` keyed `["planner-rec", entryId, gw, horizon]` (chip none, transfers on) — one Fly call per horizon value — so per-GW xPts, totals and weakest links fill in after the grid. Horizon `3 | 6` lives in the URL as `?h=` (default 6, absent); the grid always shows six columns and fades the rest. `/squad` has only single-GW xPts, so totals show "—" until the recommendation answers. `FixtureChip.tsx` is the one fixture pill (extracted from `PlayerCard`). Nav tab is "Planner".

### Transfer Planner panel (one voice, 2026-09-16 density cut; move cards 2026-10)

Since 2026-10 the **DecisionCard** body is the handoff's "Transfer moves" stack: one `TransferMoveCard` per `verdict_detail.moves[i]` (out jersey → in jersey, in-name over `for {out} · Free transfer | −4 hit` — free/hit by position against `ft_before`, the hit bill split evenly — net xPts teal/`fdr-4`, out/in bars on an 18-xPts axis only when `horizonXptsById[sell.id]` is known, one-line reason with `next_fixture`s, and the Apply control: "Apply this move" on the next move, "Apply moves 1–n" further down, Applied + Undo once covered). A roll verdict shows `roll_alternative.moves` as cards netted against `plan_net`, with "Make the move anyway"/"Take the hit anyway" only when the move maps onto `transfers.moves` (`beamMoves` prop) — otherwise no button. Plan-vs-roll reasoning sits in a lightbulb tip box (`data-testid="plan-tip"`). The shell (`TransferPlanner.tsx`) is titled "Transfer moves" with a horizon-sized subtitle. The paragraph below describes what still holds underneath.

The **DecisionCard** (`src/components/DecisionCard.tsx`) is the only advice: it renders `transfer_plan_horizon.verdict_detail` — the action, `+x this GW · +y over GWa–b`, the plan-vs-roll nets, ITB after, and the only Apply/Undo controls (since the v2 flow, Apply sets `plan.transfer = "make"` — all of the verdict's moves at once — and Undo clears it; the index argument is ignored). Every GW range renders inside a `whitespace-nowrap` span so it never wraps mid-string at phone width. Below the nets/Apply row, a `runner-ups` block (present when `verdict_detail.runner_ups` is non-empty) shows the best swap for every other squad player — "Also considered" on spend, "Best available — all below the bar" on roll — numbered from 2 on spend / 1 on roll, first 3 rows visible then a `show N more` `<details>`; rows below the positional bar carry a muted "below bar" tag.
The legacy `reasoning` banner renders only when `verdict_detail` is absent (older backend).
The staircase (`HorizonTransferPlan`) now collapses entirely behind one closed `<details>` — summary `Plan GWa–b · N moves · net +x` (` · N hits` when hits > 0) — so the tab isn't dense with every GW visible; all rows (including later GWs) render inside it, no nested "show the rest" any more. Plan moves may carry `h2h_conflicts` → amber "faces your X" badge. A "Prioritise removing injured players" switch in `ParameterForm.tsx` (default on, persisted `fpl_prioritize_injured`) sends `prioritize_injured` to `/recommendations`; when a move's seller carries availability risk, `sell_availability` renders as an amber fitness chip (`{chance}% fit` or the status word) after the seller on the move card and in `RunnerUpRow`.
**`TransferPlanner.tsx` is now a shell** (title + `planSlot` + loading/empty states only) — the beam engine's own Alternatives list is gone from the UI entirely (it still feeds Apply indexing server-side, just isn't displayed). Hot Targets moved off this tab onto Watchlist: `src/components/HotTargets.tsx` (extracted, same rendering) renders under a "Hot targets" heading in `WatchlistTab`, fed by `recommendation.transfers?.hot_by_position`.

### Vercel preview CORS (recurring)

Every new branch's preview origin must be appended to `FPL_API_CORS_ORIGINS` on BOTH Fly apps (read current value via `fly ssh console -a <app> -C "printenv FPL_API_CORS_ORIGINS"` first — `fly secrets set` replaces the whole list). Permanent fix (backlogged): `allow_origin_regex` in backend `api/main.py`.

### League page

`League.tsx` uses `pt-20 pb-8` (not `py-8`) to clear the fixed navbar height of `h-14`.

### PlayerCard fixture chip

The fixture chip (`fixtureShort`) renders on its **own line** between the player name and points — not inline with the team abbreviation. See `PlayerCard.tsx`.

### Deployment

Vercel auto-deploys on push to `main`. `vercel.json` rewrites all paths to `index.html` for SPA routing. Set `VITE_FPL_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` as Vercel environment variables.

For feature branch testing, create a Vercel preview environment variable pointing `VITE_FPL_API_BASE_URL` at `fpl-assistant-api-dev.fly.dev`.

### Backend endpoints consumed

| Endpoint | Used by |
|---|---|
| `GET /squad` | Index.tsx squad fetch |
| `GET /recommendations` | Index.tsx recommendation mutation |
| `GET /events/next` | Index.tsx next event |
| `POST /explain` | ExplanationPanel |
| `GET /league/list` | League.tsx |
| `POST /league/strategy` | League.tsx |
| `GET /chips/plan` | Index.tsx chip plan query (Chips tab + nudge card) |
| `GET /entry/identity` | entry-id linking (manager/team name snapshot) |
| `POST /squad/optimize` | OptimizeSquadDialog |
| `GET /fixtures/difficulty` | Fixtures.tsx |
| `POST /chat`, `POST /chat/{captain,transfer,chip}` | AiAdvisorPanel |
