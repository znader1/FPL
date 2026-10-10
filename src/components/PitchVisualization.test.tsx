// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
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
