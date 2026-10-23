import type { StepCopy } from "@/lib/planFlow";

interface StepHeaderProps {
  copy: StepCopy;
  /** Squad step while the plan is locked. */
  savedBanner: boolean;
}

/** Pink eyebrow, 24/32px title, one-line sub — and the teal saved banner under it. */
export function StepHeader({ copy, savedBanner }: StepHeaderProps) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[.08em] text-primary">{copy.eyebrow}</p>
        <h2 className="text-2xl font-black leading-[1.1] tracking-[-0.02em] text-foreground [text-wrap:pretty] lg:text-[32px]">{copy.title}</h2>
        <p className="mt-1.5 max-w-[620px] text-[13px] leading-relaxed text-muted-foreground">{copy.sub}</p>
      </div>
      {savedBanner && (
        <div className="flex items-center gap-2.5 rounded-xl border border-accent/40 bg-accent/[0.08] px-3.5 py-2.5 text-[13px] text-foreground">
          <span aria-hidden className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent text-[11px] font-bold text-white">✓</span>
          <span>Plan saved. Any edit reopens it until the deadline.</span>
        </div>
      )}
    </div>
  );
}
