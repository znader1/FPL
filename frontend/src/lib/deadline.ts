/** `1d 04:12:33`, or `04:12:33` once under a day. Floors to whole seconds, never negative. */
export const formatCountdown = (ms: number): string => {
  const total = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const z = (n: number) => String(n).padStart(2, "0");
  const hms = `${z(h)}:${z(m)}:${z(s)}`;
  return d > 0 ? `${d}d ${hms}` : hms;
};

const HAS_ZONE = /(Z|[+-]\d{2}:?\d{2})$/i;

/** Milliseconds from `now` to the deadline; null when absent or unparseable.
 *  A bare ISO timestamp (no zone) is read as UTC — the backend's `deadline_time_utc`
 *  is UTC by name, and JS would otherwise parse it as local time. */
export const remainingMs = (deadlineIso: string | null | undefined, now: number): number | null => {
  const t = parseDeadline(deadlineIso);
  return t === null ? null : t - now;
};

/** The deadline as epoch ms under the same zone rule as the countdown — the one
 *  parser for anything that displays the instant. Null when absent or unparseable. */
export const parseDeadline = (deadlineIso: string | null | undefined): number | null => {
  if (!deadlineIso) return null;
  const iso = HAS_ZONE.test(deadlineIso) ? deadlineIso : `${deadlineIso}Z`;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
};
