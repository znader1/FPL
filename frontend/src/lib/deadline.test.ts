import { describe, expect, it } from "vitest";
import { formatCountdown, parseDeadline, remainingMs } from "./deadline";

describe("formatCountdown", () => {
  it("renders days, hours, minutes and seconds zero-padded", () => {
    const ms = ((1 * 86400 + 4 * 3600 + 12 * 60 + 33) * 1000);
    expect(formatCountdown(ms)).toBe("1d 04:12:33");
  });
  it("drops the day part under 24h", () => {
    expect(formatCountdown((4 * 3600 + 5 * 60 + 9) * 1000)).toBe("04:05:09");
  });
  it("floors to whole seconds and clamps at zero", () => {
    expect(formatCountdown(1999)).toBe("00:00:01");
    expect(formatCountdown(-5000)).toBe("00:00:00");
  });
});

describe("remainingMs", () => {
  const now = Date.parse("2026-10-10T12:00:00Z");
  it("uses the absolute deadline, not a stale hours figure", () => {
    expect(remainingMs("2026-10-11T16:12:33Z", now)).toBe(((28 * 3600) + 12 * 60 + 33) * 1000);
  });
  it("treats a timestamp without a zone suffix as UTC", () => {
    expect(remainingMs("2026-10-10T13:00:00", now)).toBe(3600_000);
  });
  it("exposes the parsed instant so the tooltip and the countdown agree on zone-less timestamps", () => {
    expect(parseDeadline("2026-10-10T13:00:00")).toBe(Date.parse("2026-10-10T13:00:00Z"));
    expect(parseDeadline("soon")).toBeNull();
  });
  it("returns null for a missing or unparseable deadline", () => {
    expect(remainingMs(null, now)).toBeNull();
    expect(remainingMs(undefined, now)).toBeNull();
    expect(remainingMs("soon", now)).toBeNull();
  });
});
