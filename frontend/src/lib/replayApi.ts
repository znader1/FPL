export interface ReplayPlayer {
  element: number;
  model_xpts: number;
  actual_points: number;
}

export interface ReplaySp2Candidate {
  element: number;
  differential_ev: number;
  template_xpts: number;
  global_ownership: number;
  ownership_basis: "global";
}

export interface ReplayYourSide {
  picks?: number[];
  captain?: number | null;
  vice?: number | null;
  transfers?: { in: number[]; out: number[] };
  chip?: string | null;
  points?: number | null;
  bank?: number | null;
}

export interface ReplayGwRecord {
  season: string;
  gw: number;
  setup_gw: boolean;
  players: ReplayPlayer[];
  model_captain: number | null;
  optimal_captain: number | null;
  suggested_transfer: { sell: number; buy: number; expected_gain: number } | null;
  sp2_candidates: ReplaySp2Candidate[];
  your: ReplayYourSide | null;
  names?: Record<string, string>;
}

export function replayEnabled(): boolean {
  return import.meta.env.VITE_REPLAY_MODE === "1";
}

// Mirrors the `getEnvString` + `apiBase` convention used throughout
// src/lib/fplAssistantApi.ts (see fetchLeagueStrategy, fetchFixtureDifficulty, etc.):
// guard against non-string/empty env values rather than a bare `?? ""` cast.
const getEnvString = (key: string): string | undefined => {
  const value = (import.meta.env as Record<string, unknown>)[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
};

export async function fetchReplayGw(
  season: string,
  gw: number,
  entryId: number,
  signal?: AbortSignal,
): Promise<ReplayGwRecord> {
  const apiBase = getEnvString("VITE_FPL_API_BASE_URL") ?? "";
  const path = `/replay/${season}/gw/${gw}?entry_id=${entryId}`;
  const url = apiBase ? new URL(path, apiBase).toString() : path;
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`Replay GW ${gw} failed: ${res.status}`);
  return (await res.json()) as ReplayGwRecord;
}
