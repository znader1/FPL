# Ship-Ready Frontend — Design Spec

**Date:** 2026-07-18
**Goal:** Take fpl-decision-hub (FPLedge) from demo-grade to public launch: strangers can sign up and use it unassisted.
**Approach:** Blocker-first vertical slices. Each slice independently shippable. No rebuild.

## Decisions (locked)

| Question | Decision |
|---|---|
| Ship bar | Public launch, real users |
| Timeline | ASAP, no hard date — quality over calendar |
| Monetization | Free now, billing-ready scaffold (no Stripe) |
| Landing claims | Replace fabricated stats/testimonial with honest copy |

## Slice 1 — Onboarding

**Problem:** New user lands on `/app` and sees `SAMPLE_SQUAD` (someone else's team). Entry ID buried in collapsible sidebar.

- First-run gate on `/app`: if no `fpl_entry_id` in localStorage and none in query param, show onboarding screen instead of pitch: "Enter your FPL Team ID" with inline helper (find it in the FPL site URL: `fantasy.premierleague.com/entry/XXXXXX/...`).
- Validate on submit via existing `GET /squad?entry_id&event_id`. Success → store ID, load squad. Failure → inline error, stay on gate.
- Kill sample-squad fallback for signed-in users. `SAMPLE_SQUAD` may remain only as explicit demo data, never silently presented as the user's squad.
- Persist `entry_id` to a new Supabase `profiles` table (in addition to localStorage) so it follows the user across devices. Login on new device → profile lookup instead of empty gate.
- `/app/league` reuses the same stored ID (already reads the same localStorage key).

## Slice 2 — Mobile `/app`

**Problem:** `Index.tsx` has zero responsive classes; desktop-only. League page is already mobile-friendly.

- Single-column stack under `lg:`. Order: GW nav → pitch → recommendations. Desktop layout unchanged.
- `PitchVisualization` scales fluidly (max-width + aspect ratio); player cards shrink via responsive text/padding. Same component, no mobile fork.
- `ParameterSidebar` stays on desktop; mobile gets a floating settings button opening a `vaul` drawer (already a dependency) with the same form contents.
- `RecommendationsPanel` full-width below pitch; verify tab paddings at small widths.
- Test targets: 375px, 390px, 768px. Devtools pass + real-device sanity check.

## Slice 3 — P0 bug + error/empty/loading states

- **P0 GW-navigation bug** (BACKLOG): selecting an earlier GW can fail to load. Reproduce first (systematic-debugging), identify failing endpoint, fix root cause. Suspect area: `squadGW`/`selectedGW` split + `/squad` for past GWs.
- **Loading:** skeleton pitch (grey placeholders), standardized spinner + progress line for recommendations.
- **Error:** inline card per failed section with message + Retry (TanStack `refetch`). Distinguish backend-down (Fly.io cold start → "waking up, retrying…" with auto-retry/backoff) from bad-request. No raw errors, no white screens.
- **Empty:** pre-season / no-data GW → explicit "Season hasn't started" card, never sample data.
- **Global React error boundary** wrapping routes: friendly crash card + reload button.
- Cleanup: remove `transfers.note` debug text from UI; keep `?debug_transfers=1` gate as-is.

## Slice 4 — Honest landing

**Problem:** Fabricated stats ("42,000+ managers", "£4.6m+ won", "#1 rated"), fake testimonial, pricing tiers for billing that doesn't exist.

- Stats row → honest value props ("Every player, every GW modelled" / "Multi-GW xPts horizon" / "Built for 2026/27"). No invented numbers.
- Testimonial section → cut until real quotes exist.
- Pricing → single card: "Free while in beta — full access, no card." Optional muted "coming soon" roadmap teaser for Pro/Elite perks. CTAs → `/auth`.
- Audit 6 feature cards against shipped reality; tone down oversells (verify "Wildcard AI Drafter" claim matches backend).
- Replace dead `href="#"` Privacy/Terms links with real minimal static pages (honest: we store email + FPL entry ID via Supabase).

## Slice 5 — Entitlement scaffold (billing-ready, no Stripe)

- `profiles` table (from Slice 1) gets `plan` column: `'free' | 'pro' | 'elite'`, default `'free'`. One migration covers entry_id + plan.
- `src/hooks/useEntitlement.ts`: reads plan, returns capability flags (`canUseWildcardDrafter`, `canUseMultiGwHorizon`, `canUseLeagueDashboard`, …). All `true` during beta via single `BETA_ALL_ACCESS = true` const.
- Components consume capability flags, never plan strings. Future Stripe drop-in = flip const + add checkout; zero component rewrites.
- No Stripe SDK, webhooks, or checkout now.

## Slice 6 — QA + ship

- Per-slice verify: `npm run build` + `npm run lint` + drive the real flow in dev against local backend.
- Final sweep: fresh incognito signup → onboarding → squad → recommendations → league → mobile viewports, against prod Fly.io backend.
- Branch hygiene: implement on a feature branch; merge to `main` only when ship-clean (Vercel auto-deploys `main`). Reconcile current `chat-backend` branch (ahead of `main`, 1 unpushed commit) before or as part of first merge.
- No full test suite this pass. New pure logic (entitlement hook, entry-ID validation) gets lightweight Vitest units if cheap; otherwise backlog.

## Out of scope

- Stripe checkout / real billing
- `/app` visual redesign or rebuild
- Full test-suite adoption
- New backend features (frontend consumes existing endpoints only; exception: Supabase `profiles` migration, which is frontend-owned infra)

## Slice order

1 → 2 → 3 → 4 → 5 → 6. Slices 4 and 5 can swap or interleave; 6 is final gate.
