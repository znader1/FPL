import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

/**
 * Regression guard for the light-portal bug (audit finding U2).
 *
 * `dark` was applied per page on a wrapper div, but Radix portals (dialogs,
 * selects, drawers, hover cards) mount to document.body — outside that div —
 * so every popover rendered in the light palette over a dark app. The mobile
 * parameter drawer, the GW picker, both sidebar selects and all 15 player score
 * breakdowns were affected; only OptimizeSquadDialog remembered to re-add it.
 *
 * The invariant: `dark` lives on <html> exactly once, and nowhere else.
 */
const root = join(__dirname, "..", "..", "..");

const collectTsx = (dir: string): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return collectTsx(full);
    return entry.name.endsWith(".tsx") && !entry.name.includes(".test.") ? [full] : [];
  });

/** Matches `dark` as a standalone class token, not the `dark:` variant prefix. */
const PER_PAGE_DARK = /className=(?:"|\{`)[^"`]*\bdark\b(?!:)/;

describe("dark theme is applied globally", () => {
  it("sets the dark class on <html> so portals inherit it", () => {
    const html = readFileSync(join(root, "index.html"), "utf8");
    expect(html).toMatch(/<html[^>]*\bclass="[^"]*\bdark\b/);
  });

  it("has no per-component dark wrapper left to shadow it", () => {
    const offenders = collectTsx(join(root, "src"))
      .filter((file) => PER_PAGE_DARK.test(readFileSync(file, "utf8")))
      .map((file) => file.slice(root.length + 1));

    expect(offenders).toEqual([]);
  });
});
