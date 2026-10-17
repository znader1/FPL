import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CaptainCard } from "@/components/CaptainCard";
import type { CaptainGoal, CaptainLab } from "@/lib/captainLab";

interface CaptainStepProps {
  lab: CaptainLab;
  goal: CaptainGoal;
  onGoal: (goal: CaptainGoal) => void;
  onMakeCaptain: (id: number) => void;
  onMakeVice: (id: number) => void;
}

/** Step 2: the Captain Lab's three cards with Make captain / Make vice buttons. */
export function CaptainStep({ lab, goal, onGoal, onMakeCaptain, onMakeVice }: CaptainStepProps) {
  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">Your goal this week</span>
        <ToggleGroup
          type="single"
          value={goal}
          onValueChange={(v) => (v === "safe" || v === "chase") && onGoal(v)}
          aria-label="Captaincy goal"
          className="min-w-[260px] whitespace-nowrap rounded-lg border border-border bg-card p-0.5"
        >
          <ToggleGroupItem value="safe" className="h-8 flex-1 rounded-md px-3 text-xs font-semibold data-[state=on]:bg-primary data-[state=on]:text-white">
            Protect rank
          </ToggleGroupItem>
          <ToggleGroupItem value="chase" className="h-8 flex-1 rounded-md px-3 text-xs font-semibold data-[state=on]:bg-primary data-[state=on]:text-white">
            Chase rank
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      {!lab.rankAware && (
        <p className="text-xs text-muted-foreground/80">Rank-aware picks need ownership data from the backend; until then both goals use the projection.</p>
      )}
      <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(240px,1fr))]">
        {lab.candidates.map((c) => (
          <CaptainCard
            key={c.id}
            c={c}
            role={c.id === lab.captainId ? "C" : c.id === lab.viceId ? "VC" : null}
            znPick={c.id === lab.znPickId}
            ownershipBasis={lab.ownershipBasis}
            eoEventId={lab.eoEventId}
            onMakeCaptain={onMakeCaptain}
            onMakeVice={onMakeVice}
          />
        ))}
      </div>
    </div>
  );
}
