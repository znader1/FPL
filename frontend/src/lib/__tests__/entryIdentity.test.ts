import { describe, expect, it } from "vitest";
import { checkEntryIdentity, rolloverMessage } from "@/lib/entryIdentity";
import type { FplEntryIdentity } from "@/lib/fplAssistantApi";

const ziad: FplEntryIdentity = {
  entry_id: 588004,
  manager_name: "Ziad Nader",
  team_name: "ZN Elite",
  joined_time: "2025-07-21T17:40:54.591240Z",
};

// Same id, next season, different human — the real observed rollover.
const stranger: FplEntryIdentity = {
  entry_id: 588004,
  manager_name: "Jon Snow",
  team_name: "Stach 'n' Cheese",
  joined_time: "2026-07-23T20:52:58.603458Z",
};

const storedZiad = {
  managerName: "Ziad Nader",
  teamName: "ZN Elite",
  joinedTime: "2025-07-21T17:40:54.591240Z",
};

describe("checkEntryIdentity", () => {
  it("passes when the id still resolves to the same manager", () => {
    expect(checkEntryIdentity(storedZiad, ziad).status).toBe("ok");
  });

  it("flags a rollover when joined_time changed", () => {
    const check = checkEntryIdentity(storedZiad, stranger);
    expect(check.status).toBe("rolled-over");
    expect(check.currentManager).toBe("Jon Snow");
  });

  it("does not flag a rollover when only the team was renamed", () => {
    // Managers rename teams mid-season; treating that as a rollover would lock
    // them out of their own squad.
    const renamed: FplEntryIdentity = { ...ziad, team_name: "ZN Elite 2.0" };
    expect(checkEntryIdentity(storedZiad, renamed).status).toBe("ok");
  });

  it("falls back to manager name for rows linked before the snapshot existed", () => {
    const legacy = { managerName: "Ziad Nader" };
    expect(checkEntryIdentity(legacy, ziad).status).toBe("ok");
    expect(checkEntryIdentity(legacy, stranger).status).toBe("rolled-over");
  });

  it("compares manager names case-insensitively", () => {
    const legacy = { managerName: "ziad nader" };
    expect(checkEntryIdentity(legacy, ziad).status).toBe("ok");
  });

  it("returns unknown when there is no stored snapshot", () => {
    expect(checkEntryIdentity(null, ziad).status).toBe("unknown");
    expect(checkEntryIdentity({}, ziad).status).toBe("unknown");
  });

  it("returns unknown when the lookup failed, rather than blocking", () => {
    // A false rollover is worse than a missed one — it hides a correct squad.
    expect(checkEntryIdentity(storedZiad, null).status).toBe("unknown");
  });

  it("ignores blank strings on either side", () => {
    expect(checkEntryIdentity({ managerName: "  " }, ziad).status).toBe("unknown");
    expect(
      checkEntryIdentity(storedZiad, { entry_id: 1, manager_name: "", joined_time: "" }).status,
    ).toBe("unknown");
  });
});

describe("rolloverMessage", () => {
  it("names the new owner and says where to find the right ID", () => {
    const message = rolloverMessage(checkEntryIdentity(storedZiad, stranger));
    expect(message).toContain("Jon Snow");
    expect(message).toContain("Points tab");
  });

  it("stays readable when the new owner is unknown", () => {
    const message = rolloverMessage({ status: "rolled-over" });
    expect(message).toContain("new IDs each season");
    expect(message).not.toContain("undefined");
  });
});
