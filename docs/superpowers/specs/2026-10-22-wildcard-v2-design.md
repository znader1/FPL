# Wildcard v2 — three structured squads on an honest budget

**Date:** 2026-10-22
**Status:** approved 2026-10-22 (one PR per repo, one security review, Vercel preview)
**Origin:** brainstorm over the GW8 wildcard proposal (Verbruggen / De Cuyper / Vuskovic / O'Shea / Ouattara / Neto / Mbeumo / Rudoni / Palmer / Haaland / Isak; bench B.Fernandes / van Ewijk / Walle Egeli / Balcombe).

## 1. Intent and why

The wildcard draft today is one greedy squad maximising a single score that is
dominated by the last two gameweeks. The user's read of GW8 (confirmed in code):

- **Recency bias.** Form enters the wildcard score three times: the base xPts
  blend (`PROJ_DEFAULT_FORM_WEIGHT` 0.45 → last-5-GW average at
  `PROJ_PLAYER_RECENT_BLEND_WEIGHT` 0.65 with the last two GWs double
  weighted), then `wildcard_form_bonus`, then `form` again inside
  `captain_signal`. Neto 6.08 over Palmer 4.63 in the same fixture is this.
- **Bench is leftovers.** `optimizer.build_chip_squad` starts from the cheapest
  player per position and greedy-upgrades the largest score gain until the
  budget runs out. There is no XI/bench split, no minutes floor, no bench rule.
  The objective sums all 15 scores, so a £9m Bruno Fernandes on the bench counts
  the same as in the XI. The free-hit builder has bench logic
  (`_bench_sort`, `CHIP_BENCH_MIN_MINUTES`); the wildcard never got it.
- **Triple-ups on non-premium defences.** Same-team defenders share one clean
  sheet, so three Brighton defenders at Anfield is one bet counted three times,
  on top of the known promoted / small-sample cluster inflation (CLAUDE.md
  open issue).
- **Wrong budget.** `squad_builder.estimate_squad_budget_m` sums current
  market `now_cost` plus bank. FPL sells at purchase price plus half the rise,
  so a risen squad is overstated. Bank comes from the last finished GW's picks
  payload (or a £0.5m default) when no my-team link exists. The my-team payload
  carries `selling_price` per pick; `transforms.picks_to_df` drops it via
  `config.SQUAD_COLUMNS`. Verified 2026-10-22 on a public entry:
  `entry_history.value` = Σ selling prices + bank (value 1018, bank 1,
  Σ now_cost 1020), so the honest budget is already in the payload we fetch.
- **Nothing for rotation, fatigue, availability, trend, position-specific
  value or gems.** All wildcard bonuses are gated on `is_attacker`;
  `wildcard_ownership_bonus` rewards *high* ownership, the opposite of gem
  hunting. `PROJ_APPLY_MINUTES_MODEL` is off (backtest: never beat baseline;
  stays off for scoring). The European haircut lives in `chip_advisor` timing,
  not in the draft path. The repo's calendar seed has 9 teams filled in
  (commit `29b77f4`), but `ensure_seed_models` never overwrites a file already
  on the Fly volume, so prod may still hold the older empty map.

Why now: the user is about to play a wildcard (GW8+) and wants squads they can
trust and explain, not one squad they have to argue with.

Success: the page shows three structurally different legal squads built on the
user's real selling-price budget, each with a per-player explanation the user
agrees with, and the user plays one of them (or the shared core) with at most
a couple of manual swaps.

## 2. Goals, non-goals, anti-goals

**Goals**
1. Budget = Σ selling prices + live bank, exact for a linked account,
   reconstructed for a public entry, and shown on the page.
2. Three presets, enforced as structural constraints (not weights):
   Aggressive / Balanced / Gems. Shared "core" (players in all three) surfaced.
3. Bench built by role rules with an availability gate, not from leftovers.
4. Recency retuned for a multi-GW chip; trend (direction) added; form level
   counted once.
5. Same-team defensive correlation handled (cap + penalty).
6. Horizon-wide availability: injury-history prior + status, plus a European
   rotation haircut in the draft path once the calendar is populated.
7. Position-aware value: defenders score attacking threat and DC; midfielders
   score DC floor; nothing is attacker-only by construction.
8. Pins and excludes (user's "surprise me": included, my call): lock or ban
   players, all three squads rebuild around them.
9. Per-player explanation with the actual score components, plus narrative
   facts (record vs opponent, milestone chase) that never touch the score.
10. One draft engine serves wildcard and the dev squad picker.

**Non-goals**
- Turning the minutes model back on for scoring. It stays a gate only.
- GK rotating pair. Default is set-and-forget starter + cheap 90-minute
  backup in all three presets. A rotating-pair toggle is a later item.
- Free hit changes beyond sharing the bench helpers.
- Mini-league / ownership-EV integration in the wildcard page.
- Backtesting the presets as a whole (no ground truth for "would the user
  have liked it"). Component changes that alter xPts are backtested.

**Anti-goals** (failure even if it works)
- Three squads that share 12 players. Presets must produce visibly different
  structures.
- A bench with a sub-£4.5m "ghost" that never plays.
- A squad that costs more than the user can actually afford after selling.
- Explanations that quote numbers the engine did not produce.

## 3. Constraints

- All tunables in `src/config.py`, tagged (`[untested]` / `[tuned]` /
  `[operational]` / `[flag]`), no `getattr` fallbacks (PR #61 rule).
- FPL rulebook facts come from `src/rules.py` (`OUTPUT_DC_THRESHOLD`:
  GKP/DEF 10, MID/FWD 12; `OUTPUT_DC_POINTS` 2.0). Never hardcode.
- Any change to per-GW xPts must go through the backtest harness before it
  ships to the shared projection path. Note the harness parity caveat
  (adapter zeroes `ep_next`, prod blends 0.5): evidence is directional until
  phase 4.0 lands. Wildcard-only scoring (`add_wildcard_scores`) is not on the
  backtest path and can be changed without one, but must not change
  `xpts_gw*`.
- Work in a scratch worktree, PR per phase, user merges. Security review on
  every phase diff.
- Backend: FastAPI + pandas, Fly.io. Frontend: React/TS Vite at
  `fpl-decision-hub`, Vercel. Supabase JWT required on all user routes.
- Request budget: three greedy scalar builds per request (same algorithm as
  today, run three times). No new FPL calls.

## 4. Decisions (as decided)

### 4.1 Budget (user: "based on my actual value team")
- Public entry: budget = `entry_history.value` / 10 from the latest picks
  payload (verified: value = Σ selling prices + bank). No extra FPL call, no
  reconstruction. Limitation: as of the last finished GW; transfers made since
  are not reflected until the next deadline passes. Say so on the page.
- Linked my-team: keep `selling_price` through `picks_to_df` (add it to
  `SQUAD_COLUMNS`); budget = Σ `selling_price`/10 + `transfers.bank`/10, live.
  Builder verifies whether my-team `transfers.value` already includes bank
  before using it as a shortcut.
- Response carries `budget_breakdown` {source: my_team|entry_value|market,
  squad_sell_value_m, bank_m, budget_m}. The page shows it next to each squad.
- Market-price fallback remains only when both sources fail, and it is
  labelled as such.

### 4.2 Horizon (user: "maybe not 5GW, it could be 7")
- `CHIP_WILDCARD_DEFAULT_HORIZON_GWS` stays 5; the request already clamps
  1..8, the page exposes 3..8.
- `CHIP_WILDCARD_GW_WEIGHTS` is already a gentle decay (1.0 → 0.7 over 8 GWs;
  GW1 is ~17% of a 7-GW sum). No change. The recency problem is in the form
  inputs (4.3), not the horizon weights.

### 4.3 Recency retune and trend (user: "lot of recency bias", "include trend")
Wildcard-only (does not touch `xpts_gw*`):
- `wildcard_form_bonus` is replaced by a single **level + trend** term:
  - level = `baseline_blended_xpts` share already inside xPts (no extra form).
  - trend = shrunk slope of rolling per-90 xGI (goals + assists expected) over
    the last `CHIP_WILDCARD_TREND_WINDOW` (6) team games versus the prior 6,
    clipped to ±`CHIP_WILDCARD_TREND_CLIP`, scaled by
    `CHIP_WILDCARD_TREND_WEIGHT`. Data: per-match
    `data/processed/fpl/<season>/player_match_history_<season>.csv`
    (`expected_goals`, `expected_assists`, `expected_goals_conceded`,
    `defensive_contribution`, `starts`), loaded by
    `fixture_difficulty.load_match_history`, refreshed on every `/admin/refresh`.
    Window = min(6, floor(n/2)) so it exists early in the season; shrink by
    `n/(n + CHIP_WILDCARD_TREND_SHRINK_GAMES)`. Accepted: at GW8 the term is
    near zero and the card says "trend: thin sample". It grows into itself.
  - Defenders/GK: trend on xGC-against of their team + own DC rate, same shape.
- `captain_signal` drops its `form` term; keeps next-GW xPts, premium price,
  penalty duty.
- `wildcard_ownership_bonus` is removed from the shared score. Ownership
  becomes a preset constraint (Gems) only.
- Shared projection path (`projections.py`) is **not** changed in this
  project. A separate backtest ticket covers lowering the last-2 double
  weight; its result feeds all products, not just the wildcard.

### 4.4 Objective and bench (user: Bruno on the bench "not great"; bench spec)
- Two-stage build, scalar objective. Stage 1 picks the 11 XI slots with the
  existing greedy on the horizon scalar `wildcard_score` (one legal formation
  shape per preset, config), no per-GW XI search inside the loop. Stage 2
  fills the 4 bench slots by role rules. Reported objective = Σ XI
  `wildcard_score` + `CHIP_WILDCARD_BENCH_WEIGHT` (0.15) × Σ bench. Bench no
  longer competes with XI money. Per-GW best XI is computed once at the end
  for display, as today.
- Bench is filled by **role rules**, cheapest qualifying body per role, after
  the XI, under `CHIP_WILDCARD_BENCH_BUDGET_MAX_M` (17.5):
  - **GK2**: starts ≥ `CHIP_BENCH_START_SHARE` (0.85) of team games, cheapest.
  - **DEF cover**: starts ≥ 0.85, cheapest with `p_clean_sheet` or `p_dc` above
    the position median.
  - **DC midfielder**: `p_dc` ≥ `CHIP_BENCH_MID_DC_PROB` (0.5), i.e. reaches 12
    CBIRT in at least half of games, starts ≥ 0.85, cheapest. If no such MID
    exists under budget, fall back to a DEF with `p_dc` ≥ 0.5 and note it.
  - **Free slot**: highest chip_score under the remaining bench budget that
    passes the availability gate; in Gems it must also pass the gem filter.
- Availability gate (hard filter, all bench; XI at `CHIP_XI_START_SHARE`
  0.70): start share this season, `status == 'a'`, no injury-prior flag
  (4.6), not in a flagged European-rotation squad.
- The free-hit builder's `_bench_sort` and the new role rules live in one
  shared helper module (`src/chip_bench.py`); free hit keeps its
  cheapest-fodder behaviour via a parameter.

### 4.5 Correlation and clustering (user: "triple up … on defence … fishy")
- `CHIP_WILDCARD_MAX_DEF_PER_TEAM` = 2 (GK counts as DEF for this cap) unless
  the team's xG defensive rating rank ≤ `CHIP_WILDCARD_ELITE_DEF_RANK` (4).
- Second same-team defender/GK's whole `wildcard_score` is docked
  `CHIP_WILDCARD_SAME_TEAM_DEF_PENALTY` (0.15), third 0.30, applied inside the
  upgrade loop's delta so the greedy search sees it. Whole-score, because
  clean-sheet components exist for GW1 only and a horizon CS share would need
  a model change this project avoids.
- Small-sample guard: a player on a team with fewer than
  `CHIP_WILDCARD_MIN_TEAM_MATCHES` (8) xG-rated matches this season has his
  `wildcard_score` shrunk toward the price prior by the remaining share.
  Stopgap documented as such; the root fix is the backlogged home/away split.

### 4.6 Availability over the horizon (user: Isak "risk of injury")
- Injury prior = share of GWs with status `i`/`d` in a status-history CSV
  on the Fly volume (`CHIP_WILDCARD_STATUS_HISTORY_PATH`), appended by every
  `/admin/refresh` from the bootstrap (idempotent per GW). Chosen over the
  Supabase snapshot table because the backend has no Supabase data client
  and the refresh job already runs 6-hourly. Shrunk to a per-GW miss
  probability with `CHIP_WILDCARD_INJURY_PRIOR_SHRINK_GWS`. No zero-minutes
  proxy (it conflates rotation with injury). Empty until the first refresh
  after deploy, honest on the card, grows over time. Applied as a multiplier over all
  horizon GWs in the wildcard score only: `(1 − p_miss)^k` fade with
  `CHIP_WILDCARD_INJURY_PRIOR_WEIGHT`.
- Surfaced on the card as "injury prior: missed N of last M".
- European haircut: the draft path applies `CHIP_PLAN_EURO_XPTS_MULT` to
  exposed players. Phase 6 checks the Fly volume holds the 9-team seed and
  force-copies it if not.

### 4.7 Position-aware value (user: "maximizing points … defenders, midfielders, forwards")
- Remove the `is_attacker` gate from every wildcard bonus.
- DEF: add `ep_goals + ep_assists` (attacking threat) and `ep_dc` to a
  position-neutral "upside" term; GK: `ep_saves` + `p_clean_sheet`.
- MID: `ep_dc` counts; FWD unchanged.
- Captaincy bonus stays attacker-only in Aggressive and Balanced (that is
  what captains are), off in Gems.

### 4.8 Three presets (user's proposal; constraints are mine)

| | Aggressive | Balanced | Gems |
|---|---|---|---|
| Premiums ≥ `CHIP_WILDCARD_PREMIUM_CAPTAIN_PRICE_FLOOR` (10.5) | exactly 3 | exactly 2 | ≤ 1 |
| Bench | 4 enablers, `BENCH_BUDGET_MAX_M` 17.0 | role rules (4.4) | 4 enablers, gem-filtered free slot |
| Ownership | none | none | ≥ 6 XI players with `selected_by_percent` < 10 |
| Team spread | 3 per team allowed; DEF cap 2 (4.5) applies | DEF cap 2 | max 2 per team, any position |
| Captaincy bonus | ×1.5 | ×1.0 | off |
| Extra signal | none | none | trend weight ×2; minutes gate 0.85 for XI |
| Availability gate (XI) | 0.70 | 0.80 | 0.85 |

- Presets are config dicts `CHIP_WILDCARD_PRESETS[name]` overriding the
  defaults above. The builder takes a preset dict, so a fourth preset or a
  user-custom one is config only.
- Pins/excludes: `pinned_ids` are placed first and never swapped;
  `excluded_ids` are dropped from the market. Applied to all three.
- Core = intersection of the three squads' XIs; shown as its own strip.

### 4.9 Explanation (user: "I need an explanation for each one")
- Every record carries `score_breakdown` with the new components:
  weighted_xpts, trend, upside (position-aware), captaincy, dgw, correlation
  penalty, injury prior, small-sample shrink, role (XI / GK2 / DEF cover /
  DC mid / free slot / pinned).
- Narrative facts, engine-blind, computed from history CSVs and shown on the
  card: record vs the next-GW opponent (goals, assists, points in the last 5
  meetings, with sample size), active milestone within 5 of a round number
  (goals / assists / clean sheets), and streak ("returned in 4 straight").
  The LLM explainer may cite only these fields.

### 4.10 One draft engine (user did not ask; mine, from the two-engine finding)
- `build_chip_squad` gains the objective split, role bench, caps and a
  preset dict. The **default preset is legacy-equivalent** (single-stage
  greedy, no caps, no bench rules), so the three existing callers —
  `chip_advisor` WC/FH timing EV (bridged market with `xpts` only),
  `squad_draft.build_squad` (squad picker) and free hit — keep today's
  behaviour and tests. Only the wildcard route passes a non-default preset.
  Markets missing a column a preset needs (`status`, `p_dc`, starts share)
  fail loud with the missing column named.

### 4.11 API shape and page
- New route `POST /wildcard/drafts` (require_user) returns the three squads,
  the core, `budget_breakdown` and per-record `score_breakdown`. It does not
  touch `/recommendations`.
- `/recommendations` gains `wildcard_preset` (default `balanced`) and builds
  that one squad with the same engine, so everything downstream (lineup,
  transfer steps, horizon plan, chip hand-off via `plan.chip`) keeps one
  squad as today. Preview state stays out of persisted `chipStrategy`.
- The wildcard preview on `pages/Index.tsx` (`wildcardDraftShown`) becomes
  three pitches side by side (stacked on mobile), each
  with: XI xPts over horizon, bench xPts, cost vs budget, premiums count,
  average ownership, transfers from the current squad, flags count. Core
  strip above. Pin/exclude via the existing player list panel. "Use this
  squad" hands off to the existing plan/lineup flow exactly as the single
  wildcard does today.
- Budget breakdown line under the header (4.1).

## 5. Delivery (user decision 2026-10-22: one PR, one security review, Vercel preview)

- **One backend PR** on `FPL/` (branch `feature/wildcard-v2`, scratch worktree)
  carrying budget truth, builder restructure, scoring, explanations, the
  `/wildcard/drafts` route and the `wildcard_preset` param. Work is still
  built in the order 4.1 → 4.4/4.5/4.8/4.10 → 4.3/4.6/4.7 → 4.9/4.11 so each
  commit is testable, but merged as one PR.
- **One frontend PR** on `fpl-decision-hub` (branch `feature/wildcard-v2`)
  for 4.11. Two repos, so two PRs is the floor; one review covers both.
- **One security review** across both diffs, findings in the backend PR body.
- **Preview testing before merge:** backend branch deployed to the Fly dev
  app (`fpl-assistant-api-dev`, `fly deploy -c fly.dev.toml` from `FPL/`,
  manual `/admin/refresh` after deploy since staging has no scheduled
  refresh). Frontend branch pushed → Vercel preview on project `fpl-decision`
  in team `ziad-naders-projects`; Preview env already points
  `VITE_FPL_API_BASE_URL` at the dev app. Preview alias must be in the dev
  app's `FPL_API_CORS_ORIGINS` secret (explicit list, never `*`). The PR
  bodies carry the preview link.
- Ops follow-up outside the PR: check the Fly volumes hold the 9-team
  European calendar seed; CLAUDE.md stale notes; shared recency-window
  backtest ticket.

## 6. Left to the builder

- Exact column names for xG/xA in the history CSVs and the snapshot table.
- Where the transfers-endpoint cache lives (follow the existing TTL pattern).
- Formation search reuse for the per-GW best XI inside the objective.
- Tie-break order inside role rules when several bodies qualify at one price.
- Mobile layout details for three pitches.
- Whether `src/chip_bench.py` or an `optimizer` submodule is the cleaner home.

## 7. Open questions resolved as my calls (user said "surprise me")

- Pins/excludes: in.
- Three squads live on a new `/wildcard/drafts` route; `/recommendations`
  builds the chosen preset only (4.11).
- Two-stage scalar build, not per-GW XI search (4.4).
- Budget from `entry_history.value` (verified), no transfers reconstruction.
- Same-team penalty on the whole defender score, not a CS share (4.5).
- Injury prior from snapshot status history only, this season (4.6).
- Trend ships with a shrinking window, near zero at GW8, labelled (4.3).
- Default preset legacy-equivalent; chip_advisor and squad picker unchanged.
- GK: set-and-forget + cheap 90-minute backup; rotating pair deferred.
- Bench weight 0.15, bench budget cap 17.5 / 17.0, availability bars
  0.85 / 0.80 / 0.70, DC probability 0.5, decay 0.96, DEF cap 2 with
  elite-defence exception. All config, all `[untested]`.
