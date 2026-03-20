# recommender.py
import numpy as np
import pandas as pd

from . import config


def to_number(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def series_num(df, col, default=0.0):
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(float(default))


def series_ratio_clip(series, denom, low=0.0, high=1.0):
    d = float(denom) if float(denom) > 0 else 1.0
    return (pd.to_numeric(series, errors="coerce").fillna(0.0) / d).clip(lower=float(low), upper=float(high))


def position_attack_bonus(pos):
    return to_number(config.TRANSFER_ATTACK_BONUS.get(pos, 0.0), 0.0)


def status_sell_boost(status):
    key = str(status or "").strip().lower()
    mapping = {
        "a": 0.0,
        "d": 0.45,
        "u": 0.9,
        "s": 1.1,
        "i": 1.35,
    }
    return to_number(mapping.get(key, 0.0), 0.0)


def status_buy_bonus(status):
    key = str(status or "").strip().lower()
    mapping = {
        "a": 0.2,
        "d": -0.35,
        "u": -0.95,
        "s": -1.15,
        "i": -1.35,
    }
    return to_number(mapping.get(key, 0.0), 0.0)


def set_piece_score(row):
    p_order = pd.to_numeric(row.get("penalties_order"), errors="coerce")
    d_order = pd.to_numeric(row.get("direct_freekicks_order"), errors="coerce")
    c_order = pd.to_numeric(row.get("corners_and_indirect_freekicks_order"), errors="coerce")

    score = 0.0
    if pd.notna(p_order):
        score += to_number(config.TRANSFER_SET_PIECE_WEIGHTS.get("penalties", {}).get(int(p_order), 0.0), 0.0)
        if int(p_order) == 1:
            score += to_number(config.TRANSFER_SET_PIECE_PRIMARY_BONUS.get("penalties", 0.0), 0.0)

    if pd.notna(d_order):
        score += to_number(config.TRANSFER_SET_PIECE_WEIGHTS.get("direct_free_kicks", {}).get(int(d_order), 0.0), 0.0)
        if int(d_order) == 1:
            score += to_number(config.TRANSFER_SET_PIECE_PRIMARY_BONUS.get("direct_free_kicks", 0.0), 0.0)

    if pd.notna(c_order):
        score += to_number(config.TRANSFER_SET_PIECE_WEIGHTS.get("corners_indirect", {}).get(int(c_order), 0.0), 0.0)
        if int(c_order) == 1:
            score += to_number(config.TRANSFER_SET_PIECE_PRIMARY_BONUS.get("corners_indirect", 0.0), 0.0)

    return float(score)


def build_transfer_scores(elements_all, score_col=None):
    el = elements_all.copy()
    numeric_cols = [
        "now_cost",
        "price_m",
        "form",
        "points_per_game",
        "total_points",
        "minutes",
        "selected_by_percent",
        "transfers_in_event",
        "transfers_out_event",
        "penalties_order",
        "direct_freekicks_order",
        "corners_and_indirect_freekicks_order",
    ]
    for c in numeric_cols:
        if c in el.columns:
            el[c] = pd.to_numeric(el[c], errors="coerce")

    if "price_m" not in el.columns:
        el["price_m"] = series_num(el, "now_cost", 0.0) / 10.0
    else:
        miss = el["price_m"].isna()
        if miss.any():
            el.loc[miss, "price_m"] = (series_num(el, "now_cost", 0.0) / 10.0).loc[miss]

    if score_col and score_col in el.columns:
        el["base_score"] = series_num(el, score_col, 0.0)
    else:
        ppg = series_num(el, "points_per_game", 0.0)
        form = series_num(el, "form", 0.0)
        el["base_score"] = float(config.TRANSFER_BASE_PPG_WEIGHT) * ppg + float(config.TRANSFER_BASE_FORM_WEIGHT) * form

    form = series_num(el, "form", 0.0)
    ppg = series_num(el, "points_per_game", 0.0)
    total_points = series_num(el, "total_points", 0.0)
    minutes = series_num(el, "minutes", 0.0)
    selected = series_num(el, "selected_by_percent", 0.0)
    in_event = series_num(el, "transfers_in_event", 0.0)
    out_event = series_num(el, "transfers_out_event", 0.0)
    momentum = np.log1p(in_event.clip(lower=0.0)) - np.log1p(out_event.clip(lower=0.0))
    el["hot_score"] = (
        float(config.TRANSFER_HOT_FORM_WEIGHT) * form
        + float(config.TRANSFER_HOT_PPG_WEIGHT) * ppg
        + float(config.TRANSFER_HOT_MOMENTUM_WEIGHT) * momentum
        + float(config.TRANSFER_HOT_SELECTED_WEIGHT) * (selected / float(config.TRANSFER_HOT_SELECTED_SCALE))
    )
    el["consistency_score"] = (
        float(config.TRANSFER_CONSISTENCY_TOTAL_POINTS_WEIGHT)
        * series_ratio_clip(total_points, config.TRANSFER_CONSISTENCY_TOTAL_POINTS_SCALE)
        + float(config.TRANSFER_CONSISTENCY_MINUTES_WEIGHT)
        * series_ratio_clip(minutes, config.TRANSFER_CONSISTENCY_MINUTES_TARGET)
    )

    el["set_piece_score"] = el.apply(set_piece_score, axis=1)
    el["attack_bonus"] = el.get("pos", "").apply(position_attack_bonus) if "pos" in el.columns else 0.0

    el["transfer_score"] = (
        el["base_score"].fillna(0.0)
        + el["consistency_score"].fillna(0.0)
        + float(config.TRANSFER_HOT_SCORE_BLEND) * el["hot_score"].fillna(0.0)
        + el["set_piece_score"].fillna(0.0)
        + el["attack_bonus"].fillna(0.0)
    )
    return el


def hot_by_position(el, owned_ids, n=config.TRANSFER_DEFAULT_HOT_TOPN):
    out = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    pool = el[~el["id"].astype(int).isin(set(int(x) for x in owned_ids))].copy()
    for pos in out.keys():
        g = pool[pool["pos"] == pos].sort_values("transfer_score", ascending=False).head(int(n))
        rows = []
        for _, r in g.iterrows():
            rows.append(
                {
                    "id": int(r["id"]),
                    "name": r.get("web_name"),
                    "team": r.get("team_short"),
                    "pos": r.get("pos"),
                    "price": round(to_number(r.get("price_m"), 0.0), 1),
                    "transfer_score": round(to_number(r.get("transfer_score"), 0.0), 2),
                    "hot_score": round(to_number(r.get("hot_score"), 0.0), 2),
                    "set_piece_score": round(to_number(r.get("set_piece_score"), 0.0), 2),
                }
            )
        out[pos] = rows
    return out


def required_gain_for_seller(seller):
    required = float(config.TRANSFER_MIN_SCORE_GAIN)
    pos = str(seller.get("pos") or "")
    if pos == "GKP":
        required = max(required, float(config.TRANSFER_MIN_SCORE_GAIN_GKP))
    if not bool(seller.get("is_starter")):
        required = max(required, float(config.TRANSFER_MIN_SCORE_GAIN_BENCH))
    injury_boost = to_number(seller.get("injury_sell_boost"), 0.0)
    if injury_boost >= float(config.TRANSFER_GUARDRAIL_INJURY_OVERRIDE):
        required = float(config.TRANSFER_MIN_SCORE_GAIN)
    return float(required)


def pick_sellers_for_state(sellers_df, sold_ids):
    if sellers_df is None or sellers_df.empty:
        return sellers_df
    out = sellers_df[~sellers_df["player_id"].isin(sold_ids)].copy()
    out = out.sort_values(["sell_priority", "is_starter", "injury_sell_boost"], ascending=[True, False, False])
    limit = max(1, int(getattr(config, "TRANSFER_BEAM_SELLERS", 8) or 8))
    return out.head(limit)


def pick_buy_candidates(el, current_ids, sell_pos, budget, blocked_ids=None):
    blocked_ids = set(blocked_ids or [])
    excluded = set(int(x) for x in current_ids).union(set(int(x) for x in blocked_ids))
    pool = el[
        (el["pos"] == sell_pos)
        & (~el["id"].astype(int).isin(excluded))
        & (pd.to_numeric(el["price_m"], errors="coerce").fillna(99.0) <= float(budget) + 1e-9)
    ].copy()
    if pool.empty:
        return pool
    pool = pool.sort_values(["buy_priority", "transfer_score", "hot_score", "base_score"], ascending=False)
    limit = max(1, int(getattr(config, "TRANSFER_BEAM_BUYERS", 6) or 6))
    return pool.head(limit)


def move_from_seller_buyer(seller, buy, gain):
    sell_price = to_number(seller.get("price_m"), 0.0)
    buy_price = to_number(buy.get("price_m"), 0.0)
    return {
        "position": seller.get("pos"),
        "sell": {
            "id": int(seller.get("player_id")),
            "name": seller.get("web_name"),
            "team": seller.get("team_short"),
            "price": round(sell_price, 1),
        },
        "buy": {
            "id": int(buy.get("id")),
            "name": buy.get("web_name"),
            "team": buy.get("team_short"),
            "price": round(buy_price, 1),
        },
        "score_gain": round(gain, 2),
        "buy_hot_score": round(to_number(buy.get("hot_score"), 0.0), 2),
        "buy_set_piece_score": round(to_number(buy.get("set_piece_score"), 0.0), 2),
    }


def estimate_best_next_gain(state, sellers_df, el):
    max_gain = 0.0
    avail_sellers = pick_sellers_for_state(sellers_df, state["sold_ids"])
    if avail_sellers is None or avail_sellers.empty:
        return 0.0

    for _, seller in avail_sellers.iterrows():
        sell_price = to_number(seller.get("price_m"), 0.0)
        budget = float(state["remain"]) + sell_price
        candidates = pick_buy_candidates(
            el,
            state["current_ids"],
            seller.get("pos"),
            budget,
            blocked_ids=state["sold_ids"],
        )
        if candidates is None or candidates.empty:
            continue
        req = required_gain_for_seller(seller)
        for _, buy in candidates.iterrows():
            gain = to_number(buy.get("transfer_score"), 0.0) - to_number(seller.get("transfer_score"), 0.0)
            if gain >= req and gain > max_gain:
                max_gain = float(gain)
    return float(max_gain)


def suggest_transfers(
    squad_df,
    elements_all,
    itb_m,
    free_transfers,
    hit_cap=0,
    score_col=None,
    horizon_gws=0,
):
    if squad_df is None or squad_df.empty:
        return {"note": "No squad loaded.", "moves": [], "remaining_itb": itb_m}

    el = build_transfer_scores(elements_all, score_col=score_col)
    need_cols = [
        "id",
        "web_name",
        "team_short",
        "pos",
        "price_m",
        "base_score",
        "hot_score",
        "set_piece_score",
        "transfer_score",
        "selected_by_percent",
        "status",
        "chance_of_playing_this_round",
        "chance_of_playing_next_round",
    ]
    for c in need_cols:
        if c not in el.columns:
            if c in ["id"]:
                return {"note": "Elements table missing id.", "moves": [], "remaining_itb": itb_m}
            el[c] = None

    sq = squad_df.copy()
    for c in ["player_id", "multiplier"]:
        if c in sq.columns:
            sq[c] = pd.to_numeric(sq[c], errors="coerce")
    sq = sq[sq["player_id"].notna()].copy()
    sq["player_id"] = sq["player_id"].astype(int)

    market = el[need_cols].rename(
        columns={
            "id": "player_id",
            "web_name": "market_web_name",
            "team_short": "market_team_short",
            "pos": "market_pos",
        }
    )
    sq = sq.merge(
        market,
        on="player_id",
        how="left",
    )
    if "pos" not in sq.columns:
        sq["pos"] = sq["market_pos"]
    else:
        sq["pos"] = sq["pos"].where(sq["pos"].notna(), sq["market_pos"])

    if "web_name" not in sq.columns:
        sq["web_name"] = sq["market_web_name"]
    else:
        sq["web_name"] = sq["web_name"].where(sq["web_name"].notna(), sq["market_web_name"])

    if "team_short" not in sq.columns:
        sq["team_short"] = sq["market_team_short"]
    else:
        sq["team_short"] = sq["team_short"].where(sq["team_short"].notna(), sq["market_team_short"])

    sq = sq.drop(columns=["market_web_name", "market_team_short", "market_pos"], errors="ignore")
    sq["price_m"] = pd.to_numeric(sq["price_m"], errors="coerce").fillna(0.0)
    sq["transfer_score"] = pd.to_numeric(sq["transfer_score"], errors="coerce").fillna(0.0)
    sq["hot_score"] = pd.to_numeric(sq["hot_score"], errors="coerce").fillna(0.0)
    sq["set_piece_score"] = pd.to_numeric(sq["set_piece_score"], errors="coerce").fillna(0.0)
    sq["selected_by_percent"] = pd.to_numeric(sq.get("selected_by_percent"), errors="coerce").fillna(0.0)
    sq["chance_of_playing_next_round"] = pd.to_numeric(sq.get("chance_of_playing_next_round"), errors="coerce")
    sq["chance_of_playing_this_round"] = pd.to_numeric(sq.get("chance_of_playing_this_round"), errors="coerce")

    if "chance_of_playing_next_round" in sq.columns:
        fallback_mask = sq["chance_of_playing_next_round"].isna()
        if "chance_of_playing_this_round" in sq.columns:
            sq.loc[fallback_mask, "chance_of_playing_next_round"] = sq.loc[fallback_mask, "chance_of_playing_this_round"]
    sq["chance_of_playing_next_round"] = sq["chance_of_playing_next_round"].fillna(100.0).clip(lower=0.0, upper=100.0)
    sq["availability_risk"] = (100.0 - sq["chance_of_playing_next_round"]) / 100.0
    sq["status_sell_boost"] = sq.get("status", "").apply(status_sell_boost) if "status" in sq.columns else 0.0

    sq["is_captain"] = sq.get("is_captain", False).astype(bool)
    sq["is_vice_captain"] = sq.get("is_vice_captain", False).astype(bool)
    sq["is_starter"] = pd.to_numeric(sq.get("multiplier"), errors="coerce").fillna(0.0) > 0
    sq["keep_penalty"] = (
        sq["is_captain"].astype(int) * float(config.TRANSFER_KEEP_CAPTAIN_PENALTY)
        + sq["is_vice_captain"].astype(int) * float(config.TRANSFER_KEEP_VICE_PENALTY)
    )
    sq["starter_sell_boost"] = sq["is_starter"].astype(int) * float(config.TRANSFER_SELL_STARTER_BOOST)
    sq["bench_sell_penalty"] = (~sq["is_starter"]).astype(int) * float(config.TRANSFER_SELL_BENCH_PENALTY)
    sq["gkp_sell_penalty"] = (sq["pos"] == "GKP").astype(int) * float(config.TRANSFER_SELL_GKP_PENALTY)
    sq["premium_sell_boost"] = (
        (sq["price_m"] - float(config.TRANSFER_SELL_PREMIUM_PRICE_FLOOR)).clip(lower=0.0)
        * float(config.TRANSFER_SELL_PREMIUM_BOOST)
    )
    sq["injury_sell_boost"] = (
        sq["availability_risk"].fillna(0.0) * float(config.TRANSFER_SELL_INJURY_BOOST)
        + sq["status_sell_boost"].fillna(0.0)
    )
    sq["sell_priority"] = (
        sq["transfer_score"]
        + sq["keep_penalty"]
        + sq["bench_sell_penalty"]
        + sq["gkp_sell_penalty"]
        - sq["starter_sell_boost"]
        - sq["premium_sell_boost"]
        - sq["injury_sell_boost"]
    )

    el["selected_by_percent"] = pd.to_numeric(el.get("selected_by_percent"), errors="coerce").fillna(0.0)
    el["chance_of_playing_next_round"] = pd.to_numeric(el.get("chance_of_playing_next_round"), errors="coerce")
    el["chance_of_playing_this_round"] = pd.to_numeric(el.get("chance_of_playing_this_round"), errors="coerce")
    fallback_mask_el = el["chance_of_playing_next_round"].isna()
    el.loc[fallback_mask_el, "chance_of_playing_next_round"] = el.loc[fallback_mask_el, "chance_of_playing_this_round"]
    el["chance_of_playing_next_round"] = el["chance_of_playing_next_round"].fillna(100.0).clip(lower=0.0, upper=100.0)
    el["buy_availability_bonus"] = (
        (el["chance_of_playing_next_round"] / 100.0) * float(config.TRANSFER_BUY_AVAILABILITY_WEIGHT)
    )
    el["buy_status_bonus"] = el.get("status", "").apply(status_buy_bonus) if "status" in el.columns else 0.0
    el["buy_premium_bonus"] = (
        (pd.to_numeric(el.get("price_m"), errors="coerce").fillna(0.0) - float(config.TRANSFER_BUY_PREMIUM_PRICE_FLOOR))
        .clip(lower=0.0)
        * float(config.TRANSFER_BUY_PREMIUM_BONUS)
        * (el.get("pos", "").isin(["MID", "FWD"]).astype(int))
    )
    el["buy_ownership_bonus"] = (
        (el["selected_by_percent"] / 100.0) * float(config.TRANSFER_BUY_OWNERSHIP_BONUS)
    )
    el["buy_priority"] = (
        el["transfer_score"].fillna(0.0)
        + el["buy_availability_bonus"].fillna(0.0)
        + el["buy_status_bonus"].fillna(0.0)
        + el["buy_premium_bonus"].fillna(0.0)
        + el["buy_ownership_bonus"].fillna(0.0)
    )

    free_transfers = max(0, int(free_transfers or 0))
    horizon_gws = max(0, int(horizon_gws or 0))
    hit_cap = max(0, int(hit_cap or 0))
    extra_from_hits = int(hit_cap // int(config.TRANSFER_HIT_POINTS_STEP))
    transfer_count = free_transfers + horizon_gws + extra_from_hits
    transfer_count = max(1, min(int(config.TRANSFER_MAX_MOVES), transfer_count))

    sellers = sq[sq["pos"].notna()].copy()
    beam_width = max(1, int(getattr(config, "TRANSFER_BEAM_WIDTH", 8) or 8))
    start_state = {
        "remain": float(to_number(itb_m, 0.0)),
        "current_ids": set(sq["player_id"].astype(int).tolist()),
        "sold_ids": set(),
        "moves": [],
        "gain_total": 0.0,
        "score_estimate": 0.0,
    }
    beam = [start_state]

    for _ in range(int(transfer_count)):
        expanded = []
        for state in beam:
            sellers_for_state = pick_sellers_for_state(sellers, state["sold_ids"])
            if sellers_for_state is None or sellers_for_state.empty:
                state_keep = dict(state)
                state_keep["score_estimate"] = float(state_keep["gain_total"])
                expanded.append(state_keep)
                continue

            state_generated = False
            for _, seller in sellers_for_state.iterrows():
                sell_id = int(seller["player_id"])
                sell_price = to_number(seller.get("price_m"), 0.0)
                budget = float(state["remain"]) + sell_price
                candidates = pick_buy_candidates(
                    el,
                    state["current_ids"],
                    seller.get("pos"),
                    budget,
                    blocked_ids=state["sold_ids"],
                )
                if candidates is None or candidates.empty:
                    continue

                required_gain = required_gain_for_seller(seller)
                for _, buy in candidates.iterrows():
                    buy_id = int(buy["id"])
                    buy_price = to_number(buy.get("price_m"), 0.0)
                    gain = to_number(buy.get("transfer_score"), 0.0) - to_number(seller.get("transfer_score"), 0.0)
                    if gain < required_gain:
                        continue

                    next_current_ids = set(state["current_ids"])
                    if sell_id in next_current_ids:
                        next_current_ids.remove(sell_id)
                    next_current_ids.add(buy_id)

                    next_sold_ids = set(state["sold_ids"])
                    next_sold_ids.add(sell_id)
                    next_remain = float(state["remain"]) - (buy_price - sell_price)
                    next_moves = list(state["moves"])
                    next_moves.append(move_from_seller_buyer(seller, buy, gain))
                    gain_total = float(state["gain_total"]) + float(gain)

                    next_state = {
                        "remain": next_remain,
                        "current_ids": next_current_ids,
                        "sold_ids": next_sold_ids,
                        "moves": next_moves,
                        "gain_total": gain_total,
                    }
                    lookahead_gain = estimate_best_next_gain(next_state, sellers, el)
                    next_state["score_estimate"] = float(gain_total + 0.6 * lookahead_gain)
                    expanded.append(next_state)
                    state_generated = True

            if not state_generated:
                state_keep = dict(state)
                state_keep["score_estimate"] = float(state_keep["gain_total"])
                expanded.append(state_keep)

        if not expanded:
            break

        expanded = sorted(
            expanded,
            key=lambda s: (
                float(s.get("score_estimate", 0.0)),
                float(s.get("gain_total", 0.0)),
                len(s.get("moves", [])),
            ),
            reverse=True,
        )
        beam = expanded[:beam_width]

    best_state = max(
        beam,
        key=lambda s: (float(s.get("gain_total", 0.0)), len(s.get("moves", [])), float(s.get("remain", 0.0))),
    )
    moves = list(best_state.get("moves", []))
    remain = float(best_state.get("remain", to_number(itb_m, 0.0)))

    by_pos = {}
    for m in moves:
        pos = m.get("position") or "UNK"
        by_pos[pos] = by_pos.get(pos, 0) + 1

    return {
        "note": "Beam-search transfer planner with horizon, consistency, set-piece certainty, and guardrails.",
        "transfer_plan": {
            "free_transfers": int(free_transfers),
            "horizon_gws": int(horizon_gws),
            "hit_cap": int(hit_cap),
            "transfer_count_target": int(transfer_count),
            "transfer_count_built": int(len(moves)),
        },
        "moves_by_position": by_pos,
        "hot_by_position": hot_by_position(el, owned_ids=list(sq["player_id"].astype(int).tolist()), n=config.TRANSFER_DEFAULT_HOT_TOPN),
        "moves": moves,
        "remaining_itb": round(remain, 1),
    }
