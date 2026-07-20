"""Pure per-GW model-vs-reality records for personal GW replay.

Reuses the leak-safe walk-forward engine (Vaastav data via backtest_adapter).
No network, no FastAPI."""
import pandas as pd

from src import projections, ownership_ev, backtest_data
from src.backtest_adapter import build_engine_inputs

POS_NAME = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def optimal_captain(squad_ids, actuals):
    if not squad_ids or actuals.empty:
        return None
    a = actuals[actuals["player_id"].isin([int(x) for x in squad_ids])]
    a = a.dropna(subset=["total_points"])
    if a.empty:
        return None
    return int(a.loc[a["total_points"].astype(float).idxmax(), "player_id"])


def model_projection(gw, season="2025-26", horizon=3):
    """Leak-safe per-player projection. Mirrors backtest_season.project_gw_engine
    but kept in src/ so the builder does not import from scripts/."""
    elements, fixtures, teams_short, history_df = build_engine_inputs(gw, season, horizon)
    orig = projections.load_latest_player_gw_history
    projections.load_latest_player_gw_history = lambda **kw: history_df
    try:
        proj = projections.project_elements_next_gws(
            elements=elements, fixtures=fixtures, teams_short_map=teams_short,
            gw_start=gw, horizon_gws=horizon,
        )
    finally:
        projections.load_latest_player_gw_history = orig
    return pd.DataFrame({
        "player_id": proj["id"].astype(int),
        "model_xpts": pd.to_numeric(proj.get(f"xpts_gw{gw}"), errors="coerce").fillna(0.0),
    })


def _model_captain(squad_ids, proj):
    """Highest model_xpts player among the squad."""
    in_squad = proj[proj["player_id"].isin([int(x) for x in squad_ids])]
    if in_squad.empty:
        return None
    return int(in_squad.loc[in_squad["model_xpts"].idxmax(), "player_id"])


def build_gw_record(gw, season, entry_snapshot, horizon=3):
    gw_entry = (entry_snapshot.get("gws") or {}).get(gw) or {}
    squad_ids = gw_entry.get("picks", [])
    setup_gw = gw <= 1
    record = {"season": season, "gw": int(gw), "setup_gw": setup_gw,
              "players": [], "model_captain": None, "optimal_captain": None,
              "suggested_transfer": None, "sp2_candidates": []}
    if setup_gw:
        return record

    actuals = backtest_data.player_actuals_at(gw, season)[["player_id", "total_points", "minutes"]].copy()
    actuals["player_id"] = actuals["player_id"].astype(int)
    proj = model_projection(gw, season, horizon)

    merged = pd.DataFrame({"player_id": [int(x) for x in squad_ids]}).merge(
        proj, on="player_id", how="left").merge(
        actuals, on="player_id", how="left")
    merged["model_xpts"] = merged["model_xpts"].fillna(0.0)
    merged["total_points"] = merged["total_points"].fillna(0)
    record["players"] = [
        {"element": int(r.player_id), "model_xpts": round(float(r.model_xpts), 2),
         "actual_points": int(r.total_points)}
        for r in merged.itertuples()
    ]
    record["model_captain"] = _model_captain(squad_ids, proj)
    record["optimal_captain"] = optimal_captain(squad_ids, actuals)
    return record
