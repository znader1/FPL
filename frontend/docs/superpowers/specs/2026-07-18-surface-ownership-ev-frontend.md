# Surface Ownership-EV Intelligence in League.tsx — Design

**Date:** 2026-07-18
**Repo:** `fpl-decision-hub/` (frontend)
**Status:** Approved design (A+B+C tight slice), pre-implementation
**Companion:** backend sub-project 2 (`FPL/docs/superpowers/specs/2026-07-18-ownership-adjusted-ev-design.md`)

## Goal
Make the new backend differential intelligence **visible and sellable** on the
mini-league page. The `/league/strategy` response now carries `differential_ev` /
`template_xpts` per candidate and a top-level `captain_differential` — currently
unused by the UI. Surface them.

## Scope (A+B+C — tight)
- **A. Types** (`src/lib/fplAssistantApi.ts`): add `differential_ev` + `template_xpts`
  to `LeagueStrategyCandidate`; add `LeagueCaptainDifferential(Player)` types; add
  `captain_differential?: LeagueCaptainDifferential | null` to `LeagueStrategyResponse`.
- **B. Captain-differential callout** (`src/pages/League.tsx`): a prominent amber
  highlighted box at the top of the results card (after the league/rank header,
  before the rivals grid), shown only when `captain_differential` is present. Renders
  the `reason` sentence + a "consensus → differential" badge pair with league-ownership %.
  This is the shareable "beat your mates" hook.
- **C. Diff-EV chips** (`src/pages/League.tsx`): on each `recommended_targets` row,
  add `+X.X diff-EV` (amber) and `Y% league-own` chips beside the existing xPts, via
  a `diffEv` field added to the `playerLookup` map.

## Out of scope
- Differential board / full candidate table (deferred — user chose tight slice).
- Rotation badge from sub-project 1 (minutes model is dormant; later).
- Any backend change (fields already serialized by the response).
- Deploy (branch `chat-backend`, no push — Vercel auto-deploys on push to `main`).

## Non-breaking
All new type fields are optional (`?`), and all new UI is conditionally rendered
(`captain_differential && ...`, `meta?.diffEv != null && ...`), so an older backend
response without the fields renders exactly as today.

## Verification
- `npm run build` (also type-checks) passes.
- Visual: run the dev server, load `/app/league`, run a strategy, confirm the callout
  and chips render and degrade gracefully when `captain_differential` is null.

## Style
Follow existing shadcn/Tailwind patterns already in `League.tsx` (Card, Badge,
`text-muted-foreground`, the amber accent used for watchouts). Theme-aware
(dark/light) via existing token classes.
```
