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

from src.chip_advisor import recommend_chips


MODEL = "claude-sonnet-4-6"  # latest Sonnet 4.x
SYSTEM_PROMPT_PATH = Path(__file__).parent / "chip_agent.md"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""

TOOLS = [
    {
        "name": "get_chip_recommendations",
        "description": (
            "Returns the top-ranked chip recommendations from the deterministic "
            "engine. Each item has: chip name, target gameweek, expected_value "
            "(extra pts vs not playing), confidence (0-1), reasoning facts."
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
) -> list[dict]:
    """Route tool calls to the deterministic advisor."""
    if name == "get_chip_recommendations":
        recs = recommend_chips(
            squad=squad,
            current_gw=int(args["current_gw"]),
            gw_projections=gw_projections,
            chips_remaining=chips_remaining,
            gws_ahead=int(args.get("gws_ahead", 5)),
        )
        return [r.to_dict() for r in recs[:10]]
    raise ValueError(f"Unknown tool: {name}")


def run_chip_agent(
    squad: pd.DataFrame,
    current_gw: int,
    gw_projections: dict,
    chips_remaining: list[str],
    verbose: bool = False,
) -> str:
    """
    Entry point. Returns a natural-language recommendation string.

    squad: DataFrame with player_id, name, pos, team, price_m
    gw_projections: dict {gw: market_df}
    chips_remaining: list like ["wildcard", "free_hit", "bench_boost", "triple_captain"]
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")

    client = Anthropic(api_key=api_key)

    user_msg = (
        f"Current GW: {current_gw}\n"
        f"Chips still available: {', '.join(chips_remaining)}\n"
        f"Squad size: {len(squad)} players\n\n"
        f"Should I play a chip this GW, or hold? Use the tool to see options."
    )

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
