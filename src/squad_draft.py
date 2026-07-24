"""Pure, dependency-injectable from-scratch squad draft (dev tool + API core)."""
import pandas as pd

from src import config, optimizer, projections, transforms

UNAVAILABLE_STATUSES = {"i", "s", "u", "n"}

# NOT wired in v1 (frontend must not surface until implemented): league_id
# (ownership_ev differential).
DEFAULT_PARAMS = {
    "gw_start": 1,
    "horizon_gws": None,
    "budget_m": 100.0,
    "objective": "wildcard",          # wildcard | free_hit | plain
    "projection_basis": "ppg",        # ppg | xg | blend
    "blend_weight": 0.0,
    "fdr_strength": 1.0,              # scales fixture-difficulty multiplier swing (0=off,1=default,>1=amplified)
    "minutes_prior_k": 500.0,
    "include_flagged": False,
    "min_chance_of_playing": 0,
    "max_per_team": None,
    "min_fwd_minutes": 0.0,
    "min_premium_attackers": None,
    "premium_floor": None,
    "formation": "auto",
    "team_nudges": None,              # per-request xg/blend attack/defense nudges
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


def _notable_exclusion_notes(elements, top_n=10, ppg_floor=4.0):
    """Surface notable flagged-out players (high points_per_game but unavailable)
    as concise note strings, e.g. for display alongside the squad build result."""
    if elements is None or len(elements) == 0:
        return []
    df = elements.copy()
    status = df.get("status", pd.Series("a", index=df.index)).astype(str)
    flagged = df[status.isin(UNAVAILABLE_STATUSES)].copy()
    if flagged.empty:
        return []
    flagged["_ppg"] = pd.to_numeric(flagged.get("points_per_game"), errors="coerce").fillna(0.0)
    notable = flagged[flagged["_ppg"] >= float(ppg_floor)].sort_values("_ppg", ascending=False).head(int(top_n))
    notes = []
    for _, row in notable.iterrows():
        web_name = row.get("web_name", "?")
        team_short = row.get("team_short", "?")
        price_m = float(pd.to_numeric(row.get("price_m"), errors="coerce") or 0.0)
        news = row.get("news")
        if news is None or (isinstance(news, float) and pd.isna(news)) or str(news).strip() == "":
            news = f"status={row.get('status')}"
        notes.append(f"{web_name} ({team_short}, £{price_m:.1f}m) out — {news}")
    return notes


def _parse_formation(spec, notes=None):
    """Parse a 'D-M-F' formation spec into an optimizer `formations` list.

    Returns None (search all valid formations) for None/"auto" input. Returns
    a single-entry list [(d, m, f)] for a valid explicit spec like "3-4-3".
    For malformed input, returns None and (if `notes` is given) appends an
    "Invalid formation" note to it.
    """
    if spec is None:
        return None
    spec_str = str(spec).strip().lower()
    if spec_str in ("", "auto"):
        return None
    parts = spec_str.split("-")
    if len(parts) == 3:
        try:
            d, m, f = (int(x) for x in parts)
            return [(d, m, f)]
        except (TypeError, ValueError):
            pass
    if notes is not None:
        notes.append(f"Invalid formation '{spec}'; using auto.")
    return None


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


def _projected_points(lineup, proj, gws, gw_start):
    if not lineup:
        return {"per_gw": [], "horizon_total": 0.0}
    xi_ids = [int(x) for x in lineup["starting_xi"]["player_id"].tolist()]
    cap_id = lineup.get("captain_player_id")
    pm = proj.drop_duplicates("id").set_index("id")
    per_gw = []
    for g in gws:
        col = f"xpts_gw{g}"
        if col not in proj.columns:
            continue
        xi_pts = 0.0
        for pid in xi_ids:
            if pid in pm.index:
                xi_pts += float(pd.to_numeric(pm.loc[pid, col], errors="coerce") or 0.0)
        cap_bonus = 0.0
        if cap_id is not None and int(cap_id) in pm.index:
            cap_bonus = float(pd.to_numeric(pm.loc[int(cap_id), col], errors="coerce") or 0.0)
        per_gw.append({"gw": g, "xi_points": round(xi_pts, 2),
                       "captain_bonus": round(cap_bonus, 2),
                       "total": round(xi_pts + cap_bonus, 2)})
    return {"per_gw": per_gw, "horizon_total": round(sum(r["total"] for r in per_gw), 2)}


def build_squad_from_frames(elements, fixtures, teams_short, params):
    p = {**DEFAULT_PARAMS, **(params or {})}
    notes = _notable_exclusion_notes(elements)
    gw_start = int(p["gw_start"])
    horizon = int(p["horizon_gws"]) if p["horizon_gws"] is not None \
        else int(getattr(config, "CHIP_WILDCARD_DEFAULT_HORIZON_GWS", 5) or 5)
    horizon = max(1, min(8, horizon))
    gws = list(range(gw_start, gw_start + horizon))

    avail = _filter_availability(elements, p["include_flagged"], p["min_chance_of_playing"])
    avail = _apply_minutes_shrink(avail, p["minutes_prior_k"])
    mins = pd.to_numeric(avail.get("minutes"), errors="coerce").fillna(0.0)
    if float(p["min_fwd_minutes"]) > 0:
        drop = (avail["pos"] == "FWD") & (mins < float(p["min_fwd_minutes"]))
        avail = avail[~drop].copy()

    basis = str(p["projection_basis"])
    ppg_proj = projections.project_elements_next_gws(
        elements=avail, fixtures=fixtures, teams_short_map=teams_short,
        gw_start=gw_start, horizon_gws=horizon, fdr_strength=p["fdr_strength"])
    if basis in ("xg", "blend"):
        from src import squad_draft_xg
        proj = squad_draft_xg.xg_projection(
            avail, fixtures, teams_short, gw_start, horizon,
            blend_weight=(float(p["blend_weight"]) if basis == "blend" else 1.0),
            ppg_proj=ppg_proj, team_nudges=p["team_nudges"])
    else:
        proj = ppg_proj
    proj = projections.add_wildcard_scores(proj, gw_start=gw_start, horizon_gws=horizon)

    xpts_cols = [f"xpts_gw{g}" for g in gws if f"xpts_gw{g}" in proj.columns]
    proj["xpts_horizon"] = proj[xpts_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1) \
        if xpts_cols else 0.0

    objective = str(p["objective"])
    budget_m = float(p["budget_m"])
    max_per_team = int(p["max_per_team"]) if p["max_per_team"] is not None \
        else int(getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3)
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
        return {
            "ok": False,
            "reason": build.get("reason"),
            "notes": notes,
            "squad": [],
            "starting_xi": [],
            "bench": [],
            "captain_player_id": None,
            "vice_player_id": None,
            "formation": None,
            "budget_m": round(float(p["budget_m"]), 2),
            "squad_cost_m": None,
            "remaining_budget_m": None,
            "value_menu": {},
            "gw_start": gw_start,
            "horizon_gws": horizon,
            "objective": str(p["objective"]),
            "projection_basis": str(p["projection_basis"]),
            "projected_points": {"per_gw": [], "horizon_total": 0.0},
        }

    squad_df = build["squad_df"]
    fixed_formations = _parse_formation(p["formation"], notes)
    lineup = optimizer.optimize_lineup(
        squad_df, proj, score_col=f"xpts_gw{gw_start}", formations=fixed_formations)
    if lineup is None and fixed_formations is not None:
        notes.append(f"Formation '{p['formation']}' not possible for this squad; using auto.")
        lineup = optimizer.optimize_lineup(squad_df, proj, score_col=f"xpts_gw{gw_start}")

    disp = proj[[c for c in ["id", "web_name", "pos", "team_short", "price_m",
                             "points_per_game", "xpts_horizon", f"xpts_gw{gw_start}"] if c in proj.columns]]
    view = squad_df.merge(disp, left_on="player_id", right_on="id", how="left", suffixes=("", "_p"))
    squad_records = view.to_dict("records")

    cost = float(pd.to_numeric(view.get("price_m"), errors="coerce").fillna(0.0).sum())
    projected = _projected_points(lineup, proj, gws, gw_start)
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
        "projected_points": projected,
    }


def _next_gw(bootstrap):
    for e in bootstrap.get("events", []):
        if e.get("is_next"):
            return int(e["id"])
    for e in bootstrap.get("events", []):
        if e.get("is_current"):
            return int(e["id"])
    return 1


def build_squad(bootstrap, fixtures_raw, params=None):
    """Live wrapper: runs transforms on raw bootstrap/fixtures, defaults gw_start
    from the bootstrap's next event, then delegates to build_squad_from_frames."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    if params is None or params.get("gw_start") is None:
        p["gw_start"] = _next_gw(bootstrap)
    elements, teams, _etypes = transforms.tables_from_bootstrap(bootstrap)
    fixtures = transforms.fixtures_df(fixtures_raw)
    teams_short = teams.set_index("id")["short_name"].to_dict()
    return build_squad_from_frames(elements, fixtures, teams_short, p)
