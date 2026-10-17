/** "Top N%" of the field for a projected total, read off the backend's
 *  `projected_field.overall_quantiles` (101 values, q0 = min … q100 = max of
 *  the uniformly sampled league's projected totals). Lets the rail's ring
 *  follow a client-side total (captain swap, bench edit) without a request.
 *  Floored at 1 so it never reads "top 0%". */
const FLOOR = 1;

export function percentileFromQuantiles(quantiles: ReadonlyArray<number> | null | undefined, points: number | null | undefined): number | undefined {
  if (!quantiles || quantiles.length !== 101 || typeof points !== "number" || !Number.isFinite(points)) return undefined;
  if (quantiles.some((v) => typeof v !== "number" || !Number.isFinite(v))) return undefined;
  if (points < quantiles[0]) return 100;
  if (points >= quantiles[100]) return FLOOR;
  let i = 0;
  while (i < 100 && quantiles[i + 1] <= points) i++;
  const lo = quantiles[i];
  const hi = quantiles[i + 1];
  const frac = hi > lo ? (points - lo) / (hi - lo) : 0;
  return Math.max(FLOOR, 100 - (i + frac));
}
