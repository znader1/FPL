# Sessions 2026-09-16/17 — Transfer Decision Card + Chips fixture context (shipped)

Handoff note for the next working session. Everything below is in prod as of
2026-09-16 ~21:20 UTC (backend `master` = `269b91e`, frontend `main` = `02de56d`).

## What shipped

### Backend (`FPL`, 10 commits on master)
- `transfer_plan_horizon.verdict_detail` — structured verdict beside the old prose
  `reasoning`: `action`, `horizon{start_gw,end_gw,n}`, `ft_before/after`, `threshold`,
  `moves[{sell,buy,position,this_gw_gain,horizon_gain,forced_injury,h2h_conflicts}]`,
  `this_gw_gain`, `horizon_gain`, `hit_cost`, `plan_net`, `roll_alternative`, `next_move`,
  `runner_ups[...+clears_bar]`. `reasoning` is now one clause and has no consumer on a new
  frontend (kept as version-skew fallback).
- `src/plan_merge.py` — the plan's first-GW moves lead `transfers.moves` with `in_plan: true`,
  so `squad_with_transfers_steps[k]` (what "Apply" uses) applies the recommendation. Beam
  survivors follow; the beam's own `transfer_count_built` / `remaining_itb` keep their meaning.
- Runner-ups (`_ranked_swaps`, `TRANSFER_PLAN_RUNNER_UPS=5`): best swap per seller on the
  original first-GW squad, XI-aware scoring, positive gains only, distinct buys, max 2 per
  position, chosen buy excluded, `clears_bar` per positional bar. Roll verdicts list the best
  swaps that all failed the bar.
- `src/seed_models.py` + Dockerfile/.dockerignore — the git-tracked `data/models/*.json`
  seeds (team-ratings seed, 2025-26 ratings, knowledge file) ship in the image at
  `/app/seed/models` and are copied into the volume on boot only when absent. Before this,
  NO server had the team-ratings seed (Docker excluded `data`, the volume shadowed `/app/data`).
- `refresh-backend.yml` — also refreshes staging (`FPL_DEV_API_BASE_URL` / `FPL_DEV_ADMIN_KEY`
  repo secrets; step skips when empty, `continue-on-error`).

### Frontend (`fpl-decision-hub`, main)
- `DecisionCard.tsx` — action chip, move line, `+x this GW · +y over GWa–b`, plan vs roll nets,
  ITB after, Apply → Applied/Undo, "Also considered" runner-ups (3 visible + show more),
  legacy prose banner only when `verdict_detail` is absent. `fmtGain`/`gwRange` exported.
- `HorizonTransferPlan` — one closed `<details>`: `Plan GW5–7 · N moves · net +x`.
- `TransferPlanner.tsx` — shell only (title + plan slot). Beam alternatives no longer rendered.
- `HotTargets.tsx` — extracted; rendered on the Watchlist tab.
- Removed: "not in plan" badge, quick-option Apply/Reset/Moves/Gain/ITB badges, GW/FT header
  badges, `canApplyNextTransfer`/`onApplyNextTransfer` plumbing.

Tests: backend 479, frontend 140. Specs/plans in `docs/superpowers/{specs,plans}/2026-09-16-*`.

## Environment facts learned today (don't relearn)
- **Local laptop had only 2025-26 history files.** Any local engine run before the refresh was
  wrong (Mount projected as a 73-min starter). Refresh locally with
  `fpl_refresh_next_gw.refresh_next_gw_snapshot(out_base="data/processed")` +
  `api.main.refresh_match_history(bootstrap, fixtures)` before quoting numbers.
- History pickers (`find_latest_*`) choose newest by mtime — fine on servers, fragile locally.
- Staging pair: preview `https://fpl-decision-git-feature-decision-card-ziad-naders-projects.vercel.app`
  (Vercel SSO gate, then app login) → `fpl-assistant-api-dev` (now has `ODDS_API_KEY`; CORS list
  = that alias + `fix-auth-token` alias + localhost 5173/8080). Dev admin key was pasted in chat →
  **rotate**: `fly secrets set FPL_ADMIN_KEY=… --app fpl-assistant-api-dev` AND
  `gh secret set FPL_DEV_ADMIN_KEY -R znader1/FPL`.
- User entry_id 107342. Supabase project `tetvymwgpaordnmsnneo` shared by preview + prod.
- Why Barry edged Calvert-Lewin on staging after seeds: Leeds face ARS(A)/MUN(H) in GW6-7,
  last-season ratings make those defences stronger; Everton face IPS(H). Margin ~0.4 pts, noise.

## Open items / next session candidates
1. **Sub-project 2 (engine), first item: zero-minutes gate.** Players with 0 minutes across
   N≥3 finished GWs and no positive news still get ~1 xPts/GW from priors (Mount). Rule +
   backtest gate (`scripts/backtest_season.py --smart-transfers`, season points is the gate).
2. FT-banking 5-cap + chip survival (roadmap B2); `min_gain` calibration; hit valuation.
3. `this_gw_gain` on plan moves is raw (buy − sell GW xPts) while `horizon_gain` is XI-aware;
   consider making the GW slice XI-aware too.
4. Runner-up tie-break: for equal gain prefer selling the displaced (weakest) player so the
   line reads "Brobbey → Barry" not "João Pedro → Barry".
5. Non-cumulative apply for a runner-up (currently informational only).
6. Frontend follow-ups: move `fmtGain`/`gwRange` to `src/lib` (react-refresh warnings),
   375px visual pass, `_first_transfer(plan)` helper backend-side.
7. Sub-project 3 (chips): score `chip_plan_snapshots` GW1-7, WC min-EV retune.
8. Sub-project 4 (ship): Google sign-in, FPL data/ToS position, audit gate-1 leftovers,
   evidence gate. Prod admin key is not in the repo or local `.env`.

## 2026-09-17 addendum — chips branch landed (prod: backend `e3b3960`, frontend `5b6bdbc`)

Cloud-session branch `claude/chips-fixtures-points-projection-a0r34t` reviewed, fixed, merged:
- European weeks + cup clashes (`src/european.py`, seed `data/models/european_calendar.json`).
  Team map filled 2026-09-17: UCL ARS MCI MUN AVL LIV · UEL BOU SUN CRY · UECL BHA. `cup_rounds`
  still empty (enter FA Cup / EFL Cup dates when drawn). Delete a club when knocked out.
- Per-GW points distributions (`src/chip_distribution.py`): pmf mean = xPts MINUS continuous share;
  axis = MAX_POINTS×n_fixtures (bench convolved on 4×); `p80_open`; bar scaled onto the pmf axis for
  `p_beats_bar`; BB payload omits per-player return/haul/blank. Review fixed a Critical (modal pinned
  at 30 on DGW rows) + bar-axis mismatch + BB thresholds + `days_before`. Deferred F4 (weak-bench
  appearance-mass floor inflates BB pmf mean) — TODO in the module.
- Frontend: fixture-context strip, likelihood badges, distribution line; hotfix `5b6bdbc` clamps
  calendar badges (`N in Europe`) and stops Europe-only weeks counting as "notable".
- Seed-file gotcha: `ensure_seed_models` never overwrites — to push a changed seed to a server,
  `fly ssh console --app <app> -C "rm /app/data/models/<file>"` then deploy.

### Why no Wildcard / Free Hit recommendation (user question, answered 2026-09-17)
- WC: EV = best 8-GW squad − (your squad + planned free transfers over 8 GWs). Planned transfers are
  credited in full (+70.7 for entry 107342) so WC EV is never positive; bar 120 on top. Both were set
  to suppress WC while the promoted-team clamp bug stood; that bug is fixed → **retune is due**.
- FH: gate = ≥3 starters blank or ≥6 on tough fixtures; nothing in GW5–12; cup dates empty so no
  provisional beyond-horizon hold either.

### Next session — sub-project 3 (chips), proposed order
1. WC: compare against a realistic transfer plan (discount planned gains / cap at reliable 1-FT value);
   set `CHIP_PLAN_MIN_EV["wildcard"]` from the 2025-26 backtest, not by hand.
2. Season priors as provisional guidance: FH "hold for the blank (typ. GW29–33)", BB/TC "hold for a
   double (typ. GW24–26 / GW34–37)", firmed as FPL announces; enter FA Cup dates in `cup_rounds`.
3. Plain-language "why hold" line per chip row (fan vocabulary, not bar/EV-window).
4. Knowledge rail: prod `knowledge_discount.json` is an EMPTY object → consolidate PRs 43/55/56 + the
   repo's HUL entry, merge, then replace the empty prod file once (seeder won't overwrite it).
5. Then sub-project 2 engine items (zero-minutes gate first) and the mini-league enhancements.
