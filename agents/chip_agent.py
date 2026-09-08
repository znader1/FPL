"""
Chip Strategy Agent — LLM wrapper over src/chip_advisor.py.

Wraps the deterministic chip recommendation engine with Claude so it can:
  - Reason about whether to play a chip THIS GW vs hold
  - Cite specific facts from the advisor output
  - Explain risks in natural language

Usage:
    from agents.chip_agent import run_chip_agent
    advice = run_chip_agent(squad, current_gw, gw_projections, chips_remaining)
    print(advice)
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import pandas as pd
from anthropic import Anthropic

from src.chip_advisor import build_chip_plan


MODEL = "claude-haiku-4-5-20251001"  # fast specialist; Sonnet is overkill here
SYSTEM_PROMPT_PATH = Path(__file__).parent / "chip_agent.md"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""

TOOLS = [
    {
        "name": "get_chip_recommendations",
        "description": (
            "Returns the full chip plan from the deterministic engine: model-zone "
            "EV recommendations (chip, target gameweek, ev_gain, reasons, ev_curve), "
            "structural provisional windows for chips beyond the model horizon "
            "(e.g. a known double gameweek), each chip's expiry deadline (phase 1 "
            "vs phase 2), a nudge flagging if a chip should be played THIS gameweek, "
            "and transfer_context. Grounds chip advice in the same plan the UI shows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "current_gw": {
                    "type": "integer",
                    "description": "The current gameweek the user is deciding for",
                },
                "gws_ahead": {
                    "type": "integer",
                    "description": "How many future GWs to evaluate (default 5)",
                    "default": 5,
                },
            },
            "required": ["current_gw"],
        },
    },
]


def _handle_tool_call(
    name: str,
    args: dict,
    squad: pd.DataFrame,
    gw_projections: dict,
    chips_remaining: list[str],
    chips_played: list | None = None,
    bank_m: float = 0.0,
    fixtures: pd.DataFrame | None = None,
    breaks: dict[int, dict] | None = None,
) -> dict:
    """Route tool calls to the deterministic advisor.

    bank_m / fixtures ground the tool call the same way the REST /chips/plan
    route does (itb_m for wildcard/free-hit budget, fixtures for the
    structural DGW/BGW zone) — without them the chat agent was silently
    working off a bank_m=0 / no-fixtures plan that could disagree with what
    the UI shows for the same entry.

    breaks: {event_id: {"gap_days", "prev_event"}} for GWs right after an
    international break (src.breaks.international_break_gws). Threaded into
    build_chip_plan so its confidence haircut / "wait_for_team_news" nudge
    flag apply here too, and surfaced (stringified keys, for JSON) directly
    in the payload so the agent can cite it even when the affected GW isn't
    the top-ranked recommendation.
    """
    if name == "get_chip_recommendations":
        result = build_chip_plan(
            squad=squad,
            current_gw=int(args["current_gw"]),
            gw_projections=gw_projections,
            chips_played=chips_played or [],
            itb_m=float(bank_m or 0.0),
            fixtures=fixtures,
            horizon_gws=int(args.get("gws_ahead", 5)) + 1,
            breaks=breaks,
        )
        if breaks:
            result["breaks"] = {str(k): v for k, v in breaks.items()}
        return result
    raise ValueError(f"Unknown tool: {name}")


def run_chip_agent(
    squad: pd.DataFrame,
    current_gw: int,
    gw_projections: dict,
    chips_remaining: list[str],
    verbose: bool = False,
    extra_context: str | None = None,
    chips_played: list | None = None,
    bank_m: float = 0.0,
    fixtures: pd.DataFrame | None = None,
    breaks: dict[int, dict] | None = None,
) -> str:
    """
    Entry point. Returns a natural-language recommendation string.

    squad: DataFrame with player_id, name, pos, team, price_m
    gw_projections: dict {gw: market_df}
    chips_remaining: list like ["wildcard", "free_hit", "bench_boost", "triple_captain"]
        (still used for the user-message text below)
    chips_played: raw chip-play records (as returned by the FPL entry-history
        endpoint's "chips" key) — threaded to the tool so it can derive
        per-chip availability/expiry windows via build_chip_plan.
    bank_m: in-the-bank cash (itb_m) — threaded to the tool so WC/FH budget
        matches the REST /chips/plan route instead of defaulting to 0.
    fixtures: fixtures DataFrame — threaded to the tool so the structural
        DGW/BGW zone beyond the model horizon is available to the agent too.
    breaks: international-break map ({event_id: {"gap_days", "prev_event"}})
        — threaded to the tool so the chat agent's advice reflects the same
        break-aware confidence haircut and post-break "hold for team news"
        nudge as the REST /chips/plan route.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")

    client = Anthropic(api_key=api_key)

    user_msg = (
        f"Current GW: {current_gw}\n"
        f"Chips still available: {', '.join(chips_remaining)}\n"
        f"Squad size: {len(squad)} players\n"
    )
    if extra_context:
        user_msg += f"\n{extra_context}\n"
    user_msg += "\nShould I play a chip this GW, or hold? Use the tool to see options."

    messages = [{"role": "user", "content": user_msg}]

    for iteration in range(5):  # safety cap on tool-use loops
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if verbose:
            print(f"[iter {iteration}] stop_reason={response.stop_reason}")

        if response.stop_reason == "tool_use":
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            tool_results = []
            for tu in tool_uses:
                if verbose:
                    print(f"  → tool: {tu.name}({dict(tu.input)})")
                result = _handle_tool_call(
                    tu.name, dict(tu.input),
                    squad, gw_projections, chips_remaining,
                    chips_played,
                    bank_m=bank_m,
                    fixtures=fixtures,
                    breaks=breaks,
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result),
                })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        # Stopped — extract text
        text_blocks = [b.text for b in response.content if b.type == "text"]
        return "\n".join(text_blocks).strip()

    return "Agent exceeded tool-call iteration limit without producing a final answer."
