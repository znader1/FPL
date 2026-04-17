import pandas as pd

from src import optimizer
from src.lineup_builder import pack_lineup_records
from src.utils import round_float, safe_float, safe_int


def estimate_squad_budget_m(squad_df, elements, itb_m=0.0):
    if squad_df is None or squad_df.empty:
        return float(max(0.0, safe_float(itb_m, default=0.0) or 0.0))
    if elements is None or elements.empty or "id" not in elements.columns:
        return float(max(0.0, safe_float(itb_m, default=0.0) or 0.0))

    prices = elements.copy()
    prices["id"] = pd.to_numeric(prices["id"], errors="coerce")
    if "price_m" in prices.columns:
        prices["price_m"] = pd.to_numeric(prices["price_m"], errors="coerce")
    elif "now_cost" in prices.columns:
        prices["price_m"] = pd.to_numeric(prices["now_cost"], errors="coerce") / 10.0
    else:
        return float(max(0.0, safe_float(itb_m, default=0.0) or 0.0))
    prices = prices[prices["id"].notna() & prices["price_m"].notna()][["id", "price_m"]].copy()
    if prices.empty:
        return float(max(0.0, safe_float(itb_m, default=0.0) or 0.0))
    prices["id"] = prices["id"].astype(int)

    sq = squad_df.copy()
    if "player_id" not in sq.columns:
        return float(max(0.0, safe_float(itb_m, default=0.0) or 0.0))
    sq["player_id"] = pd.to_numeric(sq["player_id"], errors="coerce")
    sq = sq[sq["player_id"].notna()].copy()
    if sq.empty:
        return float(max(0.0, safe_float(itb_m, default=0.0) or 0.0))
    sq["player_id"] = sq["player_id"].astype(int)

    merged = sq.merge(prices.rename(columns={"id": "player_id"}), on="player_id", how="left")
    squad_value = float(pd.to_numeric(merged.get("price_m"), errors="coerce").fillna(0.0).sum())
    itb_val = float(max(0.0, safe_float(itb_m, default=0.0) or 0.0))
    return float(round(max(0.0, squad_value + itb_val), 2))


def apply_transfer_moves_to_squad(squad_df, transfer_moves, elements):
    if squad_df is None or squad_df.empty:
        return squad_df, {"requested": 0, "applied": 0, "skipped": 0}

    moves = transfer_moves if isinstance(transfer_moves, list) else []
    if not moves:
        return squad_df.copy(), {"requested": 0, "applied": 0, "skipped": 0}

    out = squad_df.copy()
    if "player_id" not in out.columns:
        return out, {"requested": len(moves), "applied": 0, "skipped": len(moves)}
    out["player_id"] = pd.to_numeric(out["player_id"], errors="coerce")
    out = out[out["player_id"].notna()].copy()
    out["player_id"] = out["player_id"].astype(int)

    el_cols = [c for c in ["id", "web_name", "team", "team_short", "team_name", "pos"] if c in elements.columns]
    el_map = elements[el_cols].drop_duplicates("id").set_index("id") if "id" in elements.columns else pd.DataFrame()

    applied = 0
    skipped = 0
    for move in moves:
        if not isinstance(move, dict):
            skipped += 1
            continue
        sell = move.get("sell") or {}
        buy = move.get("buy") or {}
        sell_id = safe_int(sell.get("id"))
        buy_id = safe_int(buy.get("id"))
        if not sell_id or not buy_id or int(sell_id) == int(buy_id):
            skipped += 1
            continue

        idxs = out.index[out["player_id"] == int(sell_id)].tolist()
        if not idxs:
            skipped += 1
            continue
        if int(buy_id) in set(out["player_id"].astype(int).tolist()):
            skipped += 1
            continue

        idx = idxs[0]
        out.at[idx, "player_id"] = int(buy_id)
        if "is_captain" in out.columns:
            out.at[idx, "is_captain"] = False
        if "is_vice_captain" in out.columns:
            out.at[idx, "is_vice_captain"] = False

        if not el_map.empty and int(buy_id) in el_map.index:
            row = el_map.loc[int(buy_id)]
            for col in ["web_name", "team", "team_short", "team_name", "pos"]:
                if col in out.columns and col in row.index:
                    out.at[idx, col] = row[col]
        else:
            if "web_name" in out.columns:
                out.at[idx, "web_name"] = buy.get("name")
            if "team_short" in out.columns:
                out.at[idx, "team_short"] = buy.get("team")

        applied += 1

    return out, {"requested": len(moves), "applied": applied, "skipped": skipped}


def build_transfer_step(
    applied_count,
    moves,
    squad_df,
    elements,
    proj_all,
    score_col,
    gws,
    teams_code,
    base_res,
    base_points,
    base_starting_records,
    base_bench_records,
):
    applied_count = max(0, int(applied_count or 0))
    moves = list(moves or [])
    selected_moves = moves[:applied_count]

    if applied_count <= 0 or not selected_moves:
        apply_info = {"requested": 0, "applied": 0, "skipped": 0}
        return {
            "applied_count": 0,
            "transfer_application": {**apply_info, "available_moves": int(len(moves)), "requested_apply_count": 0},
            "transfer_impact": {
                "base_projected_points_with_captain": float(base_points),
                "with_transfers_projected_points_with_captain": float(base_points),
                "delta_projected_points_with_captain": round_float(0.0, 2, 0.0),
            },
            "formation": list(base_res["formation"]),
            "captain_player_id": int(base_res["captain_player_id"]),
            "vice_player_id": int(base_res["vice_player_id"]),
            "projected_points_with_captain": float(base_points),
            "starting_xi": base_starting_records,
            "bench": base_bench_records,
        }

    squad_after_df, apply_info = apply_transfer_moves_to_squad(
        squad_df=squad_df, transfer_moves=selected_moves, elements=elements,
    )

    res_after = None
    if apply_info.get("applied", 0) > 0:
        try:
            res_after = optimizer.optimize_lineup(squad_after_df, proj_all, score_col=score_col)
        except Exception:
            res_after = None

    if not res_after:
        return {
            "applied_count": int(applied_count),
            "transfer_application": {**apply_info, "available_moves": int(len(moves)), "requested_apply_count": int(applied_count)},
            "transfer_impact": {
                "base_projected_points_with_captain": float(base_points),
                "with_transfers_projected_points_with_captain": float(base_points),
                "delta_projected_points_with_captain": round_float(0.0, 2, 0.0),
            },
            "formation": list(base_res["formation"]),
            "captain_player_id": int(base_res["captain_player_id"]),
            "vice_player_id": int(base_res["vice_player_id"]),
            "projected_points_with_captain": float(base_points),
            "starting_xi": base_starting_records,
            "bench": base_bench_records,
        }

    step_points = float(res_after["projected_points_with_captain"])
    step_starting_records, step_bench_records = pack_lineup_records(
        starting_df=res_after["starting_xi"],
        bench_df=res_after["bench"],
        elements=elements,
        proj_all=proj_all,
        gws=gws,
        teams_code=teams_code,
    )

    return {
        "applied_count": int(applied_count),
        "transfer_application": {**apply_info, "available_moves": int(len(moves)), "requested_apply_count": int(applied_count)},
        "transfer_impact": {
            "base_projected_points_with_captain": float(base_points),
            "with_transfers_projected_points_with_captain": float(step_points),
            "delta_projected_points_with_captain": round_float(step_points - float(base_points), 2, 0.0),
        },
        "formation": list(res_after["formation"]),
        "captain_player_id": int(res_after["captain_player_id"]),
        "vice_player_id": int(res_after["vice_player_id"]),
        "projected_points_with_captain": float(step_points),
        "starting_xi": step_starting_records,
        "bench": step_bench_records,
    }
