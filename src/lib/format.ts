/** `+0.9` / `−1.3`; one decimal, typographic minus. */
export const fmtGain = (n: number) => `${n < 0 ? "−" : "+"}${Math.abs(n).toFixed(1)}`;

/** `GW5–7`, `GW5`, or `the horizon` when unknown. */
export const gwRange = (h: { start_gw: number | null; end_gw: number | null }) => {
  if (h.start_gw == null) return "the horizon";
  if (h.end_gw == null || h.end_gw === h.start_gw) return `GW${h.start_gw}`;
  return `GW${h.start_gw}–${h.end_gw}`;
};

/** "1,896,801" → "1.9M", "412,338" → "412k" for a phone-width bar; anything
 *  that isn't a plain number comes back unchanged. */
export const compactRank = (rank: string): string => {
  const n = Number(rank.replace(/,/g, ""));
  if (!Number.isFinite(n) || rank.trim() === "") return rank;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 100_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1_000) return `${(n / 1000).toFixed(1)}k`;
  return rank;
};

