// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Navbar } from "./Navbar";

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "u1" }, signOut: vi.fn() }),
}));
vi.mock("./DeadlineCountdown", () => ({
  DeadlineCountdown: () => <div data-testid="deadline-pill">GW29 deadline</div>,
}));

afterEach(cleanup);

const renderAt = (path: string, extras?: React.ReactNode, planStatus?: { changes: number; locked: boolean }) => {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Navbar extras={extras} planStatus={planStatus} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("Navbar on app routes", () => {
  it("shows the deadline pill and the extras slot", () => {
    renderAt("/app", <span>Bank £1.4m</span>);
    expect(screen.getByTestId("deadline-pill")).toBeTruthy();
    expect(screen.getByText("Bank £1.4m")).toBeTruthy();
  });

  it("keeps the active tab visible and marks it", () => {
    renderAt("/app/league");
    const tabs = screen.getByTestId("app-tabs");
    const active = tabs.querySelector('[aria-current="page"]');
    expect(active?.textContent).toBe("Mini-league");
    expect(tabs.textContent).toContain("Squad");
  });
});

describe("Navbar tab strip", () => {
  it("keeps the secondary Draft squad tab off the strip below lg", () => {
    renderAt("/app");
    const draft = screen.getByTestId("app-tabs").querySelector('a[href="/app/squad-picker"]');
    expect(draft?.className).toContain("hidden lg:inline-flex");
  });
});

describe("Navbar on the landing page", () => {
  it("renders no deadline pill", () => {
    renderAt("/");
    expect(screen.queryByTestId("deadline-pill")).toBeNull();
  });
});

describe("Navbar plan status pill (v2 flow)", () => {
  it("reads No changes yet / n unsaved changes / Plan saved, with a short form for phones", () => {
    const { rerender } = renderAt("/app", undefined, { changes: 0, locked: false });
    expect(screen.getByTestId("plan-status").textContent).toContain("No changes yet");
    cleanup();
    renderAt("/app", undefined, { changes: 2, locked: false });
    const pill = screen.getByTestId("plan-status");
    expect(pill.textContent).toContain("2 unsaved changes");
    expect(pill.textContent).toContain("2 unsaved");
    expect(pill.getAttribute("data-tone")).toBe("warning");
    cleanup();
    renderAt("/app", undefined, { changes: 1, locked: false });
    expect(screen.getByTestId("plan-status").textContent).toContain("1 unsaved change");
    cleanup();
    renderAt("/app", undefined, { changes: 2, locked: true });
    expect(screen.getByTestId("plan-status").textContent).toContain("Plan saved");
    expect(screen.getByTestId("plan-status").getAttribute("data-tone")).toBe("saved");
    void rerender;
  });

  it("renders no pill without a plan status", () => {
    renderAt("/app");
    expect(screen.queryByTestId("plan-status")).toBeNull();
  });

  it("lights Squad on every plan step except the captain's, which lights Captain", () => {
    renderAt("/app/plan/bench");
    expect(screen.getByTestId("app-tabs").querySelector('[aria-current="page"]')?.textContent).toBe("Squad");
    cleanup();
    renderAt("/app/plan/captain");
    expect(screen.getByTestId("app-tabs").querySelector('[aria-current="page"]')?.textContent).toBe("Captain");
  });
});
