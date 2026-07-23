"""Pure, dependency-injectable from-scratch squad draft (dev tool + API core)."""
import pandas as pd

from src import config, optimizer, projections

UNAVAILABLE_STATUSES = {"i", "s", "u", "n"}

DEFAULT_PARAMS = {
    "gw_start": 1,
    "horizon_gws": 5,
    "budget_m": 100.0,
    "objective": "wildcard",          # wildcard | free_hit | plain
    "projection_basis": "ppg",        # ppg | xg | blend
    "blend_weight": 0.0,
    "minutes_prior_k": 500.0,
    "fdr_strength": 1.0,
    "include_flagged": False,
    "min_chance_of_playing": 0,
    "team_nudges": None,
    "max_per_team": 3,
    "min_fwd_minutes": 0.0,
    "min_premium_attackers": None,
    "premium_floor": None,
    "formation": "auto",
    "league_id": None,
}


def _filter_availability(elements, include_flagged, min_chance):
    out = elements.copy()
    status = out.get("status", pd.Series("a", index=out.index)).astype(str)
    if not include_flagged:
        out = out[~status.isin(UNAVAILABLE_STATUSES)].copy()
    if min_chance and float(min_chance) > 0:
        chance = pd.to_numeric(out.get("chance_of_playing_next_round"), errors="coerce").fillna(100.0)
        out = out[chance >= float(min_chance)].copy()
    return out


def _apply_minutes_shrink(elements, minutes_prior_k):
    out = elements.copy()
    raw_ppg = pd.to_numeric(out.get("points_per_game"), errors="coerce").fillna(0.0)
    mins = pd.to_numeric(out.get("minutes"), errors="coerce").fillna(0.0)
    k = max(1.0, float(minutes_prior_k))
    out["raw_ppg"] = raw_ppg
    out["points_per_game"] = raw_ppg * (mins / (mins + k))
    return out


def _premium_params(params):
    premium_floor = params.get("premium_floor")
    if premium_floor is None:
        premium_floor = float(
            getattr(config, "CHIP_WILDCARD_PREMIUM_CAPTAIN_PRICE_FLOOR",
                    getattr(config, "CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR", 9.0)) or 9.0)
    premium_positions = list(
        getattr(config, "CHIP_WILDCARD_PREMIUM_CAPTAIN_POSITIONS", ["MID", "FWD"]) or ["MID", "FWD"])
    min_premium = params.get("min_premium_attackers")
    if min_premium is None:
        min_premium = int(getattr(config, "CHIP_WILDCARD_MIN_PREMIUM_CAPTAINS", 1) or 0)
    return float(premium_floor), premium_positions, int(min_premium)


def _value_menu(proj, top_n=8):
    menu = {}
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        sub = proj[proj["pos"] == pos].sort_values("xpts_horizon", ascending=False).head(top_n)
        menu[pos] = [
            {"id": int(r["id"]), "web_name": r.get("web_name"), "team_short": r.get("team_short"),
             "price_m": float(pd.to_numeric(r.get("price_m"), errors="coerce") or 0.0),
             "xpts_horizon": float(pd.to_numeric(r.get("xpts_horizon"), errors="coerce") or 0.0)}
            for _, r in sub.iterrows()
        ]
    return menu


def build_squad_from_frames(elements, fixtures, teams_short, params):
    p = {**DEFAULT_PARAMS, **(params or {})}
    notes = []
    gw_start = int(p["gw_start"])
    horizon = max(1, min(8, int(p["horizon_gws"])))
    gws = list(range(gw_start, gw_start + horizon))

    avail = _filter_availability(elements, p["include_flagged"], p["min_chance_of_playing"])
    avail = _apply_minutes_shrink(avail, p["minutes_prior_k"])
    mins = pd.to_numeric(avail.get("minutes"), errors="coerce").fillna(0.0)
    if float(p["min_fwd_minutes"]) > 0:
        drop = (avail["pos"] == "FWD") & (mins < float(p["min_fwd_minutes"]))
        avail = avail[~drop].copy()

    proj = projections.project_elements_next_gws(
        elements=avail, fixtures=fixtures, teams_short_map=teams_short,
        gw_start=gw_start, horizon_gws=horizon)
    proj = projections.add_wildcard_scores(proj, gw_start=gw_start, horizon_gws=horizon)

    xpts_cols = [f"xpts_gw{g}" for g in gws if f"xpts_gw{g}" in proj.columns]
    proj["xpts_horizon"] = proj[xpts_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1) \
        if xpts_cols else 0.0

    objective = str(p["objective"])
    budget_m = float(p["budget_m"])
    max_per_team = int(p["max_per_team"])
    premium_floor, premium_positions, min_premium = _premium_params(p)

    if objective == "free_hit":
        build = optimizer.build_free_hit_squad(
            elements_all=proj, score_col=f"xpts_gw{gw_start}",
            budget_m=budget_m, max_per_team=max_per_team)
    else:
        score_col = "wildcard_score" if objective == "wildcard" else f"xpts_gw{gw_start}"
        build = optimizer.build_chip_squad(
            elements_all=proj, score_col=score_col, budget_m=budget_m,
            max_per_team=max_per_team, min_premium_attackers=min_premium,
            premium_floor=premium_floor, premium_positions=premium_positions)

    if not build.get("ok"):
        return {"ok": False, "reason": build.get("reason"), "notes": notes,
                "squad": [], "starting_xi": [], "bench": []}

    squad_df = build["squad_df"]
    lineup = optimizer.optimize_lineup(squad_df, proj, score_col=f"xpts_gw{gw_start}")

    disp = proj[[c for c in ["id", "web_name", "pos", "team_short", "price_m",
                             "points_per_game", "xpts_horizon", f"xpts_gw{gw_start}"] if c in proj.columns]]
    view = squad_df.merge(disp, left_on="player_id", right_on="id", how="left", suffixes=("", "_p"))
    squad_records = view.to_dict("records")

    cost = float(pd.to_numeric(view.get("price_m"), errors="coerce").fillna(0.0).sum())
    return {
        "ok": True,
        "reason": build.get("reason"),
        "notes": notes,
        "gw_start": gw_start,
        "horizon_gws": horizon,
        "objective": objective,
        "projection_basis": str(p["projection_basis"]),
        "formation": lineup["formation"] if lineup else None,
        "captain_player_id": lineup["captain_player_id"] if lineup else None,
        "vice_player_id": lineup["vice_player_id"] if lineup else None,
        "budget_m": round(budget_m, 2),
        "squad_cost_m": round(cost, 2),
        "remaining_budget_m": round(max(0.0, budget_m - cost), 2),
        "squad": squad_records,
        "starting_xi": lineup["starting_xi"].to_dict("records") if lineup else [],
        "bench": lineup["bench"].to_dict("records") if lineup else [],
        "value_menu": _value_menu(proj),
    }
