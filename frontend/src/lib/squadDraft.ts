import type {
  SquadBuildParams,
  SquadBuildResult,
  SquadPlayer,
  TeamNudge,
} from "./squadPickerApi";

export const DRAFT_STORAGE_KEY = "fpl_squad_draft";
const DRAFT_VERSION = 1;

export interface SquadDraft {
  params: SquadBuildParams;
  teamNudges: TeamNudge[];
  squadIds: number[];
  lastGood: SquadBuildResult | null;
}

const POS_ORDER: SquadPlayer["pos"][] = ["GKP", "DEF", "MID", "FWD"];

export type HandoffPlayer = Pick<
  SquadPlayer,
  "web_name" | "pos" | "team_short" | "price_m"
>;

/** Plain-text 15 grouped by position — pasteable into notes/WhatsApp while
 *  entering the team on fantasy.premierleague.com. */
export function formatSquadForClipboard(squad: HandoffPlayer[]): string {
  return POS_ORDER.map((pos) => {
    const rows = squad
      .filter((p) => p.pos === pos)
      .map((p) => `${p.web_name} (${p.team_short}) £${p.price_m.toFixed(1)}m`);
    return [pos, ...rows].join("\n");
  }).join("\n\n");
}

export function serializeDraft(draft: SquadDraft): string {
  return JSON.stringify({ v: DRAFT_VERSION, ...draft });
}

export function parseDraft(raw: string | null): SquadDraft | null {
  if (!raw) return null;
  try {
    const data = JSON.parse(raw);
    if (data?.v !== DRAFT_VERSION || !Array.isArray(data.squadIds)) return null;
    return {
      params: data.params ?? {},
      teamNudges: Array.isArray(data.teamNudges) ? data.teamNudges : [],
      squadIds: data.squadIds,
      lastGood: data.lastGood ?? null,
    };
  } catch {
    return null;
  }
}
