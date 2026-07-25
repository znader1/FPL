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
    "home_away_strength": 1.0,        # scales home/away multiplier swing (home 1.06/away 0.94; 0=off,1=default,>1=amplified)
    "minutes_prior_k": 500.0,
    "include_flagged": False,
    "min_chance_of_playing": 0,
    "max_per_team": None,
    "min_fwd_minutes": 0.0,
    "min_premium_attackers": None,
    "premium_floor": None,
    "max_player_price": None,          # auto-build only: cap price per player to avoid loading up on premiums
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


def project_pool(elements, fixtures, teams_short, params):
    """Shared projection pipeline for /build, /players, /lineup. Returns the
    fully projected pool DataFrame plus the resolved gw window and notes.
    No optimizer / squad-building -- pure per-player projection."""
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
    # Pre-season the FPL `form` field is ~0 for everyone, so the default
    # 0.55*ppg + 0.45*form blend would halve every projection with no upside.
    # With no form signal, weight ppg fully (cold-start). Scoped to the squad
    # picker only; in-season (form>0) this is a no-op.
    form_series = pd.to_numeric(avail.get("form"), errors="coerce").fillna(0.0)
    preseason = bool(len(form_series) and form_series.abs().max() < 1e-9)
    ppg_w = 1.0 if preseason else config.PROJ_DEFAULT_PPG_WEIGHT
    form_w = 0.0 if preseason else config.PROJ_DEFAULT_FORM_WEIGHT
    ppg_proj = projections.project_elements_next_gws(
        elements=avail, fixtures=fixtures, teams_short_map=teams_short,
        gw_start=gw_start, horizon_gws=horizon, fdr_strength=p["fdr_strength"],
        home_away_strength=p["home_away_strength"], ppg_weight=ppg_w, form_weight=form_w)
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
    return proj, gw_start, horizon, gws, notes


def build_squad_from_frames(elements, fixtures, teams_short, params):
    p = {**DEFAULT_PARAMS, **(params or {})}
    proj, gw_start, horizon, gws, notes = project_pool(elements, fixtures, teams_short, p)

    objective = str(p["objective"])
    budget_m = float(p["budget_m"])
    max_per_team = int(p["max_per_team"]) if p["max_per_team"] is not None \
        else int(getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3)
    premium_floor, premium_positions, min_premium = _premium_params(p)

    # Auto-build only: optionally cap price per player so the optimizer doesn't
    # load up on premiums. The full pool (proj) is still used for the XI
    # optimization, value menu, and the /players list -- only the draft market
    # is capped.
    draft_pool = proj
    mpp = p.get("max_player_price")
    if mpp is not None and float(mpp) > 0:
        keep = pd.to_numeric(proj["price_m"], errors="coerce").fillna(0.0) <= float(mpp)
        draft_pool = proj[keep].copy()
        notes.append(f"Auto-build capped to players ≤ £{float(mpp):.1f}m.")
        # No premium exists under the cap, so don't require one (the premium
        # captaincy constraint would otherwise be unsatisfiable and the build
        # would collapse to all-fodder, leaving budget unspent).
        if float(mpp) < premium_floor:
            min_premium = 0

    if objective == "free_hit":
        build = optimizer.build_free_hit_squad(
            elements_all=draft_pool, score_col=f"xpts_gw{gw_start}",
            budget_m=budget_m, max_per_team=max_per_team)
    else:
        score_col = "wildcard_score" if objective == "wildcard" else f"xpts_gw{gw_start}"
        build = optimizer.build_chip_squad(
            elements_all=draft_pool, score_col=score_col, budget_m=budget_m,
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


def _pool_num(v, d=0.0):
    n = pd.to_numeric(v, errors="coerce")
    return d if pd.isna(n) else float(n)


def _team_fixture_map(fixtures, teams_short, gws):
    """{team_id: [{gw, opp(short), home, diff}, ...]} over the horizon GWs."""
    out = {}
    for g in gws:
        by_team = transforms.fixtures_by_team_for_gw(fixtures, int(g))
        for tid, items in (by_team or {}).items():
            for it in items:
                out.setdefault(int(tid), []).append({
                    "gw": int(g),
                    "opp": teams_short.get(int(it["opp"]), "?"),
                    "home": bool(it["is_home"]),
                    "diff": int(it["diff"]),
                })
    return out


def _pool_records(proj, gws, team_fixtures=None):
    """One JSON-safe record per projected player, for the /players list."""
    team_fixtures = team_fixtures or {}
    out = []
    for _, r in proj.iterrows():
        tid = int(_pool_num(r.get("team"), 0))
        fx = sorted(team_fixtures.get(tid, []), key=lambda x: x["gw"])
        diffs = [f["diff"] for f in fx if f["diff"] > 0]
        avg_diff = round(sum(diffs) / len(diffs), 2) if diffs else None
        home_games = sum(1 for f in fx if f["home"])
        out.append({
            "player_id": int(r["id"]),
            "web_name": r.get("web_name"),
            "pos": r.get("pos"),
            "team_short": r.get("team_short"),
            "team_id": int(_pool_num(r.get("team"), 0)),
            "price_m": _pool_num(r.get("price_m")),
            "points_per_game": _pool_num(r.get("points_per_game")),
            "total_points": _pool_num(r.get("total_points")),
            "minutes": int(_pool_num(r.get("minutes"), 0)),
            "starts": int(_pool_num(r.get("starts"), 0)),
            "selected_by_percent": _pool_num(r.get("selected_by_percent")),
            "xpts_horizon": _pool_num(r.get("xpts_horizon")),
            "xpts_per_gw": [_pool_num(r.get(f"xpts_gw{g}")) for g in gws],
            "fixtures": fx,
            "avg_diff": avg_diff,
            "home_games": home_games,
        })
    return out


def player_pool(bootstrap, fixtures_raw, params=None):
    """Live wrapper: full projected player pool (no optimizer)."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    if params is None or params.get("gw_start") is None:
        p["gw_start"] = _next_gw(bootstrap)
    elements, teams, _etypes = transforms.tables_from_bootstrap(bootstrap)
    fixtures = transforms.fixtures_df(fixtures_raw)
    teams_short = teams.set_index("id")["short_name"].to_dict()
    proj, gw_start, horizon, gws, _notes = project_pool(elements, fixtures, teams_short, p)
    team_fixtures = _team_fixture_map(fixtures, teams_short, gws)
    return {
        "gw_start": gw_start,
        "horizon_gws": horizon,
        "projection_basis": str(p["projection_basis"]),
        "players": _pool_records(proj, gws, team_fixtures),
    }


POSITION_QUOTA = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


def _validate_squad(picked, params):
    """picked: pool rows filtered to the chosen ids. Returns a list of
    human-readable violation strings ([] when the 15 is legal)."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    budget_m = float(p["budget_m"])
    max_per_team = int(p["max_per_team"]) if p["max_per_team"] is not None \
        else int(getattr(config, "CHIP_MAX_PER_TEAM", 3) or 3)
    v = []
    if len(picked) != 15:
        v.append(f"Squad must have 15 players (has {len(picked)}).")
    counts = picked["pos"].value_counts().to_dict()
    for pos, need in POSITION_QUOTA.items():
        have = int(counts.get(pos, 0))
        if have != need:
            v.append(f"{pos}: need {need}, have {have}.")
    team_counts = picked["team"].value_counts()
    for team_id, n in team_counts[team_counts > max_per_team].items():
        v.append(f"More than {max_per_team} from team {int(team_id)} (has {int(n)}).")
    cost = float(pd.to_numeric(picked.get("price_m"), errors="coerce").fillna(0.0).sum())
    if cost > budget_m + 1e-6:
        v.append(f"Over budget: £{cost:.1f}m > £{budget_m:.1f}m.")
    return v


def build_lineup(bootstrap, fixtures_raw, player_ids, params=None):
    """Live wrapper: validate a chosen 15 + auto-optimize the XI. Legal squads
    return a /build-shaped result with valid=True; illegal squads return
    valid=False plus violations (HTTP-200 user-editing state, not an error)."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    if params is None or params.get("gw_start") is None:
        p["gw_start"] = _next_gw(bootstrap)
    elements, teams, _etypes = transforms.tables_from_bootstrap(bootstrap)
    fixtures = transforms.fixtures_df(fixtures_raw)
    teams_short = teams.set_index("id")["short_name"].to_dict()
    proj, gw_start, horizon, gws, notes = project_pool(elements, fixtures, teams_short, p)

    ids = [int(x) for x in (player_ids or [])]
    picked = proj[proj["id"].isin(ids)].copy()
    known = set(int(x) for x in picked["id"].tolist())
    missing = [i for i in ids if i not in known]
    violations = _validate_squad(picked, p)
    if missing:
        violations.append(f"Unknown player ids: {missing}.")
    if violations:
        return {"ok": False, "valid": False, "violations": violations, "notes": notes}

    squad_df = picked[["id", "pos", "team"]].rename(columns={"id": "player_id"})
    fixed_formations = _parse_formation(p["formation"], notes)
    lineup = optimizer.optimize_lineup(
        squad_df, proj, score_col=f"xpts_gw{gw_start}", formations=fixed_formations)
    if lineup is None and fixed_formations is not None:
        notes.append(f"Formation '{p['formation']}' not possible; using auto.")
        lineup = optimizer.optimize_lineup(squad_df, proj, score_col=f"xpts_gw{gw_start}")

    disp = proj[[c for c in ["id", "web_name", "pos", "team_short", "price_m",
                             "points_per_game", "xpts_horizon", f"xpts_gw{gw_start}"] if c in proj.columns]]
    view = squad_df.merge(disp, left_on="player_id", right_on="id", how="left", suffixes=("", "_p"))
    cost = float(pd.to_numeric(view.get("price_m"), errors="coerce").fillna(0.0).sum())
    budget_m = float(p["budget_m"])
    return {
        "ok": True,
        "valid": True,
        "violations": [],
        "notes": notes,
        "gw_start": gw_start,
        "horizon_gws": horizon,
        "projection_basis": str(p["projection_basis"]),
        "formation": lineup["formation"] if lineup else None,
        "captain_player_id": lineup["captain_player_id"] if lineup else None,
        "vice_player_id": lineup["vice_player_id"] if lineup else None,
        "budget_m": round(budget_m, 2),
        "squad_cost_m": round(cost, 2),
        "remaining_budget_m": round(max(0.0, budget_m - cost), 2),
        "squad": view.to_dict("records"),
        "starting_xi": lineup["starting_xi"].to_dict("records") if lineup else [],
        "bench": lineup["bench"].to_dict("records") if lineup else [],
        "projected_points": _projected_points(lineup, proj, gws, gw_start),
    }
