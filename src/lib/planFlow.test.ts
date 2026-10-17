import { describe, expect, it } from "vitest";
import {
  autoSubPreview,
  chipOptions,
  chipPick,
  wildcardDraftShown,
  wildcardToggle,
  firstUnfinishedStep,
  footerFor,
  reviewSummary,
  reviewWarnings,
  stepCopy,
  transferOptions,
} from "./planFlow";
import { buildPlayerLookup, makeMoves, resolvePlan, seedPlan, swapPlayers, type GwPlan } from "./gwPlan";
import type { WeekDecision } from "./weekDecisions";
import {
  SAMPLE_SQUAD,
  SAMPLE_TEAM_RECOMMENDATION,
  type ChipPlanResponse,
  type FplTeamRecommendation,
  type FplTransferVerdictDetail,
} from "./fplAssistantApi";

const seed = seedPlan(SAMPLE_SQUAD); // cap B.Fernandes 449, vice Enzo 237; bench Dúbravka, Thiago, Calvert-Lewin, Estève
const lookup = buildPlayerLookup(SAMPLE_SQUAD, undefined);
const dec = (over: Partial<Record<"transfers" | "captain" | "bench" | "chip", Partial<WeekDecision>>> = {}): WeekDecision[] =>
  (["transfers", "captain", "bench", "chip"] as const).map((key) => ({ key, label: key, value: "", done: false, ...over[key] }));

const detail = (over: Partial<FplTransferVerdictDetail> = {}): FplTransferVerdictDetail => ({
  action: "spend",
  horizon: { start_gw: 29, end_gw: 31, n: 3 },
  ft_before: 1,
  ft_after: 0,
  threshold: 2,
  moves: [{ sell: { id: 430, name: "Haaland", team: "MCI", price: 14, next_fixture: "LIV (A)" }, buy: { id: 9, name: "Solanke", team: "BOU", price: 7, next_fixture: "WHU (H)" }, this_gw_gain: 0.8, horizon_gain: 2.4 }],
  this_gw_gain: 0.8,
  horizon_gain: 2.4,
  hit_cost: 0,
  plan_net: 2.4,
  roll_alternative: { net: 1.1, gw: 30, moves: [] },
  next_move: null,
  runner_ups: [
    { sell: { id: 21, name: "Rice", team: "ARS", price: 6 }, buy: { id: 50, name: "Rogers", team: "AVL", price: 5.5 }, this_gw_gain: 0.2, horizon_gain: 1.1, clears_bar: false },
    { sell: { id: 5, name: "Gabriel", team: "ARS", price: 6 }, buy: { id: 51, name: "Guéhi", team: "CRY", price: 4.5 }, this_gw_gain: 0.9, horizon_gain: 2.9, clears_bar: true },
  ],
  ...over,
});
const rec = (d?: FplTransferVerdictDetail): FplTeamRecommendation => ({
  ...SAMPLE_TEAM_RECOMMENDATION,
  transfer_plan_horizon: d ? { verdict: d.action, verdict_detail: d } : undefined,
});
const chipPlan = (over: Partial<ChipPlanResponse> = {}): ChipPlanResponse => ({
  entry_id: 1,
  current_gw: 29,
  chips_remaining: [
    { name: "bench_boost", available: true, half: 2, expires_gw: 38 },
    { name: "free_hit", available: true, half: 2, expires_gw: 38 },
    { name: "triple_captain", available: false, half: 2, expires_gw: 38 },
    { name: "wildcard", available: true, half: 2, expires_gw: 38 },
  ],
  horizon_model_gws: 6,
  recommendations: [
    { chip: "bench_boost", event_id: 32, ev_gain: 15.1, provisional: false, reasons: [], ev_curve: [] },
    { chip: "free_hit", event_id: 33, ev_gain: 9.4, provisional: false, reasons: [], ev_curve: [] },
  ],
  outlook: [{ chip: "free_hit", event_id: 33, ev_gain: 9.4, bar: 6, status: "hold", reasons: [], guidance: "Hold it for the GW33 blank." }],
  nudge: null,
  transfer_context: { planned_transfers_net_gain: 0, wc_alternative_gw: null },
  ...over,
});

describe("firstUnfinishedStep", () => {
  it("is the first undecided decision, or the review when all four are done", () => {
    expect(firstUnfinishedStep(dec())).toBe("transfers");
    expect(firstUnfinishedStep(dec({ transfers: { done: true }, captain: { done: true } }))).toBe("bench");
    expect(firstUnfinishedStep(dec({ transfers: { done: true }, captain: { done: true }, bench: { done: true }, chip: { done: true } }))).toBe("confirm");
  });
});

describe("footerFor", () => {
  it("squad: a short label for the desktop GW bar, where the long one wraps the bar", () => {
    const all = dec({ transfers: { done: true }, captain: { done: true }, bench: { done: true }, chip: { done: true } });
    expect(footerFor({ step: "squad", plan: seed, decisions: dec(), warnings: [], gw: 29 }).short).toBe("Start GW29 plan");
    expect(footerFor({ step: "squad", plan: seed, decisions: dec({ chip: { done: true } }), warnings: [], gw: 29 }).short).toBe("Continue · 3 left");
    expect(footerFor({ step: "squad", plan: seed, decisions: all, warnings: [], gw: 29 }).short).toBe("Review plan");
    expect(footerFor({ step: "squad", plan: { ...seed, locked: true }, decisions: all, warnings: [], gw: 29 }).short).toBe("Review plan");
    expect(footerFor({ step: "confirm", plan: seed, decisions: all, warnings: [], gw: 29 }).short).toBe("Save GW29 plan");
  });
  it("squad: Start / Continue with what's left, Review when all four are made, no Back", () => {
    expect(footerFor({ step: "squad", plan: seed, decisions: dec(), warnings: [], gw: 29 })).toMatchObject({ label: "Start GW29 plan · 4 decisions", hasBack: false, disabled: false });
    expect(footerFor({ step: "squad", plan: seed, decisions: dec({ chip: { done: true } }), warnings: [], gw: 29 }).label).toBe("Continue plan · 3 left");
    const all = dec({ transfers: { done: true }, captain: { done: true }, bench: { done: true }, chip: { done: true } });
    expect(footerFor({ step: "squad", plan: seed, decisions: all, warnings: [], gw: 29 }).label).toBe("Review and save plan");
    expect(footerFor({ step: "squad", plan: { ...seed, locked: true }, decisions: all, warnings: [], gw: 29 }).label).toBe("Plan saved · review");
  });
  it("names the next step and blocks Transfers/Chip until a choice is made", () => {
    expect(footerFor({ step: "transfers", plan: seed, decisions: dec(), warnings: [], gw: 29 })).toMatchObject({ label: "Next: Captain", disabled: true, hint: "Pick an option to continue", hasBack: true });
    expect(footerFor({ step: "transfers", plan: { ...seed, transfer: "roll" }, decisions: dec(), warnings: [], gw: 29 }).disabled).toBe(false);
    expect(footerFor({ step: "chip", plan: seed, decisions: dec(), warnings: [], gw: 29 })).toMatchObject({ label: "Next: Review", disabled: true });
    expect(footerFor({ step: "chip", plan: { ...seed, chip: "none" }, decisions: dec(), warnings: [], gw: 29 }).disabled).toBe(false);
    expect(footerFor({ step: "captain", plan: seed, decisions: dec(), warnings: [], gw: 29 })).toMatchObject({ label: "Next: Bench", disabled: false });
  });
  it("review: Save (accent), blocked by a warning, Done · back to squad once locked", () => {
    const decided = { ...seed, transfer: "roll" as const, chip: "none" as const };
    expect(footerFor({ step: "confirm", plan: decided, decisions: dec(), warnings: [], gw: 29 })).toMatchObject({ label: "Save GW29 plan", variant: "accent", disabled: false });
    expect(footerFor({ step: "confirm", plan: decided, decisions: dec(), warnings: [{ text: "x", fixStep: "captain" }], gw: 29 })).toMatchObject({ disabled: true, hint: "Fix the warning to save" });
    // Once saved there is nothing left to do here: the button takes you home.
    expect(footerFor({ step: "confirm", plan: { ...decided, locked: true }, decisions: dec(), warnings: [], gw: 29 })).toMatchObject({ label: "Done · back to squad", disabled: false, hint: "Plan saved" });
  });
  it("review: Save waits for the transfers and chip choices (step chips can skip those steps)", () => {
    expect(footerFor({ step: "confirm", plan: seed, decisions: dec(), warnings: [], gw: 29 })).toMatchObject({ disabled: true, hint: "Decide transfers and chip first" });
    expect(footerFor({ step: "confirm", plan: { ...seed, chip: "none" }, decisions: dec(), warnings: [], gw: 29 })).toMatchObject({ disabled: true, hint: "Decide transfers first" });
    expect(footerFor({ step: "confirm", plan: { ...seed, transfer: "make" }, decisions: dec(), warnings: [], gw: 29 })).toMatchObject({ disabled: true, hint: "Decide your chip first" });
  });
  it("squad with no plan yet is disabled", () => {
    expect(footerFor({ step: "squad", plan: null, decisions: dec(), warnings: [], gw: 29 }).disabled).toBe(true);
  });
});

describe("stepCopy", () => {
  it("writes the eyebrow, title and sub for each step", () => {
    expect(stepCopy("squad", 29, { locked: false, desktop: true })).toMatchObject({ eyebrow: "Overview", title: "Your GW29 squad" });
    expect(stepCopy("squad", 29, { locked: false, desktop: false }).sub).toContain("below");
    expect(stepCopy("transfers", 29, { locked: false, desktop: true })).toMatchObject({ eyebrow: "Step 1 of 4 · Transfers", title: "Make the move or roll?" });
    expect(stepCopy("bench", 29, { locked: false, desktop: true }).eyebrow).toBe("Step 3 of 4 · Bench");
    expect(stepCopy("confirm", 29, { locked: false, desktop: true }).title).toBe("Review and save your plan");
    expect(stepCopy("confirm", 29, { locked: true, desktop: true }).title).toBe("You're set for GW29.");
  });
});

describe("reviewWarnings / reviewSummary", () => {
  it("warns when the captain sits on the bench and points at the captain step", () => {
    expect(reviewWarnings(resolvePlan(seed, []))).toEqual([]);
    const benched = swapPlayers(seed, 136, 449);
    expect(reviewWarnings(resolvePlan(benched, []))).toEqual([{ text: "Your captain is on the bench. Pick a starter.", fixStep: "captain" }]);
  });

  it("summarises the four decisions with Changed badges against the seed", () => {
    const r = rec(detail());
    const lk = buildPlayerLookup(SAMPLE_SQUAD, r);
    const edited: GwPlan = { ...seed, transfer: "make", cap: 237, vice: 449, chip: "bench_boost" };
    const rows = reviewSummary(edited, seed, makeMoves(r), lk, dec({ transfers: { value: "Haaland → Solanke · +2.4" } }));
    expect(rows.map((x) => [x.key, x.changed])).toEqual([["transfers", true], ["captain", true], ["bench", false], ["chip", true]]);
    expect(rows[0].value).toBe("Haaland → Solanke · +2.4");
    expect(rows[1].value).toBe("Enzo (C) · B.Fernandes (VC)");
    expect(rows[2].value).toBe("Thiago, Calvert-Lewin, Estève · Dúbravka (GK)");
    expect(rows[3].value).toBe("Bench Boost");
    const fresh = reviewSummary(seed, seed, [], lk, dec());
    expect(fresh.every((x) => !x.changed)).toBe(true);
    expect(fresh[3].value).toBe("Not decided");
    expect(reviewSummary({ ...seed, chip: "none" }, seed, [], lk, dec())[3]).toMatchObject({ value: "Save chips", changed: false });
  });
});

describe("transferOptions", () => {
  it("spend verdict: Make is the ZN Pick with the move, gain and horizon meta; Roll shows the FT progression", () => {
    const o = transferOptions(rec(detail()));
    expect(o.make).toMatchObject({ zn: true, gain: 2.4, meta: "xPts over GW29–31 · free transfer", moves: [expect.objectContaining({ buy: expect.objectContaining({ name: "Solanke" }) })] });
    expect(o.make?.why).toBe("Haaland has LIV (A); Solanke gets WHU (H).");
    expect(o.roll).toMatchObject({ zn: false, gain: 0, meta: "this week · 2 FTs in GW30" });
    expect(o.roll.why).toContain("Rolling nets +1.1");
    expect(o.alsoConsidered).toEqual([{ sell: "Rice", buy: "Rogers", net: 1.1, hit: false, bar: 2 }]);
  });
  it("hit moves show the cost in the meta and net it from the gain", () => {
    const o = transferOptions(rec(detail({ ft_before: 0, ft_after: 0, hit_cost: 4, horizon_gain: 6.5 })));
    expect(o.make).toMatchObject({ gain: 2.5, meta: "xPts over GW29–31 · −4 hit" });
  });
  it("roll verdict: Roll is the ZN Pick; Make is the rejected alternative when there is one", () => {
    const alt = detail({ action: "roll", moves: [], ft_after: 2, plan_net: 3.0, roll_alternative: { net: 1.9, gw: 29, moves: detail().moves } });
    const o = transferOptions(rec(alt));
    expect(o.roll).toMatchObject({ zn: true, meta: "this week · 2 FTs in GW30" });
    expect(o.make).toMatchObject({ zn: false, gain: 2.4 });
    const bare = transferOptions(rec(detail({ action: "roll", moves: [], roll_alternative: null })));
    expect(bare.make).toBeNull();
  });
  it("is empty without a verdict", () => {
    expect(transferOptions(undefined)).toMatchObject({ make: null, alsoConsidered: [] });
    expect(transferOptions(undefined).roll.meta).toBe("");
  });
});

describe("chipOptions", () => {
  const r = resolvePlan(seed, []);
  it("lists Save, Bench Boost, Free Hit and Triple Captain with this week's gain and the best week", () => {
    const opts = chipOptions({ resolved: r, lookup, chipPlan: chipPlan(), gw: 29 });
    expect(opts.map((o) => o.chip)).toEqual(["none", "bench_boost", "free_hit", "triple_captain", "wildcard"]);
    const [save, bb, fh, tc] = opts;
    expect(save).toMatchObject({ zn: true, gain: 0 });
    expect(save.why).toBe("Bench Boost is worth +15.1 in GW32, the best week left for any chip.");
    // Bench xPts in the sample: Dúbravka + Thiago + Calvert-Lewin + Estève.
    expect(bb.gain).toBeCloseTo([470, 136, 691, 191].reduce((s, id) => s + lookup[id].xpts, 0), 5);
    expect(bb.why).toContain("GW32");
    expect(fh).toMatchObject({ gain: null, used: false });
    expect(fh.why).toBe("Hold it for the GW33 blank.");
    expect(tc).toMatchObject({ gain: lookup[449].xpts, used: true });
  });
  it("the nudge makes its chip the ZN Pick and Free Hit takes the engine's gain for this week", () => {
    const opts = chipOptions({
      resolved: r,
      lookup,
      chipPlan: chipPlan({ nudge: { chip: "free_hit", event_id: 29, ev_gain: 6.2 }, recommendations: [{ chip: "free_hit", event_id: 29, ev_gain: 6.2, provisional: false, reasons: [], ev_curve: [] }] }),
      gw: 29,
    });
    expect(opts[0].zn).toBe(false);
    expect(opts[2]).toMatchObject({ zn: true, gain: 6.2 });
  });
  it("without a chip plan, Save is still the pick and unknown gains are null", () => {
    const opts = chipOptions({ resolved: r, lookup, chipPlan: null, gw: 29 });
    expect(opts[0].zn).toBe(true);
    expect(opts[2].gain).toBeNull();
    expect(opts[3].used).toBe(false);
  });
  it("a benched captain makes Triple Captain unavailable this week", () => {
    const opts = chipOptions({ resolved: resolvePlan(swapPlayers(seed, 136, 449), []), lookup, chipPlan: null, gw: 29 });
    expect(opts[3].gain).toBeNull();
    expect(opts[3].why).toBe("Your captain is on the bench.");
  });
});

describe("chipOptions — wildcard", () => {
  const r = resolvePlan(seed, []);
  const wcOutlook = { chip: "wildcard" as const, event_id: 31, ev_gain: 18.4, bar: 120, status: "hold" as const, reasons: [], guidance: "Hold for now. GW31 is the best week so far (+18.4 pts)." };
  const wc = (over: Partial<ChipPlanResponse> = {}, gw = 29) =>
    chipOptions({ resolved: r, lookup, chipPlan: chipPlan({ outlook: [wcOutlook], ...over }), gw }).find((o) => o.chip === "wildcard");

  it("is offered with the engine's guidance; no gain when its best week is another GW", () => {
    expect(wc()).toMatchObject({ title: "Wildcard", zn: false, gain: null, used: false });
    expect(wc()?.why).toBe("Rebuilds all 15 for free. Hold for now. GW31 is the best week so far (+18.4 pts).");
  });
  it("takes the multi-GW uplift as its gain on its best week, labelled as such", () => {
    expect(wc({}, 31)).toMatchObject({ gain: 18.4, gainNote: "over the wildcard window" });
  });
  it("is the ZN Pick when the nudge names it", () => {
    expect(wc({ nudge: { chip: "wildcard", event_id: 29, ev_gain: 130 } })?.zn).toBe(true);
  });
  it("is disabled once played this half", () => {
    const used = chipPlan().chips_remaining.map((c) => (c.name === "wildcard" ? { ...c, available: false } : c));
    expect(wc({ chips_remaining: used })?.used).toBe(true);
  });
  it("falls back to a plain line without an outlook row or a chip plan", () => {
    expect(wc({ outlook: [] })?.why).toBe("Rebuilds all 15 for free. No wildcard week stands out yet.");
    expect(chipOptions({ resolved: r, lookup, chipPlan: null, gw: 29 }).find((o) => o.chip === "wildcard")?.why).toBe(
      "Rebuilds all 15 for free. The chip plan hasn't answered yet.",
    );
  });
  it("waits while ZN Pick is running", () => {
    expect(wc()?.disabled).toBeUndefined();
    const opts = chipOptions({ resolved: r, lookup, chipPlan: chipPlan(), gw: 29, pickPending: true });
    expect(opts.find((o) => o.chip === "wildcard")?.disabled).toBe(true);
  });
  it("is left out when the wildcard drafter isn't in the user's plan", () => {
    const opts = chipOptions({ resolved: r, lookup, chipPlan: chipPlan(), gw: 29, wildcardAllowed: false });
    expect(opts.map((o) => o.chip)).not.toContain("wildcard");
  });
});

describe("chipPick", () => {
  it("wildcard switches ZN Pick to a wildcard draft and shows the drafted squad", () => {
    expect(chipPick("wildcard", "none")).toEqual({ patch: { chip: "wildcard" }, chipStrategy: "wildcard", goTo: "squad" });
  });
  it("picking the wildcard again doesn't ask for a second draft", () => {
    expect(chipPick("wildcard", "wildcard")).toEqual({ patch: { chip: "wildcard" }, chipStrategy: null, goTo: "squad" });
  });
  it("leaving a wildcard restores the normal pick and stays on the step", () => {
    expect(chipPick("bench_boost", "wildcard")).toEqual({ patch: { chip: "bench_boost" }, chipStrategy: "none", goTo: null });
    expect(chipPick("none", "wildcard")).toEqual({ patch: { chip: "none" }, chipStrategy: "none", goTo: null });
  });
  it("any other chip only records the choice", () => {
    expect(chipPick("triple_captain", "none")).toEqual({ patch: { chip: "triple_captain" }, chipStrategy: null, goTo: null });
  });
});

describe("wildcard preview", () => {
  const wcRec = (selected: "wildcard" | "none", is_active: boolean) =>
    ({ ...SAMPLE_TEAM_RECOMMENDATION, chip_strategy: { ...SAMPLE_TEAM_RECOMMENDATION.chip_strategy, selected, is_active } }) as FplTeamRecommendation;
  it("the draft shows only when the recommendation on the pitch is an active wildcard", () => {
    expect(wildcardDraftShown({ pitchMode: "recommendation", rec: wcRec("wildcard", true) })).toBe(true);
    expect(wildcardDraftShown({ pitchMode: "squad", rec: wcRec("wildcard", true) })).toBe(false);
    expect(wildcardDraftShown({ pitchMode: "recommendation", rec: wcRec("wildcard", false) })).toBe(false);
    expect(wildcardDraftShown({ pitchMode: "recommendation", rec: wcRec("none", false) })).toBe(false);
    expect(wildcardDraftShown({ pitchMode: "recommendation", rec: undefined })).toBe(false);
  });
  it("the card starts a preview, fetches a draft the persisted strategy never ran, or goes back", () => {
    expect(wildcardToggle("none", false)).toBe("start");
    expect(wildcardToggle("wildcard", false)).toBe("fetch");
    expect(wildcardToggle("wildcard", true)).toBe("stop");
  });
});

describe("autoSubPreview", () => {
  it("names who comes on for the flagged starter, honouring the swap rules", () => {
    const flagged = buildPlayerLookup(
      { ...SAMPLE_SQUAD, starting_xi: SAMPLE_SQUAD.starting_xi.map((p) => (p.player_id === 253 ? { ...p, alerts: [{ severity: "medium", text: "75% fit" }] } : p)) },
      undefined,
    );
    // Henderson (GK) flagged → only the bench GK Dúbravka can come on.
    expect(autoSubPreview(resolvePlan(seed, []), flagged)).toBe("If Henderson (75% fit) doesn't play, Dúbravka comes on automatically. Order your bench by who you'd want first.");
    expect(autoSubPreview(resolvePlan(seed, []), lookup)).toBe("No flagged starters. Order your bench by who you'd want first.");
  });
});
