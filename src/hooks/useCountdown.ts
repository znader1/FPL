import { useEffect, useState } from "react";
import { remainingMs } from "@/lib/deadline";

/** Milliseconds until `deadlineIso`, re-read every second; null without a deadline.
 *  The interval stops once the countdown hits zero. */
export function useCountdown(deadlineIso: string | null | undefined): number | null {
  const [now, setNow] = useState(() => Date.now());
  const remaining = remainingMs(deadlineIso, now);
  const running = remaining !== null && remaining > 0;

  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [deadlineIso, running]);

  if (remaining === null) return null;
  return Math.max(0, remaining);
}
