import { useQuery } from "@tanstack/react-query";
import { fetchNextEvent, type FplNextEventSummary } from "@/lib/fplAssistantApi";
import { useCountdown } from "@/hooks/useCountdown";
import { formatCountdown } from "@/lib/deadline";

/** Navbar pill: pulsing dot · "GW29 deadline" · `1d 04:12:33`, ticking every second.
 *  Shares the `["next-event"]` cache entry with Index, so it costs no extra request.
 *  Renders nothing with no upcoming deadline or once it has passed. */
export function DeadlineCountdown() {
  const { data } = useQuery<FplNextEventSummary>({
    queryKey: ["next-event"],
    queryFn: ({ signal }) => fetchNextEvent(signal),
    staleTime: 5 * 60_000,
  });
  const remaining = useCountdown(data?.deadline_time_utc);
  if (remaining === null || remaining <= 0 || typeof data?.event_id !== "number") return null;

  return (
    <div
      data-testid="deadline-pill"
      className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full border border-primary/35 bg-primary/10 px-3 py-1.5 text-xs"
      title={`Deadline ${new Date(data.deadline_time_utc as string).toLocaleString()}`}
    >
      <span aria-hidden className="h-[7px] w-[7px] rounded-full bg-primary animate-fpl-pulse" />
      <span className="font-semibold text-foreground">GW{data.event_id} deadline</span>
      <span className="font-bold tabular-nums text-primary">{formatCountdown(remaining)}</span>
    </div>
  );
}
