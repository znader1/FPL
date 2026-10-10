interface FixtureChipProps {
  /** Pre-formatted label (e.g. a backend `next_fixtures` string); wins over the parts. */
  label?: string;
  opponent?: string;
  isHome?: boolean;
  /** 1 (easiest) … 5 (hardest); untinted when absent. */
  difficulty?: number;
  /** Extra fixtures in the same GW ("+1" on a double). */
  extraCount?: number;
  className?: string;
}

const TONE: Record<number, string> = {
  1: "bg-fdr-1/15 text-fdr-1",
  2: "bg-fdr-2/15 text-fdr-2",
  3: "bg-fdr-3/15 text-fdr-3",
  4: "bg-fdr-4/15 text-fdr-4",
  5: "bg-fdr-5/20 text-fdr-5",
};

/** `H-BOU(D2)` pill tinted by difficulty — the one fixture label used on the
 *  pitch cards and in the planner grid. */
export function FixtureChip({ label, opponent, isHome, difficulty, extraCount, className = "" }: FixtureChipProps) {
  const fdr = typeof difficulty === "number" && Number.isFinite(difficulty) ? Math.round(difficulty) : undefined;
  const text =
    label ??
    `${isHome === false ? "A-" : isHome === true ? "H-" : ""}${opponent ?? ""}${fdr ? `(D${fdr})` : ""}`;
  const meta = typeof extraCount === "number" && extraCount > 0 ? ` +${extraCount}` : "";
  const tone = fdr && TONE[fdr] ? TONE[fdr] : "bg-muted/60 text-muted-foreground";
  return (
    <span
      className={`inline-block max-w-full truncate rounded-full px-1 py-0.5 text-[9px] font-medium sm:px-1.5 ${tone} ${className}`}
      title={fdr ? `FDR ${fdr}` : undefined}
    >
      {text}
      {meta}
    </span>
  );
}
