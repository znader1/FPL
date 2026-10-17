import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * Guard against shipping marketing claims the product does not implement
 * (audit finding U8).
 *
 * - "projected rank gain": no rank_gain / projected_rank field exists anywhere
 *   in the frontend or the backend — grep returns zero hits in both repos.
 * - "fine-tuned": the LLM is stock claude-haiku-4-5 driven by prompts
 *   (src/explainer.py), not a fine-tuned model.
 * - "Win your FPL league": an outcome guarantee for a projection tool.
 * - "Ready for the new season": the 2026/27 season is already underway.
 *
 * Free, these are puff. Charged for, they are consumer-protection exposure.
 */
const landing = readFileSync(
  join(__dirname, "..", "..", "pages", "Landing.tsx"),
  "utf8",
);

describe("Landing page claims match what is built", () => {
  it("does not promise projected rank gain", () => {
    expect(landing).not.toMatch(/projected rank gain/i);
  });

  it("does not claim a fine-tuned model", () => {
    expect(landing).not.toMatch(/fine-tuned/i);
  });

  it("does not guarantee winning a league", () => {
    expect(landing).not.toMatch(/win your fpl league/i);
  });

  it("does not describe the live season as upcoming", () => {
    expect(landing).not.toMatch(/ready for the new season/i);
  });

  it("still names the features that do exist", () => {
    expect(landing).toMatch(/free transfer/i);
    expect(landing).toMatch(/xPts/);
  });
});
