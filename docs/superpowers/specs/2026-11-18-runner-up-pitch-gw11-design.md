# Runner-up transfers on the pitch — GW11 batch (design)

Date: 2026-11-18 · Deadline: GW11, 21 Nov · Size: small change, two repos
(FPL backend, fpl-decision-hub frontend).

## Why

The owner picked the runner-up move Brobbey → Evanilson in the
Transfers step. The review pitch then looked broken and the numbers disagreed:

1. **Misaligned card.** Evanilson's card is shorter than Haaland's. Runner-up
   moves (`verdict_detail.runner_ups`) carry no fixture, so the card prints the
   plain team ("BOU") instead of a fixture chip, and the card loses height.
2. **Wrong starter dropped.** Brobbey was a bench FWD. The frontend promotes the
   buy over the weakest *same-position* non-captain starter (`gwPlan.ts:154`), so
   Evanilson (5.88) displaced Barry. The −0.5 also includes the owner's own
   Kinsky-for-Verbruggen keeper swap, so Barry's exact xPts is back-solved, not
   read. Schade (2.68, MID) was the cheaper starter to drop (3-5-2 → 3-4-3).
3. **Misleading "IN +4.1".** `this_gw_gain` is buy − seller even when the seller
   is benched (`transfer_planner._move_record`), while the horizon gain (+0.2)
   already uses an XI floor. Two numbers on one move, measured differently.

Owner also wants a UX/data check of the whole flow after the fixes land.

## Goals

- Every pitch card in a row has the same height, fixture or not.
- A runner-up buy shows its real fixture chip and its own xPts (no estimate).
- A buy that has to come off the bench displaces whoever makes the best legal
  XI, any outfield position, not only same-position.
- "IN +x", the sidebar gain, and the projected delta tell one consistent story.

## Non-goals

- Retuning thresholds/bars, wildcard logic, or the decision card copy.
- Redesigning the Transfers step (separate brainstorm after the UX check).

## Anti-goals

- Shipping an engine change that alters which move ZN Pick recommends without a
  backtest comparison against current master.

## Approach (agreed: fix at source, same batch)

Two backend PRs: (a) display-only fields — `this_gw_gain` is read only by
`_verdict_detail` sums and reasoning copy (`transfer_planner.py:305,618`), so
changing it does not change picks; (b) the XI-aware horizon gain in
`_best_swap`, which does change picks and goes behind the backtest.

**Backend (`FPL`)**
- Annotate verdict moves *and* runner-ups: `buy.next_fixtures` in the pitch
  grammar (`H-OPP(Dn)`, DGW comma-joined, same producer as squad players) and
  `buy.xpts` read from the same projection column that fills
  `starting_xi[].xpts`. Leave the existing `next_fixture` ("OPP (H)") alone:
  `planFlow.ts:204` copy and `tests/test_next_fixture_labels.py` depend on it;
  extend that annotation to `verdict_detail.moves` and `runner_ups` too.
- XI-aware gain for a bench seller: gain = value of the best legal XI after the
  swap − before (`_likely_xi` over VALID_FORMATIONS), for both the horizon gain
  and `this_gw_gain` (GW-only values). Starter sellers stay buy − seller.
  This can change ZN Pick's choice → run the season backtest on master vs
  branch; ship only if not worse, report numbers in the PR. Confirm the
  harness reaches the bench-seller branch (`xi` at `:403`). Precompute
  per-position sorted values rather than calling `_likely_xi` per candidate.

**Frontend (`fpl-decision-hub`)**
- `PlayerCard`: fixed-height fixture line (no-fixture fallback matches chip
  height). Nudge the "IN" pill so it does not collide with the row above.
- `buildPlayerLookup`: use `buy.xpts` / `buy.next_fixtures` when present; keep
  the estimate only as a fallback for old payloads.
- `transferChoicePatch`: displace the weakest non-captain outfield starter whose
  removal keeps DEF≥3, MID≥2, FWD≥1 (FPL rules) — this-GW xPts, as today.
- "IN +x" pill = what the pitch actually gained: buy xPts − displaced player's
  xPts (or − seller when the seller started). Derived from the resolved plan,
  so the pill matches the projected delta. The backend `this_gw_gain` stays a
  pre-pick estimate (horizon-ranked likely XI, never forces a start); the
  sidebar/decision card label it as the engine's estimate. No equality test.
- Stored plans: `reconcilePromotion` keeps an old same-position promotion
  (seller/buy unchanged → null). Re-run promotion when the lineup was not
  hand-edited since; check `swapPlayers` + undo with a FWD-for-MID swap.
- Height is verified by screenshot of the running app (jsdom has no layout):
  a runner-up picked, and a no-fixture card.

## Left to the builder

Exact pill offset, test fixtures, where the label helper is shared.

## After

UX/data walkthrough of the plan flow with the owner's real squad (verify skill),
listing anything that still reads wrong, before the next brainstorm.
