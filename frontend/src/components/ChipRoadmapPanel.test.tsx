// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { ChipRoadmapPanel } from "./ChipRoadmapPanel";
import type { ChipCalendarRow, ChipPlanResponse } from "@/lib/fplAssistantApi";

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

  it("renders a distinct error state when the request failed", () => {
    render(<ChipRoadmapPanel plan={null} isLoading={false} isError={true} />);
    expect(screen.getByText(/couldn't load the chip plan/i)).toBeTruthy();
    expect(screen.queryByText(/set your entry id/i)).toBeNull();
  });

  it("toggles recommendation details on click and hides reason on second click", () => {
    render(<ChipRoadmapPanel plan={basePlan} isLoading={false} />);
    const wildcardButton = screen.getByText("Wildcard").closest("button");
    expect(wildcardButton).toBeTruthy();

    // Initially, reason should not be visible
    expect(screen.queryByText("Large gap to optimal — squad needs reset")).toBeNull();

    // Click to expand
    fireEvent.click(wildcardButton!);
    expect(screen.getByText("Large gap to optimal — squad needs reset")).toBeTruthy();

    // Click to collapse
    fireEvent.click(wildcardButton!);
    expect(screen.queryByText("Large gap to optimal — squad needs reset")).toBeNull();
  });

  it("renders EV curve bars with correct title attributes for expanded recommendation", () => {
    render(<ChipRoadmapPanel plan={basePlan} isLoading={false} />);
    const wildcardButton = screen.getByText("Wildcard").closest("button");

    // Click to expand
    fireEvent.click(wildcardButton!);

    // Check for EV curve container
    const evCurveContainer = screen.getByLabelText("EV by gameweek");
    expect(evCurveContainer).toBeTruthy();

    // Check for bars with correct title attributes
    const gw5Bar = screen.getByTitle("GW5: +4.2 xPts");
    const gw8Bar = screen.getByTitle("GW8: +9.1 xPts");
    expect(gw5Bar).toBeTruthy();
    expect(gw8Bar).toBeTruthy();
  });
});

describe("chip outlook", () => {
  const outlookPlan: ChipPlanResponse = {
    ...basePlan,
    recommendations: [],
    nudge: null,
    outlook: [
      {
        chip: "triple_captain",
        event_id: 8,
        ev_gain: 11.2,
        bar: 15,
        status: "hold",
        reasons: ["Captain projected xPts: 11.2"],
      },
      {
        chip: "free_hit",
        event_id: null,
        ev_gain: null,
        bar: 8,
        status: "hold",
        reasons: ["No blank-heavy or tough-fixture week in the model horizon"],
      },
    ],
  };

  it("renders hold outlook rows with best window, EV and bar", () => {
    render(<ChipRoadmapPanel plan={outlookPlan} isLoading={false} />);
    expect(screen.getByText("Triple Captain")).toBeTruthy();
    expect(screen.getByText("GW8")).toBeTruthy();
    expect(screen.getByText(/\+11\.2 vs bar 15/)).toBeTruthy();
  });

  it("renders a no-window outlook row without a GW", () => {
    render(<ChipRoadmapPanel plan={outlookPlan} isLoading={false} />);
    fireEvent.click(screen.getByText("Free Hit"));
    expect(
      screen.getByText("No blank-heavy or tough-fixture week in the model horizon")
    ).toBeTruthy();
  });

  it("falls back to the legacy holding list when outlook is absent", () => {
    render(
      <ChipRoadmapPanel plan={{ ...basePlan, recommendations: [] }} isLoading={false} />
    );
    expect(screen.getByText("Wildcard")).toBeTruthy();
    expect(screen.getAllByText(/expires GW19/).length).toBeGreaterThan(0);
  });
});

describe("chip distributions", () => {
  const withDistributions: ChipPlanResponse = {
    ...basePlan,
    // bench_boost is "used" in basePlan — make it available so the only
    // "Bench Boost" on screen is the recommendation row under test.
    chips_remaining: basePlan.chips_remaining.map((c) =>
      c.name === "bench_boost" ? { ...c, available: true } : c
    ),
    recommendations: [
      {
        chip: "triple_captain",
        event_id: 8,
        ev_gain: 18.4,
        provisional: false,
        reasons: ["Captain projected xPts: 18.4"],
        ev_curve: [{ gw: 8, ev: 18.4, p_beats_bar: 0.61 }],
        distribution: {
          mean: 16.6,
          modal: 9,
          p_return: 0.72,
          p_haul: 0.44,
          p_blank: 0.18,
          p80_low: 2,
          p80_high: 28,
          bar: 15,
          p_beats_bar: 0.61,
        },
      },
      {
        chip: "bench_boost",
        event_id: 9,
        ev_gain: 21.8,
        provisional: false,
        reasons: ["Bench most likely 19 pts (80% band 11–29)"],
        ev_curve: [{ gw: 9, ev: 21.8, p_beats_bar: 0.83 }],
        // F3: a bench-4 sum carries no per-player return/haul/blank rates
        distribution: {
          mean: 19.8,
          modal: 19,
          p80_low: 11,
          p80_high: 29,
          bar: 10,
          p_beats_bar: 0.83,
        },
      },
    ],
  };

  it("shows per-player return/haul/blank for TC but not for bench boost", () => {
    render(<ChipRoadmapPanel plan={withDistributions} isLoading={false} />);

    fireEvent.click(screen.getByText("Triple Captain").closest("button")!);
    expect(screen.getByText(/captain returns \(6\+\)/)).toBeTruthy();
    expect(screen.getByText(/haul \(10\+\)/)).toBeTruthy();
    expect(screen.getByText(/blank/)).toBeTruthy();

    fireEvent.click(screen.getByText("Bench Boost").closest("button")!);
    expect(screen.queryByText(/bench returns \(6\+\)/)).toBeNull();
    // the bench line still carries the shape that does mean something
    // (the backend reason line says the same thing, hence getAllByText)
    expect(screen.getAllByText(/most likely 19/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/83%/).length).toBeGreaterThan(0);
  });

  it("marks an 80% band that runs off the axis as open-ended", () => {
    const open: ChipPlanResponse = {
      ...withDistributions,
      recommendations: [
        {
          ...withDistributions.recommendations[1],
          distribution: { ...withDistributions.recommendations[1].distribution!, p80_open: true },
        },
      ],
    };
    render(<ChipRoadmapPanel plan={open} isLoading={false} />);
    fireEvent.click(screen.getByText("Bench Boost").closest("button")!);
    // the band and its open-ended marker are separate text nodes
    const band = screen
      .getAllByText(/80% band/)
      .map((el) => el.textContent?.replace(/\s+/g, " ").trim());
    expect(band.some((t) => t?.includes("80% band 11–29+"))).toBe(true);
  });

  it("gives each EV curve bar a single title so the GW label does not duplicate it", () => {
    render(<ChipRoadmapPanel plan={withDistributions} isLoading={false} />);
    fireEvent.click(screen.getByText("Triple Captain").closest("button")!);
    expect(
      screen.getAllByTitle(/^GW8: \+18\.4 xPts/).length
    ).toBe(1);
  });

  it("truncates the outlook chip label so the row cannot outgrow a narrow card", () => {
    const plan: ChipPlanResponse = {
      ...basePlan,
      recommendations: [],
      outlook: [
        {
          chip: "triple_captain",
          event_id: 8,
          ev_gain: 11.2,
          bar: 15,
          status: "hold",
          reasons: ["Captain projected xPts: 11.2"],
        },
      ],
    };
    render(<ChipRoadmapPanel plan={plan} isLoading={false} />);
    expect(screen.getByText("Triple Captain").className).toContain("truncate");
  });
});

describe("fixture calendar", () => {
  const baseRow: ChipCalendarRow = {
    gw: 8,
    deadline_utc: null,
    in_model_zone: true,
    post_break: false,
    break_gap_days: null,
    european: {},
    squad_european: [],
    n_teams_playing: null,
    dgw_teams: [],
    blank_teams: [],
    is_blank_heavy: false,
    has_dgw: false,
    cup_clash: null,
  };

  it("renders the squad-in-Europe tag as an exact count, not a competition list", () => {
    const squadEuropean = Array.from({ length: 6 }, (_, i) => ({
      name: `Player ${i + 1}`,
      team: "Team",
      competition: "ucl" as const,
      when: "before" as const,
    }));
    const plan: ChipPlanResponse = {
      ...basePlan,
      calendar: [
        {
          ...baseRow,
          european: { ucl: ["Team"] },
          squad_european: squadEuropean,
        },
      ],
    };
    render(<ChipRoadmapPanel plan={plan} isLoading={false} />);
    expect(screen.getByText("6 in Europe")).toBeTruthy();
  });

  it("does not count a Europe-only beyond-horizon week as notable, but does count a DGW week", () => {
    const europeOnlyRow: ChipCalendarRow = {
      ...baseRow,
      gw: 20,
      in_model_zone: false,
      european: { ucl: ["Team"] },
      squad_european: [{ name: "Player 1", team: "Team", competition: "ucl", when: "before" }],
    };
    const dgwRow: ChipCalendarRow = {
      ...baseRow,
      gw: 21,
      in_model_zone: false,
      has_dgw: true,
      dgw_teams: ["Team"],
    };
    const plan: ChipPlanResponse = {
      ...basePlan,
      calendar: [europeOnlyRow, dgwRow],
    };
    render(<ChipRoadmapPanel plan={plan} isLoading={false} />);
    expect(screen.getByText(/Beyond the model horizon · 1 notable week/)).toBeTruthy();
  });
});

describe("chip guidance", () => {
  const guidancePlan: ChipPlanResponse = {
    ...basePlan,
    recommendations: [
      {
        chip: "wildcard",
        event_id: 8,
        ev_gain: 9.1,
        provisional: false,
        reasons: ["Large gap to optimal — squad needs reset"],
        ev_curve: [{ gw: 8, ev: 9.1 }],
        guidance: "Play it in GW8: +9.1 pts over the bar of 5.0.",
      },
    ],
    nudge: null,
    outlook: [
      {
        chip: "triple_captain",
        event_id: 8,
        ev_gain: 11.2,
        bar: 15,
        status: "hold",
        reasons: ["Captain projected xPts: 11.2"],
        guidance:
          "Hold for now. GW8 is the best week so far (+11.2 pts). Best use: a double gameweek for your captain, usually GW24–26 or GW34–37.",
      },
      {
        chip: "free_hit",
        event_id: null,
        ev_gain: null,
        bar: 8,
        status: "hold",
        reasons: ["No blank-heavy or tough-fixture week in the model horizon"],
        guidance:
          "Hold. Nothing in the next 8 GWs beats keeping it. Best use: the blank gameweek, usually GW29–33 (FA Cup rounds).",
      },
    ],
  };

  it("shows guidance as the first line on a hold outlook row, above the collapsed model detail", () => {
    render(<ChipRoadmapPanel plan={guidancePlan} isLoading={false} />);
    fireEvent.click(screen.getByText("Triple Captain").closest("button")!);
    expect(
      screen.getByText(
        "Hold for now. GW8 is the best week so far (+11.2 pts). Best use: a double gameweek for your captain, usually GW24–26 or GW34–37."
      )
    ).toBeTruthy();
    // the engine reason now lives behind a "model detail" disclosure
    expect(screen.getByText("model detail")).toBeTruthy();
    const detail = screen.getByText("model detail").closest("details");
    expect(detail).toBeTruthy();
    expect(detail?.querySelector("summary")?.textContent).toBe("model detail");
    expect(screen.getByText("Captain projected xPts: 11.2")).toBeTruthy();
  });

  it("shows guidance on a no-window hold outlook row too", () => {
    render(<ChipRoadmapPanel plan={guidancePlan} isLoading={false} />);
    fireEvent.click(screen.getByText("Free Hit").closest("button")!);
    expect(
      screen.getByText(
        "Hold. Nothing in the next 8 GWs beats keeping it. Best use: the blank gameweek, usually GW29–33 (FA Cup rounds)."
      )
    ).toBeTruthy();
  });

  it("shows guidance above the reasons on a recommendation row", () => {
    render(<ChipRoadmapPanel plan={guidancePlan} isLoading={false} />);
    fireEvent.click(screen.getByText("Wildcard").closest("button")!);
    expect(screen.getByText("Play it in GW8: +9.1 pts over the bar of 5.0.")).toBeTruthy();
    expect(screen.getByText("Large gap to optimal — squad needs reset")).toBeTruthy();
  });

  it("renders the old layout — no guidance line, no model-detail collapse — when guidance is absent", () => {
    const noGuidance: ChipPlanResponse = {
      ...basePlan,
      recommendations: [],
      nudge: null,
      outlook: [
        {
          chip: "triple_captain",
          event_id: 8,
          ev_gain: 11.2,
          bar: 15,
          status: "hold",
          reasons: ["Captain projected xPts: 11.2"],
        },
      ],
    };
    render(<ChipRoadmapPanel plan={noGuidance} isLoading={false} />);
    fireEvent.click(screen.getByText("Triple Captain").closest("button")!);
    expect(screen.getByText("Captain projected xPts: 11.2")).toBeTruthy();
    expect(screen.queryByText("model detail")).toBeNull();
  });

  it("renders the old recommendation layout when guidance is absent", () => {
    render(<ChipRoadmapPanel plan={basePlan} isLoading={false} />);
    fireEvent.click(screen.getByText("Wildcard").closest("button")!);
    expect(screen.getByText("Large gap to optimal — squad needs reset")).toBeTruthy();
  });
});
