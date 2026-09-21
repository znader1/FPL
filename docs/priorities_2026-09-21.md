# Priorities — 21 Sep 2026 (chips first)

**Where this sits:** the international-break plan (`docs/plan_intl_break_2026-09.md`, 19 Sep → 9 Oct)
stays the calendar. This document re-orders it: **the chip recommendations (Wildcard / Free Hit)
come first and have to be nailed on before anything else ships**, then the engine signals
(xGI trend, fixture trend), then the rest. Each item names its root cause, the branch it lives on,
and the gate it has to pass. Cross-referenced with every open branch in both repos (bottom).

**Rule of the road unchanged:** engine changes are backtest-gated (season points, MAE reported);
merges go through pull requests; user says "merge".

---

## Shipped in this pass (branch `claude/fpl-chip-recommendations-jy45s0`, both repos)

| # | Item | Root cause | What changed | Gate |
|---|---|---|---|---|
| S1 | **Wildcard draft rebuilt XI-first** (`optimizer.build_wildcard_squad`) | The legacy `build_chip_squad` maximised the sum of the objective over all **15** players. The upgrade loop spent money on bench slots and on whichever position the projections inflated that week — a 4-5 DEF XI and a bench that never plays. No formation search, no rotation awareness. | Objective = the **starting XI** over the build horizon; every legal formation searched (greedy shortlist → full knapsack on the best 3); `CHIP_WILDCARD_XI_POS_MULT` (DEF 0.93) so a defender-heavy shape must be clearly better on raw xPts; XI candidates gated on recent **start rate** (`CHIP_WILDCARD_XI_MIN_START_RATE` 0.6) so rotation risks can only be bench bodies; **rotation bench**: the ≤4.5m keeper and one ≤4.5m defender that best complement the XI keeper / weakest XI defender week by week (home/away alternation falls out of the per-GW xPts), cheapest playing fodder for the rest; both chip drafts built on a **European-week-discounted** copy of the projections (`CHIP_DRAFT_EURO_XPTS_MULT` 0.95). Same builder feeds `chip_advisor.score_wildcard`, so the Chips tab's WC value and the drafted squad agree. Response carries `formation`, `xi_player_ids`, `bench_rotation`, `xi_gated_out`. | 15 new unit tests (`tests/test_optimizer_wildcard.py`); synthetic 420-player market: 1.6 s/build (was 0.6 s), horizon best-XI +2 xPts vs legacy. **Live spot-check still owed** (this container could not reach the FPL API) — see P0-1. |
| S2 | **"GW6 is the best week, but hold"** | `CHIP_PLAN_MIN_EV["wildcard"]` was **120** xPts over 5 GWs — a 2 Sep stopgap against an unbudgeted, unclamped dream squad (+281/+109). Since then the WC side is budget-constrained, position-clamped, European-discounted and (now) XI-first, but the bar never came back down, so *every* window read "hold", including the week the manager had pencilled the chip in for. | Bar → **20** (+4 xPts/GW of pure chip value, net of what free transfers already capture; expiry ramp unchanged). Outlook rows carry `ev_curve` on hold rows too. Guidance says "short of the N-pt bar". Frontend: **"Your plan" card** on the Chips tab quotes the pencilled-in GW's value vs the bar and vs the planner's best week ("planner prefers GW8 (+15.1)"), or says the GW is beyond the model horizon. | Unit tests; **backtest of the bar value owed** (P0-2). |
| S3 | **Browsing gameweeks without a recommendation** | `setGwAndReset` re-ran the recommendation on every GW change whenever a chip was selected — a full wildcard build per arrow press, and the pitch flipped to the recommendation instead of the squad. | Squad mode stays squad mode: `/squad?event_id=` already returns that GW's projected xPts per player and `/fixtures?event_id=` the opponents; only a pitch already showing a recommendation follows the GW with a new one. | Frontend tests (160 pass), typecheck clean. |

---

## P0 — nail the chips (this week, before GW6 deadline Sat 10 Oct 10:00 UTC)

| # | Item | Size | Gate / owner |
|---|---|---|---|
| **P0-1** | **Live spot-check of the new Wildcard draft** on your entry: `PYTHONPATH=. python -m scripts.spotcheck_chip_plan <entry_id>` + a `/recommendations?chip_strategy=wildcard&chip_play_event_id=6&chip_horizon_gws=5` call on staging. Check: formation (expect 3-4-3 / 3-5-2 / 4-4-2 unless DEF are genuinely better), `bench_rotation` names two cheap rotating bodies, `xi_gated_out` lists the rotation risks you would expect, the European-haircut note counts ~30-40 players. Tune `CHIP_WILDCARD_XI_POS_MULT` / `_XI_MIN_START_RATE` / bench caps from what you see — they are config, not code. | 1 h | user + staging |
| **P0-2** | **Backtest the wildcard bar** (`CHIP_PLAN_MIN_EV["wildcard"]` 20 vs 40 vs legacy 120) with `scripts/backtest_season.py --season 2025-26 --use-engine --weekly-chips --smart-transfers`; keep whichever maximises season points. Same run reports whether the XI-first draft beats the legacy 15-sum on the WC weeks (add a `--wc-builder legacy|xi` switch to the harness). | 0.5 d | backtest |
| **P0-3** | **Free Hit threshold branch** — `claude/free-hit-threshold-g547ne` (FPL: 3 commits, 0 behind master; hub: 1 commit) adds the squad-stress opener (blend of blanks/tough/benching) to the FH gate and shows the stress reading on a held row. Review, PR, merge — it is the FH half of "chips nailed on". | 1 h review | user go |
| **P0-4** | **GK pair-first strategy** — extend the rotation bench: compare (premium keeper + fodder) with (two rotating ~4.5m keepers, XI slot value = Σ max(A, B) per GW, savings re-spent on the XI) and take the better. Today the bench keeper only rotates when a ≤4.5m body beats the XI keeper in some weeks. | 0.5 d | unit tests + P0-1 style spot-check |
| **P0-5** | **Injury/minutes knowledge into the transfer paths** — `feat/player-knowledge-in-recommendations` (1 commit, 0 behind). Review + merge; then the same `player_knowledge.json` should gate the wildcard XI too (a known long-term injury with a return GW inside the horizon). | 1 h + 0.5 d | user go |
| **P0-6** | **Knowledge rail on** — `feature/knowledge-consolidation` is 17 commits behind master: rebase, remove the empty `knowledge_discount.json` on the prod volume so the seed loads (plan item 4). | 0.5 h | user go |

## P1 — engine signals the user asked for (backtest-gated, week 2)

| # | Item | Design | Gate |
|---|---|---|---|
| **P1-1** | **xGI trend** ("how the player is evolving") | Per player: recent-window xG+xA per 90 (last `N` GWs, recency-weighted, from `player_gw_history`) vs season per 90 → a bounded multiplier on the xG-model output (`OUTPUT_XGI_TREND_WEIGHT`, clamp ±15 %) blended exactly like the existing recency weighting on ppg/form; plus a `trend` field per player (`xgi_recent_per90`, `xgi_season_per90`, `direction`) on `/squad`, `/recommendations` and the watchlist so the PlayerCard can show ↑/↓ with both numbers. Backtest: MAE, captain hit-rate, top-N precision vs baseline; ship only on a win (the minutes model taught us multipliers can lose). | backtest |
| **P1-2** | **Fixture trend on the pitch** | `compute_fixture_swings` (next-3 vs previous-3 difficulty) already exists for chips; surface it per player as a `fixture_trend` badge (easier/harder, Δ difficulty) on the PlayerCard and in Hot Targets, so "the path" is visible when browsing GWs. No engine change. | UI review |
| **P1-3** | **Zero-minutes gate** and **early-season form trust** (intl-break plan items 6-7) — both feed the same start-rate signal the wildcard gate now uses. | backtest |
| **P1-4** | **Same-fixture stacking discount** (plan item 5). | backtest |
| **P1-5** | **FT-banking valuation** (plan item 8). | backtest |

## P2 — after the chips are proven

| # | Item | Note |
|---|---|---|
| P2-1 | `refactor/config-single-source-of-truth` (4 commits, 0 behind) — touches `config.py`, will conflict with this pass's `CHIP_WILDCARD_*` / `CHIP_DRAFT_*` additions; rebase after merge. | merge after P0 |
| P2-2 | `feat/llm-usage-logging` (2 commits, 0 behind) — cheap, independent. | merge any time |
| P2-3 | Mini-league upgrade (plan item 10) — scope still to confirm. | user decision |
| P2-4 | Ship hardening (plan item 11): Google sign-in end-to-end, rollover guard, admin-key rotation. | before 8 Oct freeze |
| P2-5 | Backtest evidence page (plan item 9). | 0.5 d |

## Open decisions for you

1. `CHIP_WILDCARD_XI_POS_MULT["DEF"] = 0.93` — a preference, not a rule: 1.0 restores pure xPts, 0.85 makes 3-DEF shapes near-automatic. Set from P0-1.
2. `CHIP_WILDCARD_XI_MIN_START_RATE = 0.6` — strict enough to bench a 50 % rotation risk, loose enough to keep a 2-of-3 starter. 0 disables.
3. `CHIP_PLAN_MIN_EV["wildcard"] = 20` — pending P0-2. If you would rather the chips tab *never* say "play" for a wildcard before a fixture swing, that is a product stance the bar cannot express; say so and it becomes a structural gate like the FH blank gate.

## Branch hygiene (cross-check of every open branch, 21 Sep)

**FPL (backend)**

| Branch | State vs master | Action |
|---|---|---|
| `claude/free-hit-threshold-g547ne` | 3 ahead / 0 behind — FH squad-stress opener | **P0-3: review + merge** |
| `feat/player-knowledge-in-recommendations` | 1 ahead / 0 behind | **P0-5: review + merge** |
| `refactor/config-single-source-of-truth` | 4 ahead / 0 behind | P2-1: merge after P0, rebase over this pass's config |
| `feat/llm-usage-logging` | 2 ahead / 0 behind | P2-2: merge |
| `feature/knowledge-consolidation` | 17 behind | P0-6: rebase, then merge |
| `claude/chips-fixtures-points-projection-a0r34t` | 0 ahead / 21 behind (already merged) | delete |
| `develop` | 63 behind; its 8 "ahead" commits are the weekly-db work already on master via PR #42 | verify, delete |
| `knowledge-watch/week-2026-08-28`, `-09-04`, `-09-11` | weekly snapshots | delete once the knowledge rail (P0-6) is on |
| `feature/xpts-components`, `feature/chip-guidance`, `feature/decision-card`, `feature/h2h-penalty`, `feature/planner-honours-horizon`, `fix/planner-same-gw-resell` | merged into master (fast-forward / PR) | delete |

**fpl-decision-hub (frontend)**

| Branch | State vs main | Action |
|---|---|---|
| `claude/free-hit-threshold-g547ne` | 1 ahead / 0 behind | merge with its backend twin (P0-3) |
| `feature/squad-picker` | 42 ahead / 106 behind — the squad picker is already on main (`SquadPicker.tsx`) | confirm nothing unique, delete |
| `chat-backend` | 3 ahead / 106 behind — `/app/fixtures` ticker page is on main (`Fixtures.tsx`) | confirm, delete |
| `feature/transfer-clarity` | 1 docs commit (ops/UX backlog from the GW3 incident) | cherry-pick the doc, delete |
| `feature/smarter-projections` | 55 ahead / 107 behind, last commit **14 May 2026** (pre-season front-end work superseded by main) | confirm nothing unique, delete |
| `claude/chips-fixtures-points-projection-a0r34t`, `feature/chip-outlook`, `feature/chip-planner-frontend`, `release/chip-strategy`, `feature/live-points-and-components`, `feature/stack-odds`, `feature/differential-toggle`, `fix/auth-token-on-api-calls`, `feature/chip-guidance`, `feature/decision-card`, `feature/planner-verdict` | 0 ahead | delete |
