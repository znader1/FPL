# FPL Decision Hub — Backlog

Use this file for quick capture and prioritization. If you want collaboration/history, create a GitHub Issue for an item and paste the link next to it.

## P0 — Bugs
- [x] **GW navigation can fail to load** — cause: `/squad` silently substitutes the nearest available GW's picks (200 OK, different `event_id`) when the requested GW's picks can't be fetched (deterministic for future GWs; transient for historical GWs on upstream hiccups), and Index.tsx's snap-back effect adopted that returned `event_id` into `squadGW` while `selectedGW` stayed put — desyncing GW nav from the rendered squad with no indication shown. Fixed frontend-side: GW state is never mutated from a response; a substitution now renders the returned squad with an explicit informational banner ("Showing your latest squad (GW X) — your GW Y picks aren't available yet."), and hard failures keep the retryable `QueryErrorCard`. Details + proposed backend patch in `.superpowers/sdd/task-7-report.md`.

## P1 — UX / Cleanup
- [x] **Remove debug UI** (Entry ID / Requested GW / Returned Event ID / Request URL boxes) or gate behind a `VITE_SHOW_DEBUG=true` flag.
- [x] **Remove “notes” from UI** (e.g., backend `transfers.note`) for production.

## P2 — UI Polish
- [ ] **Pitch background colors**: make it more FPL-like (palette + lines + subtle texture).

## P1/P2 — Features (Backend-driven)
- [ ] **Multiple transfer suggestions** (group by position; show `score_gain`; show remaining ITB).
- [ ] **Constraint warning**: ensure no more than 3 players from the same team (ideally enforced in backend; also show a UI warning if violated).
- [ ] **Captain recommendations**: show captain/vice ordering/rationale from backend.
- [ ] **Bench order**: render bench priority from backend (and show suggested order vs current, if applicable).

## API Contract (Checklist)
- [ ] Confirm `include_transfers` query param name and behavior.
- [ ] Add a “current GW” source (backend endpoint or bootstrap cache) so the default GW doesn’t depend on sample data / localStorage.

## P1 — Ops & UX hardening (from the GW3-deadline incident, 2026-09-04)
- [ ] **Warm the chip-plan cache from the refresh cron** — first `/chips/plan` build per entry costs ~a minute of CPU; the twice-daily refresh (and `CHIP_SNAPSHOT_ENTRY_IDS`) should precompute it so no user ever pays it interactively.
- [ ] **Auth expiry must not look like eternal loading** — an expired Supabase session produces 401-retry skeletons; `authFetch` should bounce to `/login` on 401 (and queries should surface the retry card faster).
- [ ] **Mobile smoke tests in CI** — the pitch-collapse regression shipped silently; add Playwright viewport checks (375px + desktop) for /app render.
- [ ] **`/fixtures?event_id=` 404 spam** — the frontend calls a backend route that doesn't exist (only `/fixtures/difficulty` does); either add the route or drop the client calls.

## P2 — Model validation & benchmarking (added 2026-09-04)
- [ ] **Season backtest of the September tunables** — replay last season through the backend's SP3 backtest harness to validate what was tuned live-only: early-season shrinkage (`PROJ_SHRINKAGE_GAMES`, `PROJ_PRICE_PRIOR_SLOPE`), positional FT bar (`TRANSFER_PLAN_POS_GAIN_MULT`), XI-aware planning (`TRANSFER_PLAN_XI_AWARE`), and chip thresholds (`CHIP_PLAN_MIN_EV`, FH blank gate).
- [ ] **Outcome scoring from `chip_plan_snapshots` (Supabase)** — the table already captures pre-deadline chip/transfer recommendations + post-GW actuals for entries 107342 and 5645321 (twice-daily cron). Once enough GWs accrue: score the advice against realized points — was “roll” right, did the recommended chip GW beat the alternatives, realized vs projected EV.
- [ ] **Expert-article benchmark** — each GW, compare the model’s pre-deadline advice (transfers, captain, chip) against published expert/community advice (scout picks, chip articles). Backend already has news-ingestion plumbing to build on (`src/news_fetch.py`, `src/news_digest.py`). Store the expert picks alongside `chip_plan_snapshots` for the same GW so a hit-rate comparison (model vs experts vs actuals) falls out of one query.
- [ ] **Upstream projections outlier** — promoted-team small-sample cluster (e.g. Hull GKP/DEF projecting identically at premium levels) inflates every EV surface; shrinkage + clamp are stopgaps, root fix belongs in `src/projections.py` team-level inputs.
- [ ] **Strategy-aware hedge penalty** (2026-09-04) — the head-to-head conflict nudge (`TRANSFER_H2H_CONFLICT_PENALTY`) is a variance preference, not an EV fix: opposing own players hedge (lower ceiling, higher floor). Tie its sign/size to the mini-league mode — chase = penalize hedges harder, defend = allow or even favor them (`src/league_strategy.py` already has chase/defend/differential).
- [ ] **Per-player home/away splits** (found 2026-09-04 via the Palmer question) — the model applies one global home-advantage multiplier; a player's personal home record (e.g. Palmer at Stamford Bridge) is invisible. Per-GW history carries venue — derive a per-player home/away factor with shrinkage, blend into projections behind a config flag, validate via SP3 backtest.

