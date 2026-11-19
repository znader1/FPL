# Runner-up Pitch Fixes (GW11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runner-up transfer looks and scores right on the review pitch: real fixture chip and xPts, aligned card, the buy displaces the best legal starter, and the "IN" pill equals what the pitch gained.

**Architecture:** Backend (FPL) adds display-only fields to verdict moves; frontend (fpl-decision-hub) consumes them, fixes card height, makes promotion formation-aware and derives the pill from the resolved plan. Engine scoring (`_best_swap`) is untouched — that is a separate post-GW11 plan.

**Tech Stack:** Python/FastAPI + pandas + pytest (FPL); React + TypeScript + Vitest (fpl-decision-hub).

**Spec:** `docs/superpowers/specs/2026-11-18-runner-up-pitch-gw11-design.md` (piece 3, the `_best_swap` engine change, is deferred).

## Global Constraints

- Work only in worktrees: backend `scratchpad/be` (branch `fix/runner-up-pitch-gw11` off `origin/master`), frontend a new worktree off `origin/main` on branch `fix/runner-up-pitch-gw11`. Never switch branches in the shared checkouts.
- Ship before the GW11 deadline, 21 Nov 2026. Backend deploys first (frontend falls back when fields are absent).
- Do not change `next_fixture` ("OPP (H)") or `tests/test_next_fixture_labels.py` expectations; `planFlow.ts:204` depends on that format.
- Pitch fixture grammar: `H-OPP(Dn)`, DGW comma-joined — the `fixtures_gw{gw}` column already used for `next_fixtures` on squad players (`src/lineup_builder.py:175`).
- FPL formation rule: XI = 1 GKP, DEF ≥ 3, MID ≥ 2, FWD ≥ 1.
- Run `security-review` on each diff before its PR; report findings in the PR body. User merges.

## Review Focus

1. Buy whose team blanks this GW → no `next_fixtures`; card must keep full height (fallback line same height as chip).
2. Captain is the weakest eligible starter → never displaced (existing rule, keep).
3. Seller already starting → no promotion; pill = buy xPts − seller xPts.
4. Saved plan from before this change (Barry benched by the old same-position rule) → reconciles to the new pick unless the user hand-edited the lineup afterwards.
5. Old payload without `buy.xpts` → lookup falls back to seller xPts + `this_gw_gain` (today's estimate), no crash.

---

### Task 1: Backend — annotate verdict moves with pitch fixture + own xPts

**Files:**
- Modify: `api/main.py` (new helper next to `annotate_moves_next_fixture` ~line 460; call after `transfer_planner.plan_transfers(...)` ~line 1589)
- Test: `tests/test_next_fixture_labels.py`

**Interfaces:**
- Produces: `annotate_verdict_moves(plan_horizon: dict | None, proj: pd.DataFrame, event_id: int, fixture_labels: dict[int, str], team_by_player: dict[int, int]) -> None` — mutates in place. On every `sell`/`buy` dict in `verdict_detail.moves`, `verdict_detail.runner_ups`, `verdict_detail.roll_alternative.moves`: sets `next_fixtures` (from `proj["fixtures_gw{event_id}"]`, omitted when empty), `xpts` (from `proj["xpts_gw{event_id}"]`, rounded 2), and `next_fixture` (existing "OPP (H)" label, omitted on a blank). Frontend type gains `next_fixtures?: string; xpts?: number` on `FplTransferPlayer`.

- [ ] **Step 1: Write the failing tests**

```python
def test_annotate_verdict_moves_runner_ups_and_moves():
    proj = pd.DataFrame([
        {"id": 10, "fixtures_gw2": "H-BOU(D2)", "xpts_gw2": 1.78},
        {"id": 20, "fixtures_gw2": "A-ARS(D4)", "xpts_gw2": 5.876},
        {"id": 30, "fixtures_gw2": "", "xpts_gw2": 0.0},
    ])
    plan = {"verdict_detail": {
        "moves": [{"sell": {"id": 10}, "buy": {"id": 20}}],
        "runner_ups": [{"sell": {"id": 10}, "buy": {"id": 30}}],
        "roll_alternative": None,
    }}
    annotate_verdict_moves(plan, proj, 2, {1: "BOU (H)", 3: "ARS (A)"}, {10: 1, 20: 3, 30: 2})
    buy = plan["verdict_detail"]["moves"][0]["buy"]
    assert buy["next_fixtures"] == "A-ARS(D4)" and buy["xpts"] == 5.88 and buy["next_fixture"] == "ARS (A)"
    blank = plan["verdict_detail"]["runner_ups"][0]["buy"]
    assert "next_fixtures" not in blank and "next_fixture" not in blank and blank["xpts"] == 0.0

def test_annotate_verdict_moves_tolerates_missing_plan():
    annotate_verdict_moves(None, pd.DataFrame(), 2, {}, {})  # no raise
```

- [ ] **Step 2:** Run `pytest tests/test_next_fixture_labels.py -v` → FAIL (`annotate_verdict_moves` not importable).
- [ ] **Step 3:** Implement `annotate_verdict_moves` in `api/main.py`; build `fixture_labels` with `next_fixture_labels_by_team` and `team_by_player` the way `annotate_moves_next_fixture` does (extract its player→team loop into `_team_by_player(elements)` and reuse). Call it right after `out["transfer_plan_horizon"] = ...`, inside its own `try/except` that only logs (cosmetic, never fails the response). Note: `_detail_move` shares the sell/buy dicts with `transfers.moves`, so annotating twice is harmless — same values.
- [ ] **Step 4:** Run `pytest tests/test_next_fixture_labels.py tests/test_verdict_detail.py -v` → PASS.
- [ ] **Step 5: Parity check.** With `PYTHONPATH=.` run `scratchpad/probe.py` (calls `build_recommendations` for the owner's entry, GW11) and assert for every runner-up buy also present in `starting_xi`/`bench`/`position_panels`, `buy.xpts` equals that record's `xpts` (±0.01). Expected: equal. If not, switch the source column to whatever fills `starting_xi[].xpts` and note it in the PR.
- [ ] **Step 6:** Full suite `pytest -q` → green. Commit `feat(transfers): verdict moves carry pitch fixture + own xPts`, together with the spec and this plan.

### Task 2: Frontend — consume the new fields + fixed-height fixture line + pill placement

**Files:**
- Modify: `src/lib/fplAssistantApi.ts` (`FplTransferPlayer`), `src/lib/gwPlan.ts` (`buildPlayerLookup` ~line 271), `src/components/PlayerCard.tsx` (~lines 141-175)
- Test: `src/lib/gwPlan.test.ts`, `src/components/PlayerCard.test.tsx`

**Interfaces:**
- Consumes: Task 1 fields `buy.next_fixtures?: string`, `buy.xpts?: number`.
- Produces: synthesised lookup records with `next_fixtures` and `xpts` from the move when present.

- [ ] **Step 1: Failing tests.**
  - `buildPlayerLookup` › "runner-up buy uses its own xpts and pitch fixture": move `buy {id: 79, xpts: 5.88, next_fixtures: "H-NFO(D3)"}`, seller xpts 1.78, `this_gw_gain` 4.1 → `lookup[79].xpts === 5.88`, `lookup[79].next_fixtures === "H-NFO(D3)"`.
  - same › "falls back to seller + this_gw_gain without buy.xpts": no `xpts` on buy → `lookup[79].xpts` ≈ 5.88 (1.78 + 4.1).
  - `PlayerCard` › "no-fixture card renders the fallback line with the chip's height class": render without `fixture` → the team line element has the same height class (`h-4` or chosen token) as the `FixtureChip` wrapper; with fixture → same class present. (Structure test only; real height checked by screenshot in Task 4.)
- [ ] **Step 2:** `npx vitest run src/lib/gwPlan.test.ts src/components/PlayerCard.test.tsx` → FAIL.
- [ ] **Step 3:** Implement: add the two optional fields to `FplTransferPlayer`; in `buildPlayerLookup` set `xpts: m.buy.xpts ?? (seller?.xpts ?? 0) + m.this_gw_gain` and `next_fixtures: m.buy.next_fixtures ?? m.buy.next_fixture`; wrap the fixture/team line in a fixed-height container (same height as `FixtureChip`, centred). Move the "IN" pill so it overlaps the jersey instead of sitting above it (e.g. `top-0` instead of `-top-3.5`) — final offset decided by screenshot.
- [ ] **Step 4:** Re-run the tests → PASS. Commit `fix(pitch): runner-up buys show their fixture; cards keep one height`.

### Task 3: Frontend — formation-aware promotion, honest pill, reconcile old plans

**Files:**
- Modify: `src/lib/gwPlan.ts` (`transferChoicePatch` ~132, `reconcilePromotion` ~169, `resolvePlan` ~245), callers of `resolvePlan` (`src/pages/Index.tsx:566`, `src/lib/weekDecisions.ts:67,74`, `src/lib/planFlow.ts:139`, `src/lib/gwPlan.ts:355`)
- Test: `src/lib/gwPlan.test.ts`

**Interfaces:**
- Produces: `resolvePlan(plan: GwPlan, moves: FplTransferVerdictMove[], lookup?: PlayerLookup): ResolvedPlan` — `incoming[buyId]` = `xpts(buy) − xpts(plan.promoted.starter)` when that move was promoted, else `xpts(buy) − xpts(seller)`; falls back to `m.this_gw_gain` when lookup or an xpts is missing. Pass `lookup` at every caller that has one.
- Produces: `promotionStarter(xi: number[], buyPos: FplPosition, cap: number, lookup: PlayerLookup): number | undefined` (exported for tests) — weakest-by-this-GW-xPts non-captain outfield starter whose removal, with the buy added, keeps DEF ≥ 3, MID ≥ 2, FWD ≥ 1; GKP buy only replaces the GKP.

- [ ] **Step 1: Failing tests** (fixture: owner's squad — XI Verbruggen; Van Hecke, De Cuyper, Calafiori; Schade 2.68, Rogers 4.45, Mbeumo 3.99, Ødegaard 4.48, Palmer 4.12; Haaland (C) 5.66, Barry 6.4; bench Kinsky, Shaw, Hume, Brobbey 1.78; move Brobbey→Evanilson buy xpts 5.88):
  - "bench FWD buy displaces the weakest legal outfield starter, not the FWD" → after `transferChoicePatch(..., "make", ...)`, `xi` contains Evanilson's seller slot in place of Schade; Barry still in XI; `promoted.starter === SCHADE`.
  - "respects formation minimums": XI with exactly 2 MID and Schade weakest MID → a FWD buy displaces the weakest DEF/FWD that keeps ≥3 DEF instead (assert chosen id).
  - "captain never displaced" (Haaland weakest + captain → not chosen).
  - "incoming pill equals the pitch gain": `resolvePlan(plan, moves, lookup).incoming[EVANILSON]` ≈ 5.88 − 2.68 = 3.2.
  - "starter seller: pill is buy − seller": promote nothing; incoming = buy − seller.
  - "reconcilePromotion migrates an old same-position promotion": stored plan with `promoted {seller: BROBBEY, starter: BARRY, buy: EVANILSON}` and lineup exactly as the old rule produced → returns patch with `promoted.starter === SCHADE`, Barry back in XI.
  - "reconcilePromotion keeps a hand-edited lineup": same, but the user later swapped Barry back in for someone else (Barry not on bench) → returns null.
  - "undo after FWD-for-MID swap restores the original XI": choose "roll" after the promotion → `xi`/`bench` equal the pre-transfer plan.
- [ ] **Step 2:** `npx vitest run src/lib/gwPlan.test.ts` → FAIL.
- [ ] **Step 3:** Implement `promotionStarter`, use it in `transferChoicePatch`; extend `reconcilePromotion`: when `pr` matches the moves, `pr.starter` is still on the bench and `promotionStarter` (computed on the plan with the old promotion undone) differs from `pr.starter`, return the re-promoted patch; otherwise keep current behaviour. Thread `lookup` into `resolvePlan` callers.
- [ ] **Step 4:** `npx vitest run` (whole suite) and `npx tsc --noEmit` → green. Commit `fix(plan): buys start over the weakest legal starter; IN pill shows the pitch gain`.

### Task 4: Verify on the running app + ship

- [ ] **Step 1:** Run backend locally (Task 1 branch) + frontend dev (Task 2-3 branch) with the `run` skill; sign in as owner, open Transfers, pick runner-up Brobbey → Evanilson, go to Review.
- [ ] **Step 2: Screenshot checks** (expected): Evanilson and Haaland cards same height and level; Evanilson shows a fixture chip; Schade on bench, Barry starting, formation 3-4-3; "IN +x" equals projected delta contribution and does not touch the row above; a blank-GW player (if any) card full height.
- [ ] **Step 3:** `security-review` on both diffs; open PRs (backend first), bodies list the parity check result and screenshots. User merges; deploy backend (Fly) then frontend (Vercel, scope `ziad-naders-projects` — confirm before deploy).
- [ ] **Step 4:** After deploy, `verify` skill on prod with the owner's squad, then hand over to the UX/data walkthrough (next brainstorm).
