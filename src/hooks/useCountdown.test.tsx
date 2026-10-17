// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { useCountdown } from "./useCountdown";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-10T12:00:00Z"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useCountdown", () => {
  it("returns the remaining ms and ticks down once a second", () => {
    const { result } = renderHook(() => useCountdown("2026-10-10T12:00:10Z"));
    expect(result.current).toBe(10_000);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(result.current).toBe(9_000);
  });

  it("returns null without a deadline and sets no timer", () => {
    const { result } = renderHook(() => useCountdown(null));
    expect(result.current).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops ticking at zero", () => {
    const { result } = renderHook(() => useCountdown("2026-10-10T12:00:01Z"));
    act(() => { vi.advanceTimersByTime(3000); });
    expect(result.current).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears its timer on unmount", () => {
    const { unmount } = renderHook(() => useCountdown("2026-10-10T13:00:00Z"));
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
