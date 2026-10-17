import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchReplayGw } from "./replayApi";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("fetchReplayGw", () => {
  it("calls the replay endpoint with entry_id and returns the record", async () => {
    const record = { season: "2025-26", gw: 7, setup_gw: false, players: [],
      model_captain: 351, optimal_captain: 351, suggested_transfer: null,
      sp2_candidates: [], your: { captain: 233, points: 61 } };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(record), { status: 200, headers: { "Content-Type": "application/json" } }));
    const out = await fetchReplayGw("2025-26", 7, 588004);
    expect(out.your?.captain).toBe(233);
    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toContain("/replay/2025-26/gw/7");
    expect(calledUrl).toContain("entry_id=588004");
  });

  it("builds the exact absolute URL from VITE_FPL_API_BASE_URL", async () => {
    vi.stubEnv("VITE_FPL_API_BASE_URL", "http://localhost:9999");
    const record = { season: "2025-26", gw: 7, setup_gw: false, players: [],
      model_captain: 351, optimal_captain: 351, suggested_transfer: null,
      sp2_candidates: [], your: null };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(record), { status: 200, headers: { "Content-Type": "application/json" } }));
    await fetchReplayGw("2025-26", 7, 588004);
    expect(String(fetchMock.mock.calls[0][0]))
      .toBe("http://localhost:9999/replay/2025-26/gw/7?entry_id=588004");
  });

  it("throws when the response is not ok", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("nope", { status: 404 }));
    await expect(fetchReplayGw("2025-26", 99, 588004)).rejects.toThrow();
  });
});
