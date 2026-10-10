// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { PlannerRail } from "./PlannerRail";

afterEach(cleanup);

const chips = [
  { chip: "bench_boost" as const, gw: 32, label: "Bench Boost", reason: "6 of your players have a double gameweek.", nudged: true },
  { chip: "free_hit" as const, gw: 33, label: "Free Hit", reason: "4 starters blank.", nudged: false },
];
const links = [
  { out: "Isak", in: "Solanke", outX: 14.2, inX: 16.6, gain: 2.4, price: 6.7 },
  { out: "Van Dijk", in: "Saliba", gain: 1.1, price: 6.0 },
];

describe("PlannerRail", () => {
  it("lists chip windows, tinting the nudged one", () => {
    render(<PlannerRail chips={chips} links={links} horizon={6} />);
    const cards = screen.getAllByTestId("chip-window");
    expect(cards[0].textContent).toContain("Bench Boost");
    expect(cards[0].textContent).toContain("GW32");
    expect(cards[0].getAttribute("data-nudged")).toBe("true");
    expect(cards[1].getAttribute("data-nudged")).toBe("false");
  });

  it("lists weakest links with out struck through, xPts when known, and the gain badge", () => {
    render(<PlannerRail chips={chips} links={links} horizon={6} />);
    expect(screen.getByText("Weakest links · next 6 GWs")).toBeTruthy();
    const items = screen.getAllByTestId("weak-link");
    expect(items[0].textContent).toContain("Isak");
    expect(items[0].textContent).toContain("Solanke");
    expect(items[0].textContent).toContain("14.2 → 16.6 xPts · £6.7m");
    expect(items[0].textContent).toContain("+2.4");
    expect(items[1].textContent).toContain("£6.0m");
    expect(items[1].textContent).not.toContain("xPts ·");
    const out = items[0].querySelector("s");
    expect(out?.textContent).toBe("Isak");
  });

  it("explains empty states", () => {
    render(<PlannerRail chips={[]} links={[]} horizon={3} hasRecommendation={false} />);
    expect(screen.getByText(/No chip window in these gameweeks/)).toBeTruthy();
    expect(screen.getByText(/Loading your moves/)).toBeTruthy();
    cleanup();
    render(<PlannerRail chips={[]} links={[]} horizon={3} hasRecommendation />);
    expect(screen.getByText(/Nothing beats your current 15/)).toBeTruthy();
  });

  it("draws the five-bar FDR legend", () => {
    render(<PlannerRail chips={[]} links={[]} horizon={3} />);
    expect(screen.getByTestId("fdr-legend").querySelectorAll(".grid > div")).toHaveLength(5);
  });
});
