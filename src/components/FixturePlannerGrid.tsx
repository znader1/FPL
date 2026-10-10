import { JerseyIcon } from "@/components/JerseyIcon";
import { FixtureChip } from "@/components/FixtureChip";
import { totalTone, type ColumnTag, type PlannerRow } from "@/lib/fixturePlanner";

interface FixturePlannerGridProps {
  rows: PlannerRow[];
  gws: number[];
  horizon: number;
  tags: Array<{ gw: number; tag: ColumnTag }>;
}

const TOTAL_TONE: Record<ReturnType<typeof totalTone>, string> = {
  hot: "text-primary",
  cold: "text-fdr-4",
  neutral: "text-foreground",
};

const CELL_BG: Record<number, string> = {
  1: "bg-fdr-1/[0.14]",
  2: "bg-fdr-2/[0.14]",
  3: "bg-fdr-3/[0.14]",
  4: "bg-fdr-4/[0.14]",
  5: "bg-fdr-5/[0.14]",
};

/** The 6-GW heatmap of all 15: one row per player, one tinted cell per GW with
 *  the fixture chip(s) over that GW's xPts, and the horizon total on the right. */
export function FixturePlannerGrid({ rows, gws, horizon, tags }: FixturePlannerGridProps) {
  const tagByGw = new Map(tags.map((t) => [t.gw, t.tag]));
  return (
    <table data-testid="planner-grid" className="w-full border-separate [border-spacing:4px_0] text-sm" style={{ minWidth: 170 + gws.length * 72 + 64 }}>
      <thead>
        <tr>
          <th scope="col" className="w-[170px] pb-1.5 text-left align-bottom text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">
            Player
          </th>
          {gws.map((gw, i) => {
            const tag = tagByGw.get(gw) ?? null;
            return (
              <th
                key={gw}
                scope="col"
                className={`pb-1.5 align-bottom text-center ${i < horizon ? "" : "opacity-35"}`}
              >
                <div className="flex h-[18px] items-center justify-center">
                  {tag && (
                    <span
                      className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold tracking-[.04em] text-white ${
                        tag === "DGW" ? "bg-accent" : "bg-fdr-4"
                      }`}
                    >
                      {tag}
                    </span>
                  )}
                </div>
                <span className="text-xs font-bold text-foreground">GW{gw}</span>
              </th>
            );
          })}
          <th scope="col" className="w-16 pb-1.5 pr-1 text-right align-bottom text-[10px] font-semibold uppercase tracking-[.08em] text-muted-foreground">
            xPts
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const visible = r.cells.filter((c) => c.inHorizon).length || 1;
          const tone = TOTAL_TONE[totalTone(r.total === null ? null : r.total / visible)];
          return (
            <tr
              key={r.playerId}
              data-gap={r.gapBefore}
              className="group rounded-[10px] transition-colors hover:bg-muted/50"
            >
              <td className={`rounded-l-[10px] py-1 pl-1.5 pr-1 ${r.gapBefore ? (r.gapBefore === 14 ? "pt-[18px]" : "pt-3") : ""}`}>
                <div className="flex items-center gap-2">
                  <JerseyIcon team={r.team} size="sm" />
                  <div className="min-w-0">
                    <div className={`truncate text-[13px] font-semibold ${r.isBench ? "text-muted-foreground" : "text-foreground"}`}>
                      {r.name}
                      {r.isCaptain ? " (C)" : ""}
                    </div>
                    <div className="text-[10px] text-muted-foreground">{r.isBench ? `Bench · ${r.pos}` : r.pos}</div>
                  </div>
                </div>
              </td>
              {r.cells.map((c) => {
                const fdr = c.fixtures[0]?.fdr;
                return (
                  <td key={c.gw} className={`py-1 ${r.gapBefore ? (r.gapBefore === 14 ? "pt-[18px]" : "pt-3") : ""}`}>
                    <div
                      data-testid="planner-cell"
                      className={`flex min-h-[46px] flex-col items-center justify-center gap-[3px] rounded-lg px-0.5 py-1.5 transition-opacity duration-200 ${
                        c.blank ? "bg-fdr-4/[0.06]" : CELL_BG[fdr ?? 3]
                      } ${c.inHorizon ? "" : "opacity-30"}`}
                    >
                      {c.blank ? (
                        <span className="text-[10px] font-bold tracking-[.06em] text-fdr-4">BLANK</span>
                      ) : (
                        <>
                          <span className="flex flex-wrap items-center justify-center gap-0.5">
                            {c.fixtures.map((f, i) => (
                              <FixtureChip key={i} opponent={f.opponent} isHome={f.isHome} difficulty={f.fdr} />
                            ))}
                          </span>
                          <span className="text-[11px] font-bold tabular-nums text-foreground">
                            {typeof c.xpts === "number" ? c.xpts.toFixed(1) : "—"}
                          </span>
                        </>
                      )}
                    </div>
                  </td>
                );
              })}
              <td
                data-testid="row-total"
                className={`rounded-r-[10px] py-1 pr-1 text-right text-[15px] font-black tabular-nums ${tone} ${
                  r.gapBefore ? (r.gapBefore === 14 ? "pt-[18px]" : "pt-3") : ""
                }`}
              >
                {r.total === null ? "—" : r.total.toFixed(1)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
