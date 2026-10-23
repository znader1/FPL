/** The backend's `H-BOU(D2)` next-fixture grammar, parsed once for the pitch
 *  cards and the captain step. Tolerant: a missing H-/A- prefix leaves `isHome`
 *  undefined and `opponent` empty; `(Dn)` is found anywhere in the string. */
export interface ParsedFixtureLabel {
  label: string;
  opponent: string;
  isHome?: boolean;
  difficulty?: number;
}

export const parseFixtureLabel = (label?: string | null): ParsedFixtureLabel | undefined => {
  if (typeof label !== "string") return undefined;
  const trimmed = label.trim();
  if (!trimmed) return undefined;
  const difficultyMatch = trimmed.match(/\(D([1-5])\)/i);
  const difficulty = difficultyMatch ? Number(difficultyMatch[1]) : undefined;
  const isHome = trimmed.startsWith("H-") ? true : trimmed.startsWith("A-") ? false : undefined;
  const opponentMatch = trimmed.match(/^[HA]-([A-Z]{2,4})/);
  return { label: trimmed, opponent: opponentMatch?.[1] ?? "", isHome, difficulty };
};
