import { PlayerCard } from "./PlayerCard";
import { getRowGapClass } from "./PitchVisualization";
import {
  splitXiBench,
  toPitchPlayer,
  type DraftPitchPlayer,
} from "@/lib/draftPitch";

interface DraftPitchProps {
  squad: DraftPitchPlayer[];
  xiIds: Set<number>;
  captainId: number | null;
  viceId: number | null;
}

/**
 * Display-only pitch for the squad drafter: the optimized XI in formation
 * rows plus the bench. Player points show the horizon xPts, not GW points.
 * Swapping players happens in the adjacent "All players" panel.
 */
export function DraftPitch({ squad, xiIds, captainId, viceId }: DraftPitchProps) {
  const { rows, bench } = splitXiBench(squad, xiIds);
  const ids = { captainId, viceId };

  return (
    <div>
      <div
        className="relative rounded-2xl p-4 sm:p-6 overflow-hidden"
        style={{
          background: `linear-gradient(180deg,
            hsl(var(--pitch)) 0%,
            hsl(var(--pitch-dark)) 25%,
            hsl(var(--pitch)) 25.5%,
            hsl(var(--pitch-dark)) 50%,
            hsl(var(--pitch)) 50.5%,
            hsl(var(--pitch-dark)) 75%,
            hsl(var(--pitch)) 75.5%,
            hsl(var(--pitch-dark)) 100%)`,
        }}
      >
        <div
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 opacity-20"
          style={{ width: "120px", height: "120px", borderColor: "hsl(0 0% 100%)" }}
        />
        <div
          className="absolute left-0 right-0 top-1/2 h-[2px] opacity-15"
          style={{ background: "hsl(0 0% 100%)" }}
        />
        {rows.map((row, i) => (
          <div
            key={i}
            className={`flex justify-center ${getRowGapClass(row.length)} ${
              i < rows.length - 1 ? "mb-12" : ""
            } relative z-10`}
          >
            {row.map((p) => (
              <PlayerCard key={p.player_id} player={toPitchPlayer(p, ids)} />
            ))}
          </div>
        ))}
      </div>

      {bench.length > 0 && (
        <div className="mt-4 p-4 rounded-xl bg-card border border-border">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            Substitutes
          </p>
          <div className="flex flex-wrap justify-center gap-3 sm:gap-8">
            {bench.map((p) => (
              <PlayerCard key={p.player_id} player={toPitchPlayer(p, ids)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
