// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PitchVisualization } from "./PitchVisualization";
import { SAMPLE_TEAM_RECOMMENDATION, type FplSquad } from "@/lib/fplAssistantApi";

afterEach(cleanup);

const squad: FplSquad = {
  ...SAMPLE_TEAM_RECOMMENDATION,
  entry: { entry_id: 588004, team_name: "Aubameyangiality", manager_name: "Z N" },
};

const renderPitch = (team?: FplSquad) =>
  render(
    <MemoryRouter>
      <PitchVisualization entryId={588004} team={team} requestedGw={29} onRequestedGwChange={() => {}} gwSelectable />
    </MemoryRouter>,
  );

describe("Command Center pitch header", () => {
  it("names the team and explains the glow", () => {
    renderPitch(squad);
    expect(screen.getByRole("heading", { name: "Aubameyangiality" })).toBeTruthy();
    expect(screen.getByText("Glow = xPts this GW")).toBeTruthy();
  });

  it("draws an aura behind every starter and labels the bench strip BENCH", () => {
    renderPitch(squad);
    expect(screen.getAllByTestId("xpts-aura").length).toBeGreaterThanOrEqual(11);
    expect(screen.getByText("Bench")).toBeTruthy();
  });

  it("renders no heading without a team", () => {
    renderPitch(undefined);
    expect(screen.queryByText("Glow = xPts this GW")).toBeNull();
  });
});

describe("plan-driven pitch (v2 flow)", () => {
  const haaland = 430; // FWD starter in the sample
  const gabriel = 5; // DEF starter

  it("takes incoming players from the prop, not the payload", () => {
    render(
      <MemoryRouter>
        <PitchVisualization team={squad} requestedGw={29} onRequestedGwChange={() => {}} gwSelectable incoming={{ [haaland]: 1.5, [gabriel]: null }} />
      </MemoryRouter>,
    );
    expect(screen.getByText("IN +1.5")).toBeTruthy();
    expect(screen.getByText("IN")).toBeTruthy();
  });

  it("in swap mode, outlines valid starters, dims invalid ones, and reports taps", () => {
    const onStarterClick = vi.fn();
    render(
      <MemoryRouter>
        <PitchVisualization
          team={squad}
          requestedGw={29}
          onRequestedGwChange={() => {}}
          gwSelectable
          starterState={(id) => (id === haaland ? "valid" : "invalid")}
          onStarterClick={onStarterClick}
        />
      </MemoryRouter>,
    );
    const valid = screen.getByTestId(`starter-${haaland}`);
    const invalid = screen.getByTestId(`starter-${gabriel}`);
    expect(valid.getAttribute("data-swap")).toBe("valid");
    expect(invalid.getAttribute("data-swap")).toBe("invalid");
    fireEvent.click(valid);
    expect(onStarterClick).toHaveBeenCalledWith(haaland);
    fireEvent.click(invalid);
    expect(onStarterClick).toHaveBeenCalledWith(gabriel);
  });

  it("renders starters without swap attributes outside swap mode", () => {
    renderPitch(squad);
    expect(screen.getByTestId(`starter-${haaland}`).hasAttribute("data-swap")).toBe(false);
  });
});
