"""
Captain Selection Agent — LLM wrapper over src/captain_advisor.py.

Wraps the deterministic captain recommendation engine with Claude so it can:
  - Recommend captain + vice-captain in natural language
  - Cite reasoning facts from the advisor output
  - Flag risks (rotation, fixture difficulty, etc.)

Usage:
    from agents.captain_agent import run_captain_agent
    advice = run_captain_agent(starting_xi)
    print(advice)
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import pandas as pd
from anthropic import Anthropic

from src.captain_advisor import recommend_captain


MODEL = "claude-haiku-4-5-20251001"  # fast specialist
SYSTEM_PROMPT_PATH = Path(__file__).parent / "captain_agent.md"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""

TOOLS = [
    {
        "name": "get_captain_recommendations",
        "description": (
            "Returns the top-ranked captain candidates from the deterministic engine. "
            "Each item has: player name, position, team, xPts projection, captaincy "
            "score (after position multiplier + premium bonus), confidence (0-1), "
            "DGW status, and reasoning facts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "top_n": {
                    "type": "integer",
                    "description": "How many top candidates to return (default 5)",
                    "default": 5,
                },
            },
        },
    },
]


def _handle_tool_call(name: str, args: dict, starting_xi: pd.DataFrame) -> list[dict]:
    if name == "get_captain_recommendations":
        recs = recommend_captain(starting_xi, top_n=int(args.get("top_n", 5)))
        return [{
            "player_id": r.player_id,
            "name": r.name,
            "pos": r.pos,
            "team": r.team,
            "xpts": round(r.xpts, 2),
            "expected_captain_value": round(r.expected_captain_value, 2),
            "confidence": round(r.confidence, 2),
            "reasoning": r.reasoning,
        } for r in recs]
    raise ValueError(f"Unknown tool: {name}")


def run_captain_agent(
    starting_xi: pd.DataFrame,
    current_gw: int | None = None,
    tc_active: bool = False,
    verbose: bool = False,
) -> str:
    """
    Entry point. Returns a natural-language captain recommendation.

    starting_xi: DataFrame with player_id, name, pos, team, price_m, xpts,
                 and optionally fixture_count (for DGW detection)
    tc_active: whether Triple Captain chip is being played this GW
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = Anthropic(api_key=api_key)

    user_msg = f"Starting XI size: {len(starting_xi)} players\n"
    if current_gw is not None:
        user_msg += f"Current GW: {current_gw}\n"
    if tc_active:
        user_msg += "Triple Captain chip is ACTIVE this GW — captain points will be ×3\n"
    user_msg += "\nWho should I captain (and vice-captain)?"

    messages = [{"role": "user", "content": user_msg}]

    for _ in range(5):
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            tool_results = []
            for tu in tool_uses:
                if verbose:
                    print(f"  → tool: {tu.name}({dict(tu.input)})")
                result = _handle_tool_call(tu.name, dict(tu.input), starting_xi)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result),
                })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        text_blocks = [b.text for b in response.content if b.type == "text"]
        return "\n".join(text_blocks).strip()

    return "Agent exceeded iteration limit."
