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

    actuals = backtest_data.player_actuals_at(gw, season)[
        ["player_id", "total_points", "minutes"]].copy()
    actuals["player_id"] = actuals["player_id"].astype(int)
    # Vaastav GW files occasionally duplicate a player's row (e.g. identical
    # fixture rows); dedupe so the position merge below stays one-to-one.
    actuals = actuals.drop_duplicates(subset=["player_id"])
    # position_id from the Vaastav GW file for SP2 templates
    import pandas as _pd
    from pathlib import Path as _Path
    _gwf = _Path("data/vaastav") / season / "gws" / f"gw{int(gw)}.csv"
    if _gwf.exists():
        _pos = _pd.read_csv(_gwf)[["element", "position"]].copy()
        _pos["player_id"] = _pos["element"].astype(int)
        _pos["position_id"] = _pos["position"].map({"GKP": 1, "GK": 1, "DEF": 2, "MID": 3, "FWD": 4})
        _pos = _pos.drop_duplicates(subset=["player_id"])
        actuals = actuals.merge(_pos[["player_id", "position_id"]], on="player_id", how="left")
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

    ownership = _gw_global_ownership(gw, season)
    record["sp2_candidates"] = _sp2_candidates(gw, season, proj, actuals, ownership)
    # Suggested transfer: best single upgrade in the squad's weakest slot by model xPts.
    record["suggested_transfer"] = _suggest_transfer(squad_ids, proj)
    return record


def _gw_global_ownership(gw, season="2025-26", base="data/vaastav"):
    from pathlib import Path
    path = Path(base) / season / "gws" / f"gw{int(gw)}.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if "selected" not in df.columns or "element" not in df.columns:
        return {}
    sel = pd.to_numeric(df["selected"], errors="coerce").fillna(0.0)
    m = sel.max()
    if not m:
        return {}
    return {int(e): float(s) / float(m) for e, s in zip(df["element"], sel)}


def _sp2_candidates(gw, season, proj, actuals, ownership, top_n=8):
    """Global-ownership differential EV over the full player market that GW."""
    # Vaastav GW files occasionally contain duplicate rows for the same player
    # (e.g. identical fixture rows) — dedupe defensively before indexing.
    a = actuals.drop_duplicates(subset=["player_id"]).set_index("player_id")
    # element meta keyed by id for ownership_ev.compute_position_templates
    meta, cands = {}, []
    for r in proj.itertuples():
        pid = int(r.player_id)
        pos_row = a.loc[pid] if pid in a.index else None
        pos_id = int(pos_row["position_id"]) if pos_row is not None and "position_id" in a.columns else None
        m = {"position_id": pos_id, "model_xpts_horizon": float(r.model_xpts),
             "selected_by_percent": ownership.get(pid, 0.0) * 100.0}
        meta[pid] = m
        cands.append({"id": pid, "position_id": pos_id,
                      "model_xpts_horizon": float(r.model_xpts),
                      "league_ownership": ownership.get(pid, 0.0)})
    templates = ownership_ev.compute_position_templates(meta)
    annotated = ownership_ev.annotate_candidates(
        [c for c in cands if c["position_id"] is not None], templates)
    annotated.sort(key=lambda c: c.get("differential_ev", 0.0), reverse=True)
    return [{"element": int(c["id"]),
             "differential_ev": round(float(c["differential_ev"]), 2),
             "template_xpts": round(float(c["template_xpts"]), 2),
             "global_ownership": round(float(c["league_ownership"]), 4),
             "ownership_basis": "global"} for c in annotated[:top_n]]


def _suggest_transfer(squad_ids, proj, min_gain=0.6):
    """Weakest owned player vs. best non-owned player at the same implied rank.
    Simple, market-wide: swap the lowest-model owned player for the highest-model
    non-owned player when the gain clears min_gain."""
    owned = proj[proj["player_id"].isin([int(x) for x in squad_ids])]
    if owned.empty:
        return None
    sell = owned.loc[owned["model_xpts"].idxmin()]
    pool = proj[~proj["player_id"].isin([int(x) for x in squad_ids])]
    if pool.empty:
        return None
    buy = pool.loc[pool["model_xpts"].idxmax()]
    gain = float(buy["model_xpts"]) - float(sell["model_xpts"])
    if gain < min_gain:
        return None
    return {"sell": int(sell["player_id"]), "buy": int(buy["player_id"]),
            "expected_gain": round(gain, 2)}
