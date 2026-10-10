// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { FixturePlannerGrid } from "./FixturePlannerGrid";
import type { PlannerRow } from "@/lib/fixturePlanner";

afterEach(cleanup);

const row = (over: Partial<PlannerRow>): PlannerRow => ({
  playerId: 1, name: "Saka", team: "ARS", pos: "MID", isBench: false, isCaptain: false, gapBefore: 0, total: 20.4,
  cells: [
    { gw: 29, blank: false, count: 1, fixtures: [{ opponent: "BHA", isHome: true, fdr: 1 }], xpts: 7.4, inHorizon: true },
    { gw: 30, blank: false, count: 2, fixtures: [{ opponent: "BRE", isHome: false, fdr: 2 }, { opponent: "WOL", isHome: true, fdr: 3 }], xpts: 13.0, inHorizon: true },
    { gw: 31, blank: true, count: 0, fixtures: [], xpts: 0, inHorizon: false },
  ],
  ...over,
});

const rows = [
  row({ playerId: 1, name: "Saka", isCaptain: true }),
  row({ playerId: 2, name: "Isak", team: "NEW", pos: "FWD", gapBefore: 8, total: null, cells: row({}).cells.map((c) => ({ ...c, xpts: undefined })) }),
  row({ playerId: 3, name: "Sels", team: "NFO", pos: "GKP", isBench: true, gapBefore: 14, total: 6.0 }),
];
const tags = [{ gw: 29, tag: null }, { gw: 30, tag: "DGW" as const }, { gw: 31, tag: "BLANK" as const }];

describe("FixturePlannerGrid", () => {
  it("renders GW heads with tags, fading those beyond the horizon", () => {
    render(<FixturePlannerGrid rows={rows} gws={[29, 30, 31]} horizon={2} tags={tags} />);
    const heads = screen.getAllByRole("columnheader");
    expect(heads.map((h) => h.textContent)).toEqual(["Player", "GW29", "DGWGW30", "BLANKGW31", "xPts"]);
    expect(heads[3].className).toContain("opacity-35");
    expect(heads[2].className).not.toContain("opacity-35");
  });

  it("renders a row per player with fixture chips, xPts, blanks and the total", () => {
    render(<FixturePlannerGrid rows={rows} gws={[29, 30, 31]} horizon={2} tags={tags} />);
    const body = screen.getAllByRole("row").slice(1);
    expect(body).toHaveLength(3);
    const saka = within(body[0]);
    expect(saka.getByText("Saka (C)")).toBeTruthy();
    expect(saka.getByText("H-BHA(D1)")).toBeTruthy();
    expect(saka.getByText("A-BRE(D2)")).toBeTruthy();
    expect(saka.getByText("13.0")).toBeTruthy();
    expect(saka.getByText("BLANK")).toBeTruthy();
    expect(saka.getByTestId("row-total").textContent).toBe("20.4");
    expect(saka.getByTestId("row-total").className).toContain("text-primary"); // 10.2/GW
  });

  it("shows — for unknown xPts and a muted bench name", () => {
    render(<FixturePlannerGrid rows={rows} gws={[29, 30, 31]} horizon={2} tags={tags} />);
    const body = screen.getAllByRole("row").slice(1);
    expect(within(body[1]).getByTestId("row-total").textContent).toBe("—");
    expect(within(body[2]).getByText("Sels").className).toContain("muted");
    expect(body[2].getAttribute("data-gap")).toBe("14");
    expect(within(body[2]).getByText("Bench · GKP")).toBeTruthy();
  });

  it("dims cells past the horizon", () => {
    render(<FixturePlannerGrid rows={rows} gws={[29, 30, 31]} horizon={2} tags={tags} />);
    const cells = screen.getAllByTestId("planner-cell");
    expect(cells[2].className).toContain("opacity-30");
    expect(cells[1].className).not.toContain("opacity-30");
  });
});
