# Handoff: FPLedge decision-hub redesign (1a Command Center · 1b Captain Lab · 1c Fixture Planner)

## Overview
Three UX upgrades to the FPLedge app (`znader1/fpl-decision-hub`). Each one targets a step in a manager's week, from "deadline is coming" to "plan locked in":
- **1a Command Center**: the Squad page (`/app`) becomes a weekly checklist. It adds a deadline countdown, an xPts glow on the pitch and transfer cards that show the net gain after any hit.
- **1b Captain Lab**: a step flow (Transfers → Captain → Bench → Confirm) where the captain pick depends on rank, using effective ownership (EO) and the range of likely points.
- **1c Fixture Planner**: a 6-GW heatmap of all 15 players, with chip windows (DGW/blank) and "weakest links" replacements. It replaces or extends `/app/fixtures`.

## About the design files
`FPLedge Redesign.dc.html` is a **design reference built in HTML**, not production code. Rebuild it in the existing React + TS + Tailwind + shadcn/ui codebase, using its components (`Button`, `Badge`, `PlayerCard`, `JerseyIcon`, `GameweekNav`) and its data hooks (TanStack Query, `src/lib/fplAssistantApi.ts`). To view the file, open it from the design project; it needs `support.js` and the `_ds/` design-system bundle next to it.

## Fidelity
**High-fidelity.** Colours, type, spacing and radii all come from the FPLedge tokens already in `src/index.css`. All data in the mock (players, fixtures, xPts, EO, ranks) is sample data.

## Suggested implementation order
1. Shared: `DeadlineCountdown` in `layout/Navbar.tsx` (uses the existing `deadline_time_utc` / `hours_to_deadline`).
2. 1a: checklist and transfer cards. These reuse `DecisionCard` verdict data (`verdict_detail.action`, `hit_cost`, `threshold`, `plan_net`, `roll_alternative`).
3. 1c: planner grid. It extends `Fixtures.tsx` / `TeamStrengthGrid.tsx` and feeds `ChipRoadmapPanel`.
4. 1b: Captain Lab. **Needs new backend fields** (see State & data).

---

## Shared shell
- Navbar 56px (`h-14`), `bg-[hsl(248_20%_8%/0.85)]`, `backdrop-blur-md`, bottom border `white/10`. Logo is the existing 28px pink "FPL" square with the "FPLedge" wordmark.
- Nav tabs: Squad · Captain · Planner · Mini-league. Tabs are 13px/600 with padding 6×10 and radius 8. Active tab is `#fff` on `white/6`; inactive tabs are `white/55`.
- **Deadline pill** (right side): a pill with padding 6×12, a 1px border `primary/35` and a `primary/10` fill. Inside: a 7px pink dot that pulses (keyframe opacity 1→.4, scale 1→.8, 1.6s, `cubic-bezier(.4,0,.2,1)`, infinite), the label "GW29 deadline" (600, foreground) and the countdown `1d 04:12:33` (700, pink, `tabular-nums`). It ticks every 1s. Set `white-space: nowrap`.
- Also on the right in 1a: "Bank £1.4m" and "FT 1", 12px, muted, with the values in foreground.

## 1a Command Center (`/app`, replaces the current Index layout)
Grid: `280px | 1fr | 340px`, min-height 760.

**Left rail** (`--sidebar-background`, padding 20×16, gap 20):
- Eyebrow "THIS WEEK" (10px/600, tracking .08em, muted) and a heading "{n} of 4 decisions made" (18px/800).
- Progress bar: 4px tall, `muted` track, `accent` fill, width transitions 0.3s.
- 4 decision rows (padding 10, radius 10, gap 6), each with a 22px status dot, a label (13/600) and a value (11px muted):
  - Transfers · Captain · Bench order · Chip.
  - Done: teal dot with ✓, transparent background, `border` outline.
  - Pending: muted dot, `primary/8` background, `primary/40` border.
- "PROJECTED GW29" card (card bg, radius 12, padding 16):
  - A 72px conic ring (pink up to the percentile) with "8% / TOP" in the centre.
  - The projected total (30px/900, tabular), with the delta below in teal 12/600.
  - 3 benchmark bars (You = pink, Top 10k = teal, Average = muted). Bars are 6px, width = value/75.

**Centre**:
- Team name (20/800) above "OR 412,008 · GW28 62 pts" (12 muted). Legend on the right: "Glow = xPts this GW".
- Pitch: the existing stripe gradient, radius 16, min-height 560, rows spread with `space-between`, gap 28 between players.
- **xPts aura**: a radial gradient behind each jersey, `primary/.55 → 0 at 68%`, diameter `30 + xPts×11` px, centred on the jersey (top 22px).
- A newly applied transfer shows the pill "IN +2.4" (teal, 10/700) above the player.
- Bench strip below: card, radius 12, "BENCH" eyebrow, 4 `PlayerCard`s.

**Right panel** "Transfer moves":
- Subtitle: "Ranked by xPts gained over the next 3 GWs, after the cost of any hit."
- One card per move (radius 12, padding 14, gap 12), containing:
  - The out jersey, an arrow and the in jersey, then the in-player's name (13/700) above "for {out} · {Free transfer | −4 hit}" (11 muted).
  - Net xPts on the right (18/900): teal if positive, `--fdr-4` rose if negative.
  - Two comparison bars (out = muted/60, in = accent), width = horizon xPts / 18.
  - One-line reason (12px, foreground/80).
  - Button `sm`, full width: "Apply this move" (accent) or "Undo" (ghost) for a free move; "Take the hit anyway" (outline) for a −4 move that doesn't pay.
  - Applied state: border `accent/45`, bg `accent/8`, transition 0.2s.
- A tip box pinned to the bottom (bg `muted/50`, lightbulb icon in teal) explaining the roll benefit.
- **Data**: maps directly onto `FplTransferVerdictDetail`. `action: "roll"` gives the hit-card copy; `hit_cost`, `threshold`, `plan_net`, `roll_alternative.net` and `next_move` fill the tip text. Keep `fmtGain()` (typographic minus).

## 1b Captain Lab (new route `/app/captain`, or step 2 of a GW flow)
- Header stepper: pills with padding 6×12. Each shows an 18px numbered dot (done = teal ✓, current = pink with a `primary/15` pill background, upcoming = muted) and a 20px hairline between steps.
- Hero: a 700×500 pink glow (`primary/22`, blur 120) at the top centre.
  - Eyebrow "STEP 2 OF 4 · CAPTAIN" in pink.
  - Headline 40px/900, tracking −0.02em, `text-wrap: pretty`.
  - Subcopy 14px muted, max 600px.
- On the right: a `Segmented` toggle with "Protect rank" / "Chase rank" (nowrap, min-width 280).
  - Protect → ZN Pick is the highest-EO option (Haaland). Headline: "Protect your rank with Haaland."
  - Chase → ZN Pick is the best EO-adjusted upside (Saka). Headline: "Captain Saka to climb the ranks."
- 3 candidate cards in a grid with gap 18 (radius 16, padding 22). Clicking a card selects it.
  - Selected: border `primary/70`, bg `primary/10`, shadow `0 0 0 1px primary/.5, 0 12px 40px primary/.25`, captain "C" on the jersey.
  - Top row: `JerseyIcon lg` and name (20/800) with a `FixtureChip` below; a "ZN Pick" `Badge` on the right.
  - xPts at 56px/900 (tabular), followed by "xPts (×2 = n)".
  - **Range bar**: 10px tall on a 0–20 scale. The fill runs from p10 to p90 (gradient `primary/35 → primary`), with a 3px white tick at the median (xPts).
  - 2 stat tiles (bg `background/60`, radius 10): "TOP 10K EO" and "RANK IF HE HAULS". The rank value is teal when it's a large gain.
  - One-line note.
- Sticky footer (card bg, top border, padding 16×48) showing Transfers · Captain · Vice · Projected (in pink), with "Back" (ghost) and "Next: bench order" (primary) buttons.
- Vice rule: the highest-xPts remaining candidate.

## 1c Fixture Planner (`/app/fixtures`)
- Navbar right side: a `Segmented` toggle "3 GWs" / "6 GWs" for the horizon.
- Grid: `1fr | 320px`. The table uses `170px repeat(6, 1fr) 64px`, gap 4.
- Column heads: "GW29…GW34". Tag pills are 9px/700: "DGW" on accent, "BLANK" on `--fdr-4`. Columns beyond the horizon fade to opacity .35.
- Rows: all 15 players, with 8px gaps between position groups and 14px before the bench. Hover gives a `muted/50` row background.
  - Name cell: `JerseyIcon sm`, name (13/600; muted for bench players) and position (10px).
  - Fixture cells: radius 8, bg `hsl(var(--fdr-N) / .14)`, with a `FixtureChip` above the xPts value (11/700).
  - Blank cells show "BLANK" in rose on `fdr-4/.06`.
  - Cells outside the horizon go to opacity .3, transition 0.2s.
  - Total column (15/900): pink if average > 6/GW, rose if < 4.4, foreground otherwise.
- Right rail:
  - "CHIP WINDOWS" cards: Bench Boost GW32 (teal tint) and Free Hit GW33. Each states its reason with counts, e.g. "{n} of your players have a double gameweek…".
  - "WEAKEST LINKS · next N GWs": out (struck through) → in, "a → b xPts · £price" and a `Badge soft` showing the gain. **Only list moves with gain > 0**, sorted by gain, descending.
  - FDR legend: 5 bars, fdr-1 to fdr-5.
- **Data**: per player, the next 6 fixtures (opp, home, diff, DGW count) and xPts per GW. `ChipRoadmapPanel` already computes chip windows, so feed it the same data.

---

## State & data
| State | Where | Notes |
|---|---|---|
| `deadline` | Navbar | from `deadline_time_utc`; `setInterval(1000)` |
| `appliedTransferCount` | Index | already exists (`onApplyTransferAtIndex`, `onResetAppliedTransfers`) |
| `decisions[]` | Index (derived) | transfers = verdict applied or roll; captain set; bench validated; chip decided |
| `captainGoal: "safe" \| "chase"`, `captainId` | Captain page | resetting the goal clears the manual pick |
| `horizon: 3 \| 6` | Planner | persist in URL `?h=` |

**Backend gaps for 1b** (not in `fplAssistantApi.ts` today), per captain candidate:
- `xpts_p10`, `xpts_p90`: the range of likely points.
- `eo_top10k`: effective ownership in the top 10k.
- `rank_gain_if_haul`: estimated ranks gained if he hauls.

1a's percentile ring and benchmark bars also need `projected_top10k_avg` and `projected_overall_avg`.

## Design tokens (already in `src/index.css`)
| Token | HSL | Hex | Use |
|---|---|---|---|
| `--background` | 248 20% 8% | #121019 | app background |
| `--card` | 248 18% 11% | #1a1822 | cards |
| `--border` | 248 15% 18% | #2a2834 | hairline borders |
| `--muted-foreground` | 248 8% 58% | #908e9f | muted text |
| `--foreground` | 248 10% 92% | #eae9ef | text |
| `--primary` | 328 75% 55% | #e03c95 | pink, the single brand colour |
| `--accent` | 172 65% 42% | #26b19f | teal, positive / apply |
| `--fdr-1…5` | | | 152 60% 45% · 152 50% 50% · 38 92% 55% · 348 80% 60% · 348 85% 52% |
| pitch | 152 40% 25% / 152 44% 18% | | stripe gradient |

- **Type**: Inter. 900 for numerals and headlines, 800 for titles, 600/700 for UI, 400 for body. Use `tabular-nums` on every stat.
- **Eyebrows**: 10–11px, uppercase, tracking .08em.
- **Radii**: 8 (cells, tabs), 10 (tiles, rows), 12 (cards), 16 (pitch, hero cards), full (pills).
- **Motion**: `cubic-bezier(.4,0,.2,1)` at 0.2–0.3s. No bounce.

## Assets
- Icons are lucide, so use `lucide-react`: ArrowLeftRight, ArrowRight, Lightbulb, Star.
- Jerseys use the existing `JerseyIcon` and `teamColors.ts`.
- No images.

## Files
- `FPLedge Redesign.dc.html`: all three designs on one canvas (sections 1a, 1b, 1c), interactive.
- `icons.js`: the lucide subset used by the mock (reference only).
