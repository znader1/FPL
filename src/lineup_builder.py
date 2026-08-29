import pandas as pd

from src import config
from src.media import attach_media
from src.utils import df_records, round_float, safe_float, safe_int, safe_player_id


def _build_player_alerts(record, optimize_event_id=None):
    alerts = []
    status = str(record.get("status") or "").strip().lower()
    chance = safe_float(record.get("chance_of_playing_next_round"), default=None)

    if status and status != "a":
        severity = "high" if status in ("i", "u") else "medium"
        alerts.append({"severity": severity, "category": "availability", "text": f"Availability risk ({status})."})
    elif chance is not None and float(chance) < 100.0:
        severity = "high" if float(chance) < 50.0 else "medium"
        alerts.append({"severity": severity, "category": "availability", "text": f"Chance of playing next round is {int(round(float(chance)))}%."})

    fixtures_horizon = list(record.get("fixtures_horizon") or [])
    blank_alert = None
    double_alert = None
    for item in fixtures_horizon:
        event_id = safe_int(item.get("event_id"))
        fixture_count = int(safe_int(item.get("fixture_count")) or 0)
        if blank_alert is None and fixture_count == 0:
            severity = "high" if event_id == safe_int(optimize_event_id) else "medium"
            blank_alert = {
                "severity": severity,
                "category": "blank",
                "event_id": event_id,
                "text": f"Blank gameweek in GW{int(event_id)}." if event_id else "Blank gameweek ahead.",
            }
        if double_alert is None and fixture_count > 1:
            double_alert = {
                "severity": "info",
                "category": "double",
                "event_id": event_id,
                "text": f"Double gameweek in GW{int(event_id)}." if event_id else "Double gameweek ahead.",
            }
        if blank_alert and double_alert:
            break

    if blank_alert:
        alerts.append(blank_alert)
    if double_alert:
        alerts.append(double_alert)
    return alerts


def _opt_round(value, ndigits=2):
    """Round when a value is present, otherwise stay None. `round_float` coerces."""
    return round_float(value, ndigits, 0.0) if value is not None else None


def _build_score_breakdown(record, chip_strategy="none", objective_score_col=None):
    breakdown = {
        "note": "xPts are projected points, not actual FPL points.",
        "current_gw_xpts": round_float(record.get("xpts"), 2, 0.0) if record.get("xpts") is not None else None,
        "horizon_xpts": round_float(record.get("xpts_horizon"), 2, 0.0) if record.get("xpts_horizon") is not None else None,
        "objective_score_col": objective_score_col,
        "objective_score": None,
    }

    # Component probabilities from the xG model. A mean of 2.3 tells a manager
    # nothing they can act on; "61% to score, 78% to play 60'" does.
    #
    # These describe the MODEL half of the projection only: `xpts` above is a
    # blend of the ppg baseline and the xG model
    # (``config.PROJ_MODEL_BLEND_WEIGHT``), so `model_exp_points` is carried
    # alongside them and the components add up against that, not against `xpts`.
    components = {
        "p_goal": _opt_round(record.get("p_goal"), 3),
        "p_assist": _opt_round(record.get("p_assist"), 3),
        "p_clean_sheet": _opt_round(record.get("p_clean_sheet"), 3),
        "p_appear": _opt_round(record.get("p_appear"), 3),
        "p_60": _opt_round(record.get("p_60"), 3),
        "p_dc": _opt_round(record.get("p_dc"), 3),
        "exp_goals": _opt_round(record.get("exp_goals"), 3),
        "exp_assists": _opt_round(record.get("exp_assists"), 3),
        "exp_minutes": _opt_round(record.get("exp_minutes"), 1),
        "model_exp_points": _opt_round(record.get("model_exp_points"), 2),
        "ep_appearance": _opt_round(record.get("ep_appearance"), 2),
        "ep_goals": _opt_round(record.get("ep_goals"), 2),
        "ep_assists": _opt_round(record.get("ep_assists"), 2),
        "ep_clean_sheet": _opt_round(record.get("ep_clean_sheet"), 2),
        "ep_bonus": _opt_round(record.get("ep_bonus"), 2),
        "ep_dc": _opt_round(record.get("ep_dc"), 2),
    }
    breakdown["components"] = components if any(v is not None for v in components.values()) else None

    # The distribution behind the mean: what the player is actually likely to score.
    distribution = {
        "modal_points": safe_int(record.get("modal_points")),
        "p_return_6": _opt_round(record.get("p_return_6"), 3),
        "p_haul_10": _opt_round(record.get("p_haul_10"), 3),
        "p80_low": safe_int(record.get("p80_low")),
        "p80_high": safe_int(record.get("p80_high")),
    }
    breakdown["distribution"] = distribution if any(
        v is not None for v in distribution.values()) else None

    breakdown["recent_form"] = {
        "window_gws": safe_int(record.get("recent_history_window_gws")),
        "history_max_gw": safe_int(record.get("recent_history_max_gw")),
        "samples": safe_int(record.get("recent_gw_samples")),
        "last_gw": safe_int(record.get("recent_gw_last")),
        "available": bool(record.get("recent_history_available")),
        "avg_points": round_float(record.get("recent_gw_avg_points"), 2, None) if record.get("recent_gw_avg_points") is not None else None,
        "avg_minutes": round_float(record.get("recent_gw_avg_minutes"), 1, None) if record.get("recent_gw_avg_minutes") is not None else None,
        "avg_fixture_count": round_float(record.get("recent_gw_avg_fixture_count"), 2, None) if record.get("recent_gw_avg_fixture_count") is not None else None,
        "avg_starts": round_float(record.get("recent_gw_avg_starts"), 2, None) if record.get("recent_gw_avg_starts") is not None else None,
    }
    breakdown["baseline"] = {
        "long_term": round_float(record.get("baseline_long_term_xpts"), 3, None) if record.get("baseline_long_term_xpts") is not None else None,
        "recent_gw": round_float(record.get("baseline_recent_gw_xpts"), 3, None) if record.get("baseline_recent_gw_xpts") is not None else None,
        "blended": round_float(record.get("baseline_blended_xpts"), 3, None) if record.get("baseline_blended_xpts") is not None else None,
        "gw1_after_ep_next_blend": round_float(record.get("baseline_gw1_xpts"), 3, None) if record.get("baseline_gw1_xpts") is not None else None,
    }

    if objective_score_col and record.get(objective_score_col) is not None:
        breakdown["objective_score"] = round_float(record.get(objective_score_col), 3, 0.0)

    if chip_strategy == "wildcard" or record.get("wildcard_score") is not None:
        breakdown["objective_explanation"] = (
            "Wildcard score is a planning score: weighted future xPts plus bonuses for future doubles, recent form, ownership confidence, and premium captaincy coverage. "
            "The underlying xPts baseline blends long-term FPL data with recent calendar-gameweek averages when available."
        )
        breakdown["wildcard"] = {
            "score": round_float(record.get("wildcard_score"), 3, 0.0) if record.get("wildcard_score") is not None else None,
            "weighted_xpts": round_float(record.get("wildcard_weighted_xpts"), 3, 0.0) if record.get("wildcard_weighted_xpts") is not None else None,
            "future_dgw_bonus": round_float(record.get("wildcard_future_dgw_bonus"), 3, 0.0) if record.get("wildcard_future_dgw_bonus") is not None else None,
            "captaincy_bonus": round_float(record.get("wildcard_captaincy_bonus"), 3, 0.0) if record.get("wildcard_captaincy_bonus") is not None else None,
            "form_bonus": round_float(record.get("wildcard_form_bonus"), 3, 0.0) if record.get("wildcard_form_bonus") is not None else None,
            "ownership_bonus": round_float(record.get("wildcard_ownership_bonus"), 3, 0.0) if record.get("wildcard_ownership_bonus") is not None else None,
        }
    else:
        breakdown["objective_explanation"] = (
            "Single-gameweek xPts estimate for the selected lineup week, built from fixture context plus a blended player baseline."
        )

    breakdown["fixtures_horizon"] = list(record.get("fixtures_horizon") or [])
    return breakdown


def decorate_projection_record(record, gws, chip_strategy="none", objective_score_col=None, optimize_event_id=None):
    fixtures_h = []
    for gw in gws:
        fixtures_h.append({
            "event_id": int(gw),
            "fixtures": (record.get(f"fixtures_gw{gw}") or ""),
            "fixture_count": int(safe_int(record.get(f"fixture_count_gw{gw}")) or 0),
            "diff_avg": float(safe_float(record.get(f"diff_avg_gw{gw}"), default=0.0) or 0.0),
            "xpts": float(safe_float(record.get(f"xpts_gw{gw}"), default=0.0) or 0.0),
        })
        record.pop(f"fixtures_gw{gw}", None)
        record.pop(f"fixture_count_gw{gw}", None)
        record.pop(f"diff_avg_gw{gw}", None)
        record.pop(f"xpts_gw{gw}", None)

    record["fixtures_horizon"] = fixtures_h
    record["next_fixtures"] = fixtures_h[0]["fixtures"] if fixtures_h else ""
    record["alerts"] = _build_player_alerts(record, optimize_event_id=optimize_event_id)
    record["score_breakdown"] = _build_score_breakdown(record, chip_strategy=chip_strategy, objective_score_col=objective_score_col)
    return record


def _lineup_projection_cols(proj_all, gws):
    proj_cols = ["id"]
    for c in [
        "xpts_horizon", "status", "chance_of_playing_next_round",
        "event_points", "total_points", "form",
        "wildcard_score", "wildcard_weighted_xpts", "wildcard_future_dgw_bonus",
        "wildcard_captaincy_bonus", "wildcard_form_bonus", "wildcard_ownership_bonus",
        "baseline_long_term_xpts", "baseline_recent_gw_xpts", "baseline_blended_xpts", "baseline_gw1_xpts",
        "recent_gw_avg_points", "recent_gw_avg_fixture_count", "recent_gw_avg_minutes",
        "recent_gw_avg_starts", "recent_gw_samples", "recent_gw_last",
        "recent_history_window_gws", "recent_history_max_gw", "recent_history_available",
    ]:
        if c in proj_all.columns:
            proj_cols.append(c)
    for gw in gws:
        for c in [f"xpts_gw{gw}", f"fixtures_gw{gw}", f"fixture_count_gw{gw}", f"diff_avg_gw{gw}"]:
            if c in proj_all.columns:
                proj_cols.append(c)
    return list(dict.fromkeys(proj_cols))


def pack_lineup_records(
    starting_df,
    bench_df,
    elements,
    proj_all,
    gws,
    teams_code,
    chip_strategy="none",
    objective_score_col=None,
    optimize_event_id=None,
):
    el_img = elements.copy()
    cols = [c for c in ["id", "team", "code", "photo"] if c in el_img.columns]
    el_img = el_img[cols].rename(columns={"id": "player_id"})

    proj_small = proj_all[_lineup_projection_cols(proj_all, gws)].copy().rename(columns={"id": "player_id"})
    starting = starting_df.merge(el_img, on="player_id", how="left").merge(proj_small, on="player_id", how="left")
    bench = bench_df.merge(el_img, on="player_id", how="left").merge(proj_small, on="player_id", how="left")
    starting_records = attach_media(df_records(starting), teams_code)
    bench_records = attach_media(df_records(bench), teams_code)

    for rec in starting_records + bench_records:
        decorate_projection_record(
            rec, gws=gws, chip_strategy=chip_strategy,
            objective_score_col=objective_score_col, optimize_event_id=optimize_event_id,
        )

    return starting_records, bench_records


def build_position_panels(
    proj_all,
    gws,
    teams_code,
    owned_ids=None,
    limit_per_pos=5,
    ranking_col="xpts_horizon",
    chip_strategy="none",
    objective_score_col=None,
    optimize_event_id=None,
):
    if proj_all is None or proj_all.empty:
        return {"all": {}, "not_owned": {}}

    owned_ids = set([int(x) for x in (owned_ids or []) if safe_int(x) is not None])
    limit_per_pos = max(1, int(limit_per_pos))
    ranking_col = str(ranking_col or "xpts_horizon")
    if ranking_col not in proj_all.columns:
        ranking_col = "xpts_horizon" if "xpts_horizon" in proj_all.columns else ranking_col

    base_cols = [
        "id", "web_name", "pos", "team", "team_short", "team_name", "price_m", "code", "photo",
        "status", "chance_of_playing_next_round", "xpts_horizon",
        "event_points",
        "wildcard_score", "wildcard_weighted_xpts", "wildcard_future_dgw_bonus",
        "wildcard_captaincy_bonus", "wildcard_form_bonus", "wildcard_ownership_bonus",
        "baseline_long_term_xpts", "baseline_recent_gw_xpts", "baseline_blended_xpts", "baseline_gw1_xpts",
        "recent_gw_avg_points", "recent_gw_avg_fixture_count", "recent_gw_avg_minutes",
        "recent_gw_avg_starts", "recent_gw_samples", "recent_gw_last",
        "recent_history_window_gws", "recent_history_max_gw", "recent_history_available",
    ]
    if ranking_col not in base_cols and ranking_col in proj_all.columns:
        base_cols.append(ranking_col)
    gw_cols = []
    for gw in gws:
        for c in [f"xpts_gw{gw}", f"fixtures_gw{gw}", f"fixture_count_gw{gw}", f"diff_avg_gw{gw}"]:
            if c in proj_all.columns:
                gw_cols.append(c)
    keep_cols = list(dict.fromkeys(c for c in base_cols + gw_cols if c in proj_all.columns))

    pool = proj_all[keep_cols].copy().rename(columns={"id": "player_id"})
    pool = pool.sort_values(ranking_col, ascending=False)

    def pack(df):
        out = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
        for pos in out.keys():
            chunk = df[df["pos"] == pos].head(limit_per_pos)
            recs = attach_media(df_records(chunk), teams_code)
            for rec in recs:
                decorate_projection_record(
                    rec, gws=gws, chip_strategy=chip_strategy,
                    objective_score_col=objective_score_col or ranking_col,
                    optimize_event_id=optimize_event_id,
                )
            out[pos] = recs
        return out

    not_owned_df = pool[~pool["player_id"].astype(int).isin(owned_ids)] if owned_ids else pool.copy()
    return {"all": pack(pool), "not_owned": pack(not_owned_df)}


def player_map_from_records(starting_records, bench_records):
    by_id = {}
    for rec in list(starting_records or []) + list(bench_records or []):
        pid = safe_player_id(rec.get("player_id"))
        if pid is None:
            continue
        by_id[pid] = rec
    return by_id


def build_bench_moves(squad_df, starting_records, bench_records):
    if squad_df is None or squad_df.empty:
        return []

    cur = squad_df.copy()
    if "player_id" not in cur.columns:
        return []
    cur["player_id"] = pd.to_numeric(cur["player_id"], errors="coerce")
    cur = cur[cur["player_id"].notna()].copy()
    cur["player_id"] = cur["player_id"].astype(int)
    if cur.empty:
        return []

    if "multiplier" in cur.columns:
        cur["multiplier"] = pd.to_numeric(cur["multiplier"], errors="coerce").fillna(0.0)
    else:
        cur["multiplier"] = 0.0

    current_starting_ids = set(cur[cur["multiplier"] > 0]["player_id"].astype(int).tolist())
    current_bench_ids = set(cur[cur["multiplier"] <= 0]["player_id"].astype(int).tolist())

    rec_starting_ids = set()
    for rec in starting_records or []:
        pid = safe_player_id(rec.get("player_id"))
        if pid is not None:
            rec_starting_ids.add(pid)

    rec_bench_order = {}
    for rec in bench_records or []:
        pid = safe_player_id(rec.get("player_id"))
        if pid is None:
            continue
        rec_bench_order[pid] = safe_int(rec.get("bench_order"))

    by_id = player_map_from_records(starting_records, bench_records)

    start_candidates = []
    for pid in rec_starting_ids:
        rec = by_id.get(pid) or {}
        start_candidates.append((pid, safe_float(rec.get("xpts"), default=0.0) or 0.0))
    start_candidates.sort(key=lambda row: row[1], reverse=True)

    moves = []
    for pid, _ in start_candidates:
        if pid not in current_bench_ids:
            continue
        rec = by_id.get(pid) or {}
        moves.append({
            "player_id": int(pid),
            "web_name": rec.get("web_name"),
            "team_short": rec.get("team_short"),
            "move": "start",
            "recommended_bench_order": None,
            "xpts": round_float(rec.get("xpts"), 2, 0.0),
        })

    bench_candidates = []
    for pid, bench_order in rec_bench_order.items():
        rec = by_id.get(pid) or {}
        xpts = safe_float(rec.get("xpts"), default=0.0) or 0.0
        bench_candidates.append((pid, bench_order if bench_order is not None else 99, xpts))
    bench_candidates.sort(key=lambda row: (row[1], row[2]))

    for pid, bench_order, _ in bench_candidates:
        if pid not in current_starting_ids:
            continue
        rec = by_id.get(pid) or {}
        moves.append({
            "player_id": int(pid),
            "web_name": rec.get("web_name"),
            "team_short": rec.get("team_short"),
            "move": "bench",
            "recommended_bench_order": int(bench_order) if bench_order is not None else None,
            "xpts": round_float(rec.get("xpts"), 2, 0.0),
        })

    limit = int(getattr(config, "STRATEGY_MAX_BENCH_MOVES", 6) or 6)
    return moves[: max(1, limit)]
