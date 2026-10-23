// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TransferPlanner } from "./TransferPlanner";
import type { FplTransfersRecommendation } from "@/lib/fplAssistantApi";

afterEach(cleanup);

const transfers = {
  moves: [
    {
      position: "DEF",
      sell: { id: 1, name: "Seller", team: "AAA", price: 4.9 },
      buy: { id: 2, name: "Buyer", team: "BBB", price: 4.1 },
      score_gain: 7.1,
      this_gw_gain: 2.2,
      in_plan: true,
    },
  ],
  transfer_plan: { free_transfers: 1, horizon_gws: 3, hit_cap: 0, transfer_count_target: 1, transfer_count_built: 1 },
  remaining_itb: 0.5,
  hot_by_position: {
    GKP: [{ id: 9, name: "Keeper", team: "AVL", price: 5.0, xpts: 4.2 }],
  },
} as unknown as FplTransfersRecommendation;

describe("TransferPlanner shell", () => {
  it("renders the title and the given plan slot", () => {
    render(<TransferPlanner transfers={transfers} planSlot={<div data-testid="plan-slot">PLAN</div>} />);
    expect(screen.getByText("Transfer moves")).toBeTruthy();
    expect(screen.getByTestId("plan-slot")).toBeTruthy();
  });

  it("explains the ranking against the plan horizon", () => {
    render(<TransferPlanner transfers={transfers} horizonGws={3} planSlot={<div>PLAN</div>} />);
    expect(screen.getByText("Ranked by xPts gained over the next 3 GWs, after the cost of any hit.")).toBeTruthy();
    cleanup();
    render(<TransferPlanner transfers={transfers} horizonGws={1} planSlot={<div>PLAN</div>} />);
    expect(screen.getByText("Ranked by xPts gained this GW, after the cost of any hit.")).toBeTruthy();
  });

  it("renders no details, no Hot Targets, and no jersey icon when a plan slot is given", () => {
    const { container } = render(<TransferPlanner transfers={transfers} planSlot={<div>PLAN</div>} />);
    expect(container.querySelector("details")).toBeNull();
    expect(screen.queryByText(/Hot/i)).toBeNull();
    // JerseyIcon's svg carries this class; the header icon is the only other svg.
    expect(container.querySelector("svg.drop-shadow-md")).toBeNull();
  });

  it("shows the empty state only when there's no plan slot and no moves", () => {
    const none = { moves: [] } as unknown as FplTransfersRecommendation;
    render(<TransferPlanner transfers={none} />);
    expect(screen.getByText(/No transfer suggestions returned/i)).toBeTruthy();
  });

  it("hides the empty state when a plan slot is given, even with no moves", () => {
    const none = { moves: [] } as unknown as FplTransfersRecommendation;
    render(<TransferPlanner transfers={none} planSlot={<div>PLAN</div>} />);
    expect(screen.queryByText(/No transfer suggestions returned/i)).toBeNull();
  });

  it("hides the empty state when moves exist, even with no plan slot", () => {
    render(<TransferPlanner transfers={transfers} />);
    expect(screen.queryByText(/No transfer suggestions returned/i)).toBeNull();
  });

  it("shows the loading state instead of the empty state", () => {
    const none = { moves: [] } as unknown as FplTransfersRecommendation;
    render(<TransferPlanner transfers={none} isLoading />);
    expect(screen.getByText(/Computing transfer suggestions/i)).toBeTruthy();
    expect(screen.queryByText(/No transfer suggestions returned/i)).toBeNull();
  });
});
