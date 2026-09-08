"""GET /chips/plan — chip timing recommendations over the projection horizon."""
from __future__ import annotations
import logging
import math
import threading
import time
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from api.chat import _build_context_for_entry
from src import config, fpl_client, transfer_planner
from src.chip_advisor import build_chip_plan

router = APIRouter()
logger = logging.getLogger(__name__)

# A plan build runs the wildcard/free-hit optimizer ~16 times and takes
# minutes on the shared vCPU; with one uvicorn worker an uncached call
# head-of-line blocks every other request (live incident, GW3 deadline day).
# The inputs change twice a day, so cache per (entry, gw, horizon) and hold a
# global lock so concurrent identical calls don't stack builds.
_plan_cache: dict = {}
_plan_build_lock = threading.Lock()


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
    ttl = float(getattr(config, "CHIP_PLAN_CACHE_TTL_S", 900.0) or 0.0)
    cache_key = (int(entry_id), int(current_gw), int(model_horizon))
    hit = _plan_cache.get(cache_key)
    if hit and ttl > 0 and (time.time() - hit["ts"]) < ttl:
        return hit["data"]
    with _plan_build_lock:
        hit = _plan_cache.get(cache_key)
        if hit and ttl > 0 and (time.time() - hit["ts"]) < ttl:
            return hit["data"]
        result = _build_plan_response(entry_id, current_gw, model_horizon)
        _plan_cache[cache_key] = {"ts": time.time(), "data": result}
        return result


def build_chip_signals(bootstrap: dict, current_gw: int, model_horizon: int):
    """Build the breaks / team_difficulty_by_gw / swings / xgi_per90 strategy
    signals from an already-fetched bootstrap payload.

    Shared by `_build_plan_response` and `scripts/spotcheck_chip_plan.py` so
    the two never drift out of sync. Raises on any failure — callers wrap
    this in their own fail-soft try/except (signals must never fail the plan)
    and reset all four to None on error, rather than handing the engine a
    mix of populated and missing signals.
    """
    from src.breaks import international_break_gws
    breaks = international_break_gws(bootstrap.get("events", []))

    id_to_name = {int(t["id"]): t["name"] for t in bootstrap.get("teams", [])}
    el = pd.DataFrame(bootstrap.get("elements", []))
    xgi_per90 = None
    if not el.empty and "expected_goals_per_90" in el.columns:
        xg = pd.to_numeric(el["expected_goals_per_90"], errors="coerce").fillna(0.0)
        # xA column may be absent from the bootstrap payload — treat missing
        # as 0.0 and keep an xG-only lambda rather than losing all signals.
        if "expected_assists_per_90" in el.columns:
            xa = pd.to_numeric(el["expected_assists_per_90"], errors="coerce").fillna(0.0)
        else:
            xa = pd.Series(0.0, index=el.index)
        xgi_per90 = dict(zip(el["id"].astype(int), (xg + xa).astype(float)))

    # Ticker spans horizon + swing window so edge GWs get a forward window.
    # Lazy import: api.main imports api.chips at module load, so a
    # module-level import of build_fixture_difficulty_payload here would
    # be a circular import; importing at request time avoids the cycle.
    from api.main import build_fixture_difficulty_payload
    from src.fixture_difficulty import compute_fixture_swings
    window = int(getattr(config, "SWING_WINDOW_GWS", 3))
    ticker = build_fixture_difficulty_payload(
        gw_start=current_gw, horizon_gws=model_horizon + window)
    team_difficulty_by_gw = {}
    for row in ticker.get("teams", []):
        name = id_to_name.get(int(row.get("team_id", 0)))
        if not name:
            continue
        for gw, cell in (row.get("gws") or {}).items():
            d = (cell or {}).get("difficulty")
            # Producer contract: skip None/non-finite so the TC path's
            # int(round(d)) never sees a NaN.
            if d is None or not math.isfinite(d):
                continue
            team_difficulty_by_gw.setdefault(int(gw), {})[name] = float(d)
    swings = [
        {**s, "team": id_to_name.get(int(s.get("team_id", 0)), s.get("team_short"))}
        for s in compute_fixture_swings(ticker)
    ]
    return breaks, team_difficulty_by_gw, swings, xgi_per90


def _build_plan_response(entry_id: int, current_gw: int, model_horizon: int):
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

    # --- strategy signals: breaks, fixture difficulty, swings, per-player xGI ---
    breaks = None
    team_difficulty_by_gw = None
    swings = None
    xgi_per90 = None
    try:
        # _build_context_for_entry above already fetched a bootstrap; use the
        # shared TTL cache instead of another raw HTTPS GET. Lazy import:
        # api.main imports api.chips at module load, so a module-level import
        # here would be circular; importing at request time avoids the cycle.
        from api.main import get_bootstrap_cached
        bootstrap = get_bootstrap_cached()
        breaks, team_difficulty_by_gw, swings, xgi_per90 = build_chip_signals(
            bootstrap, current_gw, model_horizon)
    except Exception as e:  # noqa: BLE001 — signals must never fail the plan
        # All-or-nothing: a failure part-way through (e.g. the ticker call,
        # after breaks/xGI were already assigned) must not hand the engine a
        # mix of populated and missing signals — reset to the no-signals path.
        breaks = team_difficulty_by_gw = swings = xgi_per90 = None
        logger.warning("chip strategy signals unavailable: %s", e)

    plan = build_chip_plan(
        squad=ctx["squad"],
        current_gw=current_gw,
        gw_projections=ctx["gw_projections"],
        chips_played=_get_entry_chips(entry_id),
        itb_m=float(ctx["bank_m"]),
        fixtures=ctx.get("fixtures"),
        transfer_plan=transfer_plan,
        horizon_gws=model_horizon,
        breaks=breaks,
        team_difficulty_by_gw=team_difficulty_by_gw,
        swings=swings,
        xgi_per90=xgi_per90,
    )
    return {"entry_id": entry_id, **plan}
