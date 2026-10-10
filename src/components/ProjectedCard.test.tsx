// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ProjectedCard } from "./ProjectedCard";

afterEach(cleanup);

describe("ProjectedCard", () => {
  it("shows the projected total and the applied-transfer delta", () => {
    render(<ProjectedCard gw={29} projected={68.4} delta={2.4} />);
    expect(screen.getByText("Projected GW29")).toBeTruthy();
    expect(screen.getByTestId("projected-total").textContent).toBe("68.4");
    expect(screen.getByText("+2.4 from your transfers")).toBeTruthy();
  });

  it("hides the delta when nothing has been applied", () => {
    render(<ProjectedCard gw={29} projected={66} />);
    expect(screen.queryByText(/from your transfers/)).toBeNull();
  });

  it("renders the percentile ring and benchmark bars only when the backend sends them", () => {
    const { rerender } = render(<ProjectedCard gw={29} projected={66} />);
    expect(screen.queryByTestId("percentile-ring")).toBeNull();
    expect(screen.queryByTestId("benchmarks")).toBeNull();

    rerender(<ProjectedCard gw={29} projected={66} percentile={8} top10kAvg={64.1} overallAvg={55.3} />);
    expect(screen.getByTestId("percentile-ring").textContent).toContain("8%");
    const bars = screen.getAllByTestId("benchmark-bar");
    expect(bars.map((b) => b.style.width)).toEqual(["88%", "85%", "74%"]);
    expect(screen.getByTestId("benchmarks").textContent).toContain("Top 10k");
  });

  it("shows a placeholder until a recommendation exists", () => {
    render(<ProjectedCard gw={29} />);
    expect(screen.getByTestId("projected-total").textContent).toBe("—");
  });
});
