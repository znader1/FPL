import { describe, expect, it } from "vitest";
import { compactRank } from "./format";

describe("compactRank", () => {
  it("shortens a formatted rank for narrow screens", () => {
    expect(compactRank("1,896,801")).toBe("1.9M");
    expect(compactRank("412,338")).toBe("412k");
    expect(compactRank("9,950")).toBe("9.9k");
    expect(compactRank("812")).toBe("812");
    expect(compactRank("—")).toBe("—");
  });
});
