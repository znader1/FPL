// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { getInitialEntryId, parseEntryIdInput } from "../entryId";

describe("parseEntryIdInput", () => {
  it("parses plain digits", () => {
    expect(parseEntryIdInput("588004")).toBe(588004);
  });
  it("parses digits with surrounding whitespace", () => {
    expect(parseEntryIdInput("  588004  ")).toBe(588004);
  });
  it("parses a pasted FPL URL", () => {
    expect(
      parseEntryIdInput("https://fantasy.premierleague.com/entry/588004/event/38")
    ).toBe(588004);
  });
  it("parses an entry URL without event suffix", () => {
    expect(parseEntryIdInput("fantasy.premierleague.com/entry/12345/")).toBe(12345);
  });
  it("rejects garbage", () => {
    expect(parseEntryIdInput("my team")).toBeNull();
  });
  it("rejects zero and negatives", () => {
    expect(parseEntryIdInput("0")).toBeNull();
    expect(parseEntryIdInput("-5")).toBeNull();
  });
  it("rejects empty", () => {
    expect(parseEntryIdInput("")).toBeNull();
  });
  it("rejects decimals", () => {
    expect(parseEntryIdInput("58.4")).toBeNull();
  });
});

describe("getInitialEntryId", () => {
  it("prefers ?entry_id, then localStorage, else 0 (shared by Index, Fixtures, League)", () => {
    localStorage.removeItem("fpl_entry_id");
    expect(getInitialEntryId("?entry_id=588004")).toBe(588004);
    localStorage.setItem("fpl_entry_id", "12");
    expect(getInitialEntryId("?entry_id=0")).toBe(12);
    expect(getInitialEntryId("")).toBe(12);
    localStorage.setItem("fpl_entry_id", "junk");
    expect(getInitialEntryId("")).toBe(0);
  });
});
