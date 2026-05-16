"""
/chat endpoint — exposes the FPL Orchestrator agent over HTTP.

POST /chat
{
    "entry_id": 1234567,
    "message": "Should I play my Wildcard this week?",
    "current_gw": 10           // optional, defaults to next GW
}

Returns:
{
    "answer": "Hold your Wildcard for now. ...",
    "current_gw": 10,
    "latency_ms": 4123
}
"""
from __future__ import annotations
import time
import logging
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field


router = APIRouter()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    entry_id: int = Field(..., description="FPL entry/team ID")
    message: str = Field(..., min_length=1, max_length=500)
    current_gw: Optional[int] = None
    chips_remaining: Optional[list[str]] = None


class ChatResponse(BaseModel):
    answer: str
    current_gw: int
    latency_ms: int


def _build_context_for_entry(entry_id: int, current_gw: int):
    """
    Build the data context needed by the orchestrator:
    squad, market, starting_xi, gw_projections, bank, FT, captain_id.

    Uses the live FPL API + projection engine (NOT Vaastav — that's backtest-only).
    """
    # Local import to avoid circular and keep startup fast
    from src import fpl_client, transforms, projections, optimizer, config

    bootstrap = fpl_client.get_bootstrap()
    fixtures = transforms.fixtures_df(fpl_client.get_fixtures())
    elements, teams, teams_short_map = transforms.tables_from_bootstrap(bootstrap)

    # Pull entry's current picks
    try:
        picks_data = fpl_client.get_entry_picks(entry_id, current_gw)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} picks not found: {e}")

    picks = picks_data.get("picks", [])
    if not picks:
        raise HTTPException(status_code=400, detail="No picks available for this GW yet")

    entry_history = picks_data.get("entry_history", {})
    bank_m = float(entry_history.get("bank", 0)) / 10.0
    free_transfers = int(entry_history.get("event_transfers", 0))
    # Derive FT: if no transfers made in current GW → 2 next GW
    derived_ft = 2 if free_transfers == 0 else 1

    # Build squad DataFrame
    pick_ids = [int(p["element"]) for p in picks]
    captain_id = next((int(p["element"]) for p in picks if p.get("is_captain")), None)
    squad_rows = elements[elements["id"].isin(pick_ids)][
        ["id", "web_name", "team", "element_type", "now_cost"]
    ].copy()
    pos_map = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    team_name_map = dict(zip(teams["id"], teams["name"]))
    squad = pd.DataFrame({
        "player_id": squad_rows["id"].astype(int).values,
        "name": squad_rows["web_name"].values,
        "pos": squad_rows["element_type"].map(pos_map).values,
        "team": squad_rows["team"].map(team_name_map).values,
        "price_m": (squad_rows["now_cost"] / 10.0).values,
    })

    # Project next 5 GWs
    horizon = 5
    proj = projections.project_elements_next_gws(
        elements=elements, fixtures=fixtures, teams_short_map=teams_short_map,
        gw_start=current_gw, horizon_gws=horizon,
    )

    # Reshape into the simulator's market schema, one DataFrame per GW
    gw_projections = {}
    for g in range(current_gw, current_gw + horizon):
        col = f"xpts_gw{g}"
        if col not in proj.columns:
            continue
        market_g = pd.DataFrame({
            "player_id": proj["id"].astype(int).values,
            "name": proj["web_name"].values,
            "pos": (proj["pos"] if "pos" in proj.columns
                    else proj["element_type"].map(pos_map)).values,
            "team": proj["team"].map(team_name_map).values,
            "price_m": (pd.to_numeric(proj["now_cost"], errors="coerce") / 10.0).values,
            "xpts": pd.to_numeric(proj[col], errors="coerce").fillna(0).values,
            "fixture_count": 1,
        })
        gw_projections[g] = market_g

    market = gw_projections.get(current_gw)
    if market is None or market.empty:
        raise HTTPException(status_code=500, detail="Failed to build market projections")

    # Build starting XI for captain context
    squad_with_xpts = squad.merge(
        market[["player_id", "xpts", "fixture_count"]], on="player_id", how="left"
    )
    squad_with_xpts["xpts"] = squad_with_xpts["xpts"].fillna(0)
    squad_with_xpts["fixture_count"] = squad_with_xpts["fixture_count"].fillna(0).astype(int)

    # Reuse the simulator's XI picker
    from scripts.backtest_season import pick_starting_xi
    starting_xi = pick_starting_xi(squad_with_xpts)

    return {
        "squad": squad,
        "market": market,
        "starting_xi": starting_xi,
        "gw_projections": gw_projections,
        "bank_m": bank_m,
        "free_transfers": derived_ft,
        "captain_id": captain_id,
    }


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest = Body(...)):
    """Route a user question to the FPL orchestrator agent."""
    from agents.orchestrator import run_orchestrator
    from api.main import build_next_event_summary, get_bootstrap_cached, get_fixtures_cached

    t0 = time.perf_counter()

    # Resolve current GW
    if req.current_gw is None:
        summary = build_next_event_summary(
            bootstrap=get_bootstrap_cached(),
            fixtures=get_fixtures_cached(),
        )
        current_gw = summary.get("event_id") or 1
    else:
        current_gw = int(req.current_gw)

    try:
        ctx = _build_context_for_entry(req.entry_id, current_gw)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to build chat context")
        raise HTTPException(status_code=500, detail=f"Context build failed: {e}")

    try:
        answer = run_orchestrator(
            user_question=req.message,
            squad=ctx["squad"],
            market=ctx["market"],
            starting_xi=ctx["starting_xi"],
            gw_projections=ctx["gw_projections"],
            current_gw=current_gw,
            bank_m=ctx["bank_m"],
            free_transfers=ctx["free_transfers"],
            captain_id=ctx["captain_id"],
            chips_remaining=req.chips_remaining or [
                "wildcard", "free_hit", "bench_boost", "triple_captain",
            ],
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Orchestrator failed")
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    latency_ms = int((time.perf_counter() - t0) * 1000)
    return ChatResponse(answer=answer, current_gw=current_gw, latency_ms=latency_ms)
