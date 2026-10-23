# Handoff v2: connected GW flow (desktop + mobile)

This **extends** the v1 README (1a/1b/1c). It doesn't replace it, and nothing in v1 is removed. If you've already built 1a/1b/1c, keep that work and apply the changes below.

Reference files: `FPLedge Flow.dc.html` (canvas: 2a desktop, 2b mobile) and `FlowApp.dc.html` (the app itself; one component, with `mobile` as a prop).

## 1. Single plan store (the fix for "clicking Bench resets my squad")
Steps must never refetch or rebuild the squad from the server. They all read and write one client-side plan:

```ts
type GwPlan = {
  xi: PlayerId[];          // 11 starters
  bench: PlayerId[];       // [GK, sub1, sub2, sub3]
  transfer: "make" | "roll" | null;   // ties to verdict_detail (DecisionCard)
  cap: PlayerId; vice: PlayerId;
  chip: "none" | "bb" | "fh" | "tc" | null;
  reviewed: Partial<Record<"transfers"|"captain"|"bench"|"chip", true>>;
  locked: boolean;         // "saved"
};
```
- Put it in React context or zustand, keyed by `entryId + gw`, and persist it to `localStorage`. Seed it once from the squad query.
- `setPlan(patch)`: any **material** change (anything except `reviewed`/`locked`) sets `locked = false`, so a saved plan reopens when edited.
- `resetPlan()` is the **only** thing that restores the original squad.
- Every view (pitch, `PlayerCard` C/VC, `RecommendationsPanel`, projected points) derives from the plan. Applying a transfer swaps the player everywhere and adds the "IN" pill.

## 2. Routing
- Steps: `squad → transfers → captain → bench → chip → confirm`. Route as `/app/plan/:step`, or `?step=` on `/app`.
- Desktop: the left-rail checklist rows (plus "Squad overview") go to their step.
- Mobile: a horizontal step-chip row under the header, with the active chip in pink and ✓ / ! marks.
- Footer is always present:
  - **Back** (ghost) appears on every step except the first.
  - **Next: {step}** (primary) marks `reviewed[step] = true`.
  - On the squad step the button reads "Start GW29 plan" / "Continue plan" and jumps to the first unfinished step.
- Next is disabled, with a hint, when:
  - Transfers has no choice.
  - Chip has no choice.
  - Review has a warning.

## 3. Steps (new and changed)
- **Transfers**: two radio cards, "Make the move" (ZN Pick, +2.4, jerseys) and "Roll the transfer". There's also an "Also considered" row for hit moves that fall below the bar. The data is `verdict_detail`.
- **Captain**: v1 1b cards, with separate **Make captain / Make vice** buttons instead of a whole-card click.
  - Picking the current vice as captain swaps the two roles.
  - A benched candidate is dimmed and disabled, with a note.
- **Bench (new)**:
  - Bench rows: order badge (GK, 1, 2, 3), jersey, name · pos · xPts, ↑ / ↓ (36px icon buttons), and Swap.
  - Tapping **Swap** selects that row (pink) and outlines valid starters on the pitch in teal (`0 0 0 2px accent`). Invalid starters dim to .35, and tapping one shows the rule.
  - Rules: GK only swaps with GK, and the XI must keep at least 3 DEF, 2 MID and 1 FWD.
  - An auto-sub preview tip names who comes on if the flagged starter doesn't play.
  - If the captain gets benched, a rose message tells the user to pick a new one.
- **Chip (new)**: radio cards for Save (ZN Pick), Bench Boost, Free Hit and Triple Captain. Each shows this week's gain and how it compares with the chip's best week.
- **Review (new)**:
  - Summary rows (Transfers, Captain, Bench, Chip). Each row is tappable and goes to its step; changed rows carry a "Changed" badge.
  - Projected points (pink, 32/900) with the delta against the no-change plan.
  - A warning blocks saving (⚠ + Fix button).
  - **Save GW29 plan** (accent) sets `locked`, then a teal panel lists exactly what to change in the FPL app before the deadline.

## 4. Global status
- Navbar pill: "No changes yet" (muted) / "{n} unsaved changes" (warning amber, `--warning`) / "Plan saved" (teal). On mobile it shortens to "{n} unsaved" / "Saved".
- Desktop left rail: "{n} of 4 decisions made" with a progress bar, the decision rows, a projected card (34/900 with the delta) and "Reset plan" (ghost).
- Squad step: a saved banner when `locked`.

## 5. Mobile (390pt)
- Header: glyph, "GW29 plan" with the pulsing deadline, and the status pill. Below it, the step-chip row.
- Content: 16px padding, title 24px. The checklist card sits above the pitch on the squad step.
- Pitch at 72% scale (`zoom`/`transform`), 2px player gap, 14px row gap.
- Cards stack: grids use `repeat(auto-fit, minmax(240–260px, 1fr))`.
- Sticky footer: Back plus a full-width Next. Tap targets are at least 44px.

## 6. Still to design
Loading, error, no-team-ID and "deadline passed" states. Drag-to-reorder on the bench (↑/↓ already covers keyboard use).
