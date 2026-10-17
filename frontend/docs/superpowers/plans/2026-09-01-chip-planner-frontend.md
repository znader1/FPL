# Chip Planner — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface chip-timing recommendations from `GET /chips/plan` as a season roadmap tab in `RecommendationsPanel` plus a next-GW nudge card above the pitch.

**Architecture:** One TanStack Query in `Index.tsx` (gated on `gwResolved`) fetches the plan; the response flows down to a new "Chips" tab (`ChipRoadmapPanel`) and a conditional `ChipNudgeCard`. The nudge CTA sets the existing `chipStrategy` state, reusing the whole recommendation flow. No new apply path, no chip-name mapping (backend sends canonical names identical to `FplChipStrategy` values).

**Tech Stack:** React + TypeScript, TanStack Query, Tailwind, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-01-chip-planner-design.md`

## Global Constraints

- All API types and fetchers live in `src/lib/fplAssistantApi.ts`; never hardcode backend URLs in components (URL pattern: `apiBase ? new URL(path, apiBase).toString() : path` with `authFetch`).
- Canonical chip vocabulary everywhere: `wildcard`, `free_hit`, `bench_boost`, `triple_captain`. No mapping layers.
- All squad-context queries stay disabled until `gwResolved` (`selectedGW !== null`) — the flash-prevention rule.
- Component test pattern: `// @vitest-environment jsdom`, `cleanup` in `afterEach`, fixture objects typed with the API types (see `RecommendationsPanel.test.tsx`).
- Verification commands: `npx vitest run` (tests), `npm run build` (type-check), `npm run lint`.
- Backend contract (already planned in the backend repo, executable against a fixture before the backend ships): `GET /chips/plan?entry_id=&horizon=` returns `{entry_id, current_gw, chips_remaining[], horizon_model_gws, recommendations[], nudge|null, transfer_context}`.

---

### Task 1: API types, fetcher, dev proxy

**Files:**
- Modify: `src/lib/fplAssistantApi.ts` (widen `FplChipStrategy` at line 203; append chip-plan types + fetcher near `fetchUserLeagues`)
- Modify: `vite.config.ts` (add `/chips` proxy entry)

**Interfaces:**
- Produces (consumed by Tasks 2–5):

```ts
export type ChipName = "wildcard" | "free_hit" | "bench_boost" | "triple_captain";
export type ChipWindow = { name: ChipName; available: boolean; half: 1 | 2; expires_gw: number };
export type ChipEvPoint = { gw: number; ev: number };
export type ChipPlanRecommendation = {
  chip: ChipName; event_id: number; ev_gain: number | null;
  provisional: boolean; reasons: string[]; ev_curve: ChipEvPoint[];
};
export type ChipNudge = { chip: ChipName; event_id: number; ev_gain: number };
export type ChipPlanResponse = {
  entry_id: number; current_gw: number; chips_remaining: ChipWindow[];
  horizon_model_gws: number; recommendations: ChipPlanRecommendation[];
  nudge: ChipNudge | null;
  transfer_context: { planned_transfers_net_gain: number; wc_alternative_gw: number | null };
};
export const fetchChipPlan: (entryId: number, horizon?: number, signal?: AbortSignal) => Promise<ChipPlanResponse>;
export const CHIP_LABELS: Record<ChipName, string>;
```

- [ ] **Step 1: Widen `FplChipStrategy`**

At `src/lib/fplAssistantApi.ts:203` replace:

```ts
export type FplChipStrategy = "none" | "wildcard" | "free_hit";
```

with:

```ts
export type FplChipStrategy =
  | "none"
  | "wildcard"
  | "free_hit"
  | "bench_boost"
  | "triple_captain";
```

- [ ] **Step 2: Add types, labels, and fetcher**

Append after `fetchUserLeagues` (same section as the other Phase 2 endpoints):

```ts
/* ── Chip plan (chip timing recommendations) ─────────────────────────────── */

export type ChipName = "wildcard" | "free_hit" | "bench_boost" | "triple_captain";

export const CHIP_LABELS: Record<ChipName, string> = {
  wildcard: "Wildcard",
  free_hit: "Free Hit",
  bench_boost: "Bench Boost",
  triple_captain: "Triple Captain",
};

export type ChipWindow = {
  name: ChipName;
  available: boolean;
  half: 1 | 2;
  expires_gw: number;
};

export type ChipEvPoint = { gw: number; ev: number };

export type ChipPlanRecommendation = {
  chip: ChipName;
  event_id: number;
  ev_gain: number | null; // null on provisional (structural-zone) recommendations
  provisional: boolean;
  reasons: string[];
  ev_curve: ChipEvPoint[];
};

export type ChipNudge = { chip: ChipName; event_id: number; ev_gain: number };

export type ChipPlanResponse = {
  entry_id: number;
  current_gw: number;
  chips_remaining: ChipWindow[];
  horizon_model_gws: number;
  recommendations: ChipPlanRecommendation[];
  nudge: ChipNudge | null;
  transfer_context: {
    planned_transfers_net_gain: number;
    wc_alternative_gw: number | null;
  };
};

export const fetchChipPlan = async (
  entryId: number,
  horizon?: number,
  signal?: AbortSignal
): Promise<ChipPlanResponse> => {
  const apiBase = getEnvString("VITE_FPL_API_BASE_URL") ?? "";
  const params = new URLSearchParams({ entry_id: String(entryId) });
  if (horizon) params.set("horizon", String(horizon));
  const path = `/chips/plan?${params.toString()}`;
  const url = apiBase ? new URL(path, apiBase).toString() : path;
  const response = await authFetch(url, { signal });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Failed to fetch chip plan (${response.status}): ${body.slice(0, 200)}`);
  }
  return (await response.json()) as ChipPlanResponse;
};
```

- [ ] **Step 3: Add the dev proxy**

In `vite.config.ts`, add to the `proxy` object alongside `/fixtures`:

```ts
      "/chips": {
        target: process.env.VITE_FPL_API_BASE_URL ?? "https://fpl-assistant-api.fly.dev/",
        changeOrigin: true,
      },
```

- [ ] **Step 4: Verify and commit**

Run: `npm run build && npx vitest run`
Expected: build passes (widened `FplChipStrategy` may surface exhaustive-switch errors in `ParameterSidebar.tsx` — if it does, that's Task 5's file; the current code uses `===` comparisons, not exhaustive switches, so it should compile).

```bash
git add src/lib/fplAssistantApi.ts vite.config.ts
git commit -m "feat(api): chip plan types, fetcher, dev proxy"
```

---

### Task 2: `ChipRoadmapPanel` component

**Files:**
- Create: `src/components/ChipRoadmapPanel.tsx`
- Test: `src/components/ChipRoadmapPanel.test.tsx`

**Interfaces:**
- Consumes: `ChipPlanResponse`, `ChipPlanRecommendation`, `CHIP_LABELS` from Task 1.
- Produces: `<ChipRoadmapPanel plan={ChipPlanResponse | null | undefined} isLoading={boolean} />` — Task 3 mounts it in the Chips tab.

- [ ] **Step 1: Write the failing tests**

Create `src/components/ChipRoadmapPanel.test.tsx`:

```tsx
// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ChipRoadmapPanel } from "./ChipRoadmapPanel";
import type { ChipPlanResponse } from "@/lib/fplAssistantApi";

afterEach(cleanup);

const basePlan: ChipPlanResponse = {
  entry_id: 123,
  current_gw: 5,
  chips_remaining: [
    { name: "wildcard", available: true, half: 1, expires_gw: 19 },
    { name: "free_hit", available: true, half: 1, expires_gw: 19 },
    { name: "bench_boost", available: false, half: 1, expires_gw: 19 },
    { name: "triple_captain", available: true, half: 1, expires_gw: 19 },
  ],
  horizon_model_gws: 8,
  recommendations: [
    {
      chip: "wildcard",
      event_id: 8,
      ev_gain: 9.1,
      provisional: false,
      reasons: ["Large gap to optimal — squad needs reset"],
      ev_curve: [
        { gw: 5, ev: 4.2 },
        { gw: 8, ev: 9.1 },
      ],
    },
    {
      chip: "triple_captain",
      event_id: 30,
      ev_gain: null,
      provisional: true,
      reasons: ["GW30 is a double gameweek (from announced fixtures)"],
      ev_curve: [],
    },
  ],
  nudge: null,
  transfer_context: { planned_transfers_net_gain: 3.0, wc_alternative_gw: 8 },
};

describe("ChipRoadmapPanel", () => {
  it("renders a row per recommendation with GW and EV", () => {
    render(<ChipRoadmapPanel plan={basePlan} isLoading={false} />);
    expect(screen.getByText("Wildcard")).toBeTruthy();
    expect(screen.getByText(/GW8/)).toBeTruthy();
    expect(screen.getByText(/\+9\.1/)).toBeTruthy();
  });

  it("marks structural-zone recommendations as provisional", () => {
    render(<ChipRoadmapPanel plan={basePlan} isLoading={false} />);
    expect(screen.getByText(/provisional/i)).toBeTruthy();
    expect(screen.getByText("Triple Captain")).toBeTruthy();
  });

  it("shows played chips as used", () => {
    render(<ChipRoadmapPanel plan={basePlan} isLoading={false} />);
    expect(screen.getByText("Bench Boost")).toBeTruthy();
    // "used" appears in both the section header and the row — use getAllByText
    expect(screen.getAllByText(/used/i).length).toBeGreaterThan(0);
  });

  it("shows expiry deadline for available chips without a recommendation", () => {
    render(<ChipRoadmapPanel plan={basePlan} isLoading={false} />);
    // free_hit is available, unrecommended → hold with its expiry shown
    expect(screen.getAllByText(/expires GW19/i).length).toBeGreaterThan(0);
  });

  it("renders loading state without a plan", () => {
    render(<ChipRoadmapPanel plan={undefined} isLoading={true} />);
    expect(screen.getByText(/analyzing chip windows/i)).toBeTruthy();
  });

  it("renders empty state when idle without a plan", () => {
    render(<ChipRoadmapPanel plan={null} isLoading={false} />);
    expect(screen.getByText(/no chip plan/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/components/ChipRoadmapPanel.test.tsx`
Expected: FAIL — module `./ChipRoadmapPanel` not found.

- [ ] **Step 3: Implement the component**

Create `src/components/ChipRoadmapPanel.tsx`:

```tsx
import { useState } from "react";
import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import {
  CHIP_LABELS,
  type ChipName,
  type ChipPlanRecommendation,
  type ChipPlanResponse,
} from "@/lib/fplAssistantApi";

type Props = {
  plan: ChipPlanResponse | null | undefined;
  isLoading: boolean;
};

const EvCurve = ({ points }: { points: ChipPlanRecommendation["ev_curve"] }) => {
  if (!points.length) return null;
  const max = Math.max(...points.map((p) => p.ev), 1);
  return (
    <div className="flex items-end gap-1 h-10 mt-2" aria-label="EV by gameweek">
      {points.map((p) => (
        <div key={p.gw} className="flex flex-col items-center gap-0.5">
          <div
            className="w-4 rounded-t bg-primary/70"
            style={{ height: `${Math.max(4, (p.ev / max) * 32)}px` }}
            title={`GW${p.gw}: +${p.ev} xPts`}
          />
          <span className="text-[9px] text-muted-foreground">{p.gw}</span>
        </div>
      ))}
    </div>
  );
};

const RecommendationRow = ({ rec }: { rec: ChipPlanRecommendation }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border p-3">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="font-semibold text-sm">{CHIP_LABELS[rec.chip]}</span>
          {rec.provisional && (
            <span className="text-[10px] font-semibold uppercase tracking-wide rounded-full border border-dashed border-muted-foreground/50 text-muted-foreground px-2 py-0.5">
              provisional
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-sm font-bold">GW{rec.event_id}</span>
          {rec.ev_gain !== null && (
            <span className="text-sm font-semibold text-primary">+{rec.ev_gain} xPts</span>
          )}
        </div>
      </button>
      {open && (
        <div className="mt-2 pl-5">
          <ul className="space-y-1">
            {rec.reasons.map((reason) => (
              <li key={reason} className="text-xs text-muted-foreground">
                {reason}
              </li>
            ))}
          </ul>
          <EvCurve points={rec.ev_curve} />
        </div>
      )}
    </div>
  );
};

export const ChipRoadmapPanel = ({ plan, isLoading }: Props) => {
  if (isLoading && !plan) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        Analyzing chip windows…
      </div>
    );
  }
  if (!plan) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center">
        No chip plan yet — set your entry ID and gameweek.
      </div>
    );
  }

  const recommendedChips = new Set(plan.recommendations.map((r) => r.chip));
  const holds = plan.chips_remaining.filter(
    (c) => c.available && !recommendedChips.has(c.name)
  );
  const used = plan.chips_remaining.filter((c) => !c.available);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-bold">Chip roadmap</h3>
        <span className="text-[10px] text-muted-foreground ml-auto">
          model horizon: {plan.horizon_model_gws} GWs
        </span>
      </div>

      {plan.recommendations.length > 0 ? (
        <div className="space-y-2">
          {plan.recommendations.map((rec) => (
            <RecommendationRow key={`${rec.chip}-${rec.event_id}`} rec={rec} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          No chip clears the bar in the next {plan.horizon_model_gws} gameweeks — holding
          everything is the recommended play.
        </p>
      )}

      {holds.length > 0 && (
        <div>
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">
            Holding
          </h4>
          <ul className="space-y-1">
            {holds.map((c) => (
              <li key={c.name} className="text-xs text-muted-foreground flex justify-between">
                <span>{CHIP_LABELS[c.name]}</span>
                <span>expires GW{c.expires_gw}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {used.length > 0 && (
        <div>
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">
            Used this half
          </h4>
          <ul className="space-y-1">
            {used.map((c) => (
              <li key={c.name} className="text-xs text-muted-foreground/70 flex justify-between">
                <span>{CHIP_LABELS[c.name]}</span>
                <span>used</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/components/ChipRoadmapPanel.test.tsx`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/components/ChipRoadmapPanel.tsx src/components/ChipRoadmapPanel.test.tsx
git commit -m "feat(chips): ChipRoadmapPanel — season chip roadmap with EV curves"
```

---

### Task 3: "Chips" tab in `RecommendationsPanel`

**Files:**
- Modify: `src/components/RecommendationsPanel.tsx` (`type Tab` at line 36; `tabs` array and tab content at lines 567-651; props)
- Test: extend `src/components/RecommendationsPanel.test.tsx` only if it renders the full panel — it currently tests `HorizonTransferPlan` in isolation, so no test change is required; the tab render is covered by Task 2's component tests plus the build.

**Interfaces:**
- Consumes: `ChipRoadmapPanel` (Task 2), `ChipPlanResponse` (Task 1).
- Produces: `RecommendationsPanelProps` gains `chipPlan?: ChipPlanResponse | null` and `isChipPlanLoading?: boolean`. Task 5 passes them from `Index.tsx`.

- [ ] **Step 1: Widen the Tab type and props**

At `src/components/RecommendationsPanel.tsx:36`:

```ts
type Tab = "summary" | "transfers" | "watchlist" | "chips";
```

Add to `RecommendationsPanelProps` (find the interface/type near the top of the file):

```ts
  chipPlan?: ChipPlanResponse | null;
  isChipPlanLoading?: boolean;
```

with the import extended: `import type { ChipPlanResponse } from "@/lib/fplAssistantApi";` (merge into the existing type-import from that module). Destructure both in the component signature (`chipPlan`, `isChipPlanLoading = false`).

- [ ] **Step 2: Add the tab and its content**

In the `tabs` array (line 567), add a fourth entry — `Sparkles` comes from `lucide-react` (extend the existing import):

```ts
    { id: "chips", label: "Chips", icon: Sparkles },
```

In the tab content region (after the watchlist block at line 643-649):

```tsx
        {activeTab === "chips" && (
          <ChipRoadmapPanel plan={chipPlan} isLoading={isChipPlanLoading} />
        )}
```

with `import { ChipRoadmapPanel } from "./ChipRoadmapPanel";` at the top. Optional badge parity with the transfers tab: after the `moveCount` badge block (line 604-608), add a dot for an actionable (non-provisional) chip recommendation:

```tsx
              {tab.id === "chips" &&
                (chipPlan?.recommendations.some((r) => !r.provisional) ?? false) && (
                  <span className="absolute top-2 right-[18%] h-2 w-2 rounded-full bg-primary" />
                )}
```

- [ ] **Step 3: Verify and commit**

Run: `npx vitest run && npm run build`
Expected: all tests pass, build clean.

```bash
git add src/components/RecommendationsPanel.tsx
git commit -m "feat(chips): Chips tab in RecommendationsPanel"
```

---

### Task 4: `ChipNudgeCard`

**Files:**
- Create: `src/components/ChipNudgeCard.tsx`
- Test: `src/components/ChipNudgeCard.test.tsx`

**Interfaces:**
- Consumes: `ChipNudge`, `CHIP_LABELS`, `FplChipStrategy` (Task 1).
- Produces: `<ChipNudgeCard nudge={ChipNudge | null | undefined} activeChipStrategy={FplChipStrategy} onApplyChip={(chip: ChipName) => void} />` — renders nothing when `nudge` is absent or the chip is already the active strategy. Task 5 mounts it.

- [ ] **Step 1: Write the failing tests**

Create `src/components/ChipNudgeCard.test.tsx`:

```tsx
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ChipNudgeCard } from "./ChipNudgeCard";
import type { ChipNudge } from "@/lib/fplAssistantApi";

afterEach(cleanup);

const nudge: ChipNudge = { chip: "bench_boost", event_id: 5, ev_gain: 7.1 };

describe("ChipNudgeCard", () => {
  it("renders chip name and EV with an apply CTA", () => {
    render(
      <ChipNudgeCard nudge={nudge} activeChipStrategy="none" onApplyChip={() => {}} />
    );
    expect(screen.getByText(/bench boost/i)).toBeTruthy();
    expect(screen.getByText(/\+7\.1/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /apply/i })).toBeTruthy();
  });

  it("calls onApplyChip with the chip name", () => {
    const onApply = vi.fn();
    render(
      <ChipNudgeCard nudge={nudge} activeChipStrategy="none" onApplyChip={onApply} />
    );
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    expect(onApply).toHaveBeenCalledWith("bench_boost");
  });

  it("renders nothing without a nudge", () => {
    const { container } = render(
      <ChipNudgeCard nudge={null} activeChipStrategy="none" onApplyChip={() => {}} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the chip is already active", () => {
    const { container } = render(
      <ChipNudgeCard
        nudge={nudge}
        activeChipStrategy="bench_boost"
        onApplyChip={() => {}}
      />
    );
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/components/ChipNudgeCard.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

Create `src/components/ChipNudgeCard.tsx`:

```tsx
import { Zap } from "lucide-react";
import {
  CHIP_LABELS,
  type ChipName,
  type ChipNudge,
  type FplChipStrategy,
} from "@/lib/fplAssistantApi";

type Props = {
  nudge: ChipNudge | null | undefined;
  activeChipStrategy: FplChipStrategy;
  onApplyChip: (chip: ChipName) => void;
};

export const ChipNudgeCard = ({ nudge, activeChipStrategy, onApplyChip }: Props) => {
  if (!nudge || nudge.chip === activeChipStrategy) return null;

  return (
    <div className="flex items-center gap-3 rounded-lg border border-primary/40 bg-primary/5 px-4 py-3">
      <Zap className="h-4 w-4 shrink-0 text-primary" />
      <p className="text-sm min-w-0">
        <span className="font-semibold">{CHIP_LABELS[nudge.chip]}</span> this gameweek
        projects <span className="font-semibold text-primary">+{nudge.ev_gain} xPts</span>{" "}
        over holding it.
      </p>
      <button
        onClick={() => onApplyChip(nudge.chip)}
        className="ml-auto shrink-0 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
      >
        Apply chip
      </button>
    </div>
  );
};
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/components/ChipNudgeCard.test.tsx`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/components/ChipNudgeCard.tsx src/components/ChipNudgeCard.test.tsx
git commit -m "feat(chips): ChipNudgeCard — next-GW chip nudge with apply CTA"
```

---

### Task 5: Wire into `Index.tsx` + sidebar labels

**Files:**
- Modify: `src/pages/Index.tsx` (chip plan query; mount nudge card above `PitchVisualization` at line 673; pass props to `RecommendationsPanel` at line 724; apply handler)
- Modify: `src/components/ParameterSidebar.tsx:49-53` (`chipActive` / `chipLabel` cover the new values)

**Interfaces:**
- Consumes: `fetchChipPlan`, `ChipPlanResponse`, `ChipName` (Task 1); `ChipNudgeCard` (Task 4); `RecommendationsPanel` new props (Task 3); existing state `entryId`, `selectedGW`, `chipStrategy`, `setChipStrategy`, `gwResolved`.
- Produces: the complete user-facing feature.

- [ ] **Step 1: Add the chip plan query**

In `src/pages/Index.tsx`, next to the other queries (after `nextEventQuery`, ~line 170):

```tsx
  const chipPlanQuery = useQuery<ChipPlanResponse>({
    queryKey: ["chipPlan", entryId, selectedGW],
    queryFn: ({ signal }) => fetchChipPlan(entryId, undefined, signal),
    enabled: gwResolved && entryId > 0,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
```

Imports: add `fetchChipPlan`, `type ChipPlanResponse`, `type ChipName` to the existing `@/lib/fplAssistantApi` import block, and `import { ChipNudgeCard } from "@/components/ChipNudgeCard";`.

Note: `gwResolved` is derived below the queries in the current file order (`const gwResolved = selectedGW !== null`) — if the declaration sits after this query, use `selectedGW !== null && entryId > 0` directly in `enabled` instead; both express the same gate.

- [ ] **Step 2: Add the apply handler and mount the nudge card**

Handler near the other handlers:

```tsx
  const handleApplyChipNudge = (chip: ChipName) => {
    setChipStrategy(chip);
    localStorage.setItem("fpl_chip_strategy", chip);
  };
```

(Match how `setChipStrategy` persistence is done elsewhere in the file — if a setter wrapper already writes `localStorage`, call that instead of duplicating the write.)

Mount directly above `<PitchVisualization` (line 673), inside the same container:

```tsx
        <ChipNudgeCard
          nudge={chipPlanQuery.data?.nudge}
          activeChipStrategy={chipStrategy}
          onApplyChip={handleApplyChipNudge}
        />
```

- [ ] **Step 3: Pass the plan to `RecommendationsPanel`**

At the `<RecommendationsPanel` usage (line 724), add:

```tsx
        chipPlan={chipPlanQuery.data ?? null}
        isChipPlanLoading={chipPlanQuery.isLoading}
```

- [ ] **Step 4: Cover the new chips in `ParameterSidebar`**

At `src/components/ParameterSidebar.tsx:49-53` replace:

```ts
  const chipActive = chipStrategy === "wildcard" || chipStrategy === "free_hit";
  const effectiveHorizonLabel = chipStrategy === "free_hit" ? "1 GW (Free Hit)" : `${horizonGws} GWs`;
  const chipLabel = chipActive
    ? chipStrategy === "wildcard" ? "Wildcard" : "Free Hit"
    : "No chip";
```

with:

```ts
  const chipActive = chipStrategy !== "none";
  const effectiveHorizonLabel = chipStrategy === "free_hit" ? "1 GW (Free Hit)" : `${horizonGws} GWs`;
  // The !== "none" check narrows FplChipStrategy to ChipName, so the index type-checks.
  const chipLabel = chipStrategy !== "none" ? CHIP_LABELS[chipStrategy] : "No chip";
```

adding `CHIP_LABELS` to the module's `@/lib/fplAssistantApi` import. Check the rest of the file for chip strategy option lists (the chip `<Select>`/radio options): add `bench_boost` ("Bench Boost") and `triple_captain` ("Triple Captain") entries using `CHIP_LABELS`, following the exact markup of the existing wildcard/free-hit options. Also grep the repo for other `=== "wildcard" || === "free_hit"`-style guards that mean "a chip is active" and widen them: `grep -rn '"free_hit"' src/ --include="*.tsx"` — decide per site whether it means "squad-rebuilding chip" (keep as-is: only wildcard/free hit rebuild squads) or "any chip active" (use `!== "none"`). `Index.tsx:159` (`effectiveHorizonGws`) and `Index.tsx:218` (wildcard play event) are squad-rebuild semantics — leave them.

- [ ] **Step 5: Verify everything, run the app, commit**

Run: `npx vitest run && npm run build && npm run lint`
Expected: all pass.

Manual check: `npm run dev`, open `localhost:8080/app` — Chips tab renders (loading, then plan or empty state); if the backend isn't deployed yet the query errors quietly and the tab shows the empty state (acceptable: the panel must not crash without the endpoint).

```bash
git add src/pages/Index.tsx src/components/ParameterSidebar.tsx
git commit -m "feat(chips): wire chip plan query, nudge card, and sidebar chip labels"
```

---

## Self-Review Notes

- Spec coverage: types/fetcher/no-mapping (Task 1), roadmap panel with provisional + expiry + EV curve (Task 2), Chips tab (Task 3), nudge card reusing `chipStrategy` (Task 4), query gated on `gwResolved` + sidebar widening (Task 5). Vite proxy (Task 1 Step 3). Backend-independent: every component is fixture-tested; only Task 5's manual check touches the live endpoint.
- Type consistency: `ChipName` values equal the widened `FplChipStrategy` values minus `"none"`, so `setChipStrategy(chip)` type-checks directly.
- Deliberately out: EV-curve charting library (plain divs suffice), roadmap season-strip visualization as a graphic timeline (list form ships first; a visual strip is a follow-up polish item).
