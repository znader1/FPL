"""
FPL Strategy Orchestrator — top-level agent that routes user questions
to the right specialist (chip / transfer / captain agents).

Usage:
    from agents.orchestrator import run_orchestrator
    answer = run_orchestrator(
        user_question="Should I play my Wildcard this week?",
        squad=squad_df,
        market=market_df,
        starting_xi=xi_df,
        gw_projections=projs,
        current_gw=10,
        bank_m=2.0,
        free_transfers=1,
        captain_id=None,
        chips_remaining=["wildcard", "free_hit", "bench_boost", "triple_captain"],
    )
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import pandas as pd
from anthropic import Anthropic

from agents.chip_agent import run_chip_agent
from agents.transfer_agent import run_transfer_agent
from agents.captain_agent import run_captain_agent


MODEL = "claude-sonnet-4-6"
SYSTEM_PROMPT_PATH = Path(__file__).parent / "orchestrator.md"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""

TOOLS = [
    {
        "name": "ask_chip_agent",
        "description": "Route chip-related questions (WC/FH/BB/TC timing) to the chip specialist agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_gw": {"type": "integer"},
            },
            "required": ["current_gw"],
        },
    },
    {
        "name": "ask_transfer_agent",
        "description": "Route transfer questions (sell/buy/roll/hit) to the transfer specialist agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_gw": {"type": "integer"},
            },
            "required": ["current_gw"],
        },
    },
    {
        "name": "ask_captain_agent",
        "description": "Route captain/vice questions to the captain specialist agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_gw": {"type": "integer"},
                "tc_active": {"type": "boolean", "default": False},
            },
            "required": ["current_gw"],
        },
    },
]


def _handle_tool_call(name: str, args: dict, context: dict) -> str:
    if name == "ask_chip_agent":
        return run_chip_agent(
            squad=context["squad"],
            current_gw=int(args["current_gw"]),
            gw_projections=context["gw_projections"],
            chips_remaining=context["chips_remaining"],
            chips_played=context.get("chips_played"),
            bank_m=context.get("bank_m", 0.0),
            fixtures=context.get("fixtures"),
        )
    if name == "ask_transfer_agent":
        return run_transfer_agent(
            squad=context["squad"],
            market=context["market"],
            gw_projections=context["gw_projections"],
            current_gw=int(args["current_gw"]),
            bank_m=context["bank_m"],
            free_transfers=context["free_transfers"],
            captain_id=context.get("captain_id"),
        )
    if name == "ask_captain_agent":
        return run_captain_agent(
            starting_xi=context["starting_xi"],
            current_gw=int(args["current_gw"]),
            tc_active=bool(args.get("tc_active", False)),
        )
    raise ValueError(f"Unknown tool: {name}")


def run_orchestrator(
    user_question: str,
    *,
    squad: pd.DataFrame,
    market: pd.DataFrame,
    starting_xi: pd.DataFrame,
    gw_projections: dict,
    current_gw: int,
    bank_m: float,
    free_transfers: int,
    captain_id: int | None = None,
    chips_remaining: list[str] | None = None,
    chips_played: list | None = None,
    fixtures: pd.DataFrame | None = None,
    verbose: bool = False,
) -> str:
    """
    Entry point. Returns a natural-language answer to the user's question.

    chips_played: raw chip-play records (the FPL entry-history endpoint's
        "chips" key) — threaded to ask_chip_agent so the chip specialist's
        build_chip_plan tool call derives real availability/expiry instead
        of assuming every chip is still available.
    fixtures: fixtures DataFrame — threaded to ask_chip_agent so the
        structural DGW/BGW zone beyond the model horizon is available there
        too (bank_m is already threaded via the existing `bank_m` param).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = Anthropic(api_key=api_key)

    context = {
        "squad": squad,
        "market": market,
        "starting_xi": starting_xi,
        "gw_projections": gw_projections,
        "current_gw": current_gw,
        "bank_m": bank_m,
        "free_transfers": free_transfers,
        "captain_id": captain_id,
        "chips_remaining": chips_remaining or ["wildcard", "free_hit", "bench_boost", "triple_captain"],
        "chips_played": chips_played or [],
        "fixtures": fixtures,
    }

    framed = (
        f"User question: {user_question}\n\n"
        f"Context: GW{current_gw}, {free_transfers} FT, £{bank_m:.1f}m bank, "
        f"{len(chips_remaining or [])} chips remaining.\n\n"
        f"Route to the right specialist(s) and synthesize a clear answer."
    )

    messages = [{"role": "user", "content": framed}]

    for _ in range(6):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            # Handle ALL tool_use blocks in this turn (Claude may issue parallel calls)
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            tool_results = []
            for tu in tool_uses:
                if verbose:
                    print(f"  → routing to: {tu.name}({dict(tu.input)})")
                specialist_answer = _handle_tool_call(tu.name, dict(tu.input), context)
                if verbose:
                    preview = specialist_answer[:150].replace("\n", " ")
                    print(f"  ← {preview}…")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": specialist_answer,
                })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        text_blocks = [b.text for b in response.content if b.type == "text"]
        return "\n".join(text_blocks).strip()

    return "Orchestrator exceeded iteration limit."
