// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { HotTargets } from "./HotTargets";
import type { FplHotByPosition } from "@/lib/fplAssistantApi";

afterEach(cleanup);

const hotByPosition: FplHotByPosition = {
  GKP: [
    { id: 1, name: "Keeper", team: "AVL", price: 5.0, xpts: 4.2, xpts_horizon: 11.5 },
  ],
  MID: [
    { id: 2, name: "Mid1", team: "LIV", price: 7.5, next_fixture: "vs BOU (H)", xpts: 6.1 },
    { id: 3, name: "Mid2", team: "ARS", price: 8.0, transfer_score: 9.4 },
  ],
};

describe("HotTargets", () => {
  it("renders positions and players", () => {
    render(<HotTargets hotByPosition={hotByPosition} />);
    expect(screen.getByText(/hot targets/i)).toBeTruthy();
    expect(screen.getByText("GKP")).toBeTruthy();
    expect(screen.getByText("MID")).toBeTruthy();
    expect(screen.getByText("Keeper")).toBeTruthy();
    expect(screen.getByText("Mid1")).toBeTruthy();
    expect(screen.getByText("Mid2")).toBeTruthy();
    expect(screen.getByText(/4\.2 xPts/)).toBeTruthy();
    expect(screen.getByText(/11\.5 horizon/)).toBeTruthy();
    expect(screen.getByText(/vs BOU \(H\)/)).toBeTruthy();
    expect(screen.getByText(/score 9\.4/)).toBeTruthy();
  });

  it("renders nothing when hotByPosition is empty or absent", () => {
    const { container: empty } = render(<HotTargets hotByPosition={{}} />);
    expect(empty.firstChild).toBeNull();
    const { container: absent } = render(<HotTargets />);
    expect(absent.firstChild).toBeNull();
  });
});
