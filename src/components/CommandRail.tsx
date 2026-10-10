import { useState } from "react";
import { ChevronDown, Sliders } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { WeekChecklist } from "@/components/WeekChecklist";
import { ProjectedCard } from "@/components/ProjectedCard";
import { ParameterForm, type ParameterFormProps } from "@/components/ParameterForm";
import type { WeekDecision } from "@/lib/weekDecisions";

interface CommandRailProps {
  decisions: WeekDecision[];
  gw: number;
  projected?: number;
  delta?: number;
  percentile?: number;
  top10kAvg?: number;
  overallAvg?: number;
  parameters: ParameterFormProps;
}

/** The Command Center's left rail (desktop): this week's checklist, the projected
 *  score, and the recommendation parameters folded away underneath. The old
 *  icon sidebar put settings first; the week's decisions are what the manager
 *  came for, so they lead. */
export function CommandRail({ decisions, gw, projected, delta, percentile, top10kAvg, overallAvg, parameters }: CommandRailProps) {
  const [open, setOpen] = useState(false);
  return (
    <aside className="flex w-[240px] shrink-0 flex-col gap-5 overflow-y-auto border-r border-sidebar-border bg-sidebar px-4 py-5 xl:w-[280px]">
      <WeekChecklist decisions={decisions} />
      <ProjectedCard gw={gw} projected={projected} delta={delta} percentile={percentile} top10kAvg={top10kAvg} overallAvg={overallAvg} />
      <Collapsible open={open} onOpenChange={setOpen} className="-mx-4 mt-auto border-t border-sidebar-border">
        <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-3 text-xs font-semibold text-sidebar-foreground/70 transition-colors hover:text-sidebar-foreground">
          <Sliders className="h-3.5 w-3.5 text-sidebar-primary" />
          Parameters
          <ChevronDown className={`ml-auto h-3.5 w-3.5 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <ParameterForm {...parameters} />
        </CollapsibleContent>
      </Collapsible>
    </aside>
  );
}
