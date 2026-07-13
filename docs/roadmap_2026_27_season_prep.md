# Roadmap: 2026/27 Season Prep & Path to a Sellable Product

**Window:** July 13 → August 10, 2026 (4 weeks, ends before the expected GW1 deadline in mid-August)
**Goal:** the FPL Assistant survives the season rollover, gets multi-user + payments plumbing, and launches as a paid beta before GW1.

---

## Where the product stands today

What already works (and is the moat):

- FastAPI backend on Fly.io (`fly.toml`, lhr region) with a Lovable frontend.
- Projection engine (`src/projections.py`) blending PPG + form + fixture/home/opponent context.
- Transfer planner with beam search (`src/recommender.py`), lineup/chip optimizer (`src/optimizer.py`) for wildcard and free hit.
- LLM layer: `/explain` rationale and `/league/strategy` (chase/defend/differential) via Anthropic.
- Evaluation loop: `/evaluation/xpts` (MAE, RMSE, bias, rank correlation) + `scripts/backtest_baseline.py`.

What blocks selling it:

1. **Season rollover.** Player IDs reset, `form`/`points_per_game` are 0 in early GWs — the projection model is cold-start blind. History data (`player_gw_history`) is all 2025/26.
2. **Single-tenant.** One shared `FPL_API_KEY`, one default `FPL_ENTRY_ID`. No users, no accounts, no billing.
3. **No product surface.** No onboarding, pricing, or paywall; no monitoring; Fly scales to zero (cold starts for paying users).

The 4 weeks map to those three blockers, in that order — **the model being right in August is the product**; billing without a working GW1 recommendation sells nothing.

---

## Week 1 (Jul 13–19): Season rollover + data foundation

The 2026/27 game typically goes live on the FPL site in early/mid July. Everything this week is about being correct on day one.

- [ ] **Verify the 2026/27 API is live** and diff the payloads: new `events`, new `teams` (3 promoted sides), new element fields or scoring-rule changes (check `bootstrap-static.game_settings` and any new stat columns — FPL has added rules in recent seasons, e.g. defensive contributions).
- [ ] **Archive 2025/26 data** (raw + `player_gw_history` CSVs) to a `2025-26/` folder on the Fly volume before any refresh overwrites it.
- [ ] **Cross-season player mapping.** FPL element `id` resets each season but `code` is stable across seasons. Build `src/season_mapping.py`: `code → (id_2025_26, id_2026_27)`, with name+team fuzzy fallback for edge cases. Everything in week 1 depends on this.
- [ ] **Cold-start projections.** Until ~GW5, `form=0` and `ppg=0` make the current baseline useless. Add a prior layer to `src/projections.py`:
  - prior xPts from 2025/26 per-90s + minutes share (via the code mapping),
  - a conservative prior for promoted-team players and new signings (position + price percentile),
  - blend weight that decays from ~100% prior at GW1 to ~0% by GW6 as real form accumulates (new `config.py` params, documented in `docs/config_reference.md`).
- [ ] **Sweep hardcoded season assumptions**: refresh scripts (`src/season_history.py`, `src/fpl_refresh_next_gw.py`, `scripts/refresh_backend.py`), any 2025/26 paths, GW-number logic, and the derived ITB/FT logic against a fresh entry with zero history.
- [ ] **Lock a baseline metric.** Run the 2025/26 backtest one final time and record MAE/rank-correlation numbers in the repo. This is the regression bar for every model change during the season.

**Exit criteria:** `/recommendations` returns a sane GW1 squad + transfer plan for a fresh 2026/27 entry, and the cold-start blend backtests no worse than naive prior-season PPG.

## Week 2 (Jul 20–26): Multi-tenant accounts + billing plumbing

- [ ] **Auth: Supabase Auth** (email + Google). Users table stores `fpl_entry_id`, plan tier, Stripe customer id. Backend validates the Supabase JWT instead of the shared `FPL_API_KEY` (keep the key path for the admin endpoints only — `src/auth.py`).
- [ ] **Per-user scoping.** Remove the `FPL_ENTRY_ID` env fallback from user-facing paths; every request resolves the entry from the authenticated user (with an explicit override param for league-rival views).
- [ ] **Rate limiting + caching per tier.** Free: next-GW recommendation, 1 team, N requests/day. Pro: full horizon, chip drafts, league strategy, `/explain`. Cache `/recommendations` and `/explain` per `(entry_id, event_id, params)` — LLM calls are the main marginal cost, and answers don't change until data refreshes.
- [ ] **Billing: Stripe Checkout + customer portal**, one product, two prices (monthly ~£3–5, season pass ~£25–30 with founder discount). Webhook → update user tier in Supabase. (If EU VAT handling is a worry, Lemon Squeezy as merchant-of-record is the fallback — decide early, don't build both.)
- [ ] **Fly production posture:** `min_machines_running = 1` (no cold starts for customers), secrets audit, staging app for testing webhooks.

**Exit criteria:** a stranger can sign up, link their team ID, hit the free tier, pay, and get pro features unlocked — end to end on staging.

## Week 3 (Jul 27–Aug 2): Product surface + reliability

- [ ] **Onboarding flow (Lovable):** land → paste FPL team ID (with a "how to find it" helper) → instant GW1 recommendation → sign up to save it. Time-to-value under 60 seconds is the whole funnel.
- [ ] **Pricing page + paywall gating** wired to the week-2 tiers; deadline countdown via `/events/next` on every page.
- [ ] **Deadline email** (the retention hook): "Your GW deadline is in 24h — here's your recommended team + captain." One scheduled job reusing the existing refresh workflow; even a plain-text email is fine for launch.
- [ ] **Observability:** Sentry on the API, uptime check on `/health`, alert if the 6-hourly refresh fails (a stale dataset before a deadline is the worst possible failure for a paid product). Track LLM spend per user.
- [ ] **Targeted refactors only** (from `REFACTORING.md`): split `api/main.py` into routers and extract the shared LLM helper — both directly reduce risk for the code being touched this month. Everything else in that backlog stays deferred.
- [ ] **Legal minimum:** ToS + privacy page, and a clear "unofficial tool, not affiliated with the Premier League" disclaimer. Note the standing risk: the FPL API is unofficial and could change or be restricted — mitigation is the cache layer and fast redeploys, not pretending it can't happen.

**Exit criteria:** production app usable by non-technical friends without hand-holding; errors and refresh failures page you.

## Week 4 (Aug 3–10): Beta launch before GW1

- [ ] **Private beta (Aug 3–5):** 10–20 users from Substack readers + friends' mini-leagues. Watch onboarding drop-off and API errors; fix daily.
- [ ] **Content launch:** publish the drafted Substack piece (`docs/substack_article_2.md`) reframed as "the 2026/27 season assistant", plus a launch post with founder pricing. r/FantasyPL and FPL Twitter are the audience; lead with a free, concrete GW1 team reveal generated by the product.
- [ ] **Public launch (Aug 6–7):** open signups with founder season-pass pricing. Every GW1 article/tweet should end with "get your own team's plan" link.
- [ ] **GW1 dry run:** full rehearsal against the real deadline — refresh cadence in the 24h before, live points display after kickoff, auto-bump to GW2. Load smoke test at ~50 concurrent users (one Fly machine + cache should hold; scale to 2 if not).
- [ ] **Buffer.** No new features after Aug 7. Remaining days are bug fixes and the GW1 deadline itself.

**Exit criteria:** paying users get a correct GW1 recommendation before the deadline. That's the launch.

---

## Success metrics (end of month)

| Metric | Target |
|---|---|
| Signups by GW1 deadline | 100 |
| Paying users | 10 (founder pricing) |
| Onboarding: land → first recommendation | < 60s, > 50% completion |
| GW1 xPts quality | ≥ 2025/26 baseline MAE recorded in week 1 |
| Uptime through GW1 weekend | no deadline-window outage |

## Explicitly out of scope this month

- Mobile app, Discord bot, or agentic auto-transfers (needs FPL login credentials — a trust/legal question for later).
- ML upgrades beyond the cold-start prior (xG-based models, etc.) — the evaluation endpoint makes this safe to iterate on in-season.
- The full `src/` folder restructure and remaining `REFACTORING.md` items.
- Affiliate/B2B angles, localization.

## Top risks

1. **FPL changes scoring rules or API shape for 2026/27** → week 1 diff catches it early; budget a day of slack.
2. **Cold-start projections are visibly bad in GW1–3** → the founder pricing + "beta" framing buys goodwill; the deadline email keeps users through the rough patch.
3. **Solo-founder time** → weeks 2–3 are the heaviest; if slipping, cut the deadline email and league-strategy paywalling before cutting billing or onboarding.
