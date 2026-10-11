import { Button } from "@/components/ui/button";
import type { FooterSpec } from "@/lib/planFlow";

interface PlanFooterProps {
  spec: FooterSpec;
  onBack: () => void;
  onNext: () => void;
}

/** Always-present footer: Back (ghost) on every step but the first, the hint,
 *  and the primary/accent Next. Sticky on phones, full-width Next. */
export function PlanFooter({ spec, onBack, onNext }: PlanFooterProps) {
  return (
    <div className="sticky bottom-0 z-20 flex shrink-0 items-center gap-2.5 border-t border-border bg-card px-4 pb-5 pt-3 lg:px-8 lg:py-3.5">
      {spec.hasBack && (
        <Button type="button" variant="ghost" className="h-11 min-w-[44px] lg:h-10" onClick={onBack}>
          Back
        </Button>
      )}
      <span className="hidden flex-1 text-right text-xs text-muted-foreground lg:block">{spec.hint}</span>
      <div className="flex flex-1 lg:flex-none lg:basis-[200px]">
        <Button
          type="button"
          className={`h-11 w-full font-semibold lg:h-10 ${spec.variant === "accent" ? "bg-accent text-white hover:bg-accent/90" : ""}`}
          disabled={spec.disabled}
          onClick={onNext}
          title={spec.disabled && spec.hint ? spec.hint : undefined}
        >
          {spec.label}
        </Button>
      </div>
    </div>
  );
}
