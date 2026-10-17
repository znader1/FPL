import { Badge } from "@/components/ui/badge";
import { fmtGain } from "@/lib/format";
import type { PlanChip } from "@/lib/gwPlan";
import type { ChipOption } from "@/lib/planFlow";
import { RadioCard, RadioDot } from "./RadioCard";

interface ChipStepProps {
  options: ChipOption[];
  value: PlanChip;
  onPick: (chip: Exclude<PlanChip, null>) => void;
}

/** Step 4: Save / Bench Boost / Free Hit / Triple Captain / Wildcard as radio cards,
 *  each with its gain and how it compares with the chip's best week. */
export function ChipStep({ options, value, onPick }: ChipStepProps) {
  return (
    <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]">
      {options.map((o) => {
        const checked = value === o.chip;
        return (
          <RadioCard key={o.chip} checked={checked} disabled={o.used || o.disabled} onPick={() => onPick(o.chip)} label={o.title} className="gap-2 rounded-[14px] p-4">
            <div className="flex items-center gap-2">
              <RadioDot checked={checked} size={16} />
              <span className="flex-1 text-sm font-bold text-foreground">{o.title}</span>
              {o.zn && <Badge className="bg-primary text-white hover:bg-primary">ZN Pick</Badge>}
              {o.used && <Badge variant="outline" className="text-muted-foreground">Already played</Badge>}
            </div>
            <div
              className={`text-2xl font-black tabular-nums ${
                o.gain === null ? "text-muted-foreground" : o.chip === "none" || o.gain === 0 ? "text-foreground" : o.gain > 0 ? "text-accent" : "text-fdr-4"
              }`}
            >
              {o.gain === null ? "—" : fmtGain(o.gain)}
              {o.gainNote && <span className="ml-1.5 text-xs font-medium text-muted-foreground">{o.gainNote}</span>}
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">{o.why}</p>
          </RadioCard>
        );
      })}
    </div>
  );
}
