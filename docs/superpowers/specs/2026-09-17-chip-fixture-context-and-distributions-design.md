# Chip Planner — Fixture Context (European weeks, breaks, cup clashes) + Per-GW Points Distributions

**Date:** 2026-09-17
**Status:** Shipped on `claude/chips-fixtures-points-projection-a0r34t` (backend + frontend)
**Builds on:** `2026-09-08-chip-strategy-upgrades-design.md` (breaks, FH tough gate, swings, haul_prob)

## Context

The chip planner (`src/chip_advisor.py`, `GET /chips/plan`) already accounts for
international breaks (confidence haircut + `wait_for_team_news`), fixture
difficulty, swings and announced DGW/BGWs. Three gaps remained:

1. **European midweeks are invisible.** The FPL API knows nothing about the
   Champions / Europa / Conference League. A Triple Captain on a player whose
   side plays a knockout tie three days earlier, or a Bench Boost on a bench
   full of rotation-prone Europeans, looked identical to a clean week.
2. **The plan reasoned about fixtures but never showed them.** Breaks, DGWs,
   blanks and cup clashes only surfaced as prose inside `reasons[]`; the Chips
   tab had no calendar to look at.
3. **Every chip EV was a bare mean.** "TC in GW12 projects +9.1" hides whether
   that is a safe 7 or a coin-flip between 2 and 18 — and gives no likelihood
   that the chip actually clears its play/hold bar.

## Goals

- Chip EV and confidence account for European congestion (both directions:
  the midweek leading into a GW and the one right after it).
- The Chips tab shows a per-GW fixture calendar: deadline, post-break flag,
  European weeks (with the manager's own exposed players), DGW/BGW, cup
  clashes — model zone as a strip, notable later weeks collapsed.
- TC/BB recommendations carry the distribution of the chip's extra points:
  P(return), P(haul), P(blank), P(beats bar), modal score, 80% band; the EV
  curve carries P(beats bar) per GW.
- Expected (not yet announced) blank weeks from domestic-cup clashes surface
  as likelihood-tagged provisional Free Hit windows.

## Non-goals

- No change to projection math. The European haircut lives in the chip
  engine (`european.discount_projections`) and only touches the chip
  comparison; `projections.py` is untouched.
- No distribution for FH/WC — their gains come from optimizer-built dream
  squads. TC and BB are the chips whose gain is literally "points scored by
  known players", which is where a distribution is honest.
- No automatic European qualification detection — there is no source for
  it. The calendar is user-maintained (see Section 1).

## Section 1 — European calendar signal (`src/european.py`)

**Data:** `data/models/european_calendar.json` (ships as a seed like
`knowledge_discount.json`; `ensure_seed_models` copies it into the volume and
never overwrites a runtime edit).

```json
{
  "teams": {"Arsenal": "ucl", "Aston Villa": "uel"},          // FPL full name, short_name or id
  "matchdays": [{"competition": "ucl", "label": "MD1", "dates": ["2026-09-15", "2026-09-16", "2026-09-17"]}],
  "cup_rounds": [{"competition": "fa_cup", "label": "quarter-final", "dates": ["2027-03-20", "2027-03-21"], "likely_blank": true}]
}
```

The seed ships with the 2026-27 matchday spans and an **empty `teams` map**
— the signal is off until the qualified sides are filled in (`_workflow`
in the file). Wrong teams would silently discount the wrong players; empty
is the safe default.

**Windowing.** GW `g` runs deadline(g) → deadline(g+1). A team is in a
European week for `g` when a matchday of its competition is inside that
window (`when: "after"` — rested-in-the-league risk before a big tie) or in
the `CHIP_PLAN_EURO_WINDOW_BEFORE_DAYS` (5) before the deadline (`when:
"before"` — fatigue / late rotation), `"both"` when sandwiched. One Tuesday
tie therefore marks the GW before and the GW after it, which is the real
effect.

**Application in `build_chip_plan`:**

- `european.discount_projections` scales `xpts` by `CHIP_PLAN_EURO_XPTS_MULT`
  (0.95) for every player of a European team that GW, on **both** the squad
  and the market side, so a FH/WC dream squad can't dodge it. 1.0 = off.
- TC: captain in a European week → risk line naming the competition and
  timing ("plays in the Champions League 3 days before GW12 — fatigue / late
  rotation risk") and confidence × `CHIP_PLAN_EURO_CONFIDENCE_MULT` (0.9).
- BB: exposed bench players are named; ≥ `CHIP_PLAN_EURO_BB_MIN_BENCH` (2)
  of them cut confidence. A reason line counts the squad's exposure.
- `ev_curve` points carry `european: <n squad players>`.

**Cup clashes.** `cup_clashes_by_gw` maps cup rounds whose dates fall inside
a GW window. In the structural zone, a `likely_blank` clash with no announced
blank yet becomes a `provisional` FH recommendation with
`likelihood: CHIP_PLAN_CUP_CLASH_BLANK_PROB` (0.7) — announced structural
recs carry `likelihood: 1.0`. Inside the model horizon the clash is
calendar-only (the announced fixtures already drive the EV).

**Failure modes:** missing/malformed file → `{}` → no European weeks, no
cup clashes, plan identical to today. `signals.european_calendar: false`
tells the frontend to show the "not configured" hint.

## Section 2 — Per-GW points distributions (`src/chip_distribution.py`)

**Priors** (`player_priors_from_elements`, built in `api/chips.build_chip_signals`
from the bootstrap): per player `pos`, `xg90`, `xa90`, `p_appear` (starts
shrunk toward `MINUTES_START_PRIOR` over `finished_gws`, × availability from
`chance_of_playing_next_round`/status), `p_60`.

**Per player-GW pmf** (`player_gw_pmf`): the same convolution the player
cards use (`points_distribution.player_points_pmf`) with exposure = fixture
count × minutes share × difficulty multiplier (`CHIP_PLAN_TC_DIFF_MULT`) ×
`p_appear`, clean sheets from `CHIP_PLAN_CS_PROB_BY_DIFF`. The
goal/assist/CS lambdas are then bisected so the pmf mean equals the engine's
blended xPts × (1 − `CHIP_PLAN_DIST_CONTINUOUS_SHARE[pos]`) — the bonus /
saves / conceded share the pmf excludes. **The shape and the EV never
disagree.** No fixture, xPts ≤ 0 or p_appear < 2% → spike at zero; no prior
→ `None` (the field is omitted, never invented).

**Chip-level:**

- TC extra points = the captain's own score → the captain's pmf.
- BB extra points = bench-4 sum → convolution of the four bench pmfs
  (independence assumed; same-team correlation slightly understates tails).
- `summarize(pmf, bar)` → `{mean, modal, p_return (≥6), p_haul (≥10), p_blank
  (≤2), p80_low, p80_high, bar, p_beats_bar}` with the bar =
  `effective_min_ev(chip, gw, expires_gw)`.

**Surfaces:** `recommendations[].distribution`, `outlook[].distribution`,
`ev_curve[].p_beats_bar` / `p_return`, `nudge.p_beats_bar`, plus a reason
line ("62% chance the captain returns (6+), 28% of a 10+ haul, 24% of a
blank" / "Bench most likely 8 pts (80% band 6–10)"). EV ranking is untouched.

## Section 3 — Calendar payload

`build_calendar` emits one row per GW from `current_gw` to season end:

```
{gw, deadline_utc, in_model_zone, post_break, break_gap_days,
 european: {ucl: [teams], ...}, squad_european: [{name, team, competition, when}],
 n_teams_playing, dgw_teams, blank_teams, is_blank_heavy, has_dgw, cup_clash}
```

`signals` reports which inputs were present: `{breaks, european_calendar,
cup_calendar, distributions, european_xpts_mult}`.

`api/chips.build_chip_signals` now returns a dict keyed by `SIGNAL_KEYS`
(the four 2026-09-08 signals + `player_priors`, `euro_by_gw`, `cup_clashes`,
`events`, `team_labels`); `scripts/spotcheck_chip_plan.py` consumes the same
dict and prints a model-zone calendar summary. The all-or-nothing fail-soft
rule is unchanged: any signal failure drops every signal.

## Section 4 — Frontend (`fpl-decision-hub`)

- `ChipRoadmapPanel`: a **Fixture context** strip above the recommendations
  — one cell per model-zone GW (deadline date, `break` / `DGW` / `BGW` /
  `cup` / `N in UCL` tags with hover detail), notable later weeks behind a
  `<details>`, a "European weeks ×0.95 xPts" note when the discount is live
  and a "European calendar not configured" hint when it isn't.
- Recommendation rows: `NN% beats bar` pill in the header (TC/BB), a
  distribution line when expanded, `Risk:` reasons in amber, EV-curve bars
  shaded by P(beats bar) with amber GW labels on post-break / European weeks,
  provisional rows badge `~70% likely` instead of `provisional` when the
  window is expected rather than announced.
- Outlook rows: `+x vs bar y · NN% odds` and the same distribution line.
- `ChipNudgeCard`: appends "· NN% chance it beats the bar".
- All types additive in `fplAssistantApi.ts` (`ChipDistribution`,
  `ChipCalendarRow`, `ChipPlanSignals`, `likelihood`, `p_beats_bar`).

## Config additions (`src/config.py`)

| Name | Default | Meaning |
|---|---|---|
| `CHIP_PLAN_EURO_WINDOW_BEFORE_DAYS` | 5 | Days before a deadline a European tie still counts as "before" |
| `CHIP_PLAN_EURO_XPTS_MULT` | 0.95 | xPts multiplier for players of teams in a European week (both sides) |
| `CHIP_PLAN_EURO_CONFIDENCE_MULT` | 0.90 | Confidence haircut for an exposed TC captain / BB bench |
| `CHIP_PLAN_EURO_BB_MIN_BENCH` | 2 | Exposed bench players before BB confidence is cut |
| `CHIP_PLAN_CUP_CLASH_BLANK_PROB` | 0.70 | Likelihood tag on an expected cup-clash blank |
| `CHIP_PLAN_DIST_CONTINUOUS_SHARE` | GKP .25 / DEF .12 / MID .10 / FWD .10 | Share of xPts the pmf excludes (bonus, saves, conceded) |
| `CHIP_PLAN_DIST_RETURN_AT` / `HAUL_AT` / `BLANK_AT` | 6 / 10 / 2 | Distribution thresholds |
| `CHIP_PLAN_DIST_PRIOR_WEIGHT` | 2.0 | Pseudo-GWs of start prior in `p_appear` |
| `CHIP_PLAN_DIST_MINUTES_SHARE` | 0.85 | E[minutes]/90 given an appearance |
| `CHIP_PLAN_CS_PROB_BY_DIFF` | {1:.50, 2:.42, 3:.33, 4:.25, 5:.18} | Per-fixture clean-sheet prob by difficulty |

## Testing

- `tests/test_european.py` — windowing (after/before/both, configurable
  window), alias normalization, malformed file/events, the shipped seed
  parses with an empty team map, discount touches only flagged teams and
  never mutates input, squad exposure.
- `tests/test_chip_distribution.py` — pmf sums to 1 and mean tracks xPts,
  odds move with xPts, unavailable / no-fixture / no-prior paths, bar odds,
  convolution, priors from elements (start-rate shrinkage, availability,
  position fallback).
- `tests/test_chip_advisor.py` — TC European risk + confidence (EV untouched
  at the scorer), BB exposure, distributions attached only with priors, the
  plan-level discount hits both sides, curve/outlook/nudge probabilities,
  calendar rows, cup-clash provisional FH (skipped inside the horizon, when
  not blank-making, when announced, when the chip is used).
- `tests/test_chips_route.py` — the signals reach the engine through
  `build_chip_signals` (calendar file → European risk line, discounted EV,
  distribution, calendar rows, `signals`).
- Frontend: `tsc`, `eslint`, `vite build` (no test suite in that repo).
- Pre-deploy: fill `teams` in `data/models/european_calendar.json` on the
  Fly volume, then `PYTHONPATH=. python -m scripts.spotcheck_chip_plan
  <entry_id>` and read the calendar summary + TC/BB reasons.

## Release

Backend first (payload is additive; an older frontend ignores the new keys),
then frontend. The seed calendar lands in the volume on the next boot via
`ensure_seed_models`; the team map must be edited on the volume (or the seed
updated and the volume file removed) to switch the European signal on.
