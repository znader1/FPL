# Ship-Ready Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take fpl-decision-hub from demo-grade to public launch: a stranger can sign up, enter their FPL team ID, and use squad/recommendations/league unassisted on desktop and mobile.

**Architecture:** Blocker-first vertical slices on a `ship-ready` feature branch. Onboarding gate replaces the silent SAMPLE_SQUAD fallback; profile persistence via a new Supabase `profiles` table; mobile via responsive stacking + a vaul drawer reusing an extracted `ParameterForm`; resilience via a global error boundary + TanStack retry/backoff; honest landing copy; entitlement scaffold with `BETA_ALL_ACCESS = true`.

**Tech Stack:** React 18 + TypeScript + Vite, Tailwind, shadcn/ui (vaul drawer already vendored at `src/components/ui/drawer.tsx`), TanStack Query v5, Supabase (auth + profiles), Vitest (new, node-env only).

**Repo:** `/Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub` — all paths below relative to this root. Backend (FastAPI on Fly.io) is consumed read-only; local dev backend at `http://localhost:8000`.

## Global Constraints

- Work on branch `ship-ready` (created from `chat-backend` in Task 1). Merge to `main` only in Task 11 (Vercel auto-deploys `main`).
- `npm run build` and `npm run lint` must pass at the end of every task.
- Never present `SAMPLE_SQUAD` as the user's own squad. It may remain in `fplAssistantApi.ts` as data, but `Index.tsx` must not render it as the active team.
- The recommendation tab label is **"ZN Pick"** — do not rename.
- Never hardcode backend URLs in components; all API access goes through `src/lib/fplAssistantApi.ts`.
- Copy rules (landing): no invented user counts, prize totals, ratings, or testimonials. Pricing shows "Free while in beta".
- The fixture chip on `PlayerCard` renders on its own line — do not change that layout.
- League page uses `pt-20 pb-8` to clear the fixed `h-14` navbar — preserve.
- Commit at the end of every task (messages given per task).

---

### Task 1: Branch, Vitest infra, entry-ID helpers (TDD)

**Files:**
- Create: `src/lib/entryId.ts`
- Create: `src/lib/__tests__/entryId.test.ts`
- Modify: `package.json` (add vitest + `test` script)

**Interfaces:**
- Consumes: nothing.
- Produces: `parseEntryIdInput(raw: string): number | null` and `ENTRY_ID_STORAGE_KEY = "fpl_entry_id"` — used by Task 4 (overlay) and Task 4's `getInitialEntryId` rewrite.

- [ ] **Step 1: Create branch**

```bash
cd /Users/ziadnader/05_Projects/Tech/FPL-Assistant-Front/fpl-decision-hub
git checkout chat-backend && git checkout -b ship-ready
```

- [ ] **Step 2: Install vitest and add script**

```bash
npm install -D vitest
```

In `package.json` `"scripts"`, add:

```json
"test": "vitest run"
```

Create `vitest.config.ts` at the repo root (the app's `vite.config.ts` loads `lovable-tagger`, which we don't want in the test env — hence a separate config; the `@` alias must match it):

```ts
import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
```

- [ ] **Step 3: Write the failing test**

Create `src/lib/__tests__/entryId.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseEntryIdInput } from "../entryId";

describe("parseEntryIdInput", () => {
  it("parses plain digits", () => {
    expect(parseEntryIdInput("588004")).toBe(588004);
  });
  it("parses digits with surrounding whitespace", () => {
    expect(parseEntryIdInput("  588004  ")).toBe(588004);
  });
  it("parses a pasted FPL URL", () => {
    expect(
      parseEntryIdInput("https://fantasy.premierleague.com/entry/588004/event/38")
    ).toBe(588004);
  });
  it("parses an entry URL without event suffix", () => {
    expect(parseEntryIdInput("fantasy.premierleague.com/entry/12345/")).toBe(12345);
  });
  it("rejects garbage", () => {
    expect(parseEntryIdInput("my team")).toBeNull();
  });
  it("rejects zero and negatives", () => {
    expect(parseEntryIdInput("0")).toBeNull();
    expect(parseEntryIdInput("-5")).toBeNull();
  });
  it("rejects empty", () => {
    expect(parseEntryIdInput("")).toBeNull();
  });
  it("rejects decimals", () => {
    expect(parseEntryIdInput("58.4")).toBeNull();
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `npx vitest run src/lib/__tests__/entryId.test.ts`
Expected: FAIL — `Cannot find module '../entryId'` (or equivalent resolve error).

- [ ] **Step 5: Write minimal implementation**

Create `src/lib/entryId.ts`:

```ts
export const ENTRY_ID_STORAGE_KEY = "fpl_entry_id";

/**
 * Parse raw user input into an FPL entry ID.
 * Accepts plain digits ("588004") or a pasted FPL URL
 * ("https://fantasy.premierleague.com/entry/588004/event/38").
 * Returns null when no valid positive integer ID can be extracted.
 */
export const parseEntryIdInput = (raw: string): number | null => {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  const urlMatch = trimmed.match(/entry\/(\d+)/i);
  const candidate = urlMatch ? urlMatch[1] : trimmed;
  if (!/^\d+$/.test(candidate)) return null;

  const id = Number(candidate);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
};
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npx vitest run src/lib/__tests__/entryId.test.ts`
Expected: PASS (8 tests).

- [ ] **Step 7: Verify build + lint, commit**

```bash
npm run build && npm run lint
git add package.json package-lock.json src/lib/entryId.ts src/lib/__tests__/entryId.test.ts
git commit -m "feat: add entry-ID input parser with vitest infra"
```

---

### Task 2: Supabase `profiles` table (entry_id + plan) with RLS

**Files:**
- Create: `supabase/migrations/20260718120000_create_profiles.sql`
- Modify: `src/integrations/supabase/types.ts` (regenerate)

**Interfaces:**
- Consumes: existing Supabase project (auth.users).
- Produces: `public.profiles` table — `id uuid PK`, `entry_id bigint nullable`, `plan text default 'free'`. Consumed by Task 3's `useProfile`.

- [ ] **Step 1: Write the migration file**

Create `supabase/migrations/20260718120000_create_profiles.sql`:

```sql
-- Per-user profile: FPL entry ID + plan tier (billing-ready scaffold).
create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  entry_id bigint,
  plan text not null default 'free' check (plan in ('free', 'pro', 'elite')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "Users can read own profile"
  on public.profiles for select
  using (auth.uid() = id);

create policy "Users can insert own profile"
  on public.profiles for insert
  with check (auth.uid() = id);

create policy "Users can update own profile"
  on public.profiles for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- Auto-create a profile row on signup.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id) values (new.id) on conflict do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Backfill profiles for existing users.
insert into public.profiles (id)
select id from auth.users
on conflict do nothing;
```

- [ ] **Step 2: Apply the migration**

Preferred: Supabase MCP `apply_migration` against the project referenced by `VITE_SUPABASE_URL` in `.env`, with name `create_profiles` and the SQL above. Fallback: paste the SQL into the Supabase dashboard SQL editor.

Note: `plan` values are only ever written server-side (no client writes `plan` — see Task 3's upsert which omits it), so RLS update policy is safe.

- [ ] **Step 3: Verify table + RLS**

Via MCP `execute_sql` (or dashboard):

```sql
select column_name, data_type from information_schema.columns
where table_schema = 'public' and table_name = 'profiles';
```

Expected: rows for `id`, `entry_id`, `plan`, `created_at`, `updated_at`.

```sql
select policyname from pg_policies where tablename = 'profiles';
```

Expected: the three policies above.

- [ ] **Step 4: Regenerate TypeScript types**

Via MCP `generate_typescript_types`, or CLI:

```bash
npx supabase gen types typescript --project-id <project-ref> > src/integrations/supabase/types.ts
```

(`<project-ref>` = subdomain of `VITE_SUPABASE_URL` in `.env`.)
Expected: `types.ts` now contains a `profiles` table type with `entry_id: number | null` and `plan: string`.

- [ ] **Step 5: Verify build, commit**

```bash
npm run build
git add supabase/migrations/20260718120000_create_profiles.sql src/integrations/supabase/types.ts
git commit -m "feat: add profiles table (entry_id, plan) with RLS + signup trigger"
```

---

### Task 3: `useProfile` hook

**Files:**
- Create: `src/hooks/useProfile.ts`

**Interfaces:**
- Consumes: `supabase` client (`@/integrations/supabase/client`), `useAuth()` (`@/contexts/AuthContext` — exposes `user: User | null`).
- Produces: `useProfile(): { profile: Profile | null; profileLoading: boolean; saveEntryId: (entryId: number) => Promise<void> }` with `Profile = { entryId: number | null; plan: PlanTier }`, `PlanTier = "free" | "pro" | "elite"`. Consumed by Task 4 (entry hydration) and Task 9 (entitlements).

- [ ] **Step 1: Write the hook**

Create `src/hooks/useProfile.ts`:

```ts
import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/contexts/AuthContext";

export type PlanTier = "free" | "pro" | "elite";

export interface Profile {
  entryId: number | null;
  plan: PlanTier;
}

const isPlanTier = (value: unknown): value is PlanTier =>
  value === "free" || value === "pro" || value === "elite";

/**
 * Loads the signed-in user's profile (FPL entry ID + plan tier) and exposes
 * a saver for the entry ID. Plan is read-only on the client.
 */
export function useProfile() {
  const { user } = useAuth();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);

  useEffect(() => {
    if (!user) {
      setProfile(null);
      setProfileLoading(false);
      return;
    }
    let cancelled = false;
    setProfileLoading(true);
    supabase
      .from("profiles")
      .select("entry_id, plan")
      .eq("id", user.id)
      .maybeSingle()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) {
          // Profile load failure must never block the app — fall back to defaults.
          setProfile({ entryId: null, plan: "free" });
        } else {
          setProfile({
            entryId: typeof data?.entry_id === "number" ? data.entry_id : null,
            plan: isPlanTier(data?.plan) ? data.plan : "free",
          });
        }
        setProfileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  const saveEntryId = useCallback(
    async (entryId: number) => {
      setProfile((prev) =>
        prev ? { ...prev, entryId } : { entryId, plan: "free" }
      );
      if (!user) return;
      // Never write `plan` from the client.
      await supabase
        .from("profiles")
        .upsert({ id: user.id, entry_id: entryId, updated_at: new Date().toISOString() });
    },
    [user]
  );

  return { profile, profileLoading, saveEntryId };
}
```

- [ ] **Step 2: Verify build + lint**

Run: `npm run build && npm run lint`
Expected: both pass (hook is not yet consumed — that's fine).

- [ ] **Step 3: Commit**

```bash
git add src/hooks/useProfile.ts
git commit -m "feat: add useProfile hook for entry ID + plan persistence"
```

---

### Task 4: Onboarding gate — kill SAMPLE fallback, validate entry ID

**Files:**
- Modify: `src/pages/Index.tsx` (`getInitialEntryId` at lines 54–62, `getInitialGw` fallback effect at lines 208–229, component body)
- Modify: `src/components/PitchVisualization.tsx` (entry-ID overlay at lines 303–336, props at lines 17–31)

**Interfaces:**
- Consumes: `parseEntryIdInput`, `ENTRY_ID_STORAGE_KEY` (Task 1); `useProfile` (Task 3); existing `fetchSquad(params: SquadParams, signal?): Promise<FplSquad>` from `fplAssistantApi.ts:871`.
- Produces: `PitchVisualization` prop change — `onEntryIdSubmit?: (raw: string) => Promise<string | null>` (returns error message or null on success). Index's `handleEntryIdSubmit` implements it.

- [ ] **Step 1: Remove SAMPLE fallback from `getInitialEntryId`**

In `src/pages/Index.tsx`, replace lines 54–62 with:

```ts
import { parseEntryIdInput } from "@/lib/entryId";

const getInitialEntryId = () => {
  const fromQuery = Number(new URLSearchParams(window.location.search).get("entry_id"));
  if (Number.isFinite(fromQuery) && fromQuery > 0) return fromQuery;

  const fromStorage = Number(localStorage.getItem("fpl_entry_id"));
  if (Number.isFinite(fromStorage) && fromStorage > 0) return fromStorage;

  // No stored ID — 0 triggers the onboarding overlay in PitchVisualization.
  return 0;
};
```

(Put the import at the top of the file with the other imports.)

- [ ] **Step 2: Hydrate entry ID from profile, persist on change**

In the `Index` component body, after the existing `useState` block (line ~126), add:

```ts
const { profile, saveEntryId } = useProfile();

// Cross-device hydration: profile beats "nothing", localStorage beats profile.
useEffect(() => {
  if (entryId > 0) return;
  if (profile?.entryId && profile.entryId > 0) {
    setEntryId(profile.entryId);
  }
}, [entryId, profile?.entryId]);
```

Add `import { useProfile } from "@/hooks/useProfile";` at the top.

In `setEntryAndReset` (line ~395), after `setEntryId(value);` add:

```ts
if (value > 0) void saveEntryId(value);
```

- [ ] **Step 3: Add validated submit handler in Index**

Still in the component body, add:

```ts
const handleEntryIdSubmit = async (raw: string): Promise<string | null> => {
  const id = parseEntryIdInput(raw);
  if (id === null) {
    return "That doesn't look like a team ID. Paste the number or your full FPL team URL.";
  }
  try {
    await fetchSquad({ entryId: id, eventId: resolvedGW });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // Only a definitive not-found blocks onboarding; transient/backend
    // errors must not lock the user out — accept and let error states surface.
    if (/\b404\b|not found/i.test(message)) {
      return "Couldn't find a team with that ID. Double-check it on the FPL site.";
    }
  }
  setEntryAndReset(id);
  return null;
};
```

Note: `resolvedGW` already exists at line ~405; keep this handler defined after it.

- [ ] **Step 4: Rework the overlay in PitchVisualization**

In `src/components/PitchVisualization.tsx`:

Change the prop type (line 19):

```ts
onEntryIdSubmit?: (raw: string) => Promise<string | null>;
```

Add local state next to `draftId` (line 170):

```ts
const [submitError, setSubmitError] = useState<string | null>(null);
const [submitting, setSubmitting] = useState(false);
```

Replace the overlay block (lines 303–336) with:

```tsx
{/* Entry ID prompt overlay — shown when no valid ID is set */}
{onEntryIdSubmit && (!entryId || entryId <= 0) && (
  <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm rounded-2xl">
    <div className="bg-card border border-border rounded-2xl p-8 w-full max-w-sm mx-4 text-center shadow-xl">
      <Search className="h-8 w-8 text-primary mx-auto mb-3" />
      <h3 className="font-bold text-foreground mb-1">Link your FPL team</h3>
      <p className="text-sm text-muted-foreground mb-1">
        On the FPL site, open <span className="font-medium text-foreground">Points</span> —
        your team URL looks like:
      </p>
      <p className="text-xs font-mono text-muted-foreground mb-5 break-all">
        fantasy.premierleague.com/entry/<span className="text-primary font-bold">588004</span>/event/38
      </p>
      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (submitting) return;
          setSubmitting(true);
          setSubmitError(null);
          const error = await onEntryIdSubmit(draftId);
          setSubmitting(false);
          if (error) setSubmitError(error);
        }}
      >
        <Input
          type="text"
          inputMode="numeric"
          placeholder="Team ID or full URL"
          value={draftId}
          onChange={(e) => setDraftId(e.target.value)}
          className="flex-1"
          autoFocus
        />
        <Button
          type="submit"
          disabled={submitting}
          className="bg-primary text-white hover:bg-primary/90 shrink-0"
        >
          {submitting ? "Checking…" : "Load"}
        </Button>
      </form>
      {submitError && (
        <p className="mt-3 text-xs text-destructive">{submitError}</p>
      )}
    </div>
  </div>
)}
```

- [ ] **Step 5: Wire the new prop in Index**

In `Index.tsx` JSX (line ~445), change:

```tsx
onEntryIdSubmit={setEntryAndReset}
```

to:

```tsx
onEntryIdSubmit={handleEntryIdSubmit}
```

- [ ] **Step 6: Verify manually**

```bash
npm run dev
```

With the FastAPI backend running locally (`http://localhost:8000`): open an incognito window at `http://localhost:8080/app` (log in first), confirm:
- Overlay appears (no stored ID). DevTools → Application → clear localStorage first if needed.
- Garbage input shows inline error.
- Pasting a full FPL URL works.
- Valid ID loads the squad; reload keeps it; Supabase `profiles` row has `entry_id` set.

- [ ] **Step 7: Run tests, build, lint, commit**

```bash
npm test && npm run build && npm run lint
git add src/pages/Index.tsx src/components/PitchVisualization.tsx
git commit -m "feat: onboarding gate with validated entry-ID capture, no sample fallback"
```

---

### Task 5: Mobile `/app` — responsive stack, parameter drawer, navbar menu

**Files:**
- Create: `src/components/ParameterForm.tsx` (extracted from ParameterSidebar)
- Create: `src/components/MobileParameterDrawer.tsx`
- Modify: `src/components/ParameterSidebar.tsx` (use ParameterForm for expanded content)
- Modify: `src/pages/Index.tsx` (responsive container + drawer)
- Modify: `src/components/PitchVisualization.tsx` (fluid pitch, bench wrap)
- Modify: `src/components/layout/Navbar.tsx` (mobile menu)

**Interfaces:**
- Consumes: `ParameterSidebarProps` (ParameterSidebar.tsx:32–47), `Drawer` primitives from `src/components/ui/drawer.tsx`, `useIsMobile` from `src/hooks/use-mobile.tsx` (existing).
- Produces: `ParameterFormProps` = `ParameterSidebarProps` minus nothing (same fields); `<ParameterForm>` renders the form fields + CTA, no `<aside>` shell. `<MobileParameterDrawer>` takes the same props.

- [ ] **Step 1: Extract `ParameterForm`**

Create `src/components/ParameterForm.tsx`. Move from `ParameterSidebar.tsx` the CHIP_OPTIONS const and everything inside the expanded `<aside>` — the fields block (lines 176–272) and the CTA block (lines 274–292) — into one component:

```tsx
import { Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { FplChipStrategy } from "@/lib/fplAssistantApi";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const CHIP_OPTIONS: Array<{ value: FplChipStrategy; label: string }> = [
  { value: "none", label: "No chip" },
  { value: "wildcard", label: "Wildcard" },
  { value: "free_hit", label: "Free Hit" },
];

export interface ParameterFormProps {
  entryId: number;
  onEntryIdChange: (entryId: number) => void;
  horizonGws: number;
  onHorizonGwsChange: (horizonGws: number) => void;
  chipStrategy: FplChipStrategy;
  onChipStrategyChange: (strategy: FplChipStrategy) => void;
  includeTransfers: boolean;
  onIncludeTransfersChange: (includeTransfers: boolean) => void;
  canRecommend: boolean;
  isRecommending: boolean;
  onRecommend: () => void;
  recommendErrorMessage?: string;
  isLiveGw?: boolean;
  maxHorizon?: number;
}

export const ParameterForm = (props: ParameterFormProps) => {
  const {
    entryId, onEntryIdChange, horizonGws, onHorizonGwsChange,
    chipStrategy, onChipStrategyChange, includeTransfers, onIncludeTransfersChange,
    canRecommend, isRecommending, onRecommend, recommendErrorMessage,
    isLiveGw = false, maxHorizon = 6,
  } = props;

  const recommendDisabled =
    !canRecommend || !Number.isFinite(entryId) || entryId <= 0 || isRecommending || isLiveGw;
  const cappedHorizonOptions = Array.from(
    { length: Math.max(1, Math.min(6, maxHorizon)) },
    (_, i) => i + 1
  );
  const chipActive = chipStrategy === "wildcard" || chipStrategy === "free_hit";
  const includeTransfersDisabled = chipActive;

  return (
    <>
      <div className="flex flex-col gap-5 p-4 flex-1">
        {/* fields block: paste lines 177–271 of the old ParameterSidebar here unchanged */}
      </div>
      <div className="p-4 border-t border-sidebar-border space-y-2">
        {/* CTA block: paste lines 275–291 of the old ParameterSidebar here unchanged */}
      </div>
    </>
  );
};
```

The two "paste here" comments mean: move the existing JSX verbatim (Entry ID field, Horizon select, Chip select, Transfers switch, Recommend button, live-GW note, error line). The locals they reference (`recommendDisabled`, `cappedHorizonOptions`, `chipActive`, `includeTransfersDisabled`, `CHIP_OPTIONS`) are all defined above. Do not alter classNames or copy.

- [ ] **Step 2: Slim `ParameterSidebar` to use it**

In `ParameterSidebar.tsx`: keep the collapsed rail (lines 77–155) as-is; in the expanded branch replace the fields + CTA blocks with:

```tsx
<ParameterForm {...props} />
```

To do that, change the component signature to accept `props: ParameterSidebarProps` and destructure what the rail needs (`entryId`, `horizonGws`, `chipStrategy`, `includeTransfers`, `onRecommend`, `isRecommending`, `canRecommend`, `isLiveGw`) from `props`. `ParameterSidebarProps` stays identical. Remove the now-unused imports (Input, Label, Switch, Select*, CHIP_OPTIONS) from ParameterSidebar.

- [ ] **Step 3: Create `MobileParameterDrawer`**

Create `src/components/MobileParameterDrawer.tsx`:

```tsx
import { useState } from "react";
import { Sliders } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer";
import { ParameterForm, type ParameterFormProps } from "./ParameterForm";

/** Floating settings button + bottom drawer for < lg screens. */
export const MobileParameterDrawer = (props: ParameterFormProps) => {
  const [open, setOpen] = useState(false);

  return (
    <Drawer open={open} onOpenChange={setOpen}>
      <DrawerTrigger asChild>
        <Button
          size="icon"
          className="lg:hidden fixed bottom-5 right-5 z-40 h-12 w-12 rounded-full shadow-lg bg-primary text-white hover:bg-primary/90"
          aria-label="Open squad parameters"
        >
          <Sliders className="h-5 w-5" />
        </Button>
      </DrawerTrigger>
      <DrawerContent className="max-h-[85vh]">
        <DrawerHeader className="pb-0">
          <DrawerTitle className="text-sm font-bold tracking-tight">Parameters</DrawerTitle>
        </DrawerHeader>
        <div className="overflow-y-auto">
          <ParameterForm
            {...props}
            onRecommend={() => {
              setOpen(false);
              props.onRecommend();
            }}
          />
        </div>
      </DrawerContent>
    </Drawer>
  );
};
```

- [ ] **Step 4: Responsive layout in Index**

In `Index.tsx` JSX:

- Container (line ~410): change

```tsx
<div className="flex flex-1 min-h-0 pt-14">
```

to

```tsx
<div className="flex flex-1 min-h-0 pt-14 flex-col lg:flex-row overflow-y-auto lg:overflow-hidden">
```

- Wrap the sidebar (desktop-only) and add the drawer. Replace `<ParameterSidebar …/>` with:

```tsx
<div className="hidden lg:flex shrink-0">
  <ParameterSidebar {...parameterProps} />
</div>
<MobileParameterDrawer {...parameterProps} />
```

where `parameterProps` is a new const in the component body collecting the exact same 14 props currently passed inline (lines 419–441):

```ts
const parameterProps = {
  entryId,
  onEntryIdChange: setEntryAndReset,
  horizonGws,
  onHorizonGwsChange: setHorizonGws,
  chipStrategy,
  onChipStrategyChange: setChipStrategy,
  includeTransfers,
  onIncludeTransfersChange: setIncludeTransfers,
  canRecommend,
  isRecommending: recommendationMutation.isPending,
  isLiveGw,
  maxHorizon: Math.max(1, 38 - resolvedGW + 1),
  onRecommend: () => {
    const nextChipPlayEventId = chipStrategy === "wildcard" ? resolvedGW : undefined;
    if (chipStrategy === "wildcard") {
      setChipPlayEventId(nextChipPlayEventId);
    }
    setAppliedTransferCount(0);
    recommendationMutation.mutate(
      buildRecommendationParams(resolvedGW, { chipPlayEventId: nextChipPlayEventId })
    );
  },
  recommendErrorMessage,
};
```

Add `import { MobileParameterDrawer } from "@/components/MobileParameterDrawer";`.

- [ ] **Step 5: Fluid pitch + bench wrap in PitchVisualization**

In `PitchVisualization.tsx`:

- Root (line 229): `className="flex-1 min-w-0 p-2 sm:p-4 lg:overflow-y-auto"`
- Pitch container (line 289): change `px-4 py-8` to `px-2 py-6 sm:px-4 sm:py-8` and `minHeight: "600px"` to `minHeight: "480px"` with an added `sm:min-h-[600px]`-equivalent: replace the style `minHeight` entirely with Tailwind classes `min-h-[480px] sm:min-h-[600px]` on the className.
- Bench row (line 400): `className="flex flex-wrap justify-center gap-3 sm:gap-8"`
- Row gap helper (lines 33–40): halve gaps on small screens by changing returns to responsive pairs:

```ts
const getRowGapClass = (count: number) => {
  if (count >= 6) return "gap-1 sm:gap-2";
  if (count === 5) return "gap-2 sm:gap-4";
  if (count === 4) return "gap-3 sm:gap-6";
  if (count === 3) return "gap-5 sm:gap-10";
  if (count === 2) return "gap-8 sm:gap-14";
  return "gap-3 sm:gap-6";
};
```

- [ ] **Step 6: RecommendationsPanel full-width on mobile**

In `RecommendationsPanel.tsx` root (line 447): change

```tsx
<aside className="w-[380px] xl:w-[440px] shrink-0 bg-card border-l border-border flex flex-col">
```

to

```tsx
<aside className="w-full lg:w-[380px] xl:w-[440px] shrink-0 bg-card border-t lg:border-t-0 lg:border-l border-border flex flex-col">
```

- [ ] **Step 7: Navbar mobile menu**

`Navbar.tsx` nav links are `hidden md:flex` (line 42) with no mobile alternative — League/Fixtures unreachable on phones. Add a shadcn `DropdownMenu` hamburger visible below `md`: trigger = `Menu` icon button (`md:hidden`), items mirroring the desktop links (same routes/labels, read them from the existing nav array or JSX). Keep desktop untouched.

- [ ] **Step 8: Verify at target viewports**

`npm run dev`, Chrome devtools responsive mode at 375px, 390px, 768px, 1280px:
- 375px: single column — GW nav, pitch (no horizontal scroll), bench wraps, recommendations below, floating params button opens drawer, navbar hamburger reaches League.
- 1280px: identical to pre-change desktop layout.

- [ ] **Step 9: Tests, build, lint, commit**

```bash
npm test && npm run build && npm run lint
git add src/components/ParameterForm.tsx src/components/MobileParameterDrawer.tsx src/components/ParameterSidebar.tsx src/components/PitchVisualization.tsx src/components/RecommendationsPanel.tsx src/components/layout/Navbar.tsx src/pages/Index.tsx
git commit -m "feat: mobile-responsive /app with parameter drawer and navbar menu"
```

---

### Task 6: Resilience — error boundary, retry/backoff, skeleton, empty states

**Files:**
- Create: `src/components/ErrorBoundary.tsx`
- Create: `src/components/QueryErrorCard.tsx`
- Modify: `src/App.tsx` (QueryClient defaults + boundary)
- Modify: `src/pages/Index.tsx` (skeleton/empty/error rendering, drop SAMPLE team fallback)
- Modify: `src/components/PitchVisualization.tsx` (`team` optional + skeleton)

**Interfaces:**
- Consumes: `Skeleton` from `src/components/ui/skeleton.tsx` (existing), TanStack Query v5 (`retry`, `retryDelay`, `refetch`).
- Produces: `<ErrorBoundary>` (children prop); `<QueryErrorCard message={string} onRetry={() => void} retrying?: boolean>`; `PitchVisualization` prop `team?: PitchTeam` (now optional — skeleton renders when undefined).

- [ ] **Step 1: Error boundary**

Create `src/components/ErrorBoundary.tsx`:

```tsx
import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
}
interface State {
  hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="dark min-h-screen bg-background flex flex-col items-center justify-center gap-4 px-6 text-center">
          <h1 className="text-xl font-bold text-foreground">Something went wrong</h1>
          <p className="text-sm text-muted-foreground max-w-sm">
            An unexpected error broke this page. Reloading usually fixes it.
          </p>
          <Button onClick={() => window.location.reload()} className="bg-primary text-white">
            Reload
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

- [ ] **Step 2: QueryClient retry/backoff + boundary wiring**

In `src/App.tsx`, replace `const queryClient = new QueryClient();` with:

```ts
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Fly.io cold starts: retry twice with exponential backoff before failing.
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    },
  },
});
```

Wrap routes: inside `<BrowserRouter><AuthProvider>` change `<Routes>…</Routes>` to `<ErrorBoundary><Routes>…</Routes></ErrorBoundary>` and import it.

Note: `Index.tsx` queries currently set `retry: false` per-query (lines 144, 153, 160). Remove those three `retry: false` lines so the new defaults apply.

- [ ] **Step 3: Error card component**

Create `src/components/QueryErrorCard.tsx`:

```tsx
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  title?: string;
  message?: string;
  onRetry: () => void;
  retrying?: boolean;
}

export const QueryErrorCard = ({
  title = "Couldn't load data",
  message,
  onRetry,
  retrying = false,
}: Props) => (
  <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-5 text-center">
    <p className="font-semibold text-destructive mb-1">{title}</p>
    {message && <p className="text-xs text-destructive/80 mb-3 break-words">{message}</p>}
    <Button size="sm" variant="outline" onClick={onRetry} disabled={retrying}>
      <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${retrying ? "animate-spin" : ""}`} />
      {retrying ? "Retrying…" : "Retry"}
    </Button>
  </div>
);
```

- [ ] **Step 4: Skeleton pitch + optional team**

In `PitchVisualization.tsx`:
- Prop: `team?: PitchTeam;` (make optional).
- Guard the team-dependent memos: at the top of the component, after the hooks that don't need `team`, add an early return **after all hooks** — instead restructure: compute `const hasTeam = Boolean(team)` and make each `useMemo` on `team` tolerate `undefined` (return empty arrays / zeros when `!team`). Then in the JSX, where rows render, if `!hasTeam` render a skeleton pitch inside the same pitch background:

```tsx
{!hasTeam ? (
  <div className="relative z-10 flex flex-col items-center gap-10 py-4">
    {[1, 4, 4, 2].map((count, row) => (
      <div key={row} className="flex justify-center gap-4">
        {Array.from({ length: count }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-16 rounded-md bg-white/10" />
        ))}
      </div>
    ))}
  </div>
) : (
  /* existing GK/DEF/MID/FWD rows */
)}
```

Import `Skeleton` from `@/components/ui/skeleton`. Bench block: render only when `hasTeam`.

- [ ] **Step 5: Index — drop SAMPLE as active team, wire error/empty states**

In `Index.tsx`:
- Line ~446: `team={activeTeam ?? SAMPLE_SQUAD}` → `team={activeTeam}`.
- Off-season fallback effect (lines 219–223): keep the GW default (a number is harmless) but add a pre-season flag:

```ts
// isSuccess (not isFetched) — a failed next-event fetch must show the error path,
// not a false "off-season" card.
const isOffSeason = nextEventQuery.isSuccess && !Number.isFinite(nextEventQuery.data?.event_id);
```

- In the JSX above `<PitchVisualization>`, when `isOffSeason` render a card instead of the pitch column:

```tsx
{isOffSeason ? (
  <div className="flex-1 flex items-center justify-center p-6">
    <div className="max-w-sm text-center rounded-2xl border border-border bg-card p-8">
      <h3 className="font-bold text-foreground mb-2">Season hasn't started</h3>
      <p className="text-sm text-muted-foreground">
        The FPL API has no upcoming gameweek yet. Check back when the new season fixtures are live.
      </p>
    </div>
  </div>
) : (
  <PitchVisualization … />
)}
```

- Squad hard-failure: PitchVisualization's existing inline error banner (lines 268–273) says "Showing last loaded data" — correct when stale data exists. When there is **no** data at all (`squadQuery.isError && !squadQuery.data`), render `<QueryErrorCard message={activeErrorMessage} onRetry={() => squadQuery.refetch()} retrying={squadQuery.isFetching} />` in place of the pitch (same conditional slot as the off-season card).
- Remove the now-unused `SAMPLE_SQUAD` import if nothing else references it (the `resolvedGW` fallback at line 405 still uses `SAMPLE_SQUAD.event_id` — replace with the literal `38` and a comment `// pre-resolution placeholder; gwResolved gates rendering`; then delete the import).

- [ ] **Step 6: Verify**

`npm run dev`:
- Kill the local backend → `/app` shows retrying then the error card with working Retry; no white screen, no sample squad.
- Restart backend → Retry recovers.
- Normal load shows skeleton pitch briefly (throttle network to see it), no flash of someone else's squad.

- [ ] **Step 7: Tests, build, lint, commit**

```bash
npm test && npm run build && npm run lint
git add src/App.tsx src/components/ErrorBoundary.tsx src/components/QueryErrorCard.tsx src/components/PitchVisualization.tsx src/pages/Index.tsx
git commit -m "feat: error boundary, query retry/backoff, skeleton pitch, empty states"
```

---

### Task 7: P0 — GW navigation fail-to-load bug

**Files:**
- Modify: TBD by diagnosis — expected in `src/pages/Index.tsx` (GW effects, lines 208–246 and `setGwAndReset` at 371–393) and/or backend `/squad` handling of past GWs.

**Interfaces:**
- Consumes: everything from Tasks 4–6 (states now visible instead of silent failures).
- Produces: GW back/forward navigation that always resolves to data or an explicit error card.

This is a diagnosis task — use the superpowers:systematic-debugging skill. Do not patch symptoms.

- [ ] **Step 1: Reproduce**

`npm run dev` with local backend. In `/app` with a real entry ID: navigate to an earlier GW via GameweekNav prev arrow and via the GW picker. Watch DevTools Network. Record: which endpoint fails (`/squad`? `/fixtures`?), status code, response body, and the GW values in the request URL.

- [ ] **Step 2: Check the snap-back effect**

Prime suspect: `Index.tsx` lines 231–246 — when `/squad` returns a different `event_id` than requested, `squadGW` is overwritten by the response's GW. If the backend returns the latest-picks GW for past-GW requests, the UI can bounce back or wedge (`selectedGW` and `squadGW` diverge; fixtures load for one GW, squad for another). Log both values across a repro to confirm or rule out.

- [ ] **Step 3: Check the backend**

```bash
curl "http://localhost:8000/squad?entry_id=<your-id>&event_id=<past-gw>" | head -c 500
```

Record whether the backend actually serves historical GWs or errors/redirects to current. If the backend can't serve past GWs, the frontend fix is to constrain navigation to the supported range and show an explicit message — not to pretend.

- [ ] **Step 4: Root-cause and fix**

Write the fix at the identified layer only. Acceptance criteria:
- From live GW: navigate back 3 GWs one at a time — each shows that GW's squad or an explicit error card; no silent wedge, no bounce-back loop.
- Navigate forward to next GW and back — state consistent, recommendations reset appropriately (existing `setGwAndReset` behavior).
- GW1 and GW38 boundaries clamp correctly.

- [ ] **Step 5: Verify, update BACKLOG, commit**

Re-run the Step 1 repro — pass. Mark the P0 line in `BACKLOG.md` as done with a one-line cause note.

```bash
npm test && npm run build && npm run lint
git add -A
git commit -m "fix: GW navigation fail-to-load (root cause: <fill in>)"
```

---

### Task 8: Honest landing + legal pages

**Files:**
- Modify: `src/pages/Landing.tsx` (stats lines 121–125, testimonial lines 334–348, pricing lines 70–118 + 271–332, footer lines 383–386)
- Create: `src/pages/Privacy.tsx`
- Create: `src/pages/Terms.tsx`
- Modify: `src/App.tsx` (two routes)

**Interfaces:**
- Consumes: existing `Navbar`, shadcn `Button`/`Badge`.
- Produces: routes `/privacy`, `/terms`.

- [ ] **Step 1: Replace fabricated stats**

In `Landing.tsx` replace the `stats` array (lines 121–125) with:

```ts
const stats = [
  { value: "Every player", label: "xPts modelled per GW" },
  { value: "6 GWs", label: "Planning horizon" },
  { value: "2026/27", label: "Ready for the new season" },
];
```

- [ ] **Step 2: Remove the testimonial section**

Delete the entire "Social proof" section (lines 334–348). Remove the now-unused `Star` import only if unused elsewhere (it is also used in `features`? No — features uses `Star` for Captain Picks at line 37; keep the import).

- [ ] **Step 3: Beta pricing**

Replace the `plans` array (lines 71–118) with:

```ts
const betaPerks = [
  "xPts for every player, every GW",
  "Multi-GW planning horizon",
  "Wildcard & Free Hit chip drafts",
  "Transfer suggestions with point gain",
  "Captain & vice recommendations",
  "Mini-league strategy dashboard",
];

const comingSoon = ["Pro & Elite tiers", "Differential alerts", "API access"];
```

Replace the pricing section body (the `plans.map` grid, lines 284–330) with a single centered card:

```tsx
<div className="mx-auto max-w-md">
  <div className="rounded-2xl border border-primary bg-primary/10 ring-1 ring-primary/50 p-8 flex flex-col gap-5 shadow-lg shadow-primary/20">
    <Badge className="w-fit bg-primary text-white text-xs font-bold">Beta</Badge>
    <div>
      <p className="text-4xl font-black text-white">
        Free
        <span className="text-lg font-medium text-white/40"> while in beta</span>
      </p>
      <p className="text-sm text-white/40 mt-1">
        Full access. No card. Help shape the product.
      </p>
    </div>
    <ul className="flex flex-col gap-2.5">
      {betaPerks.map((perk) => (
        <li key={perk} className="flex items-start gap-2 text-sm text-white/70">
          <Check className="h-4 w-4 text-accent mt-0.5 shrink-0" />
          {perk}
        </li>
      ))}
    </ul>
    <div className="border-t border-white/10 pt-4">
      <p className="text-xs uppercase tracking-widest text-white/30 mb-2">Coming later</p>
      <ul className="flex flex-col gap-1.5">
        {comingSoon.map((item) => (
          <li key={item} className="text-sm text-white/35">{item}</li>
        ))}
      </ul>
    </div>
    <Link to="/auth" className="mt-auto">
      <Button className="w-full font-bold bg-primary hover:bg-primary/90 text-white">
        Get started free
      </Button>
    </Link>
  </div>
</div>
```

Update the section subtitle (line 281) to: `Free while we're in beta — paid tiers arrive once the product earns them.`

- [ ] **Step 4: Copy audit on remaining sections**

- Final CTA heading (line 355): `Join 42,000+ managers making smarter picks` → `Make smarter picks this season`.
- Feature cards (lines 19–68): verify each claim against the shipped app — all six exist in some form (xPts, wildcard drafter via chip strategy, captain picks, transfer planner, chip strategy, league dashboard). Soften "League Dashboard" description if it promises rank trends/H2H not yet shipped: change its description to `"Mini-league strategy: chase, defend, or hunt differentials against your rivals."`
- Hero copy: keep, it's claims-free.

- [ ] **Step 5: Legal pages**

Create `src/pages/Privacy.tsx`:

```tsx
import { Navbar } from "@/components/layout/Navbar";

export default function Privacy() {
  return (
    <div className="min-h-screen bg-[hsl(248_20%_8%)] text-white">
      <Navbar />
      <main className="mx-auto max-w-2xl px-4 sm:px-6 pt-24 pb-16 prose prose-invert prose-sm">
        <h1>Privacy Policy</h1>
        <p>Last updated: 18 July 2026</p>
        <h2>What we store</h2>
        <ul>
          <li>Your email address and authentication data, managed by Supabase.</li>
          <li>Your FPL team (entry) ID and plan tier, stored in our database.</li>
          <li>Locally on your device: your selected gameweek and squad preferences (browser storage).</li>
        </ul>
        <h2>What we don't do</h2>
        <ul>
          <li>We don't sell your data.</li>
          <li>We don't access your FPL account — we only read public FPL API data for the team ID you provide.</li>
        </ul>
        <h2>Deletion</h2>
        <p>
          Email zn.aianalytics@gmail.com to delete your account and all associated data.
        </p>
      </main>
    </div>
  );
}
```

Create `src/pages/Terms.tsx`:

```tsx
import { Navbar } from "@/components/layout/Navbar";

export default function Terms() {
  return (
    <div className="min-h-screen bg-[hsl(248_20%_8%)] text-white">
      <Navbar />
      <main className="mx-auto max-w-2xl px-4 sm:px-6 pt-24 pb-16 prose prose-invert prose-sm">
        <h1>Terms of Service</h1>
        <p>Last updated: 18 July 2026</p>
        <p>
          FPLedge provides Fantasy Premier League analysis and recommendations for
          entertainment purposes. Projections are estimates, not guarantees — transfer
          and chip decisions are your own.
        </p>
        <p>
          The service is provided "as is" during beta, without warranty. We may change
          or discontinue features at any time.
        </p>
        <p>
          FPLedge is not affiliated with the Premier League or the official Fantasy
          Premier League game.
        </p>
      </main>
    </div>
  );
}
```

(`@tailwindcss/typography` is already a devDependency — `prose` classes work; confirm the `typography` plugin is registered in `tailwind.config.ts`, add it to `plugins` if missing.)

In `App.tsx` add routes (public, no ProtectedRoute):

```tsx
<Route path="/privacy" element={<Privacy />} />
<Route path="/terms" element={<Terms />} />
```

In `Landing.tsx` footer (lines 384–385): replace `href="#"` anchors with `<Link to="/privacy">` / `<Link to="/terms">` (Link is already imported).

- [ ] **Step 6: Verify, commit**

`npm run dev`: check `/`, `/privacy`, `/terms` render; no fake numbers anywhere on `/`.

```bash
npm test && npm run build && npm run lint
git add src/pages/Landing.tsx src/pages/Privacy.tsx src/pages/Terms.tsx src/App.tsx tailwind.config.ts
git commit -m "feat: honest landing copy, beta pricing, privacy + terms pages"
```

---

### Task 9: Entitlement scaffold (TDD)

**Files:**
- Create: `src/lib/entitlements.ts`
- Create: `src/lib/__tests__/entitlements.test.ts`
- Create: `src/hooks/useEntitlement.ts`
- Modify: `src/pages/League.tsx` (one documented gate point)

**Interfaces:**
- Consumes: `PlanTier`, `useProfile` (Task 3).
- Produces: `computeEntitlements(plan: PlanTier, opts?: { betaAllAccess?: boolean }): Entitlements`; `useEntitlement(): Entitlements`; `Entitlements = { plan: PlanTier; canUseWildcardDrafter: boolean; canUseMultiGwHorizon: boolean; canUseLeagueDashboard: boolean }`.

- [ ] **Step 1: Write the failing test**

Create `src/lib/__tests__/entitlements.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { computeEntitlements, BETA_ALL_ACCESS } from "../entitlements";

describe("computeEntitlements", () => {
  it("grants everything during beta regardless of plan", () => {
    const e = computeEntitlements("free");
    expect(e.canUseWildcardDrafter).toBe(true);
    expect(e.canUseMultiGwHorizon).toBe(true);
    expect(e.canUseLeagueDashboard).toBe(true);
  });

  it("beta flag is on", () => {
    expect(BETA_ALL_ACCESS).toBe(true);
  });

  it("free plan loses pro features when beta access is off", () => {
    const e = computeEntitlements("free", { betaAllAccess: false });
    expect(e.canUseWildcardDrafter).toBe(false);
    expect(e.canUseMultiGwHorizon).toBe(false);
    expect(e.canUseLeagueDashboard).toBe(false);
  });

  it("pro plan gets pro features but not elite when beta off", () => {
    const e = computeEntitlements("pro", { betaAllAccess: false });
    expect(e.canUseWildcardDrafter).toBe(true);
    expect(e.canUseMultiGwHorizon).toBe(true);
    expect(e.canUseLeagueDashboard).toBe(false);
  });

  it("elite gets everything when beta off", () => {
    const e = computeEntitlements("elite", { betaAllAccess: false });
    expect(e.canUseLeagueDashboard).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/__tests__/entitlements.test.ts`
Expected: FAIL — cannot resolve `../entitlements`.

- [ ] **Step 3: Implement**

Create `src/lib/entitlements.ts`:

```ts
import type { PlanTier } from "@/hooks/useProfile";

export interface Entitlements {
  plan: PlanTier;
  canUseWildcardDrafter: boolean;
  canUseMultiGwHorizon: boolean;
  canUseLeagueDashboard: boolean;
}

/**
 * Beta switch: while true, every plan gets full access.
 * Flipping this to false (post-Stripe) activates real plan gating —
 * components never read plan strings, only the flags below.
 */
export const BETA_ALL_ACCESS = true;

export function computeEntitlements(
  plan: PlanTier,
  opts?: { betaAllAccess?: boolean }
): Entitlements {
  const beta = opts?.betaAllAccess ?? BETA_ALL_ACCESS;
  if (beta) {
    return {
      plan,
      canUseWildcardDrafter: true,
      canUseMultiGwHorizon: true,
      canUseLeagueDashboard: true,
    };
  }
  const proOrBetter = plan === "pro" || plan === "elite";
  return {
    plan,
    canUseWildcardDrafter: proOrBetter,
    canUseMultiGwHorizon: proOrBetter,
    canUseLeagueDashboard: plan === "elite",
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/__tests__/entitlements.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Hook + one gate point**

Create `src/hooks/useEntitlement.ts`:

```ts
import { useMemo } from "react";
import { computeEntitlements, type Entitlements } from "@/lib/entitlements";
import { useProfile } from "@/hooks/useProfile";

export function useEntitlement(): Entitlements {
  const { profile } = useProfile();
  return useMemo(
    () => computeEntitlements(profile?.plan ?? "free"),
    [profile?.plan]
  );
}
```

In `src/pages/League.tsx`, near the top of the component:

```ts
const { canUseLeagueDashboard } = useEntitlement();
```

and wrap the page body:

```tsx
if (!canUseLeagueDashboard) {
  return (
    <div className="min-h-screen bg-background pt-20 pb-8 px-4 text-center">
      <p className="text-muted-foreground">League strategy is part of a paid tier.</p>
    </div>
  );
}
```

(Unreachable while `BETA_ALL_ACCESS = true` — it's the documented gate point for the future Stripe drop-in.)

- [ ] **Step 6: Tests, build, lint, commit**

```bash
npm test && npm run build && npm run lint
git add src/lib/entitlements.ts src/lib/__tests__/entitlements.test.ts src/hooks/useEntitlement.ts src/pages/League.tsx
git commit -m "feat: entitlement scaffold with beta all-access flag"
```

---

### Task 10: Production cleanup

**Files:**
- Modify: `src/components/PlayerCard.tsx` (lines 264–266)

- [ ] **Step 1: Remove backend note from PlayerCard breakdown**

Delete the block at lines 264–266:

```tsx
{breakdown?.note && (
  <p className="text-[11px] text-muted-foreground">{breakdown.note}</p>
)}
```

(BACKLOG P1: "Remove notes from UI for production". The `?debug_transfers=1`-gated debug in `TransferPlanner.tsx` stays — already hidden by default.)

- [ ] **Step 2: Mark BACKLOG items**

In `BACKLOG.md`, tick the two P1 items (debug UI was already query-gated; notes now removed).

- [ ] **Step 3: Build, lint, commit**

```bash
npm run build && npm run lint
git add src/components/PlayerCard.tsx BACKLOG.md
git commit -m "chore: remove backend note text from player breakdown UI"
```

---

### Task 11: QA sweep + ship to main

**Files:** none new — verification + merge.

- [ ] **Step 1: Full local QA against local backend**

```bash
npm test && npm run build && npm run lint && npm run dev
```

Fresh incognito pass: sign up (new email) → confirm → `/app` shows onboarding overlay → paste FPL URL → squad loads → run recommendation → ZN Pick tab → apply a transfer → `/app/league` loads league strategy → sign out/in again on a "different device" (clear localStorage) → entry ID restored from profile.

- [ ] **Step 2: Mobile QA**

Repeat the core flow at 375px viewport: onboarding overlay usable, drawer parameters, recommendation run, league page.

- [ ] **Step 3: QA against production backend**

In `.env`, point `VITE_FPL_API_BASE_URL` at the prod Fly.io URL (value from Vercel env), rerun the incognito pass. Watch for CORS (frontend origin must be allowed in FastAPI CORSMiddleware) and cold-start retry behavior. Restore `.env` afterwards.

- [ ] **Step 4: Merge and deploy**

The unpushed `chat-backend` commit (`8cfe945`, league ownership-EV) ships as part of this branch since `ship-ready` includes it.

```bash
git checkout main && git pull origin main
git merge ship-ready
git push origin main
```

Vercel auto-deploys `main`. Confirm Vercel env vars are set: `VITE_FPL_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`.

- [ ] **Step 5: Verify production**

On the deployed URL: incognito signup → onboarding → squad → recommendation → league → `/privacy`, `/terms` → mobile device check. Then push the branch for history:

```bash
git push origin ship-ready chat-backend
```

- [ ] **Step 6: Update CLAUDE.md**

Add to `CLAUDE.md`: profiles table (entry_id/plan + RLS), `useProfile`/`useEntitlement` + `BETA_ALL_ACCESS` flag location, onboarding gate behavior (entryId 0 = overlay), `npm test` (Vitest). Commit:

```bash
git add CLAUDE.md
git commit -m "docs: document profiles, entitlements, onboarding gate, vitest"
git push origin main
```
