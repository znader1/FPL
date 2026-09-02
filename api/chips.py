"""GET /chips/plan — chip timing recommendations over the projection horizon."""
from __future__ import annotations
import logging
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from api.chat import _build_context_for_entry
from src import config, fpl_client, transfer_planner
from src.chip_advisor import build_chip_plan

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_current_gw() -> int:
    """Next unfinished GW from bootstrap events."""
    bootstrap = fpl_client.get_bootstrap()
    for e in bootstrap.get("events", []):
        if e.get("is_next"):
            return int(e["id"])
    for e in bootstrap.get("events", []):
        if not e.get("finished"):
            return int(e["id"])
    raise HTTPException(status_code=503, detail="No upcoming gameweek found")


def _get_entry_chips(entry_id: int) -> list[dict]:
    try:
        history = fpl_client.get_entry_history(entry_id)
        return history.get("chips") or []
    except Exception as e:  # noqa: BLE001 - degrade to "all chips available"
        logger.warning("entry history fetch failed for %s: %s", entry_id, e)
        return []


@router.get("/chips/plan")
def chips_plan(
    entry_id: int = Query(..., ge=1),
    horizon: Optional[int] = Query(None, ge=2, le=12),
):
    current_gw = _resolve_current_gw()
    model_horizon = int(horizon or getattr(config, "CHIP_PLAN_HORIZON_GWS", 8))
    ctx = _build_context_for_entry(entry_id, current_gw, horizon=model_horizon)

    # No-chip baseline: the horizon transfer plan. Planning must never fail the plan.
    transfer_plan = None
    try:
        proj_plan = ctx["proj"].copy()
        if "price_m" not in proj_plan.columns and "now_cost" in proj_plan.columns:
            proj_plan["price_m"] = pd.to_numeric(proj_plan["now_cost"], errors="coerce") / 10.0
        if "team_short" not in proj_plan.columns and "team" in proj_plan.columns:
            proj_plan["team_short"] = proj_plan["team"].map(ctx.get("teams_short_map") or {})
        gws = sorted(ctx["gw_projections"].keys())
        squad_ids = [int(x) for x in ctx["squad"]["player_id"].tolist()]
        transfer_plan = transfer_planner.plan_transfers(
            proj_plan, squad_ids, gws,
            itb_m=float(ctx["bank_m"]), start_ft=int(ctx["free_transfers"]),
            ft_cap=5, allow_hits=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("transfer plan baseline failed: %s", e)

    plan = build_chip_plan(
        squad=ctx["squad"],
        current_gw=current_gw,
        gw_projections=ctx["gw_projections"],
        chips_played=_get_entry_chips(entry_id),
        itb_m=float(ctx["bank_m"]),
        fixtures=ctx.get("fixtures"),
        transfer_plan=transfer_plan,
        horizon_gws=model_horizon,
    )
    return {"entry_id": entry_id, **plan}
