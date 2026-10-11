// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { PlayerCard, type Player } from "./PlayerCard";

afterEach(cleanup);

const basePlayer: Player = {
  id: 1,
  name: "Haaland",
  team: "MCI",
  teamName: "Man City",
  points: 6.4,
};

const renderCard = (over: Partial<Player> = {}) =>
  render(<PlayerCard player={{ ...basePlayer, ...over }} />);

describe("points under the player", () => {
  it("shows the projection when no actual points exist", () => {
    renderCard();
    expect(screen.getByText("6.4")).toBeTruthy();
  });

  it("shows actual points for a finished gameweek, not the projection", () => {
    // Browsing back to a finished GW used to fall through to the projection
    // because the actual score was gated on isLiveGw.
    renderCard({ livePoints: 13, isLiveGw: false });
    const actual = screen.getByTitle("Final points");
    expect(actual.textContent).toBe("13");
  });

  it("marks actual points as live during the current gameweek", () => {
    renderCard({ livePoints: 9, isLiveGw: true });
    expect(screen.getByTitle("Live points").textContent).toBe("9");
  });

  it("shows the projection alongside the actual score", () => {
    renderCard({ livePoints: 9, isLiveGw: true });
    expect(screen.getByTitle("Projected points").textContent).toBe("6.4");
  });

  it("hides a real score that belongs to a different gameweek", () => {
    // Planning a future GW renders the substituted latest squad. Painting its
    // points under a "GW3" heading claims a score that does not exist yet —
    // the caller suppresses livePoints, and the projection shows instead.
    renderCard({ livePoints: undefined, points: 4.2 });
    expect(screen.queryByTitle("Final points")).toBeNull();
    expect(screen.queryByTitle("Live points")).toBeNull();
    expect(screen.getByText("4.2")).toBeTruthy();
  });

  it("renders a dash when neither a score nor a projection is available", () => {
    renderCard({ points: Number.NaN });
    expect(screen.getByText("—")).toBeTruthy();
  });

  it("does not render a stray separator when only an actual score exists", () => {
    renderCard({ points: Number.NaN, livePoints: 4 });
    expect(screen.queryByTitle("Projected points")).toBeNull();
    expect(screen.getByTitle("Final points").textContent).toBe("4");
  });

  it("shows a zero score rather than treating it as missing", () => {
    renderCard({ livePoints: 0, isLiveGw: true });
    expect(screen.getByTitle("Live points").textContent).toBe("0");
  });
});

describe("hover card information order", () => {
  const withBreakdown = {
    ...basePlayer,
    scoreBreakdown: {
      current_gw_xpts: 4.1,
      horizon_xpts: 12.3,
      components: { p_goal: 0.61, p_60: 0.78, model_exp_points: 5.24 },
      distribution: { modal_points: 2, p_return_6: 0.34, p_haul_10: 0.12, p80_low: 1, p80_high: 9 },
      recent_form: { window_gws: 5, samples: 1, avg_points: 2, avg_minutes: 66 },
      baseline: { long_term: 2, recent_gw: 2, blended: 2 },
    },
  } as Player;

  it("keeps the model's own inputs collapsed by default", () => {
    // The card was showing ~17 diagnostic numbers ahead of the answer.
    const { container } = render(<PlayerCard player={withBreakdown} />);
    const details = container.querySelector("details");
    // Rendered but closed: available on demand, not competing with the answer.
    expect(details === null || (details as HTMLDetailsElement).open === false).toBe(true);
  });
});

describe("xPts aura (Command Center)", () => {
  it("renders no aura by default", () => {
    renderCard();
    expect(screen.queryByTestId("xpts-aura")).toBeNull();
  });

  it("sizes the aura to 30 + xPts × 11 px, centred on the jersey", () => {
    renderCard({ aura: true, points: 6.4 });
    const aura = screen.getByTestId("xpts-aura") as HTMLElement;
    expect(aura.style.width).toBe("100px");
    expect(aura.style.height).toBe("100px");
    expect(aura.getAttribute("aria-hidden")).toBe("true");
  });

  it("uses the projection, not the live score, for the aura", () => {
    renderCard({ aura: true, points: 2, livePoints: 13 });
    expect((screen.getByTestId("xpts-aura") as HTMLElement).style.width).toBe("52px");
  });
});

describe("incoming-transfer pill", () => {
  it("shows IN +gain above a newly applied player", () => {
    renderCard({ inGain: 2.4 });
    expect(screen.getByText("IN +2.4")).toBeTruthy();
  });
  it("shows a bare IN when the player is new but the gain is unknown", () => {
    renderCard({ inGain: null });
    expect(screen.getByText("IN")).toBeTruthy();
  });
  it("shows nothing when the player was already in the squad", () => {
    renderCard();
    expect(screen.queryByText(/^IN /)).toBeNull();
  });
});
