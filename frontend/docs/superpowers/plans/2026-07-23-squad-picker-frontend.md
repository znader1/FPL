# Squad Picker Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A dev-only `/squad` page that calls the backend `POST /squad-picker/build`, lets the user tune the wired parameters, and renders the drafted 15 + XI + captain + projected points + notes — gated exactly like `/replay` so it never ships to production.

**Architecture:** Mirror the `/replay` frontend pattern. New `src/lib/squadPickerApi.ts` (typed client + `squadPickerEnabled()`), new `src/pages/SquadPicker.tsx` (params panel + result view reusing `PitchVisualization` + a table), and a build-time-static gated route in `src/App.tsx`. Verified via vitest (client) + `tsc`/`vite build` (page). Repo: `fpl-decision-hub`, branch `feature/squad-picker`.

**Tech Stack:** React 18, TypeScript, Vite, TanStack Query, shadcn/ui, Tailwind. Backend endpoint `POST /squad-picker/build` (base = `VITE_FPL_API_BASE_URL`).

## Global Constraints

- The `/squad` route mounts ONLY when `import.meta.env.DEV && import.meta.env.VITE_SQUAD_PICKER === "1"` — build-time-static so production builds tree-shake it entirely (mirror the `/replay` gate at `src/App.tsx:56` and the `/* @__PURE__ */ lazy(...)` at `src/App.tsx:24`). No production surface.
- Backend base URL comes from `import.meta.env.VITE_FPL_API_BASE_URL` (empty string → relative). Endpoint path: `/squad-picker/build`, `/squad-picker/knowledge`.
- Only surface controls for WIRED params (per the backend spec's "v1 backend shipped-status"): `horizon_gws`, `budget_m`, `objective`, `projection_basis`, `blend_weight`, `minutes_prior_k`, `include_flagged`, `min_chance_of_playing`, `max_per_team`, `min_fwd_minutes`, `formation`. Do NOT add controls for `fdr_strength`, `team_nudges`, `league_id` (not wired).
- No jsdom/testing-library in this repo — component render tests are unavailable. Verify the page via `npx tsc -p tsconfig.app.json --noEmit` + `npm run build`. Client lib gets a vitest test.
- Commit prefix `feat:`/`test:`. End commit body with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task F1: Typed API client — `src/lib/squadPickerApi.ts`

**Files:**
- Create: `src/lib/squadPickerApi.ts`
- Test: `src/lib/squadPickerApi.test.ts`

**Interfaces:**
- Produces: `squadPickerEnabled(): boolean`; `buildSquad(params: SquadBuildParams): Promise<SquadBuildResult>`; `getKnowledge(): Promise<KnowledgeGrid>`; `saveKnowledge(grid: KnowledgeGrid): Promise<KnowledgeGrid>`; and the exported types below.

- [ ] **Step 1: Write the failing test**

```ts
// src/lib/squadPickerApi.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildSquad, squadPickerEnabled } from "./squadPickerApi";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("squadPickerApi", () => {
  it("squadPickerEnabled reflects VITE_SQUAD_PICKER", () => {
    vi.stubEnv("VITE_SQUAD_PICKER", "1");
    expect(squadPickerEnabled()).toBe(true);
    vi.stubEnv("VITE_SQUAD_PICKER", "");
    expect(squadPickerEnabled()).toBe(false);
  });

  it("buildSquad POSTs params to the base URL and returns JSON", async () => {
    vi.stubEnv("VITE_FPL_API_BASE_URL", "http://localhost:8009");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, squad: [], starting_xi: [], bench: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await buildSquad({ horizon_gws: 5, projection_basis: "ppg" });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8009/squad-picker/build",
      expect.objectContaining({ method: "POST" }),
    );
    expect(res.ok).toBe(true);
  });

  it("buildSquad throws on non-ok HTTP", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 500, json: async () => ({ detail: "boom" }),
    }));
    await expect(buildSquad({})).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/squadPickerApi.test.ts`
Expected: FAIL — cannot find module `./squadPickerApi`.

- [ ] **Step 3: Write minimal implementation**

```ts
// src/lib/squadPickerApi.ts
// Dev-only squad-picker client. Talks to the SQUAD_PICKER_MODE-gated backend
// (POST /squad-picker/build, GET/POST /squad-picker/knowledge). Never used in
// production (the route is DEV+flag gated in App.tsx).

export type ProjectionBasis = "ppg" | "xg" | "blend";
export type Objective = "wildcard" | "free_hit" | "plain";

export interface SquadBuildParams {
  horizon_gws?: number;
  budget_m?: number;
  objective?: Objective;
  projection_basis?: ProjectionBasis;
  blend_weight?: number;
  minutes_prior_k?: number;
  include_flagged?: boolean;
  min_chance_of_playing?: number;
  max_per_team?: number;
  min_fwd_minutes?: number;
  formation?: string; // "auto" | "3-4-3" | ...
}

export interface SquadPlayer {
  player_id: number;
  web_name: string;
  pos: "GKP" | "DEF" | "MID" | "FWD";
  team_short: string;
  team_name?: string;
  price_m: number;
  points_per_game?: number;
  xpts_horizon?: number;
  is_captain_suggested?: boolean;
  is_vice_suggested?: boolean;
  xpts?: number;
  event_points?: number;
}

export interface ProjectedGw { gw: number; xi_points: number; captain_bonus: number; total: number; }
export interface ProjectedPoints { per_gw: ProjectedGw[]; horizon_total: number; }

export interface SquadBuildResult {
  ok: boolean;
  reason?: string | null;
  notes: string[];
  gw_start?: number;
  horizon_gws?: number;
  objective?: string;
  projection_basis?: string;
  formation?: [number, number, number] | null;
  captain_player_id?: number | null;
  vice_player_id?: number | null;
  budget_m?: number;
  squad_cost_m?: number | null;
  remaining_budget_m?: number | null;
  squad: SquadPlayer[];
  starting_xi: SquadPlayer[];
  bench: SquadPlayer[];
  value_menu?: Record<string, SquadPlayer[]>;
  projected_points?: ProjectedPoints;
}

export interface KnowledgeGrid {
  as_of: string | null;
  teams: Record<string, { attack?: number; defense?: number; note?: string }>;
}

function apiBase(): string {
  const v = (import.meta.env as Record<string, unknown>)["VITE_FPL_API_BASE_URL"];
  return typeof v === "string" ? v : "";
}

export function squadPickerEnabled(): boolean {
  return import.meta.env.VITE_SQUAD_PICKER === "1";
}

export async function buildSquad(params: SquadBuildParams): Promise<SquadBuildResult> {
  const res = await fetch(`${apiBase()}/squad-picker/build`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params ?? {}),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const b = await res.json(); if (b?.detail) detail = b.detail; } catch { /* ignore */ }
    throw new Error(`Squad build failed: ${detail}`);
  }
  return (await res.json()) as SquadBuildResult;
}

export async function getKnowledge(): Promise<KnowledgeGrid> {
  const res = await fetch(`${apiBase()}/squad-picker/knowledge`);
  if (!res.ok) throw new Error(`Knowledge fetch failed: HTTP ${res.status}`);
  return (await res.json()) as KnowledgeGrid;
}

export async function saveKnowledge(grid: KnowledgeGrid): Promise<KnowledgeGrid> {
  const res = await fetch(`${apiBase()}/squad-picker/knowledge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(grid),
  });
  if (!res.ok) throw new Error(`Knowledge save failed: HTTP ${res.status}`);
  return (await res.json()) as KnowledgeGrid;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/squadPickerApi.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lib/squadPickerApi.ts src/lib/squadPickerApi.test.ts
git commit -m "feat: squad-picker API client + types"
```

---

### Task F2: The page — `src/pages/SquadPicker.tsx`

**Files:**
- Create: `src/pages/SquadPicker.tsx`

**Interfaces:**
- Consumes: `buildSquad`, `SquadBuildParams`, `SquadBuildResult`, `SquadPlayer` from `src/lib/squadPickerApi.ts`. shadcn/ui primitives from `@/components/ui/*` (button, input, label, select, card, switch, table — use whatever exists; check `src/components/ui/`). `PitchVisualization` from `@/components/PitchVisualization` (optional stretch).
- Produces: `export default function SquadPicker()`.

- [ ] **Step 1: Implement the page**

The page holds a `SquadBuildParams` state with sensible defaults, a controls panel, a "Build squad" button that calls `buildSquad` (TanStack Query `useMutation`), and a result view. Keep it self-contained and typed. Complete implementation:

```tsx
// src/pages/SquadPicker.tsx
// Dev-only squad picker. Route is DEV+VITE_SQUAD_PICKER gated in App.tsx.
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  buildSquad, type SquadBuildParams, type SquadBuildResult, type SquadPlayer,
} from "@/lib/squadPickerApi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";

const POS_ORDER: SquadPlayer["pos"][] = ["GKP", "DEF", "MID", "FWD"];

const DEFAULTS: SquadBuildParams = {
  horizon_gws: 5, budget_m: 100, objective: "wildcard", projection_basis: "ppg",
  blend_weight: 0.5, minutes_prior_k: 500, include_flagged: false,
  min_chance_of_playing: 0, max_per_team: 3, min_fwd_minutes: 0, formation: "auto",
};

export default function SquadPicker() {
  const [params, setParams] = useState<SquadBuildParams>(DEFAULTS);
  const mutation = useMutation<SquadBuildResult, Error, SquadBuildParams>({
    mutationFn: buildSquad,
  });
  const res = mutation.data;

  const set = <K extends keyof SquadBuildParams>(k: K, v: SquadBuildParams[K]) =>
    setParams((p) => ({ ...p, [k]: v }));

  const xiIds = new Set((res?.starting_xi ?? []).map((p) => p.player_id));

  return (
    <div className="mx-auto max-w-6xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Squad Picker <span className="text-xs text-muted-foreground">(dev)</span></h1>
      </div>

      <Card className="p-4 grid grid-cols-2 md:grid-cols-4 gap-3">
        <Field label="Horizon (GWs)">
          <Input type="number" min={1} max={8} value={params.horizon_gws}
            onChange={(e) => set("horizon_gws", Number(e.target.value))} />
        </Field>
        <Field label="Budget (£m)">
          <Input type="number" step={0.1} value={params.budget_m}
            onChange={(e) => set("budget_m", Number(e.target.value))} />
        </Field>
        <Field label="Objective">
          <select className="w-full rounded-md border bg-background p-2 text-sm" value={params.objective}
            onChange={(e) => set("objective", e.target.value as SquadBuildParams["objective"])}>
            <option value="wildcard">wildcard</option>
            <option value="free_hit">free_hit</option>
            <option value="plain">plain</option>
          </select>
        </Field>
        <Field label="Projection basis">
          <select className="w-full rounded-md border bg-background p-2 text-sm" value={params.projection_basis}
            onChange={(e) => set("projection_basis", e.target.value as SquadBuildParams["projection_basis"])}>
            <option value="ppg">ppg</option>
            <option value="xg">xg</option>
            <option value="blend">blend</option>
          </select>
        </Field>
        <Field label="Blend weight (xg share)">
          <Input type="number" step={0.05} min={0} max={1} value={params.blend_weight}
            onChange={(e) => set("blend_weight", Number(e.target.value))} />
        </Field>
        <Field label="Minutes prior K">
          <Input type="number" value={params.minutes_prior_k}
            onChange={(e) => set("minutes_prior_k", Number(e.target.value))} />
        </Field>
        <Field label="Max per team">
          <Input type="number" min={1} max={3} value={params.max_per_team}
            onChange={(e) => set("max_per_team", Number(e.target.value))} />
        </Field>
        <Field label="Min FWD minutes">
          <Input type="number" value={params.min_fwd_minutes}
            onChange={(e) => set("min_fwd_minutes", Number(e.target.value))} />
        </Field>
        <Field label="Min chance of playing %">
          <Input type="number" min={0} max={100} value={params.min_chance_of_playing}
            onChange={(e) => set("min_chance_of_playing", Number(e.target.value))} />
        </Field>
        <Field label="Formation">
          <Input value={params.formation} placeholder="auto or 3-4-3"
            onChange={(e) => set("formation", e.target.value)} />
        </Field>
        <Field label="Include flagged (injured)">
          <input type="checkbox" checked={!!params.include_flagged}
            onChange={(e) => set("include_flagged", e.target.checked)} />
        </Field>
        <div className="flex items-end">
          <Button className="w-full" disabled={mutation.isPending}
            onClick={() => mutation.mutate(params)}>
            {mutation.isPending ? "Building…" : "Build squad"}
          </Button>
        </div>
      </Card>

      {mutation.isError && (
        <Card className="p-4 border-destructive">
          <p className="text-sm text-destructive">{mutation.error.message}</p>
          <p className="text-xs text-muted-foreground mt-1">
            Ensure the backend runs with <code>SQUAD_PICKER_MODE=1</code> and
            <code> VITE_FPL_API_BASE_URL</code> points at it.
          </p>
        </Card>
      )}

      {!res && !mutation.isPending && !mutation.isError && (
        <Card className="p-4 text-sm text-muted-foreground">
          Set params and press <b>Build squad</b>. Requires the backend running with
          <code> SQUAD_PICKER_MODE=1</code> and <code>VITE_FPL_API_BASE_URL</code> set.
        </Card>
      )}

      {res && res.ok && (
        <>
          <Card className="p-4 flex flex-wrap gap-4 text-sm">
            <span>Cost <b>£{res.squad_cost_m?.toFixed(1)}m</b></span>
            <span>Bank <b>£{res.remaining_budget_m?.toFixed(1)}m</b></span>
            <span>Formation <b>{res.formation ? res.formation.join("-") : "?"}</b></span>
            <span>Basis <b>{res.projection_basis}</b></span>
            {res.projected_points && (
              <span>Projected GW{res.gw_start}-{(res.gw_start ?? 1) + (res.horizon_gws ?? 1) - 1}
                {" "}<b>{res.projected_points.horizon_total.toFixed(1)} pts</b></span>
            )}
          </Card>

          {res.projected_points && (
            <Card className="p-4">
              <div className="text-xs text-muted-foreground mb-2">
                Projected points per GW (XI + captain doubled) — directional cold-start estimate; do not compare totals across bases.
              </div>
              <div className="flex gap-3 flex-wrap">
                {res.projected_points.per_gw.map((g) => (
                  <div key={g.gw} className="text-center">
                    <div className="text-xs text-muted-foreground">GW{g.gw}</div>
                    <div className="font-semibold">{g.total.toFixed(1)}</div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card className="p-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr><th className="p-2"></th><th className="p-2">Player</th><th>Pos</th><th>Team</th>
                  <th className="text-right">£m</th><th className="text-right">ppg</th>
                  <th className="text-right">5GW xPts</th><th>Role</th></tr>
              </thead>
              <tbody>
                {POS_ORDER.flatMap((pos) =>
                  res.squad.filter((p) => p.pos === pos)
                    .sort((a, b) => (b.xpts_horizon ?? 0) - (a.xpts_horizon ?? 0))
                    .map((p) => {
                      const cap = p.player_id === res.captain_player_id;
                      const vice = p.player_id === res.vice_player_id;
                      return (
                        <tr key={p.player_id} className="border-t">
                          <td className="p-2 w-8 font-bold">{cap ? "C" : vice ? "V" : ""}</td>
                          <td className="p-2">{p.web_name}</td><td>{p.pos}</td><td>{p.team_short}</td>
                          <td className="text-right">{p.price_m?.toFixed(1)}</td>
                          <td className="text-right">{p.points_per_game?.toFixed(1) ?? "-"}</td>
                          <td className="text-right">{p.xpts_horizon?.toFixed(1) ?? "-"}</td>
                          <td>{xiIds.has(p.player_id) ? "XI" : "bench"}</td>
                        </tr>
                      );
                    }),
                )}
              </tbody>
            </table>
          </Card>

          {res.notes?.length > 0 && (
            <Card className="p-4">
              <div className="text-xs font-semibold mb-1">Notes</div>
              <ul className="text-xs text-muted-foreground list-disc pl-4 space-y-0.5">
                {res.notes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </Card>
          )}
        </>
      )}

      {res && !res.ok && (
        <Card className="p-4 border-destructive">
          <p className="text-sm text-destructive">Build failed: {res.reason}</p>
        </Card>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      {children}
    </div>
  );
}
```

Note: check `src/components/ui/` for the actual exports (button, input, label, card). If `Card`/`Input`/`Label`/`Button` import paths differ, adjust to match the repo's shadcn setup. Do NOT invent components that don't exist — use plain HTML with Tailwind classes if a primitive is missing.

- [ ] **Step 2: Typecheck + build**

Run: `npx tsc -p tsconfig.app.json --noEmit`
Expected: no errors in `SquadPicker.tsx` (it's not routed yet, but must type-check).

- [ ] **Step 3: Commit**

```bash
git add src/pages/SquadPicker.tsx
git commit -m "feat: squad picker page (params panel + result table + projected points)"
```

---

### Task F3: Gated route + env doc + build verification

**Files:**
- Modify: `src/App.tsx`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `SquadPicker` page (lazy), the existing App routing.

- [ ] **Step 1: Add the gated route (mirror /replay exactly)**

In `src/App.tsx`, next to the `Replay` lazy import (around line 24), add:
```tsx
const SquadPicker = /* @__PURE__ */ lazy(() => import("./pages/SquadPicker"));
```
And next to the gated `/replay` route (around line 56), add:
```tsx
{import.meta.env.DEV && import.meta.env.VITE_SQUAD_PICKER === "1" && (
  <Route path="/squad" element={<Suspense fallback={null}><SquadPicker /></Suspense>} />
)}
```
(Use the SAME `import.meta.env.DEV && import.meta.env.VITE_SQUAD_PICKER === "1"` build-time-static gate as `/replay` so production tree-shakes it. Do not wrap in `ProtectedRoute` — it's a local dev tool.)

- [ ] **Step 2: Document the flag**

In `.env.example`, under the replay flags block, add:
```
# Squad picker (personal, dev-only feature — never set in production)
# VITE_SQUAD_PICKER=1
# Requires the backend running with SQUAD_PICKER_MODE=1 and:
# VITE_FPL_API_BASE_URL=http://localhost:8009
```

- [ ] **Step 3: Verify typecheck + dev/prod builds**

Run: `npx tsc -p tsconfig.app.json --noEmit` → no errors.
Run: `npm run build` → succeeds.
Verify prod isolation: `grep -r "SquadPicker\|squad-picker" dist/ | head` should return nothing referencing the page chunk (the DEV-static gate drops it). If the build inlines the string harmlessly (as with replay's entry-id), note it; the requirement is the ROUTE and page CHUNK are absent.

- [ ] **Step 4: Commit**

```bash
git add src/App.tsx .env.example
git commit -m "feat: DEV+VITE_SQUAD_PICKER-gated /squad route + env docs"
```

---

## Self-Review

- **Client + types** → F1 (with vitest for URL + error path). ✓
- **Page (params for wired knobs only, result table, projected points, notes, error/empty states)** → F2. ✓
- **Gated route + env** → F3 (mirrors /replay build-time-static gate). ✓
- **Verification** → vitest (F1) + tsc/build + prod-isolation grep (F3), since no jsdom. ✓
- **Wired-params-only constraint** → F2 controls list excludes fdr_strength/team_nudges/league_id. ✓
- `PitchVisualization` reuse is intentionally left as an optional stretch (the table is the reliable primary view) — not required for v1.

## Local run instructions (for the user, after build)

1. Backend: `SQUAD_PICKER_MODE=1 python -m uvicorn api.main:app --port 8009` (in the FPL repo, venv active).
2. Frontend `.env`: `VITE_SQUAD_PICKER=1` and `VITE_FPL_API_BASE_URL=http://localhost:8009`.
3. `npm run dev`, open `/squad`, tune params, press Build.
