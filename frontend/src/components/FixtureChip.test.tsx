// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FixtureChip } from "./FixtureChip";

afterEach(cleanup);

describe("FixtureChip", () => {
  it("renders H-/A- opponent with the difficulty tone", () => {
    render(<FixtureChip opponent="BOU" isHome difficulty={2} />);
    const chip = screen.getByText("H-BOU(D2)");
    expect(chip.className).toContain("fdr-2");
    expect(chip.getAttribute("title")).toBe("FDR 2");
  });
  it("appends the extra-fixture count and takes a raw label", () => {
    render(<FixtureChip opponent="WOL" isHome={false} difficulty={4} extraCount={1} />);
    expect(screen.getByText("A-WOL(D4) +1")).toBeTruthy();
    cleanup();
    render(<FixtureChip label="BHA (H)" />);
    expect(screen.getByText("BHA (H)").className).toContain("muted");
  });
});
