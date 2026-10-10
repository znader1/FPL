// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CommandRail } from "./CommandRail";
import type { WeekDecision } from "@/lib/weekDecisions";

afterEach(cleanup);

const decisions: WeekDecision[] = [
  { key: "transfers", label: "Transfers", value: "Run ZN Pick", done: false },
  { key: "captain", label: "Captain", value: "—", done: false },
  { key: "bench", label: "Bench order", value: "—", done: false },
  { key: "chip", label: "Chip", value: "—", done: true },
];

const params = {
  entryId: 588004,
  onEntryIdChange: vi.fn(),
  horizonGws: 3,
  onHorizonGwsChange: vi.fn(),
  chipStrategy: "none" as const,
  onChipStrategyChange: vi.fn(),
  differential: false,
  onDifferentialChange: vi.fn(),
  prioritizeInjured: true,
  onPrioritizeInjuredChange: vi.fn(),
  includeTransfers: true,
  onIncludeTransfersChange: vi.fn(),
  canRecommend: true,
  isRecommending: false,
  onRecommend: vi.fn(),
};

describe("CommandRail", () => {
  it("stacks the checklist, the projected card and a collapsed Parameters section", () => {
    render(<CommandRail decisions={decisions} gw={29} projected={66} parameters={params} />);
    expect(screen.getByText("1 of 4 decisions made")).toBeTruthy();
    expect(screen.getByText("Projected GW29")).toBeTruthy();
    expect(screen.queryByLabelText("Team Entry ID")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /parameters/i }));
    expect(screen.getByLabelText("Team Entry ID")).toBeTruthy();
  });
});
