import { Badge } from "@/components/ui/badge";
import { JerseyIcon } from "./JerseyIcon";
import type { FplPosition, FplTransfersRecommendation } from "@/lib/fplAssistantApi";

const POSITION_ORDER: FplPosition[] = ["GKP", "DEF", "MID", "FWD"];

const formatMoney = (value?: number) => {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const fixed = value.toFixed(1).replace(/\.0$/, "");
  return `£${fixed}m`;
};

const round1 = (value: number) => Math.round(value * 10) / 10;

const formatPoints = (value?: number, withSign = false) => {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const rounded = round1(value);
  if (withSign) return `${rounded >= 0 ? "+" : ""}${rounded}`;
  return String(rounded);
};

interface HotTargetsProps {
  hotByPosition?: FplTransfersRecommendation["hot_by_position"];
}

/** The transfer market's hot picks by position — extracted off the Transfer
 * Planner card (which is now a shell for the decision card) onto Watchlist,
 * where "who's worth watching" belongs. */
export function HotTargets({ hotByPosition }: HotTargetsProps) {
  const hotRows = POSITION_ORDER
    .map((position) => ({
      position,
      players: Array.isArray(hotByPosition?.[position]) ? hotByPosition![position]! : [],
    }))
    .filter((row) => row.players.length > 0);

  if (hotRows.length === 0) return null;

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Hot targets</p>
      {hotRows.map(({ position, players }) => (
        <div key={position} className="rounded-xl border border-border bg-card/50 p-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-2">{position}</p>
          <div className="space-y-2">
            {players.slice(0, 3).map((player) => {
              const hasXpts = typeof player.xpts === "number";
              const hasHorizon = typeof player.xpts_horizon === "number";
              return (
                <div key={player.id} className="flex items-center gap-2">
                  <JerseyIcon team={player.team} size="sm" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-foreground truncate">{player.name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {player.team} · {formatMoney(player.price)}
                      {player.next_fixture ? ` · ${player.next_fixture}` : ""}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    {hasXpts ? (
                      <>
                        <p className="text-sm font-bold text-primary leading-none">
                          {formatPoints(player.xpts)} xPts
                        </p>
                        {hasHorizon && (
                          <p className="text-[10px] text-muted-foreground mt-0.5">
                            {formatPoints(player.xpts_horizon)} horizon
                          </p>
                        )}
                      </>
                    ) : typeof player.transfer_score === "number" ? (
                      <Badge variant="outline" className="text-xs">
                        score {formatPoints(player.transfer_score)}
                      </Badge>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
