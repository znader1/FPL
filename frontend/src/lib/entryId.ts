export const ENTRY_ID_STORAGE_KEY = "fpl_entry_id";

/** The entry to open with: `?entry_id=` on the URL, else the stored one, else 0
 *  (which Index reads as "show onboarding"). One rule for every hub page. */
export const getInitialEntryId = (search: string = window.location.search): number => {
  const fromQuery = Number(new URLSearchParams(search).get("entry_id"));
  if (Number.isFinite(fromQuery) && fromQuery > 0) return fromQuery;
  const fromStorage = Number(localStorage.getItem(ENTRY_ID_STORAGE_KEY));
  if (Number.isFinite(fromStorage) && fromStorage > 0) return fromStorage;
  return 0;
};

/**
 * Parse raw user input into an FPL entry ID.
 * Accepts plain digits ("588004") or a pasted FPL URL
 * ("https://fantasy.premierleague.com/entry/588004/event/38").
 * Returns null when no valid positive integer ID can be extracted.
 */
export const parseEntryIdInput = (raw: string): number | null => {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  const urlMatch = trimmed.match(/entry\/(\d+)/i);
  const candidate = urlMatch ? urlMatch[1] : trimmed;
  if (!/^\d+$/.test(candidate)) return null;

  const id = Number(candidate);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
};
