import pandas as pd

from src import config
from src.lineup_builder import build_bench_moves, player_map_from_records
from src.utils import round_float, safe_float, safe_int, safe_player_id, normalize_chip_strategy


def chip_objective_components(chip_strategy):
    chip_strategy = normalize_chip_strategy(chip_strategy)
    if chip_strategy == "wildcard":
        return ["weighted next-fixture xPts", "future double-gameweek bonus", "premium captaincy bonus"]
    if chip_strategy == "free_hit":
        return ["current gameweek xPts", "immediate doubles and blanks only"]
    return []


def build_chip_profile(chip_strategy, squad_df, proj_all, gws):
    chip_strategy = normalize_chip_strategy(chip_strategy)
    if chip_strategy == "none" or squad_df is None or squad_df.empty or proj_all is None or proj_all.empty:
        return None
    if "player_id" not in squad_df.columns or "id" not in proj_all.columns:
        return None

    def merged_series(df, col, default=None):
        for cand in [col, f"{col}_x", f"{col}_y"]:
            if cand in df.columns:
                return df[cand]
        return pd.Series(default, index=df.index)

    join_cols = ["id", "pos", "price_m"]
    for extra in ["wildcard_score", "wildcard_weighted_xpts", "wildcard_future_dgw_bonus",
                  "wildcard_captaincy_bonus", "wildcard_form_bonus", "wildcard_ownership_bonus"]:
        if extra in proj_all.columns:
            join_cols.append(extra)
    for gw in gws:
        for col in [f"fixture_count_gw{gw}", f"xpts_gw{gw}"]:
            if col in proj_all.columns:
                join_cols.append(col)

    sq = squad_df.copy()
    sq["player_id"] = pd.to_numeric(sq.get("player_id"), errors="coerce")
    sq = sq[sq["player_id"].notna()].copy()
    if sq.empty:
        return None
    sq["player_id"] = sq["player_id"].astype(int)

    merged = sq.merge(
        proj_all[list(dict.fromkeys(join_cols))].rename(columns={"id": "player_id"}),
        on="player_id", how="left",
    )
    if merged.empty:
        return None

    if chip_strategy == "free_hit":
        current_gw = int(gws[0]) if gws else None
        double_count = 0
        if current_gw is not None and f"fixture_count_gw{current_gw}" in merged.columns:
            double_count = int((pd.to_numeric(merged[f"fixture_count_gw{current_gw}"], errors="coerce").fillna(0.0) > 1).sum())
        return {
            "summary": "Free Hit is treated as a one-week attack: maximize the current gameweek score and ignore longer-term setup.",
            "focus": ["current gameweek", "immediate doubles", "short-term ceiling"],
            "current_double_players": int(double_count),
        }

    premium_floor = float(
        getattr(config, "CHIP_WILDCARD_PREMIUM_ATTACKER_FLOOR",
                getattr(config, "CAPTAIN_PREMIUM_PRICE_FLOOR", 9.0)) or
        getattr(config, "CAPTAIN_PREMIUM_PRICE_FLOOR", 9.0)
    )
    pos_series = merged_series(merged, "pos", default="")
    price_series = pd.to_numeric(merged_series(merged, "price_m", default=0.0), errors="coerce").fillna(0.0)
    attackers = pos_series.astype(str).isin(["MID", "FWD"])
    premium_attackers = int((attackers & (price_series >= premium_floor)).sum())

    future_double_gameweeks = []
    future_double_players = pd.Series(False, index=merged.index)
    for gw in list(gws)[1:]:
        fixture_col = f"fixture_count_gw{gw}"
        if fixture_col not in merged.columns:
            continue
        fixture_count = pd.to_numeric(merged[fixture_col], errors="coerce").fillna(0.0)
        doubled = fixture_count > 1.0
        if int(doubled.sum()) > 0:
            future_double_gameweeks.append({"event_id": int(gw), "player_count": int(doubled.sum())})
        future_double_players = future_double_players | doubled

    return {
        "summary": (
            "Wildcard is being developed as a setup chip: it looks across the next fixtures, "
            "keeps captaincy-grade premiums in play, leans toward in-form picks, and boosts later doubles inside the planning horizon so the squad can move toward a bench boost."
        ),
        "focus": ["next fixtures", "future double gameweeks", "captaincy premiums", "recent form", "bench boost setup"],
        "premium_attackers": int(premium_attackers),
        "future_double_gameweeks": future_double_gameweeks,
        "future_double_players": int(future_double_players.sum()),
    }


def build_strategy_recommendation(
    squad_df,
    starting_records,
    bench_records,
    captain_player_id,
    vice_player_id,
    horizon_gws,
    free_transfers,
    transfer_preview,
    active_chip=None,
    selected_chip_strategy="none",
):
    horizon_gws = max(1, int(safe_int(horizon_gws) or 1))
    free_transfers = max(0, int(safe_int(free_transfers) or 0))

    transfer_preview = transfer_preview or {}
    preview_moves = transfer_preview.get("moves")
    if not isinstance(preview_moves, list):
        preview_moves = []

    total_gain = 0.0
    for move in preview_moves:
        if isinstance(move, dict):
            total_gain += float(safe_float(move.get("score_gain"), default=0.0) or 0.0)
    planned_moves = len(preview_moves)
    avg_gain = float(total_gain / planned_moves) if planned_moves > 0 else 0.0

    if horizon_gws == 1:
        min_gain_per_transfer = float(getattr(config, "STRATEGY_MIN_GAIN_PER_TRANSFER_GW1", 1.4))
    else:
        min_gain_per_transfer = float(getattr(config, "STRATEGY_MIN_GAIN_PER_TRANSFER_MULTI", 1.1))

    suggested_transfers_count = planned_moves if avg_gain >= min_gain_per_transfer and total_gain > 0 else 0
    action = "make_transfers" if suggested_transfers_count > 0 else "roll"

    by_id = player_map_from_records(starting_records, bench_records)
    captain_rec = by_id.get(safe_player_id(captain_player_id) or -1) or {}
    vice_rec = by_id.get(safe_player_id(vice_player_id) or -1) or {}
    captain_xpts = float(safe_float(captain_rec.get("xpts"), default=0.0) or 0.0)
    bench_xpts = sum(float(safe_float(r.get("xpts"), default=0.0) or 0.0) for r in (bench_records or []))

    chip_name = "none"
    chip_should_use = False
    chip_confidence = 0.35
    chip_reason = "No strong chip signal for this setup."

    selected_chip_strategy = normalize_chip_strategy(selected_chip_strategy)

    if selected_chip_strategy in ("wildcard", "free_hit"):
        chip_name = selected_chip_strategy
        chip_should_use = True
        chip_confidence = 0.86 if selected_chip_strategy == "wildcard" else 0.84
        chip_reason = f"Scenario explicitly optimized for `{selected_chip_strategy}`."
    elif active_chip:
        chip_reason = f"Chip already active this GW ({active_chip})."
    elif horizon_gws == 1:
        bb_min = float(getattr(config, "STRATEGY_CHIP_BENCH_BOOST_MIN_XPTS", 15.0))
        tc_min = float(getattr(config, "STRATEGY_CHIP_TRIPLE_CAPTAIN_MIN_XPTS", 10.0))
        bench_boost_margin = bench_xpts - bb_min
        triple_captain_margin = captain_xpts - tc_min
        if bench_boost_margin >= 0 or triple_captain_margin >= 0:
            chip_should_use = True
            if bench_boost_margin >= triple_captain_margin:
                chip_name = "bench_boost"
                chip_confidence = min(0.92, 0.72 + max(0.0, bench_boost_margin) * 0.03)
                chip_reason = f"Bench projection is high ({round_float(bench_xpts, 1, 0.0)} xPts)."
            else:
                chip_name = "triple_captain"
                chip_confidence = min(0.92, 0.72 + max(0.0, triple_captain_margin) * 0.04)
                chip_reason = f"Captain projection is very high ({round_float(captain_xpts, 1, 0.0)} xPts)."

    reasons = []
    if action == "make_transfers":
        reasons.append(
            f"Transfer planner projects {round_float(total_gain, 2, 0.0)} points total gain "
            f"({round_float(avg_gain, 2, 0.0)} per move)."
        )
    else:
        reasons.append(
            f"Average transfer gain ({round_float(avg_gain, 2, 0.0)}) is below threshold "
            f"({round_float(min_gain_per_transfer, 2, 0.0)}), so rolling is safer."
        )

    if chip_should_use:
        reasons.append(chip_reason)
        action = "use_chip"

    if free_transfers > 0:
        reasons.append(f"Free transfers available: {int(free_transfers)}.")
    if horizon_gws > 1:
        reasons.append(f"Decision is optimized across the next {int(horizon_gws)} GWs.")

    if action == "use_chip":
        confidence = min(0.95, max(0.65, float(chip_confidence)))
    elif action == "make_transfers":
        confidence = min(0.9, 0.58 + max(0.0, min(0.28, avg_gain * 0.08)))
    else:
        confidence = min(0.88, 0.58 + max(0.0, min(0.24, (min_gain_per_transfer - avg_gain) * 0.1)))

    bench_moves = build_bench_moves(squad_df, starting_records, bench_records)

    return {
        "action": action,
        "confidence": round_float(confidence, 3, 0.6),
        "reasons": reasons,
        "captain_suggestion": {
            "captain_player_id": safe_player_id(captain_player_id),
            "vice_player_id": safe_player_id(vice_player_id),
            "captain_web_name": captain_rec.get("web_name"),
            "vice_web_name": vice_rec.get("web_name"),
            "captain_xpts": round_float(captain_xpts, 2, 0.0),
        },
        "transfer_suggestion": {
            "free_transfers": int(free_transfers),
            "horizon_gws": int(horizon_gws),
            "suggested_transfers_count": int(suggested_transfers_count),
            "considered_transfers_count": int(planned_moves),
            "estimated_total_gain": round_float(total_gain, 2, 0.0),
            "estimated_avg_gain": round_float(avg_gain, 2, 0.0),
            "min_gain_per_transfer_threshold": round_float(min_gain_per_transfer, 2, 0.0),
        },
        "chip_suggestion": {
            "chip": chip_name,
            "should_use": bool(chip_should_use),
            "confidence": round_float(chip_confidence, 3, 0.35),
            "active_chip": active_chip,
            "reason": chip_reason,
        },
        "bench_recommendation": {"moves": bench_moves},
    }


def build_scoring_guide(optimize_event_id, chip_strategy="none", objective_score_col=None):
    optimize_event_id = safe_int(optimize_event_id)
    recent_window = int(getattr(config, "PROJ_PLAYER_RECENT_GW_WINDOW", 5) or 5)
    guide = {
        "headline": "Scores in this app are projected points, not actual FPL points already earned.",
        "bullets": [],
        "objective_score_col": objective_score_col,
    }
    if optimize_event_id:
        guide["bullets"].append(f"`xpts_gw{int(optimize_event_id)}` estimates points for GW{int(optimize_event_id)}.")
    guide["bullets"].append(
        f"Player baseline blends long-term FPL signals with the last {int(recent_window)} calendar gameweeks when history is available."
    )
    guide["bullets"].append(
        "If a player misses a recent gameweek but their team had a fixture, that recent GW is treated as a zero in the player-history average."
    )
    guide["bullets"].append("`xpts_horizon` is the sum of projected xPts across the selected planning window.")
    if chip_strategy == "wildcard":
        guide["bullets"].append(
            "`wildcard_score` is a planning score for squad building: weighted future xPts plus bonuses for doubles, form, and premium captaincy cover."
        )
    else:
        guide["bullets"].append("Lineup selection still uses the selected gameweek xPts for the XI, captain, and bench order.")
    return guide


def build_squad_insights(starting_records, bench_records, optimize_event_id, chip_strategy="none", chip_profile=None):
    optimize_event_id = safe_int(optimize_event_id)
    records = list(starting_records or []) + list(bench_records or [])
    summary_points = []
    player_flags = []

    availability_names = []
    blank_now_names = []
    future_blanks = {}
    future_doubles = {}

    for rec in records:
        name = rec.get("web_name") or "Player"
        for alert in list(rec.get("alerts") or []):
            item = {
                "severity": alert.get("severity") or "info",
                "category": alert.get("category"),
                "text": f"{name}: {alert.get('text')}",
                "player_id": safe_player_id(rec.get("player_id")),
                "player_name": name,
                "event_id": safe_int(alert.get("event_id")),
            }
            player_flags.append(item)

            category = str(alert.get("category") or "")
            event_id = safe_int(alert.get("event_id"))
            if category == "availability":
                availability_names.append(name)
            elif category == "blank":
                if event_id == optimize_event_id:
                    blank_now_names.append(name)
                elif event_id:
                    future_blanks.setdefault(int(event_id), []).append(name)
            elif category == "double" and event_id:
                future_doubles.setdefault(int(event_id), []).append(name)

    if availability_names:
        unique_names = list(dict.fromkeys(availability_names))
        summary_points.append({
            "severity": "high", "category": "availability",
            "text": f"Availability risk to review: {', '.join(unique_names[:3])}" + ("." if len(unique_names) <= 3 else ", ..."),
        })

    if blank_now_names:
        unique_names = list(dict.fromkeys(blank_now_names))
        summary_points.append({
            "severity": "high", "category": "blank", "event_id": optimize_event_id,
            "text": f"Blank in GW{int(optimize_event_id)} for {', '.join(unique_names[:3])}" + ("." if len(unique_names) <= 3 else ", ..."),
        })

    for event_id in sorted(future_blanks.keys())[:2]:
        names = list(dict.fromkeys(future_blanks[event_id]))
        summary_points.append({
            "severity": "medium", "category": "blank", "event_id": int(event_id),
            "text": f"Blank risk ahead in GW{int(event_id)} for {len(names)} squad players.",
        })

    for event_id in sorted(future_doubles.keys())[:2]:
        names = list(dict.fromkeys(future_doubles[event_id]))
        summary_points.append({
            "severity": "info", "category": "double", "event_id": int(event_id),
            "text": f"Double gameweek upside in GW{int(event_id)} for {len(names)} squad players.",
        })

    bench_xpts = sum(float(safe_float(r.get("xpts"), default=0.0) or 0.0) for r in (bench_records or []))
    if chip_strategy == "wildcard":
        summary_points.append({
            "severity": "info", "category": "chip",
            "text": f"Wildcard bench projects {round_float(bench_xpts, 1, 0.0)} xPts for the selected week.",
        })
        if isinstance(chip_profile, dict) and chip_profile.get("future_double_players"):
            summary_points.append({
                "severity": "info", "category": "chip",
                "text": f"Wildcard draft already carries {int(chip_profile.get('future_double_players') or 0)} players with later doubles in the planning window.",
            })

    if not summary_points:
        summary_points.append({
            "severity": "info", "category": "stable",
            "text": "No major squad warning flags detected in the selected planning window.",
        })

    severity_rank = {"high": 0, "medium": 1, "info": 2, "low": 3}
    summary_points = sorted(summary_points, key=lambda item: severity_rank.get(str(item.get("severity")), 9))[:6]
    player_flags = sorted(player_flags, key=lambda item: severity_rank.get(str(item.get("severity")), 9))[:12]
    return {"summary_points": summary_points, "player_flags": player_flags}
