/** `+0.9` / `−1.3`; one decimal, typographic minus. */
export const fmtGain = (n: number) => `${n < 0 ? "−" : "+"}${Math.abs(n).toFixed(1)}`;

/** `GW5–7`, `GW5`, or `the horizon` when unknown. */
export const gwRange = (h: { start_gw: number | null; end_gw: number | null }) => {
  if (h.start_gw == null) return "the horizon";
  if (h.end_gw == null || h.end_gw === h.start_gw) return `GW${h.start_gw}`;
  return `GW${h.start_gw}–${h.end_gw}`;
};
