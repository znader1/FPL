import { afterEach, describe, expect, it, vi } from "vitest";
import { buildSquad, getPlayers, optimizeLineup, squadPickerEnabled } from "./squadPickerApi";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("squadPickerApi", () => {
  it("squadPickerEnabled reflects VITE_SQUAD_PICKER", () => {
    vi.stubEnv("VITE_SQUAD_PICKER", "1");
    expect(squadPickerEnabled()).toBe(true);
    vi.stubEnv("VITE_SQUAD_PICKER", "");
    expect(squadPickerEnabled()).toBe(false);
  });

  it("buildSquad POSTs params to the base URL and returns JSON", async () => {
    vi.stubEnv("VITE_FPL_API_BASE_URL", "http://localhost:8009");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ok: true, squad: [], starting_xi: [], bench: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await buildSquad({ horizon_gws: 5, projection_basis: "ppg" });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8009/squad-picker/build",
      expect.objectContaining({ method: "POST" }),
    );
    expect(res.ok).toBe(true);
  });

  it("buildSquad throws on non-ok HTTP", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 500, json: async () => ({ detail: "boom" }),
    }));
    await expect(buildSquad({})).rejects.toThrow();
  });

  it("getPlayers POSTs params to /squad-picker/players and returns the pool", async () => {
    vi.stubEnv("VITE_FPL_API_BASE_URL", "http://localhost:8009");
    const pool = {
      gw_start: 1, horizon_gws: 5, projection_basis: "ppg",
      players: [{
        player_id: 1, web_name: "X", pos: "MID", team_short: "ARS",
        team_id: 1, price_m: 5, points_per_game: 4, total_points: 100,
        selected_by_percent: 10, xpts_horizon: 12, xpts_per_gw: [2, 2, 2, 3, 3],
      }],
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => pool });
    vi.stubGlobal("fetch", fetchMock);
    const r = await getPlayers({ projection_basis: "ppg" });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8009/squad-picker/players",
      expect.objectContaining({ method: "POST" }),
    );
    expect(r.players[0].team_id).toBe(1);
  });

  it("optimizeLineup POSTs player_ids + params to /squad-picker/lineup", async () => {
    vi.stubEnv("VITE_FPL_API_BASE_URL", "http://localhost:8009");
    const res = { ok: true, valid: true, violations: [], squad: [], starting_xi: [], bench: [] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => res });
    vi.stubGlobal("fetch", fetchMock);
    const r = await optimizeLineup([1, 2, 3], { budget_m: 100 });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.player_ids).toEqual([1, 2, 3]);
    expect(r.valid).toBe(true);
  });
});
