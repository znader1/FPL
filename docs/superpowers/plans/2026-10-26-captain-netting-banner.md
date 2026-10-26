# Captaincy Bonus, Wildcard Netting and Quiet Banner Implementation Plan (plan 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Only realistic captains earn the wildcard captaincy bonus; the chip planner judges the wildcard against the plan the user actually sees, over the same weeks, against a reachable bar; the main page shows a wildcard banner only when the planner says "play it this week".

**Architecture:** Backend: the captaincy bonus in `projections.add_wildcard_scores` is scaled by the share of horizon GWs in which the player is a plausible captain. `chip_advisor.score_wildcard` scores the Balanced preset draft (built by a helper extracted from `api/wildcard.py`) and nets it against the headline transfer plan's gains for the same GWs. The wildcard nudge carries its window. Frontend: `ChipNudgeCard` renders the wildcard nudge in plain words with a link to `/app/wildcard`; the every-week `WildcardCard` and its pitch preview are removed.

**Tech Stack:** Python 3.11/pandas/pytest (backend); React + TypeScript, Vitest + Testing Library, React Router (frontend).

**Spec:** `docs/superpowers/specs/2026-10-26-wildcard-calibration-design.md` (parts 3, 4, 5 and the designer calls). Independent of plans 1 and 2; can ship before them.

## Global Constraints

- Config only in `src/config.py`, tagged; no `getattr` fallbacks.
- The banner never commits the chip and never changes the persisted chip strategy (`plan.chip` is the source of truth; previews must not leak into the plan).
- Banner copy, exactly: `Play your wildcard this week · about +{N} pts over GW{a}–{b} vs your planned transfers`, with N = `Math.round(ev_gain)` and the button label `See the squad`.
- Chip names stay canonical (`wildcard | free_hit | bench_boost | triple_captain`); the frontend never maps chip names.
- Frontend work happens in a new worktree from `origin/main` (`6d6d075`); the shared checkout at `/Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub` (on `feature/command-center`) is never switched. Backend in `/Users/ziadnader/05_Projects/Tech/FPL-Assistant/worktrees/wildcard-calibration`.
- One PR per repo; security review on each diff before its PR. The backend PR merges before the frontend one (the frontend reads the new optional `window_gws`, so an older backend still renders).

## Review Focus

- **A market with no MID/FWD projection for a GW** (all blank): the plausibility max is 0, so nobody earns the bonus that GW and there is no division by zero.
- **The Balanced draft fails to build** for a candidate GW: `score_wildcard` falls back to today's pure-xPts squad and says so in `reasoning`, so the plan never errors.
- **The transfer plan is missing** (planner failed): plan gain is 0 for every GW, the same as today.
- **A wildcard nudge without `window_gws`** (older backend): the banner says `over the next 5 GWs` instead of a range.
- **The user already has wildcard in their plan** (`plan.chip === "wildcard"`): no banner.

---

### Task 1: Captaincy bonus only for plausible captains

**Files:**
- Modify: `src/config.py` (next to `CHIP_WILDCARD_CAPTAINCY_WEIGHT`), `src/projections.py` (`add_wildcard_scores`, captaincy block around `captain_signal` / `captaincy_bonus`)
- Test: `tests/test_wildcard_scores.py` (extend)

**Interfaces:**
- Config: `CHIP_WILDCARD_CAPTAIN_PLAUSIBLE_RATIO = 0.85  # [untested] a player is a plausible captain in a GW when his xPts reach this share of the best MID/FWD xPts in the market that GW`.
- Produces: new output column `wildcard_captain_share` (0..1) = share of horizon GWs where `xpts_gw{g} >= ratio × max(MID/FWD xpts_gw{g})`; `captaincy_bonus` is multiplied by it.

- [ ] **Step 1: Write the failing tests**
  - `test_palmer_case_gets_no_captaincy_bonus`: a market with Haaland (FWD, £15.7m, xPts GW9..13 = 6.64, 6.10, 6.40, 5.20, 6.30) and Palmer (MID, £9.8m, 4.07, 3.90, 4.20, 3.60, 4.50) plus filler → Palmer `wildcard_captaincy_bonus == 0.0`, Haaland's `> 0` and his `wildcard_captain_share == 1.0`.
  - `test_shared_captaincy_is_proportional`: two premiums alternating as the best each GW across 4 GWs, each within the ratio in 2 of them → `wildcard_captain_share == 0.5` for both.
  - `test_blank_market_gw_gives_no_bonus`: one GW where every MID/FWD has 0 xPts → that GW counts as not plausible for everyone, no error.
- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_wildcard_scores.py -q`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the wildcard tests and the full suite.** Expect some existing preset-draft tests (`tests/test_wildcard_build.py`) to shift; update an expectation only when the new draft is the right answer under the new rule, and say why in the commit.
- [ ] **Step 5: Commit** — `git commit -m "fix(wildcard): captaincy bonus only for plausible captains"`

---

### Task 2: Reusable preset-draft helper

**Files:**
- Modify: `api/wildcard.py` (extract from `build_wildcard_drafts`, lines 117-175)
- Test: `tests/test_wildcard_route.py` (existing, must stay green), `tests/test_wildcard_preset_ids.py`

**Interfaces:**
- Produces: `preset_squad_ids(proj_all: DataFrame, bootstrap: dict, play_event_id: int, horizon: int, budget_m: float, preset_name: str) -> set[int] | None` — runs `european_haircut`, `attach_wildcard_signals`, `add_wildcard_scores` and `optimizer.build_chip_squad` exactly as `build_wildcard_drafts` does (no pins, no bans) and returns the 15 ids, or `None` when the build fails. `build_wildcard_drafts` calls the same internal steps so the two can never drift.

- [ ] **Step 1: Write the failing test** — with the synthetic market from `tests/wildcard_market_fixture.py`, `preset_squad_ids(..., "balanced")` returns 15 ids equal to the Balanced squad `build_wildcard_drafts` returns for the same inputs (monkeypatch `_load_context` as `tests/test_wildcard_route.py` does).
- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Extract the helper** and make `build_wildcard_drafts` use the shared steps.
- [ ] **Step 4: Run `tests/test_wildcard_route.py`, the new test, and the full suite.**
- [ ] **Step 5: Commit** — `git commit -m "refactor(wildcard): preset squad ids helper shared with the drafts route"`

---

### Task 3: Honest wildcard netting

**Files:**
- Modify: `src/config.py` (`CHIP_PLAN_BASELINE_HEADLINE_SETTINGS`, `CHIP_PLAN_MIN_EV["wildcard"]`, new `CHIP_PLAN_WC_PRESET`), `api/chips.py:185-245`, `src/chip_advisor.py` (`score_wildcard` at 760, `recommend_chips`, `build_chip_plan`, `_chip_guidance`, the nudge at ~1258)
- Test: `tests/test_chip_wildcard_netting.py`, existing chip tests

**Interfaces:**
- Consumes: Task 2 `preset_squad_ids`.
- Config: `CHIP_PLAN_BASELINE_HEADLINE_SETTINGS = True  # [flag] spec 2026-10-26 overrides the wait-for-parity note`; `CHIP_PLAN_WC_PRESET = "balanced"  # [operational]`; `CHIP_PLAN_MIN_EV["wildcard"]` recalibrated in Step 5.
- Produces:
  - `build_chip_plan(..., wc_squads: dict[int, set[int]] | None = None)` passes through `recommend_chips(..., wc_squads=...)` to `score_wildcard(..., wc_squads=..., plan_gain_by_gw: dict[int, float] | None = None)`.
  - `score_wildcard`: the wildcard side uses `wc_squads[gw]` when present (best XI per future GW from that squad, as today), else today's pure-xPts build with `" [pure-xPts squad — preset draft unavailable]"` appended to the reasoning line. The netted plan gain is `sum(plan_gain_by_gw.get(g, 0.0) for g in future_gws)`, replacing the whole-plan `transfer_plan_net_gain`.
  - `plan_gain_by_gw` is built in `build_chip_plan` from `transfer_plan["plan"]` entries (`{"gw": g, "net_gain": x}`).
  - `api/chips.py` builds `wc_squads` for every candidate GW in the model zone with `preset_squad_ids(ctx["proj"], bootstrap, g, config.CHIP_WILDCARD_DEFAULT_HORIZON_GWS, budget, config.CHIP_PLAN_WC_PRESET)`, where the budget is the squad value + bank already computed for the plan. A failure for one GW leaves that key out, and so does a candidate GW whose 5-GW window runs past the last `xpts_gw*` column in `ctx["proj"]` (the preset scores would read missing GWs as 0).
  - Wildcard nudge gains `window_gws: [g, g + horizon - 1]`.

- [ ] **Step 1: Write the failing tests**
  - `test_plan_gain_is_window_matched`: plan gains `{9: 3, 10: 2, 15: 50}`, wildcard window 9–13 → netted gain 5, not 55.
  - `test_wc_squad_from_preset_is_used`: given `wc_squads={9: ids}`, the wildcard total is computed from those ids (a squad of known xPts gives the expected total).
  - `test_missing_preset_squad_falls_back_and_says_so`.
  - `test_wildcard_nudge_carries_window`: a wildcard rec for the current GW above the floor → `nudge["window_gws"] == [9, 13]`.
  - `test_baseline_plan_uses_headline_settings`: with the flag on, `api.chips._build_plan_response` calls `plan_transfers` with `allow_hits=False` (monkeypatch `plan_transfers` to capture kwargs).
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** the config, the threading, the window-matched gain, the preset squads, and the nudge field. Update `_chip_guidance` so the "net of planned transfers" sentence names the window.
- [ ] **Step 4: Run the new tests and the full suite.**
- [ ] **Step 5: Recalibrate `CHIP_PLAN_MIN_EV["wildcard"]`** with a scratch script (not committed) on live data for the tracked entries (Supabase `chip_plan_snapshots` lists them: 107342, 5645321, 5864391): print each entry's netted wildcard EV per candidate GW, then the same for a synthetic squad with 5 of the XI set to status `i`. Choose the bar so the tracked entries read "hold" on ordinary weeks and the broken squad reads "play"; write the numbers into the config comment and tag it `[tuned]`.
- [ ] **Step 6: Time one `/chips/plan` build locally**; if the extra preset drafts add more than 10 s, limit `wc_squads` to the first 4 candidate GWs and fall back for the rest. Put the measured time in the commit message.
- [ ] **Step 7: Commit** — `git commit -m "fix(chips): wildcard netted against the headline plan over the same weeks, reachable bar"`
- [ ] **Step 8: Security review on the backend diff; open the backend PR.**

---

### Task 4: Quiet banner (frontend)

**Files:**
- Worktree: `git -C /Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub worktree add -b feature/quiet-wildcard-banner ../worktrees/quiet-wildcard-banner origin/main` (run `npm install` there)
- Modify: `src/lib/fplAssistantApi.ts` (`ChipNudge`), `src/components/ChipNudgeCard.tsx`, `src/pages/Index.tsx` (imports at 30-31 and 60; the block at ~860-880; the render block at ~1242-1257), `src/lib/planFlow.ts` (remove `wildcardDraftShown`, `wildcardToggle`)
- Delete: `src/components/WildcardCard.tsx`, `src/components/WildcardCard.test.tsx`
- Test: `src/components/ChipNudgeCard.test.tsx` (create or extend), `src/lib/planFlow.test.ts` (drop the two removed helpers' tests)

**Interfaces:**
- Consumes: backend nudge `window_gws?: [number, number]`.
- Produces: `ChipNudge.window_gws?: [number, number]`. `ChipNudgeCard` for `nudge.chip === "wildcard"` renders the exact copy from Global Constraints and a `See the squad` link to `/app/wildcard` (React Router `Link`); it never calls `onApplyChip`. Other chips render as today.

- [ ] **Step 1: Write the failing tests** (`// @vitest-environment jsdom`, wrap in `MemoryRouter`)
  - `renders the wildcard verdict in plain words`: nudge `{chip: "wildcard", event_id: 9, ev_gain: 14.3, window_gws: [9, 13]}` → text `Play your wildcard this week · about +14 pts over GW9–13 vs your planned transfers`; link `See the squad` has `href="/app/wildcard"`.
  - `the wildcard link never applies the chip`: clicking it does not call `onApplyChip`.
  - `falls back without window_gws`: → `… about +14 pts over the next 5 GWs vs your planned transfers`.
  - `other chips unchanged`: a triple-captain nudge still shows `Apply chip` and calls `onApplyChip("triple_captain")`.
- [ ] **Step 2: Run to verify they fail** — `npx vitest run src/components/ChipNudgeCard.test.tsx`.
- [ ] **Step 3: Implement** the type, the card, and the removals in `Index.tsx` and `planFlow.ts`; delete `WildcardCard` and its test. The Chip step's `Compare three wildcard squads` link stays.
- [ ] **Step 4: Run `npm run typecheck`, `npm run lint`, `npm test`** → all pass (the `GwPlanContext` suite needs `VITE_SUPABASE_URL`/`VITE_SUPABASE_PUBLISHABLE_KEY` set; a pre-existing failure without them is not this change's).
- [ ] **Step 5: Check it in the browser** against the staging backend: an ordinary week shows no banner; with a stubbed wildcard nudge the banner shows and the link opens `/app/wildcard` without changing the plan's chip.
- [ ] **Step 6: Commit** — `git commit -m "feat(plan): wildcard banner only when the planner says play it"`
- [ ] **Step 7: Security review on the frontend diff; open the frontend PR after the backend PR merges.**
