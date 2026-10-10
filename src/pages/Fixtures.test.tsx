// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Fixtures from "./Fixtures";
import { SAMPLE_TEAM_RECOMMENDATION } from "@/lib/fplAssistantApi";

const api = {
  fetchNextEvent: vi.fn(),
  fetchSquad: vi.fn(),
  fetchFixtureDifficulty: vi.fn(),
  fetchChipPlan: vi.fn(),
  fetchTeamRecommendation: vi.fn(),
};
vi.mock("@/lib/fplAssistantApi", async (orig) => ({
  ...(await orig<typeof import("@/lib/fplAssistantApi")>()),
  fetchNextEvent: (...a: unknown[]) => api.fetchNextEvent(...a),
  fetchSquad: (...a: unknown[]) => api.fetchSquad(...a),
  fetchFixtureDifficulty: (...a: unknown[]) => api.fetchFixtureDifficulty(...a),
  fetchChipPlan: (...a: unknown[]) => api.fetchChipPlan(...a),
  fetchTeamRecommendation: (...a: unknown[]) => api.fetchTeamRecommendation(...a),
}));
vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => ({ user: { id: "u1" }, signOut: vi.fn() }) }));
vi.mock("@/hooks/useProfile", () => ({ useProfile: () => ({ profile: null }) }));

const gws = [29, 30, 31, 32, 33, 34];
const cell = (opp: string) => ({ opponents: [{ opp_id: 1, opp_short: opp, home: true, difficulty: 2, band: "easy", color: "#0f0" }], difficulty: 2, count: 1, blank: false });
const teams = [...new Set([...SAMPLE_TEAM_RECOMMENDATION.starting_xi, ...SAMPLE_TEAM_RECOMMENDATION.bench].map((p) => p.team_short))];
const ticker = {
  gw_start: 29, horizon_gws: 6, gws,
  teams: teams.map((t, i) => ({ team_id: i, team_short: t, avg_difficulty: 2, sum_difficulty: 12, n_fixtures: 6, band: "easy", color: "#0f0",
    gws: Object.fromEntries(gws.map((g) => [String(g), cell("OPP")])) })),
  easiest_runs: [], hardest_runs: [],
};

const renderPage = (path = "/app/fixtures") => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Fixtures />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  localStorage.setItem("fpl_entry_id", "588004");
  api.fetchNextEvent.mockResolvedValue({ event_id: 29, deadline_time_utc: null });
  api.fetchSquad.mockResolvedValue(SAMPLE_TEAM_RECOMMENDATION);
  api.fetchFixtureDifficulty.mockResolvedValue(ticker);
  api.fetchChipPlan.mockResolvedValue({ entry_id: 588004, current_gw: 29, chips_remaining: [], horizon_model_gws: 6, recommendations: [], nudge: null, transfer_context: { planned_transfers_net_gain: 0, wc_alternative_gw: null } });
  api.fetchTeamRecommendation.mockImplementation(() => new Promise(() => {}));
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  Object.values(api).forEach((m) => m.mockReset());
});

describe("Fixture Planner page", () => {
  it("renders all 15 squad rows over six GW columns from the ticker before the recommendation lands", async () => {
    renderPage();
    await waitFor(() => expect(within(screen.getByTestId("planner-grid")).getAllByRole("row").length).toBe(16));
    expect(within(screen.getByTestId("planner-grid")).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Player", "GW29", "GW30", "GW31", "GW32", "GW33", "GW34", "xPts"]);
    expect(within(screen.getByTestId("planner-grid")).getAllByText(/\(C\)$/)).toHaveLength(1);
    expect(screen.getByText(/Loading your moves/)).toBeTruthy();
    expect(api.fetchFixtureDifficulty).toHaveBeenCalledWith(expect.objectContaining({ gw_start: 29, horizon_gws: 6 }), expect.anything());
  });

  it("asks the recommendation for the chosen horizon and reads ?h=", async () => {
    renderPage("/app/fixtures?h=3");
    await waitFor(() => expect(api.fetchTeamRecommendation).toHaveBeenCalled());
    expect(api.fetchTeamRecommendation.mock.calls[0][0]).toMatchObject({ entryId: 588004, eventId: 29, horizonGws: 3, includeTransfers: true });
    expect(screen.getAllByRole("radio", { name: "3 GWs" })[0].getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("Weakest links · next 3 GWs")).toBeTruthy();
  });

  it("switches the horizon from the toggle", async () => {
    renderPage();
    await waitFor(() => expect(api.fetchTeamRecommendation).toHaveBeenCalled());
    fireEvent.click(screen.getAllByRole("radio", { name: "3 GWs" })[0]);
    await waitFor(() => expect(api.fetchTeamRecommendation).toHaveBeenCalledTimes(2));
    expect(api.fetchTeamRecommendation.mock.calls[1][0]).toMatchObject({ horizonGws: 3 });
  });

  it("keeps the all-teams ticker behind a closed details", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("planner-grid")).toBeTruthy());
    const details = screen.getByText("All teams").closest("details");
    expect(details).toBeTruthy();
    expect(details?.hasAttribute("open")).toBe(false);
  });

  it("prompts to link a team when no entry id is known", async () => {
    localStorage.clear();
    renderPage();
    expect(await screen.findByText(/Link your FPL team/)).toBeTruthy();
    expect(api.fetchSquad).not.toHaveBeenCalled();
  });
});
