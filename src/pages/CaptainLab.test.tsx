// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import CaptainLab from "./CaptainLab";
import type { FplTeamRecommendation, FplTeamRecommendationPlayer } from "@/lib/fplAssistantApi";

const api = { fetchNextEvent: vi.fn(), fetchTeamRecommendation: vi.fn() };
vi.mock("@/lib/fplAssistantApi", async (orig) => ({
  ...(await orig<typeof import("@/lib/fplAssistantApi")>()),
  fetchNextEvent: (...a: unknown[]) => api.fetchNextEvent(...a),
  fetchTeamRecommendation: (...a: unknown[]) => api.fetchTeamRecommendation(...a),
}));
vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => ({ user: { id: "u1" }, signOut: vi.fn() }) }));
vi.mock("@/hooks/useProfile", () => ({ useProfile: () => ({ profile: null }) }));

const p = (id: number, name: string, team: string, xpts: number, over: Partial<FplTeamRecommendationPlayer> = {}): FplTeamRecommendationPlayer => ({
  player_id: id, web_name: name, team_short: team, team_name: team, pos: "MID",
  is_captain: false, is_vice_captain: false, multiplier: 1, xpts, next_fixtures: "H-BHA(D1)",
  score_breakdown: { distribution: { p80_low: 2, p80_high: 16 } }, ...over,
});
const rec: FplTeamRecommendation = {
  entry_id: 588004, event_id: 29, horizon_gws: 3, formation: [4, 4, 2], captain_player_id: 1, vice_player_id: 2,
  projected_points_with_captain: 66,
  starting_xi: [
    p(1, "Haaland", "MCI", 8.6, { is_captain_suggested: true, eo_top10k: 142, rank_gain_if_haul: 3000 }),
    p(2, "Saka", "ARS", 7.4, { eo_top10k: 38, rank_gain_if_haul: 41000 }),
    p(3, "Palmer", "CHE", 6.9, { eo_top10k: 22, rank_gain_if_haul: 29000 }),
    p(4, "Raya", "ARS", 4.2, { pos: "GKP" }),
  ],
  bench: [],
  transfer_plan_horizon: {
    verdict: "spend",
    verdict_detail: {
      action: "spend", horizon: { start_gw: 29, end_gw: 31, n: 3 }, ft_before: 1, ft_after: 0, threshold: 2,
      moves: [{ sell: { id: 9, name: "Isak", team: "NEW", price: 8.5 }, buy: { id: 50, name: "Solanke", team: "BOU", price: 6.7 }, this_gw_gain: 0.8, horizon_gain: 2.4 }],
      this_gw_gain: 0.8, horizon_gain: 2.4, hit_cost: 0, plan_net: 2.4, roll_alternative: null, next_move: null,
    },
  },
};

const renderPage = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/app/captain"]}>
        <CaptainLab />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  localStorage.setItem("fpl_entry_id", "588004");
  api.fetchNextEvent.mockResolvedValue({ event_id: 29 });
  api.fetchTeamRecommendation.mockResolvedValue(rec);
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  Object.values(api).forEach((m) => m.mockReset());
});

describe("Captain Lab page", () => {
  it("renders the stepper, the chase headline by default and three candidate cards", async () => {
    renderPage();
    expect(await screen.findByText("Captain Saka to climb the ranks.")).toBeTruthy();
    expect(screen.getByText("Step 2 of 4 · Captain")).toBeTruthy();
    expect(screen.getAllByTestId("captain-card")).toHaveLength(3);
    expect(screen.getByTestId("footer-captain").textContent).toBe("Saka (C)");
    expect(screen.getByTestId("footer-vice").textContent).toBe("Haaland (VC)");
    expect(screen.getByTestId("footer-projected").textContent).toBe("64.8 pts");
    expect(screen.getByTestId("footer-transfers").textContent).toContain("Isak → Solanke");
  });

  it("switching the goal moves the ZN Pick and clears a manual pick", async () => {
    renderPage();
    await screen.findByText("Captain Saka to climb the ranks.");
    fireEvent.click(screen.getByRole("button", { name: /Palmer/ }));
    expect(screen.getByTestId("footer-captain").textContent).toBe("Palmer (C)");
    fireEvent.click(screen.getAllByRole("radio", { name: "Protect rank" })[0]);
    expect(screen.getByText("Protect your rank with Haaland.")).toBeTruthy();
    expect(screen.getByTestId("footer-captain").textContent).toBe("Haaland (C)");
    expect(localStorage.getItem("fpl_captain_goal")).toBe("safe");
  });

  it("asks for the squad's next-GW recommendation once", async () => {
    renderPage();
    await waitFor(() => expect(api.fetchTeamRecommendation).toHaveBeenCalledTimes(1));
    expect(api.fetchTeamRecommendation.mock.calls[0][0]).toMatchObject({ entryId: 588004, eventId: 29 });
  });

  it("prompts to link a team without an entry id", async () => {
    localStorage.clear();
    renderPage();
    expect(await screen.findByText(/Link your FPL team/)).toBeTruthy();
  });
});
