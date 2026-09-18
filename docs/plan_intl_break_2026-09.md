# International-break plan — 19 Sep → 9 Oct 2026

**Window:** GW5 deadline Fri 18 Sep 17:30 UTC → GW6 deadline Sat 10 Oct 10:00 UTC.
**Goal:** ship visibly bigger transfers, chips and mini-league features before GW6,
each engine change gated on the 2025-26 backtest (season points is the gate, MAE reported).
**Rule of the road:** work on branches, review, staging test on the preview pair, user
says "merge" — via a pull request (master has a PR-required rule; direct pushes bypass it and should stop). Deploy freeze Thu 8 Oct evening; brother tests 8–9 Oct.

## Week 1 · 19–25 Sep · Transfers depth (what users see first)

| # | Item | Size | Gate |
|---|---|---|---|
| 0 | **Injury-priority toggle** (built 18 Sep, on `feature/injury-priority` both repos, review clean, on staging): sell the doubtful/injured player first when gains tie; "75% fit" chips; default on. Awaiting user go to merge. Follow-up: `_red_flag` still uses the NaN-tolerant `float()` pattern (benign). | done | user go |
| 1 | **Planned squad follows you across weeks.** Apply on the card sets a planned squad; GW6/GW7 pitch shows it with that week's fixtures and the plan's later moves pre-applied; staircase rows jump to the week; real/planned toggle. Backend adds `squad_after` ids per plan GW. | 0.5 d | UI review |
| 2 | **XI-aware `this_gw_gain`** so the "this GW" and ranking numbers agree for bench sellers; runner-up tie-break prefers selling the displaced player ("Brobbey → Barry"). | 0.5 d | tests |
| 3 | **Wildcard formula retune.** Credit the transfer plan over the SAME window as the wildcard (not the full 8 GWs); value the free transfers a wildcard preserves; set `CHIP_PLAN_MIN_EV["wildcard"]` from the backtest. Enter FA Cup / EFL Cup dates in `european_calendar.json` (`cup_rounds`). | 1.5 d | backtest |
| 4 | **Knowledge rail on.** Merge `feature/knowledge-consolidation`, remove the empty `knowledge_discount.json` on the prod volume so the seed loads; re-check entries at ~GW7 per the file's workflow. | 0.5 h | user go |
| 5 | **Same-fixture stacking discount** (two buys from one club in the same tough fixture): design + backtest; ship only if points do not drop. | 0.5 d | backtest |

## Week 2 · 26 Sep–2 Oct · Engine quality (all backtest-gated)

| # | Item | Size |
|---|---|---|
| 6 | **Zero-minutes gate.** 0 minutes across N≥3 finished GWs + no positive news → expected minutes collapse (Mount-type ghosts). | 1 d |
| 7 | **Early-season form trust.** 4 games of 8 ppg currently beats a 4.3/5 difficulty; test stronger shrinkage / capped form weight until ~6 GWs. | 1 d |
| 8 | **FT-banking valuation** (5-cap, chips don't burn FTs): roll decisions value the banked transfer; hit valuation. | 1.5 d |
| 9 | **Backtest evidence page** (local `/replay` + a short report doc): baseline vs each shipped change, so "best suggestions" is a number not a claim. | 0.5 d |

## Week 3 · 3–9 Oct · Mini-league + ship prep

| # | Item | Size |
|---|---|---|
| 10 | **Mini-league upgrade** — scope to confirm with the user: rank-swing projection vs each rival for the next 3 GWs; differential picks from rivals' actual squads; "what beats the leader" transfer suggestion; chip timing vs rivals' chips left. | 2 d |
| 11 | **Ship hardening** — Google sign-in end-to-end (button exists; account linking + entry-id claim flow), rollover/identity guard on all pages (audit U7), frontend audit U-items still open, prod admin-key rotation, staging refresh sanity. | 1.5 d |
| 12 | **Freeze + test** — Thu 8 Oct: merge, deploy, brother + user test on prod at desktop and phone; Fri 9 Oct hotfixes only. | 1 d |

## Already done this week (16–17 Sep) — for reference
Decision card + runner-ups; plan-first Apply; seeds shipped to servers; chips fixture context
(European weeks, distributions, likelihood); plain-language chip guidance; horizon = slider with
scaled bar; head-to-head penalty 3.0; same-week resell fix; staging joined the refresh job.

## Open decisions for the user
- Mini-league scope (item 10) — which of the four sub-features matter most.
- Whether the wildcard should ever be recommended before a clear fixture swing (item 3 sets the
  bar from data; the product stance still matters).
- Go/no-go on merging `feature/knowledge-consolidation` (item 4).
