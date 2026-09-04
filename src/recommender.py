# recommender.py
import numpy as np
import pandas as pd

from . import config

# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------

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
    mapping = {"a": 0.0, "d": 0.45, "u": 0.9, "s": 1.1, "i": 1.35}
    return to_number(mapping.get(str(status or "").strip().lower(), 0.0), 0.0)


def status_buy_bonus(status):
    mapping = {"a": 0.2, "d": -0.35, "u": -0.95, "s": -1.15, "i": -1.35}
    return to_number(mapping.get(str(status or "").strip().lower(), 0.0), 0.0)


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


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def build_transfer_scores(elements_all, score_col=None):
    el = elements_all.copy()
    numeric_cols = [
        "now_cost", "price_m", "form", "points_per_game", "total_points",
        "minutes", "selected_by_percent", "transfers_in_event", "transfers_out_event",
        "penalties_order", "direct_freekicks_order", "corners_and_indirect_freekicks_order",
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
        el["base_score"] = (
            float(config.TRANSFER_BASE_PPG_WEIGHT) * series_num(el, "points_per_game", 0.0)
            + float(config.TRANSFER_BASE_FORM_WEIGHT) * series_num(el, "form", 0.0)
        )

    form = series_num(el, "form", 0.0)
    ppg = series_num(el, "points_per_game", 0.0)
    momentum = np.log1p(series_num(el, "transfers_in_event", 0.0).clip(lower=0.0)) - np.log1p(series_num(el, "transfers_out_event", 0.0).clip(lower=0.0))
    selected = series_num(el, "selected_by_percent", 0.0)

    el["hot_score"] = (
        float(config.TRANSFER_HOT_FORM_WEIGHT) * form
        + float(config.TRANSFER_HOT_PPG_WEIGHT) * ppg
        + float(config.TRANSFER_HOT_MOMENTUM_WEIGHT) * momentum
        + float(config.TRANSFER_HOT_SELECTED_WEIGHT) * (selected / float(config.TRANSFER_HOT_SELECTED_SCALE))
    )
    el["consistency_score"] = (
        float(config.TRANSFER_CONSISTENCY_TOTAL_POINTS_WEIGHT) * series_ratio_clip(series_num(el, "total_points", 0.0), config.TRANSFER_CONSISTENCY_TOTAL_POINTS_SCALE)
        + float(config.TRANSFER_CONSISTENCY_MINUTES_WEIGHT) * series_ratio_clip(series_num(el, "minutes", 0.0), config.TRANSFER_CONSISTENCY_MINUTES_TARGET)
    )
    el["set_piece_score"] = el.apply(set_piece_score, axis=1)
    el["attack_bonus"] = el["pos"].apply(position_attack_bonus) if "pos" in el.columns else 0.0
    el["transfer_score"] = (
        el["base_score"].fillna(0.0)
        + el["consistency_score"].fillna(0.0)
        + float(config.TRANSFER_HOT_SCORE_BLEND) * el["hot_score"].fillna(0.0)
        + el["set_piece_score"].fillna(0.0)
        + el["attack_bonus"].fillna(0.0)
    )
    return el


def add_buyer_bonuses(el):
    """Add buy_priority and availability columns to market dataframe in-place."""
    el["selected_by_percent"] = pd.to_numeric(el.get("selected_by_percent"), errors="coerce").fillna(0.0)
    cop_next = pd.to_numeric(el.get("chance_of_playing_next_round"), errors="coerce")
    cop_this = pd.to_numeric(el.get("chance_of_playing_this_round"), errors="coerce")
    cop_next = cop_next.where(cop_next.notna(), cop_this).fillna(100.0).clip(0.0, 100.0)
    el["chance_of_playing_next_round"] = cop_next
    el["team"] = pd.to_numeric(el.get("team"), errors="coerce")

    el["buy_availability_bonus"] = (cop_next / 100.0) * float(config.TRANSFER_BUY_AVAILABILITY_WEIGHT)
    el["buy_status_bonus"] = el["status"].apply(status_buy_bonus) if "status" in el.columns else 0.0
    el["buy_premium_bonus"] = (
        (pd.to_numeric(el.get("price_m"), errors="coerce").fillna(0.0) - float(config.TRANSFER_BUY_PREMIUM_PRICE_FLOOR))
        .clip(lower=0.0)
        * float(config.TRANSFER_BUY_PREMIUM_BONUS)
        * (el.get("pos", pd.Series("", index=el.index)).isin(["MID", "FWD"]).astype(int))
    )
    el["buy_ownership_bonus"] = (el["selected_by_percent"] / 100.0) * float(config.TRANSFER_BUY_OWNERSHIP_BONUS)
    el["buy_priority"] = (
        el["transfer_score"].fillna(0.0)
        + el["buy_availability_bonus"].fillna(0.0)
        + el["buy_status_bonus"].fillna(0.0)
        + el["buy_premium_bonus"].fillna(0.0)
        + el["buy_ownership_bonus"].fillna(0.0)
    )
    return el


# ---------------------------------------------------------------------------
# Market preparation
# ---------------------------------------------------------------------------

MARKET_COLS = [
    "id", "web_name", "team", "team_short", "pos", "price_m",
    "base_score", "hot_score", "set_piece_score", "transfer_score",
    "selected_by_percent", "status", "chance_of_playing_this_round", "chance_of_playing_next_round",
]


def prepare_market(elements_all, score_col=None):
    """Score all elements and attach buyer bonuses. Returns enriched market df."""
    el = build_transfer_scores(elements_all, score_col=score_col)
    for c in MARKET_COLS:
        if c not in el.columns:
            if c == "id":
                raise ValueError("Elements table missing id column.")
            el[c] = None
    el = add_buyer_bonuses(el)
    return el


# ---------------------------------------------------------------------------
# Squad preparation
# ---------------------------------------------------------------------------

def prepare_squad(squad_df, market_df):
    """Merge market scores into squad and compute seller priority columns."""
    sq = squad_df.copy()
    for c in ["player_id", "multiplier"]:
        if c in sq.columns:
            sq[c] = pd.to_numeric(sq[c], errors="coerce")
    sq = sq[sq["player_id"].notna()].copy()
    sq["player_id"] = sq["player_id"].astype(int)

    market = market_df[MARKET_COLS].rename(columns={
        "id": "player_id",
        "web_name": "market_web_name",
        "team": "market_team",
        "team_short": "market_team_short",
        "pos": "market_pos",
    })
    sq = sq.merge(market, on="player_id", how="left")

    for col, fallback in [("pos", "market_pos"), ("web_name", "market_web_name"),
                          ("team_short", "market_team_short"), ("team", "market_team")]:
        if col not in sq.columns:
            sq[col] = sq[fallback]
        else:
            sq[col] = sq[col].where(sq[col].notna(), sq[fallback])
    sq = sq.drop(columns=["market_web_name", "market_team", "market_team_short", "market_pos"], errors="ignore")

    for c in ["price_m", "transfer_score", "hot_score", "set_piece_score"]:
        sq[c] = pd.to_numeric(sq[c], errors="coerce").fillna(0.0)
    sq["selected_by_percent"] = pd.to_numeric(sq.get("selected_by_percent"), errors="coerce").fillna(0.0)

    cop_next = pd.to_numeric(sq.get("chance_of_playing_next_round"), errors="coerce")
    cop_this = pd.to_numeric(sq.get("chance_of_playing_this_round"), errors="coerce")
    sq["chance_of_playing_next_round"] = cop_next.where(cop_next.notna(), cop_this).fillna(100.0).clip(0.0, 100.0)
    sq["availability_risk"] = (100.0 - sq["chance_of_playing_next_round"]) / 100.0
    sq["team"] = pd.to_numeric(sq.get("team"), errors="coerce")

    sq["is_captain"] = sq.get("is_captain", False).astype(bool)
    sq["is_vice_captain"] = sq.get("is_vice_captain", False).astype(bool)
    sq["is_starter"] = pd.to_numeric(sq.get("multiplier"), errors="coerce").fillna(0.0) > 0
    sq["status_sell_boost"] = sq["status"].apply(status_sell_boost) if "status" in sq.columns else 0.0

    sq["sell_priority"] = (
        sq["transfer_score"]
        + sq["is_captain"].astype(int) * float(config.TRANSFER_KEEP_CAPTAIN_PENALTY)
        + sq["is_vice_captain"].astype(int) * float(config.TRANSFER_KEEP_VICE_PENALTY)
        + (~sq["is_starter"]).astype(int) * float(config.TRANSFER_SELL_BENCH_PENALTY)
        + (sq["pos"] == "GKP").astype(int) * float(config.TRANSFER_SELL_GKP_PENALTY)
        - sq["is_starter"].astype(int) * float(config.TRANSFER_SELL_STARTER_BOOST)
        - (sq["price_m"] - float(config.TRANSFER_SELL_PREMIUM_PRICE_FLOOR)).clip(lower=0.0) * float(config.TRANSFER_SELL_PREMIUM_BOOST)
        - sq["availability_risk"].fillna(0.0) * float(config.TRANSFER_SELL_INJURY_BOOST)
        - sq["status_sell_boost"].fillna(0.0)
    )
    sq["injury_sell_boost"] = (
        sq["availability_risk"].fillna(0.0) * float(config.TRANSFER_SELL_INJURY_BOOST)
        + sq["status_sell_boost"].fillna(0.0)
    )
    return sq


# ---------------------------------------------------------------------------
# Transfer count
# ---------------------------------------------------------------------------

def resolve_transfer_count(free_transfers, hit_cap):
    free_transfers = max(0, int(free_transfers or 0))
    hit_cap = max(0, int(hit_cap or 0))
    extra = int(hit_cap // int(config.TRANSFER_HIT_POINTS_STEP))
    return max(1, min(int(config.TRANSFER_MAX_MOVES), free_transfers + extra))


# ---------------------------------------------------------------------------
# Candidate selection helpers
# ---------------------------------------------------------------------------

def required_gain_for_seller(seller):
    required = float(config.TRANSFER_MIN_SCORE_GAIN)
    pos = str(seller.get("pos") or "")
    if pos == "GKP":
        required = max(required, float(config.TRANSFER_MIN_SCORE_GAIN_GKP))
    if not bool(seller.get("is_starter")):
        required = max(required, float(config.TRANSFER_MIN_SCORE_GAIN_BENCH))
    # Same positional discipline as the horizon planner: a GKP/DEF swap must
    # clear a higher bar than MID/FWD before it's worth surfacing at all.
    pos_mult = getattr(config, "TRANSFER_PLAN_POS_GAIN_MULT", {}) or {}
    required *= float(pos_mult.get(pos, 1.0))
    if to_number(seller.get("injury_sell_boost"), 0.0) >= float(config.TRANSFER_GUARDRAIL_INJURY_OVERRIDE):
        required = float(config.TRANSFER_MIN_SCORE_GAIN)
    return float(required)


def swap_gain(seller, buy):
    """Score gain for one swap. A bench seller's replacement won't take set
    pieces or ride form from the bench, so bench swaps compete on the raw
    projection (base_score) alone; starters keep the full bonus-laden score."""
    if bool(seller.get("is_starter")):
        return to_number(buy.get("transfer_score"), 0.0) - to_number(seller.get("transfer_score"), 0.0)
    buy_base = to_number(buy.get("base_score"), to_number(buy.get("transfer_score"), 0.0))
    sell_base = to_number(seller.get("base_score"), to_number(seller.get("transfer_score"), 0.0))
    return buy_base - sell_base


def pick_sellers_for_state(sellers_df, sold_ids):
    if sellers_df is None or sellers_df.empty:
        return sellers_df
    out = sellers_df[~sellers_df["player_id"].isin(sold_ids)].copy()
    out = out.sort_values(["sell_priority", "is_starter", "injury_sell_boost"], ascending=[True, False, False])
    return out.head(max(1, int(getattr(config, "TRANSFER_BEAM_SELLERS", 8) or 8)))


def pick_buy_candidates(el, current_ids, sell_pos, budget, blocked_ids=None, team_counts=None, sell_team=None, max_per_team=3):
    excluded = set(int(x) for x in current_ids).union(set(int(x) for x in (blocked_ids or [])))
    pool = el[
        (el["pos"] == sell_pos)
        & (~el["id"].astype(int).isin(excluded))
        & (pd.to_numeric(el["price_m"], errors="coerce").fillna(99.0) <= float(budget) + 1e-9)
    ].copy()
    if pool.empty:
        return pool

    if team_counts and "team" in pool.columns:
        sell_team_id = int(sell_team) if sell_team is not None else None
        def _team_ok(team_id):
            try:
                tid = int(team_id)
            except Exception:
                return True
            count = int(team_counts.get(tid, 0))
            return count <= max_per_team if tid == sell_team_id else count < max_per_team
        pool = pool[pool["team"].apply(_team_ok)].copy()

    if pool.empty:
        return pool
    pool = pool.sort_values(["buy_priority", "transfer_score", "hot_score", "base_score"], ascending=False)
    return pool.head(max(1, int(getattr(config, "TRANSFER_BEAM_BUYERS", 6) or 6)))


def estimate_best_next_gain(state, sellers_df, el):
    avail = pick_sellers_for_state(sellers_df, state["sold_ids"])
    if avail is None or avail.empty:
        return 0.0
    max_gain = 0.0
    for _, seller in avail.iterrows():
        budget = float(state["remain"]) + to_number(seller.get("price_m"), 0.0)
        candidates = pick_buy_candidates(el, state["current_ids"], seller.get("pos"), budget, blocked_ids=state["sold_ids"])
        if candidates is None or candidates.empty:
            continue
        req = required_gain_for_seller(seller)
        for _, buy in candidates.iterrows():
            gain = swap_gain(seller, buy)
            if gain >= req and gain > max_gain:
                max_gain = gain
    return float(max_gain)


def move_from_seller_buyer(seller, buy, gain):
    return {
        "position": seller.get("pos"),
        "sell": {
            "id": int(seller.get("player_id")),
            "name": seller.get("web_name"),
            "team": seller.get("team_short"),
            "price": round(to_number(seller.get("price_m"), 0.0), 1),
        },
        "buy": {
            "id": int(buy.get("id")),
            "name": buy.get("web_name"),
            "team": buy.get("team_short"),
            "price": round(to_number(buy.get("price_m"), 0.0), 1),
        },
        "score_gain": round(gain, 2),
        "buy_hot_score": round(to_number(buy.get("hot_score"), 0.0), 2),
        "buy_set_piece_score": round(to_number(buy.get("set_piece_score"), 0.0), 2),
    }


# ---------------------------------------------------------------------------
# Beam search
# ---------------------------------------------------------------------------

def beam_search(sellers, el, start_state, transfer_count, beam_width, max_per_team):
    beam = [start_state]

    for _ in range(int(transfer_count)):
        expanded = []
        for state in beam:
            sellers_for_state = pick_sellers_for_state(sellers, state["sold_ids"])
            if sellers_for_state is None or sellers_for_state.empty:
                expanded.append({**state, "score_estimate": float(state["gain_total"])})
                continue

            state_generated = False
            for _, seller in sellers_for_state.iterrows():
                sell_id = int(seller["player_id"])
                sell_price = to_number(seller.get("price_m"), 0.0)
                sell_team = int(pd.to_numeric(seller.get("team"), errors="coerce") or 0) or None
                budget = float(state["remain"]) + sell_price

                candidates = pick_buy_candidates(
                    el, state["current_ids"], seller.get("pos"), budget,
                    blocked_ids=state["sold_ids"],
                    team_counts=state["team_counts"],
                    sell_team=sell_team,
                    max_per_team=max_per_team,
                )
                if candidates is None or candidates.empty:
                    continue

                required_gain = required_gain_for_seller(seller)
                for _, buy in candidates.iterrows():
                    gain = swap_gain(seller, buy)
                    if gain < required_gain:
                        continue

                    buy_id = int(buy["id"])
                    buy_price = to_number(buy.get("price_m"), 0.0)
                    buy_team = int(pd.to_numeric(buy.get("team"), errors="coerce") or 0) or None

                    next_ids = (state["current_ids"] - {sell_id}) | {buy_id}
                    next_sold = state["sold_ids"] | {sell_id}
                    next_remain = float(state["remain"]) - (buy_price - sell_price)
                    next_team_counts = dict(state["team_counts"])
                    if sell_team:
                        next_team_counts[sell_team] = max(0, next_team_counts.get(sell_team, 0) - 1)
                    if buy_team:
                        next_team_counts[buy_team] = next_team_counts.get(buy_team, 0) + 1

                    gain_total = float(state["gain_total"]) + gain
                    next_state = {
                        "remain": next_remain,
                        "current_ids": next_ids,
                        "sold_ids": next_sold,
                        "team_counts": next_team_counts,
                        "moves": state["moves"] + [move_from_seller_buyer(seller, buy, gain)],
                        "gain_total": gain_total,
                    }
                    lookahead = estimate_best_next_gain(next_state, sellers, el)
                    next_state["score_estimate"] = gain_total + 0.6 * lookahead
                    expanded.append(next_state)
                    state_generated = True

            if not state_generated:
                expanded.append({**state, "score_estimate": float(state["gain_total"])})

        if not expanded:
            break
        beam = sorted(expanded, key=lambda s: (s.get("score_estimate", 0.0), s.get("gain_total", 0.0), len(s.get("moves", []))), reverse=True)[:beam_width]

    return max(beam, key=lambda s: (s.get("gain_total", 0.0), len(s.get("moves", [])), s.get("remain", 0.0)))


# ---------------------------------------------------------------------------
# Hot targets
# ---------------------------------------------------------------------------

def hot_by_position(el, owned_ids, n=config.TRANSFER_DEFAULT_HOT_TOPN, xpts_col=None):
    out = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    pool = el[~el["id"].astype(int).isin(set(int(x) for x in owned_ids))].copy()
    for pos in out.keys():
        g = pool[pool["pos"] == pos].sort_values("transfer_score", ascending=False).head(int(n))
        rows = []
        for _, r in g.iterrows():
            xpts = to_number(r.get(xpts_col), None) if xpts_col else None
            xpts_horizon = to_number(r.get("xpts_horizon"), None)
            row = {
                "id": int(r["id"]),
                "name": r.get("web_name"),
                "team": r.get("team_short"),
                "pos": r.get("pos"),
                "price": round(to_number(r.get("price_m"), 0.0), 1),
                "transfer_score": round(to_number(r.get("transfer_score"), 0.0), 2),
                "hot_score": round(to_number(r.get("hot_score"), 0.0), 2),
                "set_piece_score": round(to_number(r.get("set_piece_score"), 0.0), 2),
            }
            if xpts is not None:
                row["xpts"] = round(xpts, 1)
            if xpts_horizon is not None:
                row["xpts_horizon"] = round(xpts_horizon, 1)
            rows.append(row)
        out[pos] = rows
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def suggest_transfers(squad_df, elements_all, itb_m, free_transfers, hit_cap=0, score_col=None, horizon_gws=0):
    if squad_df is None or squad_df.empty:
        return {"note": "No squad loaded.", "moves": [], "remaining_itb": itb_m}

    try:
        el = prepare_market(elements_all, score_col=score_col)
    except ValueError as exc:
        return {"note": str(exc), "moves": [], "remaining_itb": itb_m}

    sq = prepare_squad(squad_df, el)

    transfer_count = resolve_transfer_count(free_transfers, hit_cap)
    beam_width = max(1, int(getattr(config, "TRANSFER_BEAM_WIDTH", 8) or 8))
    max_per_team = int(getattr(config, "TRANSFER_MAX_PER_TEAM", 3) or 3)

    init_team_counts = {}
    for tid in sq["team"].dropna().astype(int).tolist():
        init_team_counts[tid] = init_team_counts.get(tid, 0) + 1

    start_state = {
        "remain": float(to_number(itb_m, 0.0)),
        "current_ids": set(sq["player_id"].astype(int).tolist()),
        "sold_ids": set(),
        "team_counts": init_team_counts,
        "moves": [],
        "gain_total": 0.0,
        "score_estimate": 0.0,
    }

    best = beam_search(
        sellers=sq[sq["pos"].notna()].copy(),
        el=el,
        start_state=start_state,
        transfer_count=transfer_count,
        beam_width=beam_width,
        max_per_team=max_per_team,
    )

    moves = best.get("moves", [])
    remain = float(best.get("remain", to_number(itb_m, 0.0)))
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
        "hot_by_position": hot_by_position(el, owned_ids=sq["player_id"].astype(int).tolist(), n=config.TRANSFER_DEFAULT_HOT_TOPN, xpts_col=score_col),
        "moves": moves,
        "remaining_itb": round(remain, 1),
    }
