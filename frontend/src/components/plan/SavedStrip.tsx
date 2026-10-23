interface SavedStripProps {
  gw: number;
}

/** One-line "saved" strip above the squad on desktop. Replaces the eyebrow /
 *  title / paragraph / banner stack so the pitch starts higher — the navbar
 *  pill and the footer already say "Plan saved", this only adds the reopen rule. */
export function SavedStrip({ gw }: SavedStripProps) {
  return (
    <div role="status" className="flex items-center gap-2.5 rounded-xl border border-accent/40 bg-accent/[0.08] px-3.5 py-2 text-[13px] text-foreground">
      <span aria-hidden className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent text-[11px] font-bold text-white">✓</span>
      <span>
        <span className="font-semibold">GW{gw} plan saved</span>
        <span className="text-muted-foreground"> · any edit reopens it until the deadline</span>
      </span>
    </div>
  );
}
