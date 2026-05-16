"""
Transfer Strategy Agent — LLM wrapper over src/transfer_advisor.py.

Wraps the deterministic transfer recommendation engine with Claude so it can:
  - Decide whether to make a transfer, roll, or take a hit
  - Cite specific facts from the advisor output
  - Reason about captain protection and chip context

Usage:
    from agents.transfer_agent import run_transfer_agent
    advice = run_transfer_agent(
        squad, market, gw_projections, current_gw, bank_m,
        free_transfers, captain_id,
    )
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import pandas as pd
from anthropic import Anthropic

from src.transfer_advisor import recommend_transfer


MODEL = "claude-haiku-4-5-20251001"  # fast specialist
SYSTEM_PROMPT_PATH = Path(__file__).parent / "transfer_agent.md"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""

TOOLS = [
    {
        "name": "get_transfer_recommendations",
        "description": (
            "Returns the top-ranked 1-for-1 transfer options from the deterministic "
            "engine. Each item has: sell player, buy player, expected_gain (over the "
            "horizon GWs), confidence (0-1), and reasoning facts (xPts breakdown, "
            "bonuses, penalties)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "current_gw": {
                    "type": "integer",
                    "description": "The current gameweek the user is deciding for",
                },
                "horizon": {
                    "type": "integer",
                    "description": "How many GWs to look ahead when scoring (default 3)",
                    "default": 3,
                },
                "min_gain": {
                    "type": "number",
                    "description": "Minimum expected gain threshold (default 0.8)",
                    "default": 0.8,
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
    market: pd.DataFrame,
    gw_projections: dict,
    bank_m: float,
    captain_id: int | None,
) -> list[dict]:
    if name == "get_transfer_recommendations":
        recs = recommend_transfer(
            squad=squad,
            market=market,
            gw_projections=gw_projections,
            current_gw=int(args["current_gw"]),
            bank_m=bank_m,
            horizon=int(args.get("horizon", 3)),
            captain_id=captain_id,
            min_gain=float(args.get("min_gain", 0.8)),
            top_n=5,
        )
        return [{
            "sell": {"id": r.sell_id, "name": r.sell_name, "pos": r.sell_pos, "price_m": r.sell_price},
            "buy": {"id": r.buy_id, "name": r.buy_name, "pos": r.buy_pos, "price_m": r.buy_price},
            "expected_gain": round(r.expected_gain, 2),
            "confidence": round(r.confidence, 2),
            "reasoning": r.reasoning,
        } for r in recs]
    raise ValueError(f"Unknown tool: {name}")


def run_transfer_agent(
    squad: pd.DataFrame,
    market: pd.DataFrame,
    gw_projections: dict,
    current_gw: int,
    bank_m: float,
    free_transfers: int,
    captain_id: int | None = None,
    upcoming_chip_gw: int | None = None,
    verbose: bool = False,
    extra_context: str | None = None,
) -> str:
    """
    Entry point. Returns a natural-language transfer recommendation string.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = Anthropic(api_key=api_key)

    captain_name = None
    if captain_id is not None:
        cap_row = squad[squad["player_id"] == captain_id]
        if not cap_row.empty:
            captain_name = cap_row.iloc[0]["name"]

    user_msg = (
        f"Current GW: {current_gw}\n"
        f"Free transfers available: {free_transfers}\n"
        f"Bank: £{bank_m:.1f}m\n"
        f"Squad size: {len(squad)} players\n"
        f"Captain: {captain_name or 'unknown'}\n"
    )
    if upcoming_chip_gw is not None:
        user_msg += f"Upcoming chip play planned at: GW{upcoming_chip_gw}\n"
    if extra_context:
        user_msg += f"\n{extra_context}\n"
    user_msg += "\nShould I make a transfer, take a hit, or roll my FT?"

    messages = [{"role": "user", "content": user_msg}]

    for _ in range(5):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
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
                result = _handle_tool_call(
                    tu.name, dict(tu.input),
                    squad, market, gw_projections, bank_m, captain_id,
                )
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
