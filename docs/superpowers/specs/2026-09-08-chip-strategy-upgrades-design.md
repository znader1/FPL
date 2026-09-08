# Chip Strategy Upgrades — Design

**Date:** 2026-09-08
**Status:** Approved
**Builds on:** `docs/superpowers/specs/2026-09-01-chip-planner-design.md` (chip planner engine + frontend, engine shipped, frontend unmerged)

## Context

The chip planner engine (`src/chip_advisor.py`, `GET /chips/plan`) ships on the backend and
honors the 2026-27 split chip system (2x each chip, first set expires GW19,
`CHIP_PLAN_PHASE_SPLIT_GW=19`). The frontend (ChipRoadmapPanel, ChipNudgeCard, chips tab)
exists on `feature/chip-planner-frontend` but never reached main.

Three strategy signals the engine lacks today:

1. **International breaks** — no representation anywhere in the repo. Post-break GWs carry
   elevated injury/rotation uncertainty (late flags, players returning from long travel),
   which should temper chip confidence and delay commit-style advice.
2. **Free hit trigger too narrow** — `score_free_hit` is gated on ≥3 squad players blanking
   (`CHIP_PLAN_FH_MIN_BLANKING`). The classic FH case "most of my squad faces tough
   fixtures this GW while the market offers easy ones" never opens the gate.
3. **Fixture swings are implicit** — wildcard EV uses horizon xPts so swings influence the
   number, but no explicit swing detection exists, so reasons can't say *why* a GW is a
   good wildcard window and the TC/Fixtures surfaces can't show swing context.

This release ships all three engine upgrades plus the unmerged chip frontend in one
release (backend Fly + frontend Vercel) before the next deadline.

## Goals

- Chip recommendations account for international-break uncertainty.
- Free hit fires on tough-fixture pileup weeks, not only blank weeks.
- Wildcard/TC reasons name the fixture swings driving the window.
- Chip planner UI reaches production.

## Non-goals

- No changes to projection math (`projections.py` xPts) — approach B (variance modelling,
  dynamic thresholds) rejected for mid-season regression risk.
- No new pages; chips surface inside the existing RecommendationsPanel tab + nudge card.
- No changes to chip EV formulas; new signals act through gates, confidence, and reasons.

## Section 1 — International break signal

**New module:** `src/breaks.py`

```python
def international_break_gws(events: list[dict], gap_days: float = BREAK_GAP_DAYS) -> dict[int, dict]:
    """Map event_id -> break info for GWs whose deadline sits more than
    gap_days after the previous event's deadline (first GW after a break)."""
```

- Detection is calendar-derived from FPL `events` bootstrap data (deadline-to-deadline
  gap > `BREAK_GAP_DAYS`, default 10; normal cadence is ~7 days, international windows
  produce ~14). No hardcoded dates; works every season, including rearranged calendars.
- Returned info: `{gap_days: float, prev_event: int}`.

**Application in `chip_advisor`:**

- Any recommendation targeting a post-break GW:
  - append reason: `"First GW after international break — elevated injury/rotation uncertainty"`
  - multiply confidence by `CHIP_PLAN_BREAK_CONFIDENCE_MULT` (default 0.85). EV untouched.
- Triple captain recs targeting a post-break GW additionally append a risk line
  (late flags disproportionately hurt TC value).
- The next-GW `nudge` gains `wait_for_team_news: true` when its GW is post-break;
  the frontend renders a "wait for team news" badge and softens the call-to-action.
- `POST /chat/chip` context includes the break map so the agent can explain timing.

**Failure mode:** malformed/missing events data → empty break map → engine output
identical to today.

## Section 2 — Free hit tough-pileup gate

**Change:** `score_free_hit` in `src/chip_advisor.py`.

- Keep the existing blank gate (≥ `CHIP_PLAN_FH_MIN_BLANKING` squad players blanking).
- Add an OR-path: gate also opens when ≥ `CHIP_PLAN_FH_MIN_TOUGH` (default 6) of the
  manager's 15 face fixture difficulty ≥ `CHIP_PLAN_FH_TOUGH_DIFFICULTY` (default 4.0)
  in the candidate GW.
- Difficulty comes from the existing fixture ticker
  (`fixture_difficulty.build_fixture_ticker` per-team per-GW `difficulty`), wired into
  the chip-plan context in `api/chips.py` (and `/admin/chip-plan`).
- The EV bar is unchanged: `CHIP_PLAN_MIN_EV["free_hit"]` still decides. The gate only
  opens consideration; a tough week where the rebuilt XI doesn't clear the bar still
  produces no rec.
- Reason string names the trigger, e.g.
  `"7 of your 15 face difficulty ≥4.0 in GW12; rebuilt XI gains +9.4 xPts"`.

**Failure mode:** ticker unavailable → OR-path disabled, blank gate only (today's
behavior).

## Section 3 — Fixture-swing detection

**Change:** `src/fixture_difficulty.py`.

```python
def compute_fixture_swings(ticker: dict, window: int = SWING_WINDOW_GWS,
                           min_delta: float = SWING_MIN_DELTA) -> list[dict]:
    """Swing events: at GW t, a team's avg difficulty over [t, t+window) differs from
    its avg over [t-window, t) by >= min_delta. Blank cells (difficulty 3.0 neutral)
    count as-is. Returns [{team, team_short, gw, delta, direction: easier|harder}]."""
```

- Defaults: `SWING_WINDOW_GWS = 3`, `SWING_MIN_DELTA = 0.8`.
- Pure read of the existing ticker; ratings untouched.
- The ticker consumed here is built spanning `plan horizon + window` GWs so swings near
  the horizon edge have a forward window; a GW with fewer than `window` GWs on either
  side is skipped rather than scored on a partial window.

**Consumers:**

- **Wildcard reasons:** a WC rec at GW t lists teams turning easier at ≈t, e.g.
  `"Fixture swings from GW12: ARS, SUN start easy runs"` — answers *why this window*.
- **Triple captain reasons:** when the recommended captain's team is inside an
  easier-swing run, say so.
- **Fixtures page (optional polish):** swing badges on the ticker rows. Ships only if
  frontend time allows; backend exposes swings regardless.

## Section 4 — Frontend ship + release

- Rebase/merge `feature/chip-planner-frontend` onto a main-based release branch:
  ChipRoadmapPanel, ChipNudgeCard, chips tab in RecommendationsPanel,
  `fetchChipPlan` + types in `fplAssistantApi.ts`.
- New UI work: render `wait_for_team_news` badge on the nudge card. Break/swing content
  otherwise arrives through existing `reasons[]` strings — no further UI changes.
- `feature/live-points-and-components` stays independent; not part of this release.

**API contract (additive only):**

- `nudge` object: + optional `wait_for_team_news: bool`.
- No removals or renames; existing frontend branch code remains compatible.

**Config additions (`src/config.py`):**

| Name | Default | Meaning |
|---|---|---|
| `BREAK_GAP_DAYS` | 10 | Deadline gap marking a post-break GW |
| `CHIP_PLAN_BREAK_CONFIDENCE_MULT` | 0.85 | Confidence multiplier for post-break recs |
| `CHIP_PLAN_FH_MIN_TOUGH` | 6 | Squad players on tough fixtures to open FH gate |
| `CHIP_PLAN_FH_TOUGH_DIFFICULTY` | 4.0 | Difficulty threshold counting as tough |
| `SWING_WINDOW_GWS` | 3 | Swing comparison window |
| `SWING_MIN_DELTA` | 0.8 | Min avg-difficulty delta to call a swing |

## Testing

- **Unit — breaks:** synthetic events with 7-day and 14-day gaps; malformed deadlines →
  empty map.
- **Unit — FH gates:** three paths (blank-only, tough-only, neither) in
  `tests/test_chip_advisor.py`; ticker-missing fallback.
- **Unit — swings:** synthetic ticker with a known flip; below-threshold delta ignored;
  blanks handled.
- **Route:** `tests/test_chips_route.py` asserts `wait_for_team_news` passthrough.
- **Frontend:** existing ChipRoadmapPanel/ChipNudgeCard tests from the branch + badge
  render test.
- **Pre-deploy:** `scripts/spotcheck_chip_plan.py` against live data; verify reasons read
  sensibly for the current (post-September-break) state.

## Release

One release before the next deadline:

1. Backend: engine upgrades → Fly deploy.
2. Frontend: chip UI branch merged → Vercel prod (**ziad-naders-projects** team, never
   Augura).
3. Backward-compatible payload means either side can technically deploy first; deploy
   backend first so the badge field exists when the UI lands.
