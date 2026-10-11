import { ArrowRight, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { JerseyIcon } from "@/components/JerseyIcon";
import { fmtGain } from "@/lib/format";
import type { TransferOptions } from "@/lib/planFlow";
import { RadioCard, RadioDot } from "./RadioCard";

interface TransfersStepProps {
  /** Null until the recommendation has answered. */
  options: TransferOptions | null;
  value: "make" | "roll" | null;
  onPick: (choice: "make" | "roll") => void;
  loading?: boolean;
}

/** Step 1: "Make the move" (the verdict's moves) vs "Roll the transfer", as two radio cards. */
export function TransfersStep({ options, value, onPick, loading = false }: TransfersStepProps) {
  if (!options) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-2xl border border-border bg-card p-10 text-sm text-muted-foreground">
        {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
        {loading ? "ZN Pick is working out your moves…" : "Run ZN Pick to see your moves."}
      </div>
    );
  }
  const { make, roll, alsoConsidered } = options;
  return (
    <div className="flex flex-col gap-3.5">
      <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(260px,1fr))]">
        <RadioCard checked={value === "make"} disabled={!make} onPick={() => onPick("make")} label="Make the move">
          <div className="flex items-center gap-2.5">
            <RadioDot checked={value === "make"} />
            <span className="flex-1 text-base font-extrabold text-foreground">Make the move</span>
            {make?.zn && <Badge className="bg-primary text-white hover:bg-primary">ZN Pick</Badge>}
          </div>
          {make ? (
            <>
              {make.moves.map((m) => (
                <div key={`${m.sell.id}-${m.buy.id}`} className="flex items-center gap-1.5">
                  <JerseyIcon team={m.sell.team} size="sm" />
                  <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                  <JerseyIcon team={m.buy.team} size="sm" />
                  <span className="ml-1 text-[13px]">
                    <span className="text-muted-foreground line-through">{m.sell.name}</span> <b>{m.buy.name}</b>
                  </span>
                </div>
              ))}
              <div className="flex items-baseline gap-2">
                <span className={`text-[34px] font-black leading-none tracking-tight tabular-nums ${make.gain >= 0 ? "text-accent" : "text-fdr-4"}`}>{fmtGain(make.gain)}</span>
                <span className="text-xs text-muted-foreground">{make.meta}</span>
              </div>
              <p className="text-[13px] leading-relaxed text-foreground/80">{make.why}</p>
            </>
          ) : (
            <p className="text-[13px] text-muted-foreground">No move clears the bar</p>
          )}
        </RadioCard>

        <RadioCard checked={value === "roll"} onPick={() => onPick("roll")} label="Roll the transfer">
          <div className="flex items-center gap-2.5">
            <RadioDot checked={value === "roll"} />
            <span className="flex-1 text-base font-extrabold text-foreground">Roll the transfer</span>
            {roll.zn && <Badge className="bg-primary text-white hover:bg-primary">ZN Pick</Badge>}
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-[34px] font-black leading-none tracking-tight tabular-nums text-foreground">{fmtGain(roll.gain)}</span>
            <span className="text-xs text-muted-foreground">{roll.meta}</span>
          </div>
          <p className="text-[13px] leading-relaxed text-foreground/80">{roll.why}</p>
        </RadioCard>
      </div>

      {alsoConsidered.map((a) => (
        <div key={`${a.sell}-${a.buy}`} className="flex flex-wrap items-center gap-2.5 rounded-xl border border-border px-3.5 py-3 text-xs text-muted-foreground">
          <span className="text-[10px] font-semibold uppercase tracking-[.08em]">Also considered</span>
          <span className="flex-1">
            {a.sell} → {a.buy}
            {a.hit ? " · −4 hit" : ""} · net <b className={a.net < 0 ? "text-fdr-4" : "text-foreground"}>{fmtGain(a.net)}</b>
          </span>
          <span>below the {fmtGain(a.bar)} bar</span>
        </div>
      ))}
    </div>
  );
}
