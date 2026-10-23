// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { GameweekNav } from "./GameweekNav";

afterEach(cleanup);

const base = {
  currentGW: 2,
  totalGW: 38,
  points: 44,
  rank: "412,338",
  onPrev: () => {},
  onNext: () => {},
};

describe("live-gameweek indicator", () => {
  it("collapses live to a dot with the refresh time on hover", () => {
    // A frozen score and a genuine zero are indistinguishable without the
    // timestamp — it lives in the tooltip now so the bar stays one row.
    const at = new Date("2026-08-29T14:35:00Z").getTime();
    render(<GameweekNav {...base} isLiveGw updatedAt={at} />);
    expect(screen.queryByText("Live")).toBeNull();
    const pill = screen.getByTestId("gw-state-pill");
    expect(pill.getAttribute("title")).toMatch(/^Live · last refreshed/);
  });

  it("keeps the Planning label outside a live gameweek", () => {
    render(<GameweekNav {...base} isLiveGw={false} updatedAt={Date.now()} />);
    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByTestId("gw-state-pill").getAttribute("title")).toBeNull();
  });

  it("omits the timestamp when nothing has been fetched yet", () => {
    render(<GameweekNav {...base} isLiveGw updatedAt={0} />);
    expect(screen.getByTestId("gw-state-pill").getAttribute("title")).toBe("Live");
  });
});

describe("control-bar slots", () => {
  it("shows the compact rank until the widest screens, so it never runs under the action", () => {
    render(<GameweekNav {...base} rank="1,896,801" />);
    expect(screen.getByText("1,896,801").className).toContain("2xl:inline");
    const compact = screen.getByText("1.9M");
    expect(compact.className).toContain("2xl:hidden");
    expect(compact.getAttribute("title")).toBe("1,896,801");
  });

  it("the stats clip instead of overflowing, and the numbers keep their width", () => {
    render(<GameweekNav {...base} rank="1,896,801" />);
    expect(screen.getByText("1.9M").className).toContain("shrink-0");
    expect(screen.getByText("1.9M").closest(".overflow-hidden")).toBeTruthy();
  });

  it("renders the squad toggle inside the gameweek bar", () => {
    // Merged into one bar so the two control strips cost one band of vertical
    // space — the difference between the bench being on screen or not.
    render(
      <GameweekNav {...base} leading={<button type="button">Squad</button>} />,
    );
    expect(screen.getByRole("button", { name: "Squad" })).toBeTruthy();
  });

  it("renders the primary action in the same bar", () => {
    render(<GameweekNav {...base} action={<button type="button">Plan GW3</button>} />);
    expect(screen.getByRole("button", { name: "Plan GW3" })).toBeTruthy();
  });

  it("renders without either slot", () => {
    render(<GameweekNav {...base} />);
    expect(screen.getByText("Planning")).toBeTruthy();
  });
});
