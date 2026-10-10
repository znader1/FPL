// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DeadlineCountdown } from "./DeadlineCountdown";
import type { FplNextEventSummary } from "@/lib/fplAssistantApi";

const fetchNextEvent = vi.fn<(signal?: AbortSignal) => Promise<FplNextEventSummary>>();
vi.mock("@/lib/fplAssistantApi", async (orig) => ({
  ...(await orig<typeof import("@/lib/fplAssistantApi")>()),
  fetchNextEvent: (signal?: AbortSignal) => fetchNextEvent(signal),
}));

const renderWithClient = (ui: React.ReactElement) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-10T12:00:00Z"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  fetchNextEvent.mockReset();
});

describe("DeadlineCountdown", () => {
  it("shows the GW label and a ticking countdown from the absolute deadline", async () => {
    fetchNextEvent.mockResolvedValue({ event_id: 29, deadline_time_utc: "2026-10-11T16:12:33Z", hours_to_deadline: 1 });
    renderWithClient(<DeadlineCountdown />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const pill = screen.getByTestId("deadline-pill");
    expect(pill.textContent).toContain("GW29 deadline");
    expect(pill.textContent).toContain("1d 04:12:33");
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(pill.textContent).toContain("1d 04:12:32");
    expect(pill.className).toContain("whitespace-nowrap");
  });

  it("renders nothing once the deadline has passed", async () => {
    fetchNextEvent.mockResolvedValue({ event_id: 29, deadline_time_utc: "2026-10-10T11:59:00Z" });
    renderWithClient(<DeadlineCountdown />);
    await act(async () => { await vi.advanceTimersByTimeAsync(50); });
    expect(screen.queryByTestId("deadline-pill")).toBeNull();
  });

  it("renders nothing when the backend has no deadline", async () => {
    fetchNextEvent.mockResolvedValue({ event_id: null, deadline_time_utc: null });
    renderWithClient(<DeadlineCountdown />);
    await act(async () => { await vi.advanceTimersByTimeAsync(50); });
    expect(screen.queryByTestId("deadline-pill")).toBeNull();
  });
});
