import { describe, expect, it } from "vitest";
import { percentileFromQuantiles } from "./fieldPercentile";

// q0…q100 of a field whose projected totals run evenly from 40 to 60.
const q = Array.from({ length: 101 }, (_, i) => 40 + i * 0.2);

describe("percentileFromQuantiles", () => {
  it("reads 'top N%' = share of the field above the total, interpolating inside the grid", () => {
    expect(percentileFromQuantiles(q, 50)).toBe(50);
    expect(percentileFromQuantiles(q, 58)).toBe(10);
    expect(percentileFromQuantiles(q, 58.1)).toBeCloseTo(9.5, 5);
  });
  it("floors at 1 above the field and reads 100 below it", () => {
    expect(percentileFromQuantiles(q, 61)).toBe(1);
    expect(percentileFromQuantiles(q, 60)).toBe(1);
    expect(percentileFromQuantiles(q, 39)).toBe(100);
  });
  it("is undefined without a usable grid or total", () => {
    expect(percentileFromQuantiles(null, 50)).toBeUndefined();
    expect(percentileFromQuantiles([1, 2, 3], 50)).toBeUndefined();
    expect(percentileFromQuantiles(q, undefined)).toBeUndefined();
  });
});
